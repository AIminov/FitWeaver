"""
Unified LLM client supporting Ollama and OpenAI-compatible APIs.

Includes normalization, repair, structured validation, and retry feedback.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

MAX_RETRIES = 2          # Total attempts: initial generation plus one correction.
SEGMENT_HEADER_DATE_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?P<day>\d{1,2})\.(?P<month>\d{1,2})(?:\.(?P<year>\d{2,4}))?"
    r"(?:\s*\((?P<weekday>[^)]{1,24})\))?(?:\s*,?\s+(?P<title>[^\n]+))?\s*$",
    re.IGNORECASE,
)
IDENTIFIER_PREFIX_RE = re.compile(
    r"^(?:[WwNn]\d{1,3}_)?(?:\d{2}-\d{2}_)?(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun_)?(?P<suffix>.*)$"
)
FILENAME_DATE_RE = re.compile(r"_(?P<month>\d{2})-(?P<day>\d{2})_")
INTERVAL_SOURCE_RE = re.compile(
    r"(?P<count>\d{1,2})\s*[xх×]\s*(?P<distance>\d+(?:[.,]\d+)?)\s*(?P<unit>км|km|м|m)\b",
    re.IGNORECASE,
)
DISTANCE_KM_SOURCE_RE = re.compile(r"(?P<distance>\d+(?:[.,]\d+)?)\s*(?:км|km)\b", re.IGNORECASE)
HR_CAP_RE = re.compile(
    r"(?:пульс|чсс|hr)[^\n\r]{0,32}?(?:до|up\s*to|<=?)\s*(?P<hr>\d{2,3})",
    re.IGNORECASE,
)
WEEKDAY_TOKEN_ALIASES = {
    "mon": "Mon",
    "monday": "Mon",
    "пн": "Mon",
    "пон": "Mon",
    "понедельник": "Mon",
    "tue": "Tue",
    "tues": "Tue",
    "tuesday": "Tue",
    "вт": "Tue",
    "втор": "Tue",
    "вторник": "Tue",
    "wed": "Wed",
    "wednesday": "Wed",
    "ср": "Wed",
    "среда": "Wed",
    "thu": "Thu",
    "thur": "Thu",
    "thurs": "Thu",
    "thursday": "Thu",
    "чт": "Thu",
    "четв": "Thu",
    "четверг": "Thu",
    "fri": "Fri",
    "friday": "Fri",
    "пт": "Fri",
    "пят": "Fri",
    "пятница": "Fri",
    "sat": "Sat",
    "saturday": "Sat",
    "сб": "Sat",
    "суб": "Sat",
    "суббота": "Sat",
    "sun": "Sun",
    "sunday": "Sun",
    "вс": "Sun",
    "воскр": "Sun",
    "воскресенье": "Sun",
}


@dataclass(slots=True)
class GeneratedYamlResult:
    yaml_text: str | None = None
    data: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    error_categories: dict[str, list[str]] = field(default_factory=dict)
    attempts: int = 0


@dataclass(slots=True)
class SourceWorkoutFact:
    month: int | None = None
    day: int | None = None
    week: int | None = None
    weekday: str | None = None
    header: str = ""
    interval_count: int | None = None
    interval_rep_km: float | None = None
    steady_distance_km: float | None = None
    hr_cap: int | None = None
    durations_sec: list[float] = field(default_factory=list)
    pace_ranges: list[tuple[str, str]] = field(default_factory=list)


class UnifiedLLMClient:
    """
    LLM client with retry-validation loop.

    Supports:
    - Ollama API (/api/chat endpoint)
    - OpenAI-compatible API with chat/completions auto fallback
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        api_type: str = "ollama",
        openai_mode: str = "auto",
        request_timeout_sec: int = 300,
        max_output_tokens: int = 16384,
    ):
        self.model = model
        self.api_type = api_type
        _url = base_url.rstrip("/")
        # OpenAI-compatible servers (LM Studio, vLLM, etc.) serve at /v1.
        # Auto-append /v1 so users can write "http://127.0.0.1:1234" in config.
        if api_type == "openai" and not _url.endswith("/v1"):
            _url = _url + "/v1"
        self.base_url = _url
        if openai_mode not in {"auto", "chat", "completions"}:
            raise ValueError(
                f"Unsupported openai_mode={openai_mode!r}. "
                "Expected one of: auto, chat, completions."
            )
        self.openai_mode = openai_mode
        if request_timeout_sec <= 0:
            raise ValueError("request_timeout_sec must be positive")
        self.request_timeout_sec = request_timeout_sec
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        self.max_output_tokens = max_output_tokens
        self._lmstudio_probe_done = False
        self._lmstudio_info: dict[str, Any] | None = None
        self._last_llm_error: str | None = None

    def check_connection(self) -> bool:
        """Check if LLM server is running and model is available."""
        import requests

        try:
            if self.api_type == "ollama":
                response = requests.get(f"{self.base_url}/api/tags", timeout=5)
                if response.status_code != 200:
                    return False
                models = response.json().get("models", [])
                model_names = [model.get("name", "") for model in models]
                return any(self.model in name for name in model_names)

            response = requests.get(f"{self.base_url}/models", timeout=5)
            return response.status_code == 200
        except Exception as exc:
            logger.warning(f"Connection check failed: {exc}")
            return False

    def generate_yaml_draft(
        self,
        plan_text: str,
        max_retries: int = MAX_RETRIES,
        workouts_hint: int = 0,
    ) -> GeneratedYamlResult:
        """Generate YAML plus metadata for preview, repair, and retry handling.

        Args:
            plan_text: Raw training plan text.
            max_retries: Maximum LLM retry attempts.
            workouts_hint: Explicit user-supplied workout count. Automatic header
                detection is advisory and never constrains free-form input.
        """
        from ..plan_processing import normalize_source_text, repair_plan_data
        from ..plan_validator import (
            group_issues_by_category,
            validate_plan_data_detailed,
        )
        from .prompt import get_system_prompt

        analysis = normalize_source_text(plan_text)
        if max_retries < 1:
            raise ValueError("max_retries must be at least 1 (total attempts)")
        system_prompt = get_system_prompt(
            include_text_variations=False,
            source_text=analysis.text,
        )
        original_plan = plan_text
        source_facts = self._extract_workout_facts_from_source_text(original_plan)
        user_message = self._build_source_expectations_prompt(analysis) + original_plan
        if workouts_hint > 0:
            user_message = f"User-specified workout count: {workouts_hint}\n\n" + user_message
        last_errors: list[str] = []
        last_categories: dict[str, list[str]] = {}

        for attempt in range(1, max_retries + 1):
            logger.info(f"LLM attempt {attempt}/{max_retries}...")

            self._last_llm_error = None
            raw_response = self._call_llm(system_prompt, user_message)
            if not raw_response:
                logger.warning(f"Attempt {attempt}: empty response from LLM")
                last_errors = [self._last_llm_error or "Empty response from LLM"]
                last_categories = {"llm_error": last_errors[:]}
                continue

            yaml_text = self._extract_yaml(raw_response)
            prepared = self._prepare_yaml_candidate(
                yaml_text,
                analysis_repairs=analysis.changes,
                analysis_ambiguities=analysis.ambiguities,
                expected_workout_count=max(0, workouts_hint),
                repair_plan_data=repair_plan_data,
                validate_plan_data_detailed=validate_plan_data_detailed,
                group_issues_by_category=group_issues_by_category,
            )
            # Regex extraction cannot fully interpret human prose, alternatives,
            # references or equivalent expanded intervals. Keep it diagnostic;
            # only schema/repeat validity and explicit user hints block output.
            fact_check = GeneratedYamlResult(data=prepared.data)
            self._apply_source_fact_consistency_checks(fact_check, source_facts)
            prepared.warnings.extend(
                f"Source comparison needs review (heuristic): {message}"
                for message in fact_check.validation_errors
            )
            prepared.attempts = attempt

            for warning in prepared.warnings:
                logger.warning(f"Validation warning: {warning}")

            if not prepared.validation_errors and prepared.yaml_text and prepared.data is not None:
                logger.info(f"Valid YAML generated on attempt {attempt}")
                return prepared

            last_errors = prepared.validation_errors
            last_categories = prepared.error_categories
            logger.warning(
                f"Attempt {attempt} failed with {len(prepared.validation_errors)} validation errors"
            )
            for error in prepared.validation_errors[:5]:
                logger.warning(f"  {error}")

            user_message = self._build_retry_prompt(
                original_plan=original_plan,
                issues=_issues_from_categories(last_categories),
                source_facts_text=self._format_source_facts_for_retry_prompt(source_facts),
                previous_yaml=yaml_text,
            )
            user_message = self._build_source_expectations_prompt(analysis) + user_message
            if workouts_hint > 0:
                user_message = f"User-specified workout count: {workouts_hint}\n\n" + user_message

        logger.error(f"Failed to generate valid YAML after {max_retries} attempts")
        return GeneratedYamlResult(
            warnings=[],
            repairs=analysis.changes,
            ambiguities=analysis.ambiguities,
            validation_errors=last_errors,
            error_categories=last_categories,
            attempts=max_retries,
        )

    def generate_yaml_from_plan(
        self,
        plan_text: str,
        max_retries: int = MAX_RETRIES,
        workouts_hint: int = 0,
    ) -> Optional[str]:
        """Backward-compatible convenience wrapper returning only YAML text."""
        result = self.generate_yaml_draft(
            plan_text, max_retries=max_retries, workouts_hint=workouts_hint
        )
        return result.yaml_text

    def generate_custom(self, prompt: str) -> Optional[str]:
        """Send a custom prompt (for example SBU drill parsing) and extract YAML."""
        raw = self._call_llm_raw(
            messages=[{"role": "user", "content": prompt}],
            timeout=120,
        )
        if not raw:
            return None
        return self._extract_yaml(raw)

    def _call_llm(self, system_prompt: str, user_message: str) -> Optional[str]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        return self._call_llm_raw(messages=messages, timeout=self.request_timeout_sec)

    def _call_llm_raw(self, messages: list, timeout: int = 300) -> Optional[str]:
        if self.api_type == "ollama":
            return self._call_ollama(messages, timeout)
        if self.api_type == "openai":
            return self._call_openai(messages, timeout)

        logger.error(f"Unknown api_type: {self.api_type}")
        return None

    def _call_ollama(self, messages: list, timeout: int) -> Optional[str]:
        import requests

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.0},
        }

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=timeout,
            )

            if response.status_code != 200:
                logger.error(f"Ollama API error: {response.status_code}")
                return None

            content = response.json().get("message", {}).get("content", "")
            return content if content else None

        except requests.exceptions.Timeout:
            logger.error("Timeout waiting for Ollama response")
            return None
        except requests.exceptions.ConnectionError:
            logger.error(f"Cannot connect to Ollama at {self.base_url}. Is it running?")
            return None
        except Exception as exc:
            logger.error(f"Ollama request error: {exc}")
            return None

    def _call_openai(self, messages: list, timeout: int) -> Optional[str]:
        if self.openai_mode == "auto" and self._detect_lmstudio():
            content = self._call_lmstudio(messages, timeout)
            if self._lmstudio_info is not None:
                return content
        if self.openai_mode in {"auto", "chat"}:
            chat_content = self._call_openai_chat(messages, timeout)
            if chat_content and not self._openai_chat_response_needs_fallback(chat_content):
                return chat_content
            if self.openai_mode == "chat":
                return chat_content

            fallback_reason = self._describe_openai_fallback_reason(chat_content)
            logger.info(
                "Falling back to /completions for OpenAI-compatible API: "
                f"{fallback_reason}"
            )

        prompt = self._messages_to_completion_prompt(messages)
        return self._call_openai_completion(prompt, timeout)

    def _detect_lmstudio(self) -> bool:
        """Probe once; generic OpenAI servers retain their existing transport."""
        if not self._lmstudio_probe_done:
            import requests

            self._lmstudio_probe_done = True
            try:
                response = requests.get(f"{self.base_url.removesuffix('/v1')}/api/v0/models", timeout=2)
                if response.status_code == 200:
                    self._lmstudio_info = next((item for item in response.json().get("data", [])
                                               if item.get("id") == self.model
                                               and "compatibility_type" in item and "state" in item), None)
            except (requests.RequestException, ValueError, TypeError):
                pass
        return self._lmstudio_info is not None

    def _call_lmstudio(self, messages: list, timeout: int) -> Optional[str]:
        """Use LM Studio's documented reasoning control, not ignored chat extras."""
        import requests

        info = self._lmstudio_info or {}
        context = info.get("loaded_context_length") or 8192
        # Leave room for the full source and prompt in the loaded context. Never
        # truncate the user's input to make it fit; the server reports overflow.
        output_limit = min(self.max_output_tokens, max(1, int(context) // 2))
        payload = {
            "model": self.model,
            "system_prompt": "\n\n".join(m["content"] for m in messages if m["role"] == "system"),
            "input": "\n\n".join(m["content"] for m in messages if m["role"] != "system"),
            "temperature": 0.0, "reasoning": "off", "store": False,
            "max_output_tokens": output_limit,
        }
        try:
            response = requests.post(f"{self.base_url.removesuffix('/v1')}/api/v1/chat",
                                     json=payload, timeout=timeout)
            if response.status_code in {404, 405}:
                self._lmstudio_info = None  # Older LM Studio: use compatibility API.
                return None
            if response.status_code != 200:
                self._last_llm_error = f"LM Studio native chat error: {response.status_code} {response.text[:500]}"
                logger.error(self._last_llm_error)
                return None
            data = response.json()
            stats = data.get("stats", {})
            logger.info(f"LM Studio tokens: input={stats.get('input_tokens')}, output={stats.get('total_output_tokens')}, reasoning={stats.get('reasoning_output_tokens')}")
            if stats.get("total_output_tokens", 0) >= output_limit:
                self._last_llm_error = f"LM Studio output reached token limit ({output_limit}); increase model context/output budget for this plan"
                logger.error(self._last_llm_error)
                return None
            content = "\n".join(item["content"] for item in data.get("output", [])
                                if item.get("type") == "message" and isinstance(item.get("content"), str))
            return content or None
        except (requests.RequestException, ValueError, TypeError) as exc:
            self._last_llm_error = f"LM Studio native request error: {exc}"
            logger.error(self._last_llm_error)
            return None

    def _call_openai_chat(self, messages: list, timeout: int) -> Optional[str]:
        try:
            from urllib.parse import urlsplit

            from openai import DefaultHttpxClient, OpenAI

            # httpx does not consistently honor Windows' local proxy bypass.
            # Loopback servers belong to this machine; retain proxy settings
            # for every non-loopback endpoint.
            loopback = urlsplit(self.base_url).hostname in {"localhost", "127.0.0.1", "::1"}

            client = OpenAI(
                base_url=self.base_url,
                api_key="not-needed",
                timeout=float(timeout),
                max_retries=0,  # Generation owns the retry budget.
                http_client=DefaultHttpxClient(trust_env=not loopback),
            )

            response = client.chat.completions.create(
                model=self.model,
                temperature=0.0,
                max_tokens=self.max_output_tokens,
                messages=messages,
                # Disable reasoning/thinking mode for Gemma-4, Qwen3, and similar
                # local models that auto-activate "thinking" on complex prompts.
                # LM Studio passes these through to the underlying llama.cpp server.
                extra_body={
                    "chat_template_kwargs": {"enable_thinking": False},
                    "thinking": {"type": "disabled"},
                },
            )
            content = response.choices[0].message.content
            if response.choices[0].finish_reason == "length":
                logger.error("Chat output truncated by token limit")
                return None
            return content if content else None

        except ImportError:
            logger.error("openai package not installed. Run: pip install openai")
            return None
        except Exception as exc:
            logger.error(f"OpenAI-compatible chat error: {exc}")
            return None

    def _call_openai_completion(self, prompt: str, timeout: int) -> Optional[str]:
        import json
        from urllib import error, request

        payload = {
            "model": self.model,
            "prompt": prompt,
            "temperature": 0.0,
            "max_tokens": self.max_output_tokens,
            "stop": [
                "\n\nSYSTEM:\n",
                "\n\nUSER:\n",
                "\n\nASSISTANT:\n",
                "\n\nworkouts:\n",
                "\n<think>",
                "<think>",
            ],
        }

        try:
            req = request.Request(
                f"{self.base_url}/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with request.urlopen(req, timeout=timeout) as response:
                status = getattr(response, "status", response.getcode())
                body = response.read().decode("utf-8")

            if status != 200:
                logger.error(
                    "OpenAI-compatible completions error: "
                    f"{status} {body}"
                )
                return None

            choices = json.loads(body).get("choices", [])
            if not choices:
                logger.error("OpenAI-compatible completions returned no choices")
                return None

            content = choices[0].get("text", "")
            if choices[0].get("finish_reason") == "length":
                logger.error(f"Completions output truncated by token limit ({self.max_output_tokens})")
                return None
            content = content.lstrip()
            if content.startswith("- filename:"):
                content = "workouts:\n" + "\n".join(
                    f"  {line}" if line.strip() else line
                    for line in content.splitlines()
                )
            return content.strip() or None

        except TimeoutError:
            logger.error("Timeout waiting for OpenAI-compatible completions response")
            return None
        except error.URLError:
            logger.error(
                f"Cannot connect to OpenAI-compatible completions at {self.base_url}"
            )
            return None
        except Exception as exc:
            logger.error(f"OpenAI-compatible completions request error: {exc}")
            return None

    @staticmethod
    def _extract_yaml(text: str) -> str:
        """Extract YAML from markdown code block or return raw text."""
        match = re.search(r"```yaml\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            return UnifiedLLMClient._sanitize_yaml_candidate(match.group(1).strip())

        match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            return UnifiedLLMClient._sanitize_yaml_candidate(match.group(1).strip())

        return UnifiedLLMClient._sanitize_yaml_candidate(text.strip())

    @staticmethod
    def _messages_to_completion_prompt(messages: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for message in messages:
            role = str(message.get("role", "user")).upper()
            content = str(message.get("content", "")).strip()
            if content:
                parts.append(f"{role}:\n{content}")

        parts.append(
            "ASSISTANT INSTRUCTIONS:\n"
            "- Return only valid YAML\n"
            "- Start exactly with workouts:\n"
            "- Do not repeat SYSTEM or USER text\n"
            "- Do not include reasoning, analysis, or markdown fences"
        )
        parts.append("ASSISTANT:\nworkouts:\n")
        return "\n\n".join(parts)

    @staticmethod
    def _sanitize_yaml_candidate(text: str) -> str:
        candidate = text.strip()
        # Strip only complete leading reasoning blocks; never treat an unfinished
        # reasoning response as a completed plan.
        while candidate.startswith("<think>"):
            end = candidate.find("</think>")
            if end < 0:
                return ""
            candidate = candidate[end + len("</think>"):].strip()
        if not candidate:
            return candidate

        cut_positions = [
            pos
            for marker in (
                "\nSYSTEM:\n",
                "\nUSER:\n",
                "\nASSISTANT:\n",
                "\nThinking Process:\n",
                "\n1.  **Analyze the Request:**",
                "\n1. **Analyze the Request:**",
                "\n**Analyze the Request:**",
                "\nYou are an expert Russian-speaking running coach AI",
                "\nREAD THIS SCHEMA CAREFULLY AND FOLLOW IT EXACTLY:",
                "\nI need to parse the user's input",
                "\nThe user input is:",
                "\n<think>",
            )
            if (pos := candidate.find(marker)) > 0
        ]
        if cut_positions:
            candidate = candidate[:min(cut_positions)].rstrip()

        regex_cut_positions = [
            match.start()
            for pattern in (
                r"(?m)^\s*Thinking Process:\s*$",
                r"(?m)^\s*1\.\s+\*\*Analyze the Request:\*\*",
                r"(?m)^\s*\*\*Analyze the Request:\*\*",
            )
            if (match := re.search(pattern, candidate)) and match.start() > 0
        ]
        if regex_cut_positions:
            candidate = candidate[:min(regex_cut_positions)].rstrip()

        if candidate.startswith("- filename:"):
            candidate = "workouts:\n" + "\n".join(
                f"  {line}" if line.strip() else line
                for line in candidate.splitlines()
            )

        root_matches = list(re.finditer(r"(?m)^workouts:\s*$", candidate))
        if len(root_matches) > 1:
            candidate = candidate[:root_matches[1].start()].rstrip()

        # YAML permits arbitrary key order and indentless sequences. Reformatting
        # an already parseable document by line heuristics can corrupt its steps.
        try:
            parsed = yaml.safe_load(candidate)
            if isinstance(parsed, dict) and isinstance(parsed.get("workouts"), list):
                return candidate
        except yaml.YAMLError:
            pass

        if candidate.startswith("workouts:"):
            candidate = UnifiedLLMClient._normalize_workout_yaml_indentation(candidate)

        # Fix erroneous "- key:" prefix on workout-level keys only (not drill list items at 6+ spaces)
        candidate = re.sub(
            r"(?m)^( {2,4})- (name|desc|type_code|distance_km|estimated_duration_min|steps):",
            r"\1\2:",
            candidate,
        )
        return candidate

    @staticmethod
    def _normalize_workout_yaml_indentation(candidate: str) -> str:
        """Normalize YAML indentation for workout structure.

        Preserves relative indentation within steps (so nested lists like
        sbu_block.drills keep their structure), while normalizing workout-level
        keys and the steps: header to consistent absolute positions.
        """
        normalized: list[str] = []
        saw_workouts_root = False
        in_steps = False
        step_base_indent: int | None = None  # original indent of first step content

        for raw_line in candidate.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue

            current_indent = len(raw_line) - len(raw_line.lstrip())

            if stripped == "workouts:":
                normalized.append("workouts:")
                saw_workouts_root = True
                in_steps = False
                step_base_indent = None
                continue

            if not saw_workouts_root:
                normalized.append(stripped)
                continue

            if stripped.startswith("- filename:"):
                normalized.append(f"  {stripped}")
                in_steps = False
                step_base_indent = None
                continue

            if stripped == "steps:":
                normalized.append("    steps:")
                in_steps = True
                step_base_indent = None
                continue

            if in_steps:
                # Check if this line is at or below the workout level (exit steps)
                if step_base_indent is not None and current_indent < step_base_indent:
                    # Back to workout level
                    in_steps = False
                    step_base_indent = None
                    normalized.append(f"    {stripped}")
                    continue

                if step_base_indent is None:
                    step_base_indent = current_indent

                # Preserve relative indentation within steps, anchored at 6 spaces
                relative = current_indent - step_base_indent
                normalized.append("      " + " " * relative + stripped)
                continue

            normalized.append(f"    {stripped}")

        return "\n".join(normalized)

    @staticmethod
    def _openai_chat_response_needs_fallback(content: Optional[str]) -> bool:
        if not content:
            return True

        stripped = content.strip()
        if not stripped:
            return True

        candidate = UnifiedLLMClient._extract_yaml(stripped)
        try:
            data = yaml.safe_load(candidate)
        except yaml.YAMLError:
            return True
        return not (
            isinstance(data, dict)
            and isinstance(data.get("workouts"), list)
            and data["workouts"]
            and all(isinstance(w, dict) and isinstance(w.get("steps"), list)
                    and w["steps"] for w in data["workouts"])
        )

    @classmethod
    def _describe_openai_fallback_reason(cls, content: Optional[str]) -> str:
        if not content or not content.strip():
            return "empty response"
        if cls._openai_chat_response_needs_fallback(content):
            return "chat response contained reasoning instead of YAML"
        return "chat response was not usable"

    @staticmethod
    def _prepare_yaml_candidate(
        yaml_text: str,
        *,
        analysis_repairs: list[str],
        analysis_ambiguities: list[str],
        expected_workout_count: int,
        repair_plan_data,
        validate_plan_data_detailed,
        group_issues_by_category,
    ) -> GeneratedYamlResult:
        try:
            data = yaml.safe_load(yaml_text)
        except yaml.YAMLError as exc:
            error = f"YAML parse error: {exc}"
            return GeneratedYamlResult(
                repairs=analysis_repairs[:],
                ambiguities=analysis_ambiguities[:],
                validation_errors=[error],
                error_categories={"schema_error": [error]},
            )

        if data is None:
            return GeneratedYamlResult(
                repairs=analysis_repairs[:],
                ambiguities=analysis_ambiguities[:],
                validation_errors=["YAML is empty"],
                error_categories={"schema_error": ["YAML is empty"]},
            )

        repaired_data, repair_notes = repair_plan_data(data)
        errors, warnings = validate_plan_data_detailed(
            repaired_data,
            enforce_filename_name_match=True,
        )

        warning_messages = [issue.message for issue in warnings]
        error_messages = [issue.message for issue in errors]

        if not errors:
            for index, workout in enumerate(repaired_data.get("workouts", [])):
                contributions: list[float] = []
                for step in workout.get("steps", []):
                    step_type = step.get("type")
                    if step_type in {"dist_open", "dist_hr", "dist_pace"}:
                        contributions.append(float(step["km"]))
                    elif step_type == "repeat":
                        start = step["back_to_offset"]
                        contributions.append(sum(contributions[start:]) * (step["count"] - 1))
                    else:
                        break  # Time/open/SBU steps have unknown running distance.
                else:
                    if contributions:
                        total = round(sum(contributions), 6)
                        previous = workout.get("distance_km")
                        if previous != total:
                            workout["distance_km"] = total
                            repair_notes.append(f"workouts[{index}]: recalculated distance_km from steps ({previous} -> {total})")
            rendered_yaml = yaml.safe_dump(
                repaired_data,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
            result = GeneratedYamlResult(
                yaml_text=rendered_yaml,
                data=repaired_data,
                warnings=warning_messages,
                repairs=analysis_repairs + repair_notes,
                ambiguities=analysis_ambiguities[:],
                attempts=0,
            )
            UnifiedLLMClient._apply_expected_workout_count_check(
                result,
                expected_workout_count=expected_workout_count,
            )
            return result

        result = GeneratedYamlResult(
            data=repaired_data if isinstance(repaired_data, dict) else None,
            warnings=warning_messages,
            repairs=analysis_repairs + repair_notes,
            ambiguities=analysis_ambiguities[:],
            validation_errors=error_messages,
            error_categories=group_issues_by_category(errors),
            attempts=0,
        )
        UnifiedLLMClient._apply_expected_workout_count_check(
            result,
            expected_workout_count=expected_workout_count,
        )
        return result

    @staticmethod
    def _build_retry_prompt(
        original_plan: str,
        issues: list[tuple[str, str]],
        source_facts_text: str = "",
        previous_yaml: str = "",
    ) -> str:
        grouped: dict[str, list[str]] = {}
        for category, message in issues:
            grouped.setdefault(category, []).append(message)

        sections = []
        for category in sorted(grouped):
            lines = "\n".join(f"- {message}" for message in grouped[category][:5])
            sections.append(f"{category}:\n{lines}")
        feedback = "\n\n".join(sections)

        facts_section = ""
        if source_facts_text:
            facts_section = f"Extracted source facts (must preserve):\n{source_facts_text}\n\n"

        return (
            "Your previous YAML output was invalid.\n"
            "Fix the listed problems only, keep already-correct structure, and regenerate the full YAML.\n\n"
            f"{facts_section}"
            f"Validation feedback by category:\n{feedback}\n\n"
            f"Previous output to correct:\n{previous_yaml}\n\n"
            "Requirements:\n"
            "- filename and name must stay identical\n"
            "- keep repeat semantics valid\n"
            "- output only YAML with no markdown fences\n\n"
            f"Original training plan:\n\n{original_plan}"
        )

    @staticmethod
    def _build_source_expectations_prompt(analysis) -> str:
        headers = getattr(analysis, "workout_headers", [])
        if not headers:
            return "Interpret the entire free-form plan, including shared instructions and references.\n\n"
        return (
            "Some possible date/workout headings were detected (non-exhaustive): "
            + "; ".join(headers[:12])
            + "\nThese are hints, not a required count or input format. "
            "Interpret ALL of the source, including unheaded workouts, shared rules, "
            "references to other days and rest days. Do not assume one workout per heading.\n\n"
        )

    @staticmethod
    def _apply_expected_workout_count_check(
        result: GeneratedYamlResult,
        *,
        expected_workout_count: int,
    ) -> None:
        if expected_workout_count <= 0 or not isinstance(result.data, dict):
            return

        workouts = result.data.get("workouts")
        actual_count = len(workouts) if isinstance(workouts, list) else 0
        if actual_count == expected_workout_count:
            return

        message = (
            f"expected {expected_workout_count} workouts from source text, "
            f"got {actual_count}"
        )
        result.validation_errors.append(message)
        result.error_categories.setdefault("workout_count_mismatch", []).append(message)

    @staticmethod
    def _apply_source_fact_consistency_checks(
        result: GeneratedYamlResult,
        source_facts: list[SourceWorkoutFact],
    ) -> None:
        if not source_facts or not isinstance(result.data, dict):
            return
        workouts = result.data.get("workouts")
        if not isinstance(workouts, list):
            return

        for fact in source_facts:
            passed, message = UnifiedLLMClient._evaluate_workouts_against_source_fact(workouts, fact)
            if passed:
                continue
            result.validation_errors.append(message)
            result.error_categories.setdefault("source_fact_mismatch", []).append(message)

    @staticmethod
    def _extract_segment_header_info(block_text: str) -> dict[str, Any] | None:
        lines = [line.strip() for line in str(block_text or "").splitlines() if line.strip()]
        if not lines:
            return None
        match = SEGMENT_HEADER_DATE_RE.match(lines[0])
        if not match:
            return None

        day = int(match.group("day"))
        month = int(match.group("month"))
        if not (1 <= day <= 31 and 1 <= month <= 12):
            return None

        year = date.today().year
        raw_year = match.group("year")
        if raw_year:
            year = int(raw_year)
            if year < 100:
                year += 2000
        try:
            parsed_date = date(year, month, day)
        except ValueError:
            return None

        weekday = UnifiedLLMClient._normalize_weekday_token(match.group("weekday"))
        if weekday is None:
            title_prefix = re.split(r"\s*[—–-]\s*", match.group("title") or "", maxsplit=1)[0]
            weekday = UnifiedLLMClient._normalize_weekday_token(title_prefix)
        if weekday is None:
            weekday = parsed_date.strftime("%a")

        return {
            "month": month,
            "day": day,
            "week": parsed_date.isocalendar()[1],
            "weekday": weekday,
        }

    @staticmethod
    def _extract_workout_facts_from_source_text(plan_text: str) -> list[SourceWorkoutFact]:
        from ..plan_processing import normalize_source_text

        analysis = normalize_source_text(plan_text)
        return [
            fact
            for block in analysis.workout_blocks
            if (fact := UnifiedLLMClient._extract_single_workout_fact(
                block + "\n" + analysis.shared_context
            )) is not None
        ]

    @staticmethod
    def _extract_single_workout_fact(block_text: str) -> SourceWorkoutFact | None:
        from ..plan_processing import NON_RUNNING_DAY_ONLY_RE

        lines = [line.strip() for line in str(block_text or "").splitlines() if line.strip()]
        if not lines:
            return None
        header = lines[0]
        info = UnifiedLLMClient._extract_segment_header_info(block_text)
        if info is None:
            return None

        title = SEGMENT_HEADER_DATE_RE.match(header)
        source_body = [title.group("title") or ""] if title else []
        fact_lines = [line for line in source_body + lines[1:]
                      if not NON_RUNNING_DAY_ONLY_RE.match(line)
                      and not re.match(r"\s*(?:итого|всего|total|estimated)\b", line, re.IGNORECASE)]
        lowered = "\n".join(fact_lines).lower()
        interval_match = INTERVAL_SOURCE_RE.search(lowered)
        interval_count: int | None = None
        interval_rep_km: float | None = None
        if interval_match:
            interval_count = int(interval_match.group("count"))
            raw_dist = float(interval_match.group("distance").replace(",", "."))
            unit = interval_match.group("unit").lower()
            interval_rep_km = raw_dist if unit in {"km", "км"} else raw_dist / 1000.0

        steady_distance_km: float | None = None
        km_values = [
            float(match.group("distance").replace(",", "."))
            for match in DISTANCE_KM_SOURCE_RE.finditer(lowered)
        ]
        if km_values and interval_match is None:
            if len(km_values) == 1:
                steady_distance_km = km_values[0]

        hr_cap: int | None = None
        hr_match = HR_CAP_RE.search(lowered)
        if hr_match:
            hr_cap = int(hr_match.group("hr"))

        durations_sec = [
            float(m.group(1).replace(",", ".")) * (60 if m.group(2).startswith(("мин", "min")) else 1)
            for m in re.finditer(r"(?<![\d:])(\d+(?:[.,]\d+)?)\s*(мин\w*|min\w*|сек\w*|sec\w*)\b", lowered)
        ]
        pace_ranges = [
            (m.group(1), m.group(2))
            for m in re.finditer(r"(?<!\d)(\d{1,2}:[0-5]\d)\s*[-–—]\s*(\d{1,2}:[0-5]\d)(?!\d)", lowered)
        ]

        return SourceWorkoutFact(
            month=info["month"],
            day=info["day"],
            week=info["week"],
            weekday=info["weekday"],
            header=header,
            interval_count=interval_count,
            interval_rep_km=interval_rep_km,
            steady_distance_km=steady_distance_km,
            hr_cap=hr_cap,
            durations_sec=durations_sec,
            pace_ranges=pace_ranges,
        )

    @staticmethod
    def _format_source_facts_for_retry_prompt(facts: list[SourceWorkoutFact]) -> str:
        if not facts:
            return ""

        lines: list[str] = []
        for fact in facts[:12]:
            prefix = "unknown-date"
            if fact.month and fact.day:
                prefix = f"{fact.day:02d}.{fact.month:02d}"
            bits = [prefix]
            if fact.interval_count and fact.interval_rep_km:
                bits.append(f"intervals {fact.interval_count}x{fact.interval_rep_km:.3g}km")
            if fact.steady_distance_km:
                bits.append(f"distance {fact.steady_distance_km:.3g}km")
            if fact.hr_cap:
                bits.append(f"hr<= {fact.hr_cap}")
            lines.append("- " + ", ".join(bits))
        return "\n".join(lines)

    @staticmethod
    def _detect_suspicious_workout_against_fact(
        workout: dict[str, Any],
        fact: SourceWorkoutFact | None,
    ) -> list[str]:
        if fact is None:
            return []
        issues: list[str] = []
        steps = workout.get("steps") if isinstance(workout.get("steps"), list) else []

        if fact.interval_count and fact.interval_rep_km:
            repeat_counts = [
                step.get("count")
                for step in steps
                if isinstance(step, dict) and step.get("type") == "repeat"
            ]
            if fact.interval_count not in repeat_counts:
                issues.append(f"missing repeat count {fact.interval_count}")

            rep_distances = [
                float(step.get("km"))
                for step in steps
                if isinstance(step, dict)
                and str(step.get("type", "")).startswith("dist_")
                and isinstance(step.get("km"), (int, float))
            ]
            if not any(abs(value - fact.interval_rep_km) <= 0.08 for value in rep_distances):
                issues.append(f"missing interval distance {fact.interval_rep_km:.3g}km")

            matching_groups = []
            for index, step in enumerate(steps):
                if not isinstance(step, dict) or step.get("type") != "repeat" or step.get("count") != fact.interval_count:
                    continue
                start = step.get("back_to_offset")
                if not isinstance(start, int) or not 0 <= start < index:
                    continue
                group = steps[start:index]
                if (any(isinstance(s, dict) and isinstance(s.get("km"), (int, float))
                        and abs(s["km"] - fact.interval_rep_km) <= 0.001 for s in group)
                        and not any(isinstance(s, dict) and s.get("intensity") in {"warmup", "cooldown"} for s in group)):
                    matching_groups.append(group)
            if not matching_groups:
                issues.append("repeat group must contain the active interval and exclude warmup/cooldown")

            type_code = str(workout.get("type_code", "")).lower()
            if type_code and type_code not in {"intervals", "threshold", "tempo", "fartlek"}:
                issues.append("unexpected workout type for interval source block")

        if isinstance(fact.steady_distance_km, (int, float)):
            actual_distance = workout.get("distance_km")
            if not isinstance(actual_distance, (int, float)):
                issues.append("missing distance_km")
            elif abs(float(actual_distance) - float(fact.steady_distance_km)) > 0.35:
                issues.append(
                    f"distance mismatch (expected {fact.steady_distance_km:.3g}, got {float(actual_distance):.3g})"
                )

        if isinstance(fact.hr_cap, int):
            hr_high_values = [
                int(step.get("hr_high"))
                for step in steps
                if isinstance(step, dict) and isinstance(step.get("hr_high"), (int, float))
            ]
            if not hr_high_values:
                issues.append(f"missing hr cap {fact.hr_cap}")
            elif not any(abs(value - fact.hr_cap) <= 3 for value in hr_high_values):
                issues.append(f"hr cap mismatch (expected ~{fact.hr_cap})")

        for seconds in fact.durations_sec:
            if not any(isinstance(s, dict) and isinstance(s.get("seconds"), (int, float))
                       and abs(s["seconds"] - seconds) < 0.01 for s in steps):
                issues.append(f"missing source duration {seconds:g} seconds")
        for fast, slow in fact.pace_ranges:
            if not any(isinstance(s, dict) and s.get("pace_fast") == fast
                       and s.get("pace_slow") == slow for s in steps):
                issues.append(f"missing source pace range {fast}-{slow}")

        return issues

    @staticmethod
    def _evaluate_workouts_against_source_fact(
        workouts: list[dict[str, Any]],
        fact: SourceWorkoutFact,
    ) -> tuple[bool, str]:
        def _matches_date(workout_item: dict[str, Any]) -> bool:
            filename = str(workout_item.get("filename", ""))
            match = FILENAME_DATE_RE.search(filename)
            if not match or fact.month is None or fact.day is None:
                return False
            return (
                int(match.group("month")) == fact.month
                and int(match.group("day")) == fact.day
            )

        candidates = [item for item in workouts if isinstance(item, dict) and _matches_date(item)]
        if not candidates:
            return False, f"source date {fact.day:02d}.{fact.month:02d} not found in generated filenames"

        for candidate in candidates:
            issues = UnifiedLLMClient._detect_suspicious_workout_against_fact(candidate, fact)
            if not issues:
                return True, (
                    f"source facts for {fact.day:02d}.{fact.month:02d} are preserved"
                )

        return False, (
            f"source facts mismatch for {fact.day:02d}.{fact.month:02d}: "
            f"{'; '.join(UnifiedLLMClient._detect_suspicious_workout_against_fact(candidates[0], fact)[:3])}"
        )

    @staticmethod
    def _normalize_weekday_token(token: str | None) -> str | None:
        if token is None:
            return None
        key = token.strip().lower().strip(".")
        return WEEKDAY_TOKEN_ALIASES.get(key)

    @staticmethod
    def _align_workout_identifier_with_source_header(
        workout: dict[str, Any],
        *,
        month: int,
        day: int,
        week: int,
        weekday: str,
    ) -> None:
        base = workout.get("filename") or workout.get("name") or ""
        base = str(base).strip()
        if not base:
            return

        suffix = base
        match = IDENTIFIER_PREFIX_RE.match(base)
        if match:
            suffix = (match.group("suffix") or "").strip("_")

        prefix = f"W{week:02d}_{month:02d}-{day:02d}_{weekday}"
        aligned = f"{prefix}_{suffix}" if suffix else prefix
        workout["filename"] = aligned
        workout["name"] = aligned


def _issues_from_categories(categories: dict[str, list[str]]) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for category, messages in categories.items():
        for message in messages:
            items.append((category, message))
    return items


OllamaClient = UnifiedLLMClient


def generate_yaml_from_plan(
    plan_text: str,
    model: str,
    ollama_url: str,
) -> Optional[str]:
    """Convenience function for backward compatibility."""
    client = UnifiedLLMClient(model=model, base_url=ollama_url, api_type="ollama")
    return client.generate_yaml_from_plan(plan_text)
