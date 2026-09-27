"""
Unified LLM client supporting Ollama and OpenAI-compatible APIs.

Includes normalization, repair, structured validation, and retry feedback.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from ..fileio import prune_directory
from . import source_facts, yaml_cleanup
from .source_facts import (  # noqa: F401 -- re-exported names
    _WEEKDAY_ORDER,
    DISTANCE_KM_SOURCE_RE,
    FILENAME_DATE_RE,
    HR_CAP_RE,
    IDENTIFIER_PREFIX_RE,
    INTERVAL_SOURCE_RE,
    SEGMENT_HEADER_DATE_RE,
    WEEKDAY_TOKEN_ALIASES,
    SourceWorkoutFact,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 1          # single retry is enough; extra retries trigger thinking mode
SUSPICIOUS_SEGMENT_RETRIES = 1  # one focused retry for missing source facts
# Keep a local model loaded between requests (Ollama unloads after 5 min idle by
# default, so every return to the app paid the full model load again).
DEFAULT_OLLAMA_KEEP_ALIVE = "30m"
# Plans with more workouts than this and no per-workout headers go to the model
# in one request; its output budget (num_predict) rarely fits them.
LARGE_UNSEGMENTED_PLAN_WORKOUTS = 8
# Shared plan notes (zones, paces) prepended to every segment are capped so a
# long preamble does not multiply prompt size by the number of workouts.
MAX_SHARED_CONTEXT_CHARS = 800
# Bump when the segment post-processing changes so stale cached workouts are
# not reused (prompt/model/options changes already change the cache key).
SEGMENT_CACHE_VERSION = 1
SEGMENT_CACHE_MAX_FILES = 500  # newest cached workouts kept; older ones are pruned


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
    # Segmented generation keeps the workouts that succeeded; the ones that
    # failed are listed here ({index, header, error, source}) for the user.
    failed_segments: list[dict[str, Any]] = field(default_factory=list)


class GenerationCancelled(RuntimeError):
    """Raised when the caller's cancel_event is set during generation."""


class UnifiedLLMClient:
    """
    LLM client with retry-validation loop.

    Supports:
    - Ollama API (/api/chat endpoint)
    - OpenAI-compatible API with chat/completions auto fallback
    """

    # Helpers moved to llm/source_facts.py and llm/yaml_cleanup.py; old names kept.
    _extract_segment_header_info = staticmethod(source_facts.extract_segment_header_info)
    _extract_workout_facts_from_source_text = staticmethod(source_facts.extract_workout_facts_from_source_text)
    _extract_single_workout_fact = staticmethod(source_facts.extract_single_workout_fact)
    _format_source_facts_for_retry_prompt = staticmethod(source_facts.format_source_facts_for_retry_prompt)
    _detect_suspicious_workout_against_fact = staticmethod(source_facts.detect_suspicious_workout_against_fact)
    _evaluate_workouts_against_source_fact = staticmethod(source_facts.evaluate_workouts_against_source_fact)
    _normalize_weekday_token = staticmethod(source_facts.normalize_weekday_token)
    _align_workout_identifier_with_source_header = staticmethod(source_facts.align_workout_identifier_with_source_header)
    _encode_source_hr_cap = staticmethod(source_facts.encode_source_hr_cap)
    _repair_missing_source_repeat = staticmethod(source_facts.repair_missing_source_repeat)
    _build_segment_fact_retry_input = staticmethod(source_facts.build_segment_fact_retry_input)
    _extract_yaml = staticmethod(yaml_cleanup.extract_yaml)
    _messages_to_completion_prompt = staticmethod(yaml_cleanup.messages_to_completion_prompt)
    _sanitize_yaml_candidate = staticmethod(yaml_cleanup.sanitize_yaml_candidate)
    _normalize_workout_yaml_indentation = staticmethod(yaml_cleanup.normalize_workout_yaml_indentation)
    _quote_desc_colons = staticmethod(yaml_cleanup.quote_desc_colons)
    _openai_chat_response_needs_fallback = staticmethod(yaml_cleanup.openai_chat_response_needs_fallback)
    _describe_openai_fallback_reason = staticmethod(yaml_cleanup.describe_openai_fallback_reason)

    def __init__(
        self,
        model: str,
        base_url: str,
        api_type: str = "ollama",
        openai_mode: str = "auto",
        request_timeout_sec: int = 300,
        trace_callback: Callable[[dict[str, Any]], None] | None = None,
        ollama_options: dict[str, Any] | None = None,
        ollama_keep_alive: str | None = DEFAULT_OLLAMA_KEEP_ALIVE,
        segment_cache_dir: str | Path | None = None,
        output_format: str = "yaml",
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
        self.trace_callback = trace_callback
        self.trace_context: dict[str, Any] = {}
        self._trace_sequence = 0
        self._trace_fields: dict[str, Any] = {}
        self._last_call_metrics: dict[str, Any] = {}
        self.ollama_options = {
            "temperature": 0.0,
            "num_ctx": 4096,
            "num_predict": 800,
        }
        if ollama_options:
            self.ollama_options.update(ollama_options)
        self.ollama_keep_alive = ollama_keep_alive
        self.segment_cache_dir = Path(segment_cache_dir) if segment_cache_dir else None
        if output_format not in {"yaml", "compact"}:
            raise ValueError("output_format must be 'yaml' or 'compact'")
        self.output_format = output_format
        # Optional hooks set by interactive callers (GUI):
        #   progress_callback(dict) -- {"stage", "segment", "total", "tokens"}
        #   cancel_event -- threading.Event; setting it raises GenerationCancelled
        self.progress_callback: Callable[[dict[str, Any]], None] | None = None
        self.cancel_event: Any = None
        self._segmenting = False
        # Deterministic rules for common workout lines (free_text_rules): when
        # enabled, a workout they fully understand skips the LLM. Off by default
        # so LLM evaluations measure the model, not the rules.
        self.use_rules = False
        self.rule_hr_zones: dict[str, Any] | None = None

    def _workout_from_rules(self, block_text: str) -> dict[str, Any] | None:
        if not self.use_rules:
            return None
        from ..free_text_rules import parse_workout_with_rules

        try:
            return parse_workout_with_rules(block_text, hr_zones=self.rule_hr_zones)
        except Exception as exc:  # rules are an optimisation, never a failure
            logger.info("Rule-based parsing skipped: %s", exc)
            return None

    def _check_cancelled(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise GenerationCancelled("Generation cancelled")

    def _report_progress(self, **info: Any) -> None:
        if self.progress_callback is None:
            return
        try:
            self.progress_callback(info)
        except Exception as exc:  # a display problem must not stop generation
            logger.debug("progress callback failed: %s", exc)

    def warm_up(self, timeout: int = 120) -> bool:
        """Load the model ahead of the first request (Ollama only).

        An empty generate request loads the model and keeps it for
        ``ollama_keep_alive``; on a CPU the load itself can take many seconds.
        """
        if self.api_type != "ollama":
            return False
        import requests

        payload: dict[str, Any] = {"model": self.model}
        if self.ollama_keep_alive:
            payload["keep_alive"] = self.ollama_keep_alive
        try:
            response = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=timeout)
            return response.status_code == 200
        except Exception as exc:
            logger.info("Model warm-up failed: %s", exc)
            return False

    def set_trace_context(self, **context: Any) -> None:
        """Set non-sensitive fields attached to subsequent trace events."""
        self.trace_context = {key: value for key, value in context.items() if value is not None}

    def _emit_trace(self, event: str, **fields: Any) -> None:
        if self.trace_callback is None:
            return
        self._trace_sequence += 1
        payload = {
            "sequence": self._trace_sequence,
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            **self.trace_context,
            **self._trace_fields,
            **fields,
        }
        try:
            self.trace_callback(payload)
        except Exception as exc:
            logger.warning("LLM trace callback failed: %s", exc)

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
        from ..plan_processing import normalize_source_text, repair_plan_data
        from ..plan_validator import (
            group_issues_by_category,
            validate_plan_data_detailed,
        )
        from .compact_plan import COMPACT_SYSTEM_PROMPT, CompactFormatError, compact_to_yaml
        from .prompt import get_system_prompt

        analysis = normalize_source_text(plan_text)
        if workouts_hint > 0 and analysis.expected_workouts == 0:
            analysis.expected_workouts = workouts_hint

        if not analysis.workout_blocks and _reference_day(analysis.text) is not None:
            message = "Не найдена тренировка указанного дня; укажите её шаги"
            return GeneratedYamlResult(
                validation_errors=[message],
                error_categories={"unresolved_reference": [message]},
            )

        # One request per workout whenever the source has per-workout headers:
        # small models are far more reliable on one workout at a time, output
        # stays inside num_predict, and a failure costs one workout, not all.
        if len(analysis.workout_blocks) > 1 or (
            len(analysis.workout_blocks) == 1
            and _reference_day(analysis.workout_blocks[0]) is not None
        ):
            return self._generate_segmented_yaml_draft(
                analysis=analysis,
                max_retries=max_retries,
                repair_plan_data=repair_plan_data,
                validate_plan_data_detailed=validate_plan_data_detailed,
                group_issues_by_category=group_issues_by_category,
            )

        rule_workout = self._workout_from_rules(analysis.text)
        if rule_workout is not None:
            rule_yaml = yaml.safe_dump(
                {"workouts": [rule_workout]}, allow_unicode=True, default_flow_style=False, sort_keys=False
            )
            prepared = self._prepare_yaml_candidate(
                rule_yaml,
                analysis_repairs=analysis.changes + ["workout parsed by deterministic rules (no LLM)"],
                analysis_ambiguities=analysis.ambiguities,
                expected_workout_count=1,
                source_text=analysis.text,
                repair_plan_data=repair_plan_data,
                validate_plan_data_detailed=validate_plan_data_detailed,
                group_issues_by_category=group_issues_by_category,
            )
            if not prepared.validation_errors and prepared.yaml_text:
                return prepared

        size_warning = None
        if analysis.expected_workouts > LARGE_UNSEGMENTED_PLAN_WORKOUTS:
            size_warning = (
                f"The plan has about {analysis.expected_workouts} workouts but no per-workout date "
                "headers, so it is sent in one request and the answer may be cut off. Split it into "
                "dated workouts or use the marked format (docs/MARKED_PLAN_FORMAT.md)."
            )
            logger.warning(size_warning)
        if not self._segmenting:
            self._report_progress(stage="segment", segment=1, total=1)

        system_prompt = (
            COMPACT_SYSTEM_PROMPT if self.output_format == "compact" else
            get_system_prompt(include_text_variations=False, source_text=analysis.text)
        )
        original_plan = analysis.text
        source_facts = self._extract_workout_facts_from_source_text(original_plan)
        user_message = self._build_source_expectations_prompt(analysis) + original_plan
        last_errors: list[str] = []
        last_categories: dict[str, list[str]] = {}
        generation_id = uuid.uuid4().hex
        self._emit_trace(
            "generation_started",
            generation_id=generation_id,
            source_sha256=hashlib.sha256(original_plan.encode("utf-8")).hexdigest(),
            source_chars=len(original_plan),
            expected_workouts=analysis.expected_workouts,
            model=self.model,
            api_type=self.api_type,
            output_format=self.output_format,
            openai_mode=self.openai_mode if self.api_type == "openai" else None,
        )

        for attempt in range(1, max_retries + 1):
            logger.info(f"LLM attempt {attempt}/{max_retries}...")

            old_trace_fields = self._trace_fields
            self._trace_fields = {"generation_id": generation_id, "attempt": attempt}
            try:
                raw_response = self._call_llm(system_prompt, user_message)
            finally:
                self._trace_fields = old_trace_fields
            truncated = (
                self._last_call_metrics.get("done_reason") == "length"
                or self._last_call_metrics.get("finish_reason") == "length"
            )
            if not raw_response or truncated:
                last_errors = [
                    "LLM response stopped at the token limit; increase the output budget or shorten the input"
                    if truncated else "Empty response from LLM"
                ]
                logger.warning("Attempt %d: %s", attempt, last_errors[0])
                last_categories = {"llm_error": last_errors[:]}
                self._emit_trace(
                    "candidate_rejected",
                    generation_id=generation_id,
                    attempt=attempt,
                    validation_errors=last_errors,
                    error_categories=last_categories,
                )
                continue

            compact_warnings: list[str] = []
            try:
                if self.output_format == "compact":
                    yaml_text, compact_warnings = compact_to_yaml(
                        raw_response, hr_zones=self.rule_hr_zones,
                    )
                else:
                    yaml_text = self._extract_yaml(raw_response)
            except CompactFormatError as exc:
                message = f"Compact format: {exc}"
                prepared = GeneratedYamlResult(
                    validation_errors=[message],
                    error_categories={"compact_format": [message]},
                )
            else:
                prepared = self._prepare_yaml_candidate(
                    yaml_text,
                    analysis_repairs=analysis.changes,
                    analysis_ambiguities=analysis.ambiguities,
                    expected_workout_count=analysis.expected_workouts,
                    source_text=original_plan,
                    repair_plan_data=repair_plan_data,
                    validate_plan_data_detailed=validate_plan_data_detailed,
                    group_issues_by_category=group_issues_by_category,
                )
                prepared.warnings.extend(compact_warnings)
            self._apply_source_fact_consistency_checks(prepared, source_facts)
            self._demote_source_fact_mismatch(prepared)
            prepared.attempts = attempt

            self._emit_trace(
                "candidate_validated",
                generation_id=generation_id,
                attempt=attempt,
                passed=not prepared.validation_errors and prepared.yaml_text is not None,
                validation_errors=prepared.validation_errors,
                error_categories=prepared.error_categories,
                warnings=prepared.warnings,
                repairs=prepared.repairs,
                workout_count=(len(prepared.data.get("workouts", [])) if prepared.data else 0),
            )

            for warning in prepared.warnings:
                logger.warning(f"Validation warning: {warning}")

            if not prepared.validation_errors and prepared.yaml_text and prepared.data is not None:
                if size_warning:
                    prepared.warnings.insert(0, size_warning)
                logger.info(f"Valid YAML generated on attempt {attempt}")
                self._emit_trace(
                    "generation_finished",
                    generation_id=generation_id,
                    attempts=attempt,
                    passed=True,
                )
                return prepared

            last_errors = prepared.validation_errors
            last_categories = prepared.error_categories
            logger.warning(
                f"Attempt {attempt} failed with {len(prepared.validation_errors)} validation errors"
            )
            for error in prepared.validation_errors[:5]:
                logger.warning(f"  {error}")

            if self.output_format == "compact":
                user_message = (
                    "Your previous line-protocol response was invalid. Return the full W/S/R/E/B "
                    "response again, fixing these errors only:\n"
                    + "\n".join(last_errors[:5]) + "\n\nOriginal plan:\n" + original_plan
                )
            else:
                user_message = self._build_retry_prompt(
                    original_plan=original_plan,
                    issues=_issues_from_categories(last_categories),
                    source_facts_text=self._format_source_facts_for_retry_prompt(source_facts),
                )
            user_message = self._build_source_expectations_prompt(analysis) + user_message

        logger.error(f"Failed to generate valid YAML after {max_retries} attempts")
        self._emit_trace(
            "generation_finished",
            generation_id=generation_id,
            attempts=max_retries,
            passed=False,
            validation_errors=last_errors,
            error_categories=last_categories,
        )
        return GeneratedYamlResult(
            warnings=[size_warning] if size_warning else [],
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
        self._check_cancelled()
        self._last_call_metrics = {}
        self._emit_trace(
            "llm_request",
            system_sha256=hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
            user_sha256=hashlib.sha256(user_message.encode("utf-8")).hexdigest(),
            system_chars=len(system_prompt),
            user_chars=len(user_message),
            timeout_sec=self.request_timeout_sec,
        )
        started = time.perf_counter()
        raw_response = self._call_llm_raw(messages=messages, timeout=self.request_timeout_sec)
        elapsed = time.perf_counter() - started
        self._last_call_metrics["client_elapsed_sec"] = round(elapsed, 6)
        self._emit_trace(
            "llm_response",
            response_received=bool(raw_response),
            raw_response=raw_response,
            **self._last_call_metrics,
        )
        return raw_response

    def _call_llm_raw(self, messages: list, timeout: int = 300) -> Optional[str]:
        if self.api_type == "ollama":
            return self._call_ollama(messages, timeout)
        if self.api_type == "openai":
            return self._call_openai(messages, timeout)

        logger.error(f"Unknown api_type: {self.api_type}")
        return None

    def _call_ollama(self, messages: list, timeout: int) -> Optional[str]:
        """Call Ollama /api/chat with streaming.

        Streaming lets the caller cancel mid-generation (a CPU answer can take
        minutes) and see progress in tokens; the final chunk carries the same
        timing metrics as a non-streamed response.
        """
        import requests

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "think": False,
            "options": dict(self.ollama_options),
        }
        if self.ollama_keep_alive:
            payload["keep_alive"] = self.ollama_keep_alive

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=timeout,
                stream=True,
            )
            if response.status_code != 200:
                logger.error(f"Ollama API error: {response.status_code}")
                return None

            parts: list[str] = []
            chunks = 0
            try:
                for raw_line in response.iter_lines():
                    if self.cancel_event is not None and self.cancel_event.is_set():
                        raise GenerationCancelled("Generation cancelled")
                    if not raw_line:
                        continue
                    chunk = json.loads(raw_line)
                    if chunk.get("error"):
                        logger.error(f"Ollama error: {chunk['error']}")
                        return None
                    piece = (chunk.get("message") or {}).get("content", "")
                    if piece:
                        parts.append(piece)
                        chunks += 1
                        if chunks % 10 == 0:
                            self._report_progress(stage="generating", tokens=chunks)
                    if chunk.get("done"):
                        for key in (
                            "model", "created_at", "done_reason", "total_duration", "load_duration",
                            "prompt_eval_count", "prompt_eval_duration", "prompt_eval_cached_count",
                            "eval_count", "eval_duration",
                        ):
                            if key in chunk:
                                self._last_call_metrics[key] = chunk[key]
                        break
            finally:
                response.close()
            content = "".join(parts)
            return content if content else None

        except GenerationCancelled:
            raise
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
        self._last_call_metrics.pop("finish_reason", None)
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
                # Disable reasoning/thinking mode for Gemma-4, Qwen3, and similar
                # local models that auto-activate "thinking" on complex prompts.
                # LM Studio passes these through to the underlying llama.cpp server.
                extra_body={
                    "chat_template_kwargs": {"enable_thinking": False},
                    "thinking": {"type": "disabled"},
                },
            )
            content = response.choices[0].message.content
            usage = getattr(response, "usage", None)
            self._last_call_metrics.update({
                "server_model": getattr(response, "model", self.model),
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
                "finish_reason": getattr(response.choices[0], "finish_reason", None),
            })
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

            response_data = json.loads(body)
            usage = response_data.get("usage") or {}
            self._last_call_metrics.update({
                "server_model": response_data.get("model", self.model),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            })
            choices = response_data.get("choices", [])
            if not choices:
                logger.error("OpenAI-compatible completions returned no choices")
                return None

            self._last_call_metrics["finish_reason"] = choices[0].get("finish_reason")
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
    def _prepare_yaml_candidate(
        yaml_text: str,
        *,
        analysis_repairs: list[str],
        analysis_ambiguities: list[str],
        expected_workout_count: int,
        source_text: str = "",
        repair_plan_data,
        validate_plan_data_detailed,
        group_issues_by_category,
    ) -> GeneratedYamlResult:
        try:
            data = yaml.safe_load(yaml_text)
        except yaml.YAMLError as exc:
            repaired_text = UnifiedLLMClient._quote_desc_colons(yaml_text)
            if repaired_text != yaml_text:
                try:
                    data = yaml.safe_load(repaired_text)
                    analysis_repairs = analysis_repairs + [
                        "quoted an unquoted description containing a colon so YAML can be parsed"
                    ]
                except yaml.YAMLError:
                    data = None
            else:
                data = None
            if data is None:
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

        from .marked_source_checks import (
            compile_marked_source_repeats,
            sanitize_marked_source_targets,
            validate_marked_source_structure,
        )

        repeat_repairs, repeat_warnings = compile_marked_source_repeats(
            source_text,
            data,
        )
        repaired_data, repair_notes = repair_plan_data(data)
        repair_notes.extend(repeat_repairs)
        target_repairs, target_warnings = sanitize_marked_source_targets(
            source_text,
            repaired_data,
        )
        repair_notes.extend(target_repairs)
        errors, warnings = validate_plan_data_detailed(
            repaired_data,
            enforce_filename_name_match=True,
        )
        structure_errors = validate_marked_source_structure(source_text, repaired_data)

        warning_messages = list(dict.fromkeys(
            [issue.message for issue in warnings] + target_warnings + repeat_warnings
        ))
        error_messages = [issue.message for issue in errors] + structure_errors

        if not errors and not structure_errors:
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
            error_categories={
                **group_issues_by_category(errors),
                **({"marked_source_structure": structure_errors} if structure_errors else {}),
            },
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
        """Generate one workout per request and merge the results.

        A failed workout no longer discards the ones that succeeded: they are
        returned as a valid plan and the failures are listed in
        ``failed_segments`` (and as warnings) so only those need fixing.
        """
        repairs: list[str] = list(analysis.changes)
        ambiguities: list[str] = list(analysis.ambiguities)
        shared_context = (getattr(analysis, "shared_context", "") or "").strip()
        if len(shared_context) > MAX_SHARED_CONTEXT_CHARS:
            logger.info("Shared plan notes truncated to %d chars per segment", MAX_SHARED_CONTEXT_CHARS)
            shared_context = shared_context[:MAX_SHARED_CONTEXT_CHARS]
        total = len(analysis.workout_blocks)
        self._segmenting = True
        try:
            return self._generate_segments(
                analysis, total, shared_context, max_retries, repairs, ambiguities,
                repair_plan_data, validate_plan_data_detailed, group_issues_by_category,
            )
        finally:
            self._segmenting = False

    def _generate_segments(
        self, analysis, total, shared_context, max_retries, repairs, ambiguities,
        repair_plan_data, validate_plan_data_detailed, group_issues_by_category,
    ) -> GeneratedYamlResult:
        merged_workouts: list[dict[str, Any]] = []
        merged_sources: list[str] = []
        failed: list[dict[str, Any]] = []
        attempts = 0
        for index, block_text in enumerate(analysis.workout_blocks, start=1):
            self._report_progress(stage="segment", segment=index, total=total)
            self._check_cancelled()
            logger.info(f"Segmented LLM generation for workout {index}/{total}...")
            rule_workout = self._workout_from_rules(block_text)
            if rule_workout is not None:
                logger.info(f"segment {index}: parsed by deterministic rules (no LLM)")
                repairs.append(f"workouts[{len(merged_workouts)}]: parsed by deterministic rules (no LLM)")
                merged_workouts.append(rule_workout)
                merged_sources.append(block_text)
                continue
            reference_day = _reference_day(block_text)
            if reference_day is not None:
                copied, reference_error = self._copy_referenced_day(
                    block_text, reference_day, merged_workouts, merged_sources,
                )
                if copied is None:
                    failed.append({
                        "index": index,
                        "header": block_text.splitlines()[0].strip(),
                        "error": reference_error,
                        "source": block_text,
                    })
                else:
                    repairs.append(f"workouts[{len(merged_workouts)}]: copied an explicit previous-day workout")
                    merged_workouts.append(copied)
                    merged_sources.append(block_text)
                continue
            segment_fact = self._extract_single_workout_fact(block_text)
            segment_workout, segment_error = self._generate_and_validate_segment_workout(
                block_text=block_text,
                fact=segment_fact,
                max_retries=max_retries,
                segment_index=index,
                shared_context=shared_context,
            )
            attempts += max_retries  # Upper bound approximation for nested generation.
            if segment_error or segment_workout is None:
                error = segment_error or f"segment {index}: empty result"
                logger.warning(error)
                failed.append({
                    "index": index,
                    "header": block_text.splitlines()[0].strip() if block_text.strip() else "",
                    "error": error,
                    "source": block_text,
                })
                continue
            merged_workouts.append(segment_workout)
            merged_sources.append(block_text)

        if not merged_workouts:
            errors = [item["error"] for item in failed]
            return GeneratedYamlResult(
                repairs=repairs,
                ambiguities=ambiguities,
                validation_errors=errors,
                error_categories={"segmented_generation_error": errors},
                attempts=attempts,
                failed_segments=failed,
            )

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
            expected_workout_count=len(merged_workouts),
            source_text="\n\n".join(merged_sources) if failed else getattr(analysis, "text", ""),
            repair_plan_data=repair_plan_data,
            validate_plan_data_detailed=validate_plan_data_detailed,
            group_issues_by_category=group_issues_by_category,
        )
        failure_warnings = [
            f"Workout {item['index']} ({item['header']}) was not generated: {item['error']}"
            for item in failed
        ]
        merged_result.warnings = failure_warnings + merged_result.warnings
        merged_result.failed_segments = failed
        merged_result.attempts = attempts
        return merged_result

    @staticmethod
    def _with_shared_context(block_text: str, shared_context: str) -> str:
        """Prepend plan-wide notes (zones, paces) that a single workout may refer to."""
        if not shared_context:
            return block_text
        return f"Plan-wide notes (apply to every workout):\n{shared_context}\n\n{block_text}"

    def _segment_cache_path(self, prompt_text: str) -> Path | None:
        if self.segment_cache_dir is None:
            return None
        from ..plan_processing import normalize_source_text
        from .prompt import get_system_prompt

        if self.output_format == "compact":
            from .compact_plan import COMPACT_SYSTEM_PROMPT

            system_prompt = COMPACT_SYSTEM_PROMPT
        else:
            system_prompt = get_system_prompt(
                include_text_variations=False,
                source_text=normalize_source_text(prompt_text).text,
            )
        key_material = json.dumps(
            [
                SEGMENT_CACHE_VERSION,
                self.api_type,
                self.model,
                self.openai_mode,
                self.output_format,
                sorted(self.ollama_options.items()),
                system_prompt,
                prompt_text,
            ],
            ensure_ascii=False,
            default=str,
        )
        digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
        return self.segment_cache_dir / f"{digest}.json"

    def _load_cached_segment(self, path: Path | None) -> dict[str, Any] | None:
        if path is None or not path.exists():
            return None
        try:
            workout = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.info("Ignoring unreadable segment cache %s: %s", path.name, exc)
            return None
        return workout if isinstance(workout, dict) else None

    def _store_cached_segment(self, path: Path | None, workout: dict[str, Any]) -> None:
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(workout, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
            prune_directory(path.parent, "*.json", SEGMENT_CACHE_MAX_FILES)
        except OSError as exc:
            logger.info("Could not write segment cache %s: %s", path.name, exc)

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

    @staticmethod
    def _demote_source_fact_mismatch(result: GeneratedYamlResult) -> None:
        """Keep source fact heuristics visible without triggering LLM retries."""
        msgs = result.error_categories.pop("source_fact_mismatch", [])
        if not msgs:
            return

        result.warnings.extend(msgs)
        result.validation_errors = [
            error for error in result.validation_errors if error not in msgs
        ]

    def _generate_and_validate_segment_workout(
        self,
        *,
        block_text: str,
        fact: SourceWorkoutFact | None,
        max_retries: int,
        segment_index: int,
        shared_context: str = "",
    ) -> tuple[dict[str, Any] | None, str | None]:
        prompt_text = self._with_shared_context(block_text, shared_context)
        cache_path = self._segment_cache_path(prompt_text)
        cached = self._load_cached_segment(cache_path)
        if cached is not None:
            logger.info(f"segment {segment_index}: reused cached result")
            self._report_progress(stage="cached", segment=segment_index)
            return cached, None
        last_error: str | None = None

        for retry_idx in range(SUSPICIOUS_SEGMENT_RETRIES + 1):
            segment_result = self.generate_yaml_draft(prompt_text, max_retries=max_retries)
            if segment_result.validation_errors or not isinstance(segment_result.data, dict):
                details = "; ".join(segment_result.validation_errors[:3]) or "empty result"
                last_error = f"segment {segment_index}: {details}"
                if retry_idx >= SUSPICIOUS_SEGMENT_RETRIES:
                    return None, last_error
                logger.warning(last_error)
                prompt_text = self._with_shared_context(
                    self._build_segment_fact_retry_input(block_text, fact, [details]),
                    shared_context,
                )
                continue

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

            self._repair_missing_source_repeat(workout, fact)
            self._encode_source_hr_cap(workout, fact)
            suspicious = self._detect_suspicious_workout_against_fact(workout, fact)
            if not suspicious:
                self._store_cached_segment(cache_path, workout)
                return workout, None

            last_error = f"segment {segment_index}: suspicious output ({'; '.join(suspicious[:3])})"
            if retry_idx >= SUSPICIOUS_SEGMENT_RETRIES:
                break
            logger.warning(last_error)
            prompt_text = self._with_shared_context(
                self._build_segment_fact_retry_input(block_text, fact, suspicious),
                shared_context,
            )

        return None, last_error or f"segment {segment_index}: suspicious output"

    def _copy_referenced_day(
        self,
        block_text: str,
        weekday: str,
        workouts: list[dict[str, Any]],
        sources: list[str],
    ) -> tuple[dict[str, Any] | None, str]:
        """Resolve an isolated 'повторить вторник' within the prior seven days."""
        from datetime import date

        current = self._extract_segment_header_info(block_text)
        if current is None:
            return None, "reference needs a dated workout header"
        current_date = date.fromisoformat(current["date_iso"])
        matches: list[dict[str, Any]] = []
        for workout, source in zip(workouts, sources):
            previous = self._extract_segment_header_info(source)
            if previous is None or previous["weekday"] != weekday:
                continue
            days = (current_date - date.fromisoformat(previous["date_iso"])).days
            if 0 < days <= 7:
                matches.append(workout)
        if len(matches) != 1:
            return None, f"reference to {weekday} has {len(matches)} matching previous workouts; specify the steps"
        copied = copy.deepcopy(matches[0])
        self._align_workout_identifier_with_source_header(
            copied,
            month=current["month"], day=current["day"],
            week=current["week"], weekday=current["weekday"],
        )
        return copied, ""


def _reference_day(block_text: str) -> str | None:
    """Only a whole-body reference is safe to copy; mixed instructions go to the LLM."""
    lines = [line.strip().rstrip(". ") for line in block_text.splitlines() if line.strip()]
    if len(lines) not in {1, 2}:
        return None
    match = re.fullmatch(
        r"(?:повтори(?:ть)?(?:\s+тренировку)?|как(?:\s+в)?)\s+"
        r"(?:(?:с|в|во)\s+)?([а-яёa-z]+)", lines[-1], re.IGNORECASE,
    )
    if match is None:
        return None
    return source_facts.normalize_weekday_token(match.group(1))


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
