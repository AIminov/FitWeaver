"""
Unified LLM client supporting Ollama and OpenAI-compatible APIs.

Includes normalization, repair, structured validation, and retry feedback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import logging
import re
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
SUSPICIOUS_SEGMENT_RETRIES = 1
SEGMENT_HEADER_DATE_RE = re.compile(
    r"^\s*(?P<day>\d{1,2})\.(?P<month>\d{1,2})(?:\.(?P<year>\d{2,4}))?(?:\s*\((?P<weekday>[^)]{1,12})\))?\s*$",
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
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_type = api_type
        if openai_mode not in {"auto", "chat", "completions"}:
            raise ValueError(
                f"Unsupported openai_mode={openai_mode!r}. "
                "Expected one of: auto, chat, completions."
            )
        self.openai_mode = openai_mode
        if request_timeout_sec <= 0:
            raise ValueError("request_timeout_sec must be positive")
        self.request_timeout_sec = request_timeout_sec

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
            workouts_hint: Override for expected workout count when auto-detection
                returns 0. Has no effect if the plan text already yields a count.
        """
        from .prompt import get_system_prompt
        from ..plan_processing import normalize_source_text, repair_plan_data
        from ..plan_validator import (
            group_issues_by_category,
            validate_plan_data_detailed,
        )

        analysis = normalize_source_text(plan_text)
        if workouts_hint > 0 and analysis.expected_workouts == 0:
            analysis.expected_workouts = workouts_hint

        if 1 < analysis.expected_workouts <= 10 and analysis.workout_blocks:
            return self._generate_segmented_yaml_draft(
                analysis=analysis,
                max_retries=max_retries,
                repair_plan_data=repair_plan_data,
                validate_plan_data_detailed=validate_plan_data_detailed,
                group_issues_by_category=group_issues_by_category,
            )

        system_prompt = get_system_prompt(
            include_text_variations=False,
            source_text=analysis.text,
        )
        original_plan = analysis.text
        source_facts = self._extract_workout_facts_from_source_text(original_plan)
        user_message = self._build_source_expectations_prompt(analysis) + original_plan
        last_errors: list[str] = []
        last_categories: dict[str, list[str]] = {}

        for attempt in range(1, max_retries + 1):
            logger.info(f"LLM attempt {attempt}/{max_retries}...")

            raw_response = self._call_llm(system_prompt, user_message)
            if not raw_response:
                logger.warning(f"Attempt {attempt}: empty response from LLM")
                last_errors = ["Empty response from LLM"]
                last_categories = {"llm_error": last_errors[:]}
                continue

            yaml_text = self._extract_yaml(raw_response)
            prepared = self._prepare_yaml_candidate(
                yaml_text,
                analysis_repairs=analysis.changes,
                analysis_ambiguities=analysis.ambiguities,
                expected_workout_count=analysis.expected_workouts,
                repair_plan_data=repair_plan_data,
                validate_plan_data_detailed=validate_plan_data_detailed,
                group_issues_by_category=group_issues_by_category,
            )
            self._apply_source_fact_consistency_checks(prepared, source_facts)
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
            )
            user_message = self._build_source_expectations_prompt(analysis) + user_message

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

    def _call_openai_chat(self, messages: list, timeout: int) -> Optional[str]:
        try:
            from openai import OpenAI

            client = OpenAI(
                base_url=self.base_url,
                api_key="not-needed",
                timeout=float(timeout),
            )

            response = client.chat.completions.create(
                model=self.model,
                temperature=0.0,
                messages=messages,
            )
            content = response.choices[0].message.content
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
            "max_tokens": 4000,
            "stop": [
                "\n\nSYSTEM:\n",
                "\n\nUSER:\n",
                "\n\nASSISTANT:\n",
                "\n\nworkouts:\n",
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

        lowered = stripped.lower()
        if "```yaml" in lowered or "workouts:" in lowered:
            return False

        return (
            lowered.startswith("thinking process:")
            or lowered.startswith("<think>")
            or lowered.startswith("analysis:")
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
            "Requirements:\n"
            "- filename and name must stay identical\n"
            "- keep repeat semantics valid\n"
            "- output only YAML with no markdown fences\n\n"
            f"Original training plan:\n\n{original_plan}"
        )

    def _generate_segmented_yaml_draft(
        self,
        *,
        analysis,
        max_retries: int,
        repair_plan_data,
        validate_plan_data_detailed,
        group_issues_by_category,
    ) -> GeneratedYamlResult:
        merged_workouts: list[dict[str, Any]] = []
        warnings: list[str] = []
        repairs: list[str] = list(analysis.changes)
        ambiguities: list[str] = list(analysis.ambiguities)
        attempts = 0

        for index, block_text in enumerate(analysis.workout_blocks, start=1):
            logger.info(
                f"Segmented LLM generation for workout {index}/{analysis.expected_workouts}..."
            )
            segment_fact = self._extract_single_workout_fact(block_text)
            segment_workout, segment_error = self._generate_and_validate_segment_workout(
                block_text=block_text,
                fact=segment_fact,
                max_retries=max_retries,
                segment_index=index,
            )
            if segment_error:
                return GeneratedYamlResult(
                    warnings=warnings,
                    repairs=repairs,
                    ambiguities=ambiguities,
                    validation_errors=[segment_error],
                    error_categories={"segmented_generation_error": [segment_error]},
                    attempts=attempts,
                )
            if segment_workout is None:
                return GeneratedYamlResult(
                    warnings=warnings,
                    repairs=repairs,
                    ambiguities=ambiguities,
                    validation_errors=[f"segment {index}: empty result"],
                    error_categories={"segmented_generation_error": [f"segment {index}: empty result"]},
                    attempts=attempts,
                )
            attempts += max_retries  # Upper bound approximation for nested generation.
            merged_workouts.append(segment_workout)

        merged_yaml = yaml.safe_dump(
            {"workouts": merged_workouts},
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        merged_result = self._prepare_yaml_candidate(
            merged_yaml,
            analysis_repairs=repairs,
            analysis_ambiguities=ambiguities,
            expected_workout_count=analysis.expected_workouts,
            repair_plan_data=repair_plan_data,
            validate_plan_data_detailed=validate_plan_data_detailed,
            group_issues_by_category=group_issues_by_category,
        )
        merged_result.warnings = warnings + merged_result.warnings
        merged_result.attempts = attempts
        return merged_result

    @staticmethod
    def _build_source_expectations_prompt(analysis) -> str:
        expected = getattr(analysis, "expected_workouts", 0)
        if not expected:
            return ""

        phase_weeks = getattr(analysis, "phase_weeks", 0)
        days_per_week = getattr(analysis, "days_per_week", 0)
        headers = ", ".join(getattr(analysis, "workout_headers", [])[:12])

        lines = [f"Expected workout items: {expected}"]
        if phase_weeks and days_per_week:
            lines.append(
                f"Plan structure: {phase_weeks} weeks x {days_per_week} training days/week = {expected} total workouts."
            )
            lines.append(
                "Generate ALL workouts for ALL weeks — do not stop early or produce only one example per phase."
            )
            lines.append(
                "Each week in each phase must produce exactly one workout entry per training day."
            )
        elif headers:
            lines.append(f"Detected workout headers: {headers}")
        lines.append("Skip rest/off days and output exactly that many workout items.")
        return "\n".join(lines) + "\n\n"

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

    def _generate_and_validate_segment_workout(
        self,
        *,
        block_text: str,
        fact: SourceWorkoutFact | None,
        max_retries: int,
        segment_index: int,
    ) -> tuple[dict[str, Any] | None, str | None]:
        prompt_text = block_text
        last_error: str | None = None

        for retry_idx in range(SUSPICIOUS_SEGMENT_RETRIES + 1):
            segment_result = self.generate_yaml_draft(prompt_text, max_retries=max_retries)
            if segment_result.validation_errors or not isinstance(segment_result.data, dict):
                details = "; ".join(segment_result.validation_errors[:3]) or "empty result"
                return None, f"segment {segment_index}: {details}"

            segment_workouts = segment_result.data.get("workouts")
            if not isinstance(segment_workouts, list) or len(segment_workouts) != 1:
                count = len(segment_workouts) if isinstance(segment_workouts, list) else 0
                return None, (
                    f"segment {segment_index}: expected exactly 1 workout item, got {count}"
                )

            workout = segment_workouts[0]
            if not isinstance(workout, dict):
                return None, f"segment {segment_index}: workout payload is not a mapping"

            if fact and fact.week and fact.month and fact.day and fact.weekday:
                self._align_workout_identifier_with_source_header(
                    workout,
                    month=fact.month,
                    day=fact.day,
                    week=fact.week,
                    weekday=fact.weekday,
                )

            suspicious = self._detect_suspicious_workout_against_fact(workout, fact)
            if not suspicious:
                return workout, None

            last_error = f"segment {segment_index}: suspicious output ({'; '.join(suspicious[:3])})"
            if retry_idx >= SUSPICIOUS_SEGMENT_RETRIES:
                break
            logger.warning(last_error)
            prompt_text = self._build_segment_fact_retry_input(block_text, fact, suspicious)

        return None, last_error or f"segment {segment_index}: suspicious output"

    @staticmethod
    def _build_segment_fact_retry_input(
        block_text: str,
        fact: SourceWorkoutFact | None,
        suspicious: list[str],
    ) -> str:
        lines = ["\nMandatory facts:"]
        if fact:
            if fact.month and fact.day and fact.weekday:
                lines.append(f"- date: {fact.day:02d}.{fact.month:02d} ({fact.weekday})")
            if fact.interval_count and fact.interval_rep_km:
                lines.append(
                    f"- intervals: {fact.interval_count} x {fact.interval_rep_km:.3g} km"
                )
            if fact.steady_distance_km:
                lines.append(f"- distance_km: {fact.steady_distance_km:.3g}")
            if fact.hr_cap:
                lines.append(f"- hr cap: {fact.hr_cap}")
        lines.append("Issues to fix:")
        lines.extend(f"- {item}" for item in suspicious[:5])
        return block_text + "\n" + "\n".join(lines)

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

        year = 2025
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
            if (fact := UnifiedLLMClient._extract_single_workout_fact(block)) is not None
        ]

    @staticmethod
    def _extract_single_workout_fact(block_text: str) -> SourceWorkoutFact | None:
        lines = [line.strip() for line in str(block_text or "").splitlines() if line.strip()]
        if not lines:
            return None
        header = lines[0]
        info = UnifiedLLMClient._extract_segment_header_info(block_text)
        if info is None:
            return None

        lowered = "\n".join(lines[1:]).lower()
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
            if hr_high_values and not any(abs(value - fact.hr_cap) <= 3 for value in hr_high_values):
                issues.append(f"hr cap mismatch (expected ~{fact.hr_cap})")

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
