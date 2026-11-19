"""Display the marked plan without its parser delimiters."""


def render_plan_preview(marked: str) -> str:
    lines = []
    depth = 0
    for raw in marked.splitlines():
        line = raw.strip()
        if line.startswith("==== ТРЕНИРОВКА ===="):
            depth = 0
            lines.extend(("", line.removeprefix("==== ТРЕНИРОВКА ====").strip()))
        elif line == "**** КОНЕЦ ПОВТОРА ****":
            depth = max(0, depth - 1)
        elif line.startswith("**** ПОВТОР:") and line.endswith("****"):
            lines.append(f"{'    ' * depth}↻ {line[4:-4].strip().capitalize()}")
            depth += 1
        elif line == "**** ШАГ ****":
            lines.append("")
        elif line.startswith("Тип:"):
            lines.append(f"{'    ' * depth}• {line[4:].strip().capitalize()}")
        elif line:
            lines.append(f"{'    ' * depth}{line}")
    return "\n".join(lines).strip()
