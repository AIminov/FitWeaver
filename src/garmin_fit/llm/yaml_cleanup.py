"""Cleanup of raw model answers before YAML parsing.

Extracts the YAML block, strips reasoning text and markdown fences, fixes
common indentation and quoting problems, and decides whether an
OpenAI-compatible chat answer needs the completions fallback. Moved out of
``client.py``; the client keeps aliases with the old names.
"""

from __future__ import annotations

import re
from typing import Any, Optional


def extract_yaml(text: str) -> str:
    """Extract YAML from markdown code block or return raw text."""
    match = re.search(r"```yaml\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return sanitize_yaml_candidate(match.group(1).strip())

    match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return sanitize_yaml_candidate(match.group(1).strip())

    return sanitize_yaml_candidate(text.strip())


def messages_to_completion_prompt(messages: list[dict[str, Any]]) -> str:
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


def sanitize_yaml_candidate(text: str) -> str:
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

    if candidate.startswith("workouts:"):
        candidate = normalize_workout_yaml_indentation(candidate)

    # Fix erroneous "- key:" prefix on workout-level keys only (not drill list items at 6+ spaces)
    candidate = re.sub(
        r"(?m)^( {2,4})- (name|desc|type_code|distance_km|estimated_duration_min|steps):",
        r"\1\2:",
        candidate,
    )
    return candidate


def normalize_workout_yaml_indentation(candidate: str) -> str:
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

        if stripped == "steps:" and not in_steps:
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


def quote_desc_colons(yaml_text: str) -> str:
    """Quote plain description scalars with ``: `` that break YAML parsing."""
    changed = False
    output: list[str] = []
    for line in yaml_text.splitlines():
        match = re.match(r"^(\s*(?:-\s*)?desc:\s*)(.*)$", line)
        if match:
            value = match.group(2)
            if ": " in value and not value.startswith(("'", '"', "|", ">")):
                value = "'" + value.replace("'", "''") + "'"
                line = match.group(1) + value
                changed = True
        output.append(line)
    return "\n".join(output) + ("\n" if yaml_text.endswith("\n") else "") if changed else yaml_text


def openai_chat_response_needs_fallback(content: Optional[str]) -> bool:
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


def describe_openai_fallback_reason(content: Optional[str]) -> str:
    if not content or not content.strip():
        return "empty response"
    if openai_chat_response_needs_fallback(content):
        return "chat response contained reasoning instead of YAML"
    return "chat response was not usable"
