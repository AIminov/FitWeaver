"""Visual workout builder tab methods for the desktop application."""

from __future__ import annotations

import datetime
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import yaml

from .fileio import atomic_write_text
from .gui_messages import ru_count
from .gui_palette import (
    BG,
    BG2,
    BG3,
    DEFAULT_WO_COLOR,
    FG,
    GREEN,
    MUTED,
    PURPLE,
    RED,
    STEP_INTENSITY_COLORS,
    YELLOW,
)
from .gui_validation import parse_builder_value, parse_repeat_count

# Editable field set per step_type for the builder's generic block editor.
# (field_attr_name, label, python_type)
_STEP_TYPE_FIELDS = {
    "dist_open": (("km", "Расстояние (км)", float),),
    "dist_hr": (
        ("km", "Расстояние (км)", float),
        ("hr_low", "Пульс от", int),
        ("hr_high", "Пульс до", int),
    ),
    "dist_pace": (
        ("km", "Расстояние (км)", float),
        ("pace_fast", "Темп быстрый (мм:сс)", str),
        ("pace_slow", "Темп медленный (мм:сс)", str),
    ),
    "dist_cadence": (
        ("km", "Расстояние (км)", float),
        ("cad_low", "Частота шагов от (шаг/мин)", int),
        ("cad_high", "Частота шагов до (шаг/мин)", int),
    ),
    "time_open": (("seconds", "Длительность (сек)", int),),
    "time_hr": (
        ("seconds", "Длительность (сек)", int),
        ("hr_low", "Пульс от", int),
        ("hr_high", "Пульс до", int),
    ),
    "time_pace": (
        ("seconds", "Длительность (сек)", int),
        ("pace_fast", "Темп быстрый (мм:сс)", str),
        ("pace_slow", "Темп медленный (мм:сс)", str),
    ),
    "time_cadence": (
        ("seconds", "Длительность (сек)", int),
        ("cad_low", "Частота шагов от (шаг/мин)", int),
        ("cad_high", "Частота шагов до (шаг/мин)", int),
    ),
}


class BuilderTabMixin:
    # ── Builder tab (visual, no-LLM workout construction) ─────────────────────
    def _build_builder_tab(self, parent):
        from garmin_fit.workout_builder import BLOCK_DEFS, TEMPLATES

        self._build_page_header(
            parent, "Визуальный конструктор", "Соберите новую тренировку из блоков, шаблонов и повторов")
        # Top bar: filename + templates
        top = ttk.Frame(parent)
        top.pack(fill="x", pady=(0, 4))
        ttk.Label(top, text="Тренировка:", style="Muted.TLabel").pack(side="left")
        self._builder_filename_var = tk.StringVar()
        ttk.Entry(top, textvariable=self._builder_filename_var, width=32).pack(
            side="left", padx=(4, 12))
        ttk.Label(top, text="Дата и тип задаются в имени Wнеделя_ММ-ДД_…",
                  style="Muted.TLabel").pack(side="left", padx=(0, 8))
        for key, (label, _factory) in TEMPLATES.items():
            ttk.Button(top, text=label,
                       command=lambda k=key: self._builder_apply_template(k)).pack(side="left", padx=2)
        ttk.Button(top, text="Очистить", command=self._builder_clear).pack(side="left", padx=(12, 2))
        tk.Label(parent, text="Имя по шаблону W{неделя}_{ММ-ДД}_{День}_{Тип}_{Детали}, "
                              "иначе тренировка не появится в календаре по дате",
                 bg=BG, fg=MUTED, font=("Segoe UI", 8), anchor="w").pack(fill="x", pady=(0, 6))

        # Personal template library (per-profile)
        my_templates_bar = ttk.Frame(parent)
        my_templates_bar.pack(fill="x", pady=(0, 6))
        ttk.Label(my_templates_bar, text="Мои шаблоны:", style="Muted.TLabel").pack(side="left")
        self._builder_my_templates_frame = ttk.Frame(my_templates_bar)
        self._builder_my_templates_frame.pack(side="left", padx=(6, 12))
        ttk.Button(my_templates_bar, text="💾  Сохранить как шаблон",
                   command=self._builder_save_as_template).pack(side="left")

        ttk.Separator(parent).pack(fill="x", pady=(0, 6))

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)

        # Palette
        palette = tk.Frame(body, bg=BG, width=170)
        palette.pack(side="left", fill="y")
        palette.pack_propagate(False)
        ttk.Label(palette, text="БЛОКИ", style="Section.TLabel").pack(anchor="w", pady=(0, 4))
        for key, block_def in BLOCK_DEFS.items():
            ttk.Button(palette, text=block_def.label,
                       command=lambda k=key: self._builder_add_block(k)).pack(fill="x", pady=2)

        ttk.Separator(body, orient="vertical").pack(side="left", fill="y", padx=4)

        # Sequence list
        sequence = ttk.Frame(body)
        sequence.pack(side="left", fill="both", expand=True)

        repeat_bar = ttk.Frame(sequence)
        repeat_bar.pack(fill="x", pady=(0, 4))
        self._builder_repeat_btn = ttk.Button(
            repeat_bar, text="🔁  Повторить ×N", state="disabled", command=self._builder_add_repeat)
        self._builder_repeat_btn.pack(side="left")
        self._builder_repeat_count = tk.StringVar(value="4")
        ttk.Spinbox(repeat_bar, from_=2, to=20, textvariable=self._builder_repeat_count,
                    width=4).pack(side="left", padx=(6, 6))
        tk.Label(repeat_bar, text="выделите блоки: клик, затем Shift+клик",
                 bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(side="left")

        seq_container = ttk.Frame(sequence)
        seq_container.pack(fill="both", expand=True)
        self._builder_canvas = tk.Canvas(seq_container, bg=BG2, highlightthickness=0)
        seq_vsb = ttk.Scrollbar(seq_container, orient="vertical", command=self._builder_canvas.yview)
        self._builder_canvas.configure(yscrollcommand=seq_vsb.set)
        seq_vsb.pack(side="right", fill="y")
        self._builder_canvas.pack(side="left", fill="both", expand=True)

        self._builder_list_frame = tk.Frame(self._builder_canvas, bg=BG2)
        self._builder_list_win = self._builder_canvas.create_window(
            (0, 0), window=self._builder_list_frame, anchor="nw")
        self._builder_list_frame.bind("<Configure>", self._builder_on_frame_resize)
        self._builder_canvas.bind("<Configure>", self._builder_on_canvas_resize)
        self._builder_canvas.bind("<MouseWheel>", self._builder_scroll)

        ttk.Separator(body, orient="vertical").pack(side="left", fill="y", padx=4)

        # Block editor
        self._builder_editor_frame = tk.Frame(body, bg=BG, width=250)
        self._builder_editor_frame.pack(side="left", fill="y")
        self._builder_editor_frame.pack_propagate(False)

        ttk.Separator(parent).pack(fill="x", pady=6)

        bottom = ttk.Frame(parent)
        bottom.pack(fill="x")
        self._builder_validation_lbl = tk.Label(bottom, text="Добавьте хотя бы один блок",
                                                 bg=BG, fg=MUTED, font=("Segoe UI", 9))
        self._builder_validation_lbl.pack(side="left")
        builder_actions = ttk.Frame(bottom)
        builder_actions.pack(side="right")
        self._builder_add_btn = ttk.Button(builder_actions, text="Добавить в локальный план",
                                           style="Primary.TButton", state="disabled",
                                           command=self._builder_commit)
        self._builder_add_btn.pack(side="left", padx=3)
        self._builder_save_yaml_btn = ttk.Button(
            builder_actions, text="Сохранить YAML", state="disabled",
            command=self._builder_export_yaml)
        self._builder_save_yaml_btn.pack(side="left", padx=3)
        self._builder_send_garmin_btn = ttk.Button(
            builder_actions, text="Отправить в Garmin", state="disabled",
            command=self._builder_send_to_garmin)
        self._builder_send_garmin_btn.pack(side="left", padx=3)

        self._builder_render_list()
        self._builder_render_editor()
        self._builder_refresh_my_templates()

    def _builder_scroll(self, e):
        self._builder_canvas.yview_scroll(-1 * (e.delta // 120), "units")

    def _builder_bind_wheel(self, widget):
        widget.bind("<MouseWheel>", self._builder_scroll)
        for child in widget.winfo_children():
            self._builder_bind_wheel(child)

    def _builder_on_frame_resize(self, _e=None):
        self._builder_canvas.configure(scrollregion=self._builder_canvas.bbox("all"))

    def _builder_on_canvas_resize(self, e):
        self._builder_canvas.itemconfig(self._builder_list_win, width=e.width)

    def _builder_hr_zones(self) -> dict[str, dict[str, int]]:
        email = self._active_profile_email
        if not email:
            return {}
        try:
            from garmin_fit.profile_store import user_profile_yaml_path

            path = user_profile_yaml_path(email)
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            zones = data.get("hr_zones", {}) if isinstance(data, dict) else {}
            return {
                str(name).lower(): {"low": int(bounds["low"]), "high": int(bounds["high"])}
                for name, bounds in zones.items()
                if isinstance(bounds, dict) and bounds.get("low") and bounds.get("high")
            }
        except (OSError, ValueError, TypeError, yaml.YAMLError):
            return {}

    def _builder_has_repeat(self) -> bool:
        return any(s.step_type == "repeat" for s in self._builder_steps)

    def _builder_add_block(self, key: str):
        from garmin_fit.workout_builder import BLOCK_DEFS
        step = BLOCK_DEFS[key].make()
        self._builder_steps.append(step)
        self._builder_select(len(self._builder_steps) - 1)

    def _builder_apply_template(self, key: str):
        from garmin_fit.workout_builder import TEMPLATES
        if self._builder_steps and not messagebox.askyesno(
                "Заменить черновик?",
                "Текущий черновик будет заменён шаблоном. Продолжить?"):
            return
        self._builder_edit_workout_id = None
        self._builder_garmin_edit_event = None
        self._builder_add_btn.config(text="Добавить в локальный план", command=self._builder_commit)
        _label, factory = TEMPLATES[key]
        self._builder_steps = factory()
        self._builder_range_start = self._builder_range_end = self._builder_selected_index = None
        self._builder_render_list()
        self._builder_render_editor()

    def _builder_clear(self):
        self._builder_steps = []
        self._builder_edit_workout_id = None
        self._builder_garmin_edit_event = None
        self._builder_filename_var.set("")
        self._builder_range_start = self._builder_range_end = self._builder_selected_index = None
        self._builder_render_list()
        self._builder_render_editor()
        self._builder_add_btn.config(text="Добавить в локальный план", command=self._builder_commit)

    # ── Personal template library (per-profile, separate from the 3
    #    built-in TEMPLATES) ──────────────────────────────────────────────
    def _builder_refresh_my_templates(self):
        for w in self._builder_my_templates_frame.winfo_children():
            w.destroy()
        if not self._active_profile_email:
            return
        from garmin_fit.profile_store import list_user_templates
        templates = list_user_templates(self._active_profile_email)
        for name in templates:
            row = ttk.Frame(self._builder_my_templates_frame)
            row.pack(side="left", padx=2)
            ttk.Button(row, text=name,
                       command=lambda n=name: self._builder_apply_my_template(n)).pack(side="left")
            tk.Button(row, text="✕", command=lambda n=name: self._builder_delete_my_template(n),
                      bg=BG, fg=RED, relief="flat", bd=0, font=("Segoe UI", 8),
                      cursor="hand2").pack(side="left")

    def _builder_save_as_template(self):
        if not self._active_profile_email:
            messagebox.showwarning(
                "Нет профиля", "Выберите или создайте профиль (email в сайдбаре), "
                "чтобы сохранять личные шаблоны.")
            return
        if not self._builder_steps:
            messagebox.showwarning("Пустой черновик", "Добавьте хотя бы один блок перед сохранением.")
            return
        name = simpledialog.askstring("Сохранить как шаблон", "Название шаблона:", parent=self)
        if not name:
            return
        from garmin_fit.plan_domain import step_to_data
        from garmin_fit.profile_store import save_user_template
        steps_data = [step_to_data(s) for s in self._builder_steps]
        save_user_template(self._active_profile_email, name.strip(), steps_data)
        self._log(f"[OK] Шаблон «{name}» сохранён")
        self._builder_refresh_my_templates()

    def _builder_apply_my_template(self, name: str):
        if self._builder_steps and not messagebox.askyesno(
                "Заменить черновик?",
                "Текущий черновик будет заменён шаблоном. Продолжить?"):
            return
        self._builder_edit_workout_id = None
        self._builder_garmin_edit_event = None
        self._builder_add_btn.config(text="Добавить в локальный план", command=self._builder_commit)
        from garmin_fit.plan_domain import step_from_data
        from garmin_fit.profile_store import list_user_templates
        steps_data = list_user_templates(self._active_profile_email).get(name, [])
        self._builder_steps = [step_from_data(s) for s in steps_data]
        self._builder_range_start = self._builder_range_end = self._builder_selected_index = None
        self._builder_render_list()
        self._builder_render_editor()

    def _builder_delete_my_template(self, name: str):
        if not messagebox.askyesno("Удалить шаблон", f"Удалить шаблон «{name}»?"):
            return
        from garmin_fit.profile_store import delete_user_template
        delete_user_template(self._active_profile_email, name)
        self._log(f"[OK] Шаблон «{name}» удалён")
        self._builder_refresh_my_templates()

    def _builder_select(self, idx: int):
        self._builder_range_start = idx
        self._builder_range_end = idx
        self._builder_selected_index = idx
        self._builder_render_list()
        self._builder_render_editor()

    def _builder_extend_range(self, idx: int):
        if self._builder_range_start is None:
            self._builder_select(idx)
            return
        self._builder_range_end = idx
        self._builder_render_list()

    def _builder_delete(self, idx: int):
        from garmin_fit.workout_builder import delete_step_from_draft
        try:
            delete_step_from_draft(self._builder_steps, idx)
        except ValueError as exc:
            messagebox.showinfo("Нельзя удалить шаг", str(exc), parent=self)
            return
        self._builder_range_start = self._builder_range_end = self._builder_selected_index = None
        self._builder_render_list()
        self._builder_render_editor()

    def _builder_move(self, idx: int, delta: int):
        if self._builder_has_repeat():
            messagebox.showinfo(
                "Нельзя переместить",
                "В тренировке уже есть блок повтора. Удалите его, чтобы менять "
                "порядок остальных шагов, затем добавьте заново.")
            return
        new_idx = idx + delta
        if not (0 <= new_idx < len(self._builder_steps)):
            return
        steps = self._builder_steps
        steps[idx], steps[new_idx] = steps[new_idx], steps[idx]
        self._builder_selected_index = new_idx
        self._builder_range_start = self._builder_range_end = None
        self._builder_render_list()
        self._builder_render_editor()

    def _builder_add_repeat(self):
        from garmin_fit.workout_builder import insert_repeat_into_draft
        start, end = self._builder_range_start, self._builder_range_end
        if start is None or end is None:
            return
        lo, hi = min(start, end), max(start, end)
        try:
            count = int(self._builder_repeat_count.get())
        except (TypeError, ValueError):
            messagebox.showwarning("Некорректно", "Количество повторов должно быть числом.")
            return
        try:
            insert_repeat_into_draft(self._builder_steps, lo, hi, count)
        except ValueError as exc:
            messagebox.showwarning("Нельзя повторить", str(exc))
            return
        self._builder_range_start = self._builder_range_end = self._builder_selected_index = None
        self._builder_render_list()
        self._builder_render_editor()

    def _builder_update_repeat_button_state(self):
        start, end = self._builder_range_start, self._builder_range_end
        valid = False
        if start is not None and end is not None and self._builder_steps:
            from garmin_fit.workout_builder import compute_repeat_step

            lo, hi = min(start, end), max(start, end)
            try:
                # Whole existing groups may be nested; a cut through one may not.
                compute_repeat_step(self._builder_steps, lo, hi, 2)
                valid = True
            except ValueError:
                valid = False
        self._builder_repeat_btn.config(state="normal" if valid else "disabled")

    def _builder_summarize(self, idx: int, step) -> str:
        if step.step_type == "repeat":
            return f"🔁  ×{step.count}  (шаги {step.back_to_offset + 1}-{idx})"
        parts = []
        if step.km is not None:
            parts.append(f"{step.km} км")
        if step.seconds is not None:
            parts.append(f"{step.seconds} с")
        if step.hr_low is not None and step.hr_high is not None:
            parts.append(f"HR {step.hr_low}-{step.hr_high}")
        if step.pace_fast and step.pace_slow:
            parts.append(f"{step.pace_fast}-{step.pace_slow}")
        if step.cad_low is not None and step.cad_high is not None:
            parts.append(f"{step.cad_low}-{step.cad_high} шаг/мин")
        if step.step_type == "sbu_block":
            parts.append(f"{len(step.drills or [])} упражнений СБУ")
        body = " · ".join(parts) if parts else step.step_type
        intensity_ru = {"warmup": "Разминка", "active": "Активно",
                        "recovery": "Восст.", "cooldown": "Заминка"}.get(step.intensity)
        prefix = f"{intensity_ru}: " if intensity_ru else ""
        return f"{idx + 1}. {prefix}{body}"

    def _builder_row_bg(self, idx: int) -> str:
        start, end = self._builder_range_start, self._builder_range_end
        if start is not None and end is not None and min(start, end) <= idx <= max(start, end):
            return BG3
        return BG2

    def _builder_render_row(self, idx: int, step):
        bg = self._builder_row_bg(idx)
        row = tk.Frame(self._builder_list_frame, bg=bg, pady=2)
        row.pack(fill="x", padx=4, pady=1)

        color = PURPLE if step.step_type == "repeat" else STEP_INTENSITY_COLORS.get(
            step.intensity, DEFAULT_WO_COLOR)
        tk.Label(row, text=" ", bg=color, width=2).pack(side="left", padx=(4, 6))

        lbl = tk.Label(row, text=self._builder_summarize(idx, step), bg=bg, fg=FG,
                       font=("Segoe UI", 9), anchor="w")
        lbl.pack(side="left", fill="x", expand=True)

        for widget in (row, lbl):
            widget.bind("<Button-1>", lambda e, i=idx: self._builder_select(i))
            widget.bind("<Shift-Button-1>", lambda e, i=idx: self._builder_extend_range(i))

        tk.Button(row, text="✕", command=lambda i=idx: self._builder_delete(i),
                  bg=bg, fg=RED, relief="flat", bd=0, font=("Segoe UI", 9),
                  cursor="hand2").pack(side="right", padx=4)
        if step.step_type != "repeat":
            tk.Button(row, text="▼", command=lambda i=idx: self._builder_move(i, 1),
                      bg=bg, fg=FG, relief="flat", bd=0, font=("Segoe UI", 7),
                      cursor="hand2").pack(side="right", padx=1)
            tk.Button(row, text="▲", command=lambda i=idx: self._builder_move(i, -1),
                      bg=bg, fg=FG, relief="flat", bd=0, font=("Segoe UI", 7),
                      cursor="hand2").pack(side="right", padx=1)

    def _builder_render_list(self):
        for w in self._builder_list_frame.winfo_children():
            w.destroy()
        for idx, step in enumerate(self._builder_steps):
            self._builder_render_row(idx, step)
        self._builder_bind_wheel(self._builder_list_frame)
        self._builder_update_repeat_button_state()
        self._builder_update_validation()

    def _builder_render_editor(self):
        for w in self._builder_editor_frame.winfo_children():
            w.destroy()
        self._builder_input_errors.clear()
        idx = self._builder_selected_index
        if idx is None or not (0 <= idx < len(self._builder_steps)):
            tk.Label(self._builder_editor_frame, text="Выберите блок слева",
                     bg=BG, fg=MUTED, font=("Segoe UI", 9), wraplength=230,
                     justify="left").pack(anchor="w", pady=8)
            return
        step = self._builder_steps[idx]
        ttk.Label(self._builder_editor_frame, text=f"Блок №{idx + 1}",
                  style="Section.TLabel").pack(anchor="w", pady=(4, 8))

        if step.step_type == "repeat":
            ttk.Label(self._builder_editor_frame, text="Повторов:",
                      style="Muted.TLabel").pack(anchor="w")
            count_var = tk.StringVar(value=str(step.count))
            count_error = tk.StringVar()

            def _on_count_change(_e=None, target_entry=None, s=step, v=count_var,
                                 err=count_error):
                value, error = parse_repeat_count(v.get())
                err.set(error or "")
                target_entry.configure(style="Invalid.TEntry" if error else "TEntry")
                if error:
                    self._builder_input_errors.add((idx, "count"))
                    self._builder_update_validation()
                    target_entry.focus_set()
                    return
                self._builder_input_errors.discard((idx, "count"))
                s.count = value
                self._builder_render_list()

            entry = ttk.Entry(self._builder_editor_frame, textvariable=count_var, width=8)
            entry.pack(anchor="w")
            entry.bind("<FocusOut>", lambda e, fn=_on_count_change, target=entry: fn(e, target))
            entry.bind("<Return>", lambda e, fn=_on_count_change, target=entry: fn(e, target))
            ttk.Label(self._builder_editor_frame, textvariable=count_error,
                      style="Error.TLabel", wraplength=230, justify="left").pack(
                          anchor="w", pady=(2, 6))
            ttk.Label(self._builder_editor_frame,
                      text=f"Повторяет шаги {step.back_to_offset + 1}-{idx}",
                      style="Muted.TLabel", wraplength=230, justify="left").pack(anchor="w")
            return

        if step.step_type == "sbu_block":
            ttk.Label(self._builder_editor_frame, text="Упражнения СБУ (по умолчанию):",
                      style="Muted.TLabel", wraplength=230, justify="left").pack(anchor="w", pady=(0, 4))
            for d in (step.drills or []):
                tk.Label(self._builder_editor_frame, text=f"· {d.name} — {d.seconds}с × {d.reps}",
                         bg=BG, fg=FG, font=("Segoe UI", 9), anchor="w").pack(anchor="w")
            return

        for field_name, label, py_type in _STEP_TYPE_FIELDS.get(step.step_type, ()):
            ttk.Label(self._builder_editor_frame, text=f"{label}:",
                      style="Muted.TLabel").pack(anchor="w")
            current = getattr(step, field_name)
            var = tk.StringVar(value="" if current is None else str(current))
            field_error = tk.StringVar()

            def _on_field_change(_e=None, target_entry=None, s=step, fn=field_name,
                                 v=var, t=py_type, err=field_error):
                value, error = parse_builder_value(fn, v.get(), t)
                err.set(error or "")
                target_entry.configure(style="Invalid.TEntry" if error else "TEntry")
                if error:
                    self._builder_input_errors.add((idx, fn))
                    self._builder_update_validation()
                    target_entry.focus_set()
                    return
                self._builder_input_errors.discard((idx, fn))
                setattr(s, fn, value)
                self._builder_render_list()

            entry = ttk.Entry(self._builder_editor_frame, textvariable=var, width=16)
            entry.pack(anchor="w")
            entry.bind("<FocusOut>", lambda e, fn=_on_field_change, target=entry: fn(e, target))
            entry.bind("<Return>", lambda e, fn=_on_field_change, target=entry: fn(e, target))
            ttk.Label(self._builder_editor_frame, textvariable=field_error,
                      style="Error.TLabel", wraplength=230, justify="left").pack(
                          anchor="w", pady=(2, 6))

        if step.step_type in {"dist_hr", "time_hr"}:
            zones = self._builder_hr_zones()
            zone_choices = {
                f"Z{index} · {zones.get(f'zone{index}', {}).get('low', '?')}–"
                f"{zones.get(f'zone{index}', {}).get('high', '?')} bpm": zones[f"zone{index}"]
                for index in range(1, 6) if f"zone{index}" in zones
            }
            if zone_choices:
                ttk.Label(self._builder_editor_frame, text="Подставить пульсовую зону:",
                          style="Muted.TLabel").pack(anchor="w")
                zone_var = tk.StringVar()

                def _apply_zone(_e=None, s=step, v=zone_var, choices=zone_choices):
                    bounds = choices.get(v.get())
                    if bounds:
                        s.hr_low, s.hr_high = bounds["low"], bounds["high"]
                        self._builder_render_list()
                        self._builder_render_editor()
                        self._builder_update_validation()

                zone_cb = ttk.Combobox(
                    self._builder_editor_frame, textvariable=zone_var, width=25,
                    values=list(zone_choices), state="readonly")
                zone_cb.pack(anchor="w", pady=(0, 6))
                zone_cb.bind("<<ComboboxSelected>>", _apply_zone)
            else:
                ttk.Label(
                    self._builder_editor_frame,
                    text="Настройте пульсовые зоны в профиле, чтобы выбирать Z1–Z5.",
                    style="Muted.TLabel", wraplength=230, justify="left").pack(
                        anchor="w", pady=(0, 6))

        ttk.Label(self._builder_editor_frame, text="Интенсивность:",
                  style="Muted.TLabel").pack(anchor="w")
        intensity_var = tk.StringVar(value=step.intensity or "")

        def _on_intensity_change(_e=None, s=step, v=intensity_var):
            s.intensity = v.get() or None
            self._builder_render_list()

        cb = ttk.Combobox(self._builder_editor_frame, textvariable=intensity_var, width=13,
                          values=["warmup", "active", "recovery", "cooldown"], state="readonly")
        cb.pack(anchor="w", pady=(0, 6))
        cb.bind("<<ComboboxSelected>>", _on_intensity_change)

    def _builder_update_validation(self):
        from garmin_fit.workout_builder import validate_draft
        if self._builder_input_errors:
            self._builder_validation_lbl.config(
                text="Исправьте ошибки в полях блока", fg=RED)
            self._builder_add_btn.config(state="disabled")
            self._builder_update_action_availability(False)
            return
        filename = self._builder_filename_var.get().strip()
        if not self._builder_steps:
            self._builder_validation_lbl.config(text="Добавьте хотя бы один блок", fg=MUTED)
            self._builder_add_btn.config(state="disabled")
            self._builder_update_action_availability(False)
            return
        if not filename:
            self._builder_validation_lbl.config(text="Укажите имя тренировки", fg=YELLOW)
            self._builder_add_btn.config(state="disabled")
            self._builder_update_action_availability(False)
            return
        errors, warnings = validate_draft(filename, filename, self._builder_steps)
        if errors:
            self._builder_validation_lbl.config(text=f"Ошибка: {errors[0]}", fg=RED)
            self._builder_add_btn.config(state="disabled")
            self._builder_update_action_availability(False)
        elif warnings:
            self._builder_validation_lbl.config(
                text=(f"Готово, {ru_count(len(warnings), 'предупреждение', 'предупреждения', 'предупреждений')}"
                      if self._store is not None else
                      f"Готово · {len(warnings)} предупреждений; сохраните YAML или отправьте в Garmin"),
                fg=YELLOW)
            self._builder_add_btn.config(state="normal")
            self._builder_update_action_availability(True)
        else:
            self._builder_validation_lbl.config(
                text=("Готово к добавлению ✓" if self._store is not None else
                      "Готово · сохраните YAML или отправьте в Garmin"), fg=GREEN)
            self._builder_add_btn.config(state="normal")
            self._builder_update_action_availability(True)

    def _builder_update_action_availability(self, valid: bool) -> None:
        if not hasattr(self, "_builder_save_yaml_btn"):
            return
        self._builder_add_btn.configure(
            state="normal" if valid and (
                self._store is not None or (
                    self._builder_garmin_edit_event is not None
                    and self._builder_garmin_edit_event.get("profile_email")
                    == self._active_profile_email
                )
            ) else "disabled")
        self._builder_save_yaml_btn.configure(state="normal" if valid else "disabled")
        self._builder_send_garmin_btn.configure(
            state="normal" if valid and self._active_profile_email
            and self._builder_garmin_edit_event is None else "disabled")

    def _builder_current_workout(self):
        from garmin_fit.plan_domain import Workout

        filename = self._builder_filename_var.get().strip()
        if not filename or not self._builder_steps:
            return None
        return Workout(
            filename=filename,
            name=filename,
            desc="",
            type_code="mixed",
            steps=list(self._builder_steps),
        )

    def _builder_export_yaml(self) -> None:
        from garmin_fit.plan_domain import WorkoutPlan, plan_to_data
        from garmin_fit.workout_builder import validate_draft

        workout = self._builder_current_workout()
        if workout is None:
            return
        errors, _warnings = validate_draft(workout.filename, workout.name, workout.steps)
        if errors:
            messagebox.showwarning("Есть ошибки", "\n".join(errors), parent=self)
            return
        path = filedialog.asksaveasfilename(
            title="Сохранить тренировку в YAML",
            defaultextension=".yaml",
            filetypes=[("YAML files", "*.yaml"), ("All files", "*.*")],
            initialdir=self._project_root / "Plan",
            initialfile=f"{Path(workout.filename).stem}.yaml",
        )
        if not path:
            return
        data = plan_to_data(WorkoutPlan(workouts=[workout]))
        atomic_write_text(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
        self._result_var.set(f"YAML сохранён: {Path(path).name}")
        self._log(f"[OK] YAML тренировки сохранён: {path}")

    def _builder_send_to_garmin(self) -> None:
        from garmin_fit.garmin_step_mapper import extract_date_from_filename
        from garmin_fit.workout_builder import validate_draft

        workout = self._builder_current_workout()
        if workout is None:
            return
        if not self._active_profile_email:
            messagebox.showwarning("Нет профиля", "Сначала выберите профиль Garmin.", parent=self)
            return
        errors, _warnings = validate_draft(workout.filename, workout.name, workout.steps)
        if errors:
            messagebox.showwarning("Есть ошибки", "\n".join(errors), parent=self)
            return
        year_str = self.year_var.get().strip()
        year = int(year_str) if year_str.isdigit() else None
        scheduled_date = extract_date_from_filename(workout.filename, year=year)
        if not scheduled_date:
            scheduled_date = simpledialog.askstring(
                "Дата тренировки", "Дата для календаря Garmin (ГГГГ-ММ-ДД):", parent=self)
        if not scheduled_date:
            return
        try:
            scheduled_date = datetime.date.fromisoformat(scheduled_date).isoformat()
        except ValueError:
            messagebox.showerror(
                "Неверная дата", "Введите дату в формате ГГГГ-ММ-ДД.", parent=self)
            return
        if not messagebox.askyesno(
                "Отправить тренировку в Garmin Connect",
                f"Будет загружена и назначена реальная тренировка.\n\n"
                f"Тренировка: {workout.name}\nДата: {scheduled_date}\n"
                f"Профиль: {self._active_profile_email}\n\nПродолжить?",
                icon="warning", parent=self):
            return
        if not self._begin_operation("Отправка тренировки в Garmin"):
            return
        self._result_var.set("Отправляю тренировку и назначаю её на выбранную дату…")

        def worker():
            try:
                from garmin_fit.garmin_calendar_export import GarminCalendarExporter
                from garmin_fit.workflow import _connect_garmin_cli_client

                client = _connect_garmin_cli_client(
                    email=self.email_var.get() or None,
                    password=self.pass_var.get() or None,
                    prompt_mfa=self._gui_mfa_prompt,
                )
                result = GarminCalendarExporter(client).upload_and_schedule(
                    workout, date=scheduled_date)
                if result.error:
                    if result.workout_id:
                        message = (
                            f"Тренировка загружена (ID {result.workout_id}), "
                            f"но назначить её на {scheduled_date} не удалось: {result.error}"
                        )
                    else:
                        message = f"Не удалось отправить тренировку: {result.error}"
                    success = False
                else:
                    message = f"Тренировка отправлена и назначена на {scheduled_date}."
                    success = True
                self.after(0, self._result_var.set, message)
                self.after(0, self._log, f"{'[OK]' if success else '[ERR]'} {message}")
                self.after(0, self._record_gc_operation,
                           "Отправка из конструктора", success, message)
                self.after(0, self._end_operation, success)
                if success:
                    self.after(0, self._nb.select, 3)
                    self.after(0, self._gc_calendar_load)
            except Exception as exc:
                message = self._gc_friendly_error(exc, "загрузку тренировки")
                self.after(0, self._result_var.set, f"Ошибка отправки: {message}")
                self.after(0, self._log, f"[ERR] Отправка из конструктора: {message}")
                self.after(0, self._record_gc_operation,
                           "Отправка из конструктора", False, message)
                self.after(0, self._end_operation, False)

        threading.Thread(target=worker, daemon=True).start()

    def _builder_commit(self):
        from garmin_fit.workout_builder import validate_draft

        filename = self._builder_filename_var.get().strip()
        if not filename or not self._builder_steps:
            return
        if self._store is None:
            messagebox.showwarning(
                "Нет плана", "Сначала откройте или создайте YAML план вверху окна.")
            return
        errors, warnings = validate_draft(filename, filename, self._builder_steps)
        if errors:
            messagebox.showwarning("Есть ошибки", "\n".join(errors))
            return

        self._store.add_workout(filename=filename, name=filename, steps=self._builder_steps)
        self._log(f"[OK] Тренировка «{filename}» добавлена в план")

        from garmin_fit.plan_domain import plan_to_data
        data = plan_to_data(self._store.get_plan())
        self.workouts = self._parse_workouts(data)
        self._draw_calendar()

        self._builder_clear()

    def _builder_save_edit(self):
        from garmin_fit.workout_builder import validate_draft

        workout_id = self._builder_edit_workout_id
        filename = self._builder_filename_var.get().strip()
        if workout_id is None or not filename or not self._builder_steps:
            return
        errors, warnings = validate_draft(filename, filename, self._builder_steps)
        if errors:
            messagebox.showwarning("Есть ошибки", "\n".join(errors), parent=self)
            return
        try:
            self._store.replace_workout_steps(
                workout_id, self._builder_steps, filename=filename)
        except Exception as exc:
            messagebox.showerror("Не удалось сохранить", str(exc), parent=self)
            return
        from garmin_fit.plan_domain import plan_to_data
        self.workouts = self._parse_workouts(plan_to_data(self._store.get_plan()))
        updated_workout = next(
            (item for item in self.workouts if item.get("filename") == filename), None)
        if updated_workout and updated_workout.get("date"):
            self.cal_month = datetime.date.fromisoformat(
                updated_workout["date"]).replace(day=1)
        self._draw_calendar()
        self._builder_clear()
        if updated_workout is not None:
            self._show_detail(updated_workout)
        self._nb.select(0)
        self._result_var.set(f"Тренировка сохранена в YAML: {filename}")
        self._log(f"[OK] Изменения сохранены в {self.yaml_path.get()}: «{filename}»")

    def _builder_replace_garmin_event(self) -> None:
        event = self._builder_garmin_edit_event
        workout = self._builder_current_workout()
        if not event or workout is None:
            return
        if event.get("profile_email") != self._active_profile_email:
            messagebox.showwarning(
                "Профиль изменён",
                "Выберите исходный профиль Garmin и снова откройте тренировку из календаря.",
                parent=self,
            )
            return
        from garmin_fit.workout_builder import validate_draft

        errors, _warnings = validate_draft(
            workout.filename or "", workout.name or "", self._builder_steps)
        if errors:
            messagebox.showwarning("Есть ошибки", "\n".join(errors), parent=self)
            return
        if not messagebox.askyesno(
            "Сохранить изменения в Garmin Connect",
            f"Загрузить новую версию «{workout.name}» на {event['date']} и убрать "
            "старое назначение из календаря?\n\n"
            "Исходный шаблон останется в библиотеке Garmin.",
            parent=self,
        ):
            return
        if not self._begin_operation("Обновление тренировки Garmin"):
            return
        workout.desc = event.get("description", "")
        profile_email = self._active_profile_email
        password = self.pass_var.get() or None
        self._result_var.set("Отправляю изменённую тренировку в Garmin Connect…")

        def worker() -> None:
            try:
                from garmin_fit.garmin_calendar_edit import replace_scheduled_workout
                from garmin_fit.workflow import _connect_garmin_cli_client

                client = _connect_garmin_cli_client(
                    email=profile_email,
                    password=password,
                    prompt_mfa=self._gui_mfa_prompt,
                )
                new_id = replace_scheduled_workout(
                    client, workout,
                    old_schedule_id=event["schedule_id"],
                    date=event["date"],
                )
                message = (
                    f"Тренировка Garmin обновлена на {event['date']} · новая версия ID {new_id}. "
                    "Исходный шаблон сохранён в библиотеке."
                )
                self.after(0, self._result_var.set, message)
                self.after(0, self._log, f"[OK] {message}")
                self.after(0, self._record_gc_operation, "Изменение тренировки", True, message)
                self.after(0, self._builder_clear)
                self.after(0, self._nb.select, 3)
                self.after(0, self._gc_views.select, 0)
                self.after(0, self._end_operation, True)
                self.after(150, self._gc_calendar_load)
            except Exception as exc:
                detail = self._gc_friendly_error(exc, "изменение тренировки")
                self.after(0, self._result_var.set, f"Не удалось обновить Garmin: {detail}")
                self.after(0, self._log, f"[ERR] Обновление Garmin: {detail}")
                self.after(0, self._record_gc_operation, "Изменение тренировки", False, detail)
                self.after(0, self._end_operation, False)

        threading.Thread(target=worker, daemon=True).start()

