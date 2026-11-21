"""Local YAML calendar tab and its edit history."""

import calendar
import datetime
import re
import tkinter as tk
from tkinter import messagebox, ttk

from .gui_palette import (
    ACCENT,
    BG,
    BG2,
    BG3,
    DAYS_RU,
    DEFAULT_WO_COLOR,
    FG,
    MONTHS_RU,
    MUTED,
    PURPLE,
    RED,
    WORKOUT_COLORS,
)


class CalendarTabMixin:
    def _build_calendar_tab(self, parent):
        self._build_page_header(
            parent, "Локальный план", "Тренировки и даты из выбранного YAML-файла")
        plan_row = ttk.Frame(parent)
        plan_row.pack(fill="x", pady=(0, 4))
        ttk.Label(plan_row, text="YAML:", style="Muted.TLabel").pack(side="left")
        ttk.Entry(plan_row, textvariable=self.yaml_path).pack(
            side="left", fill="x", expand=True, padx=(6, 4))
        ttk.Button(plan_row, text="Обзор…", command=self._browse_yaml).pack(side="left", padx=2)
        ttk.Button(plan_row, text="Обновить", command=self._reload_yaml).pack(side="left", padx=2)
        ttk.Label(parent, textvariable=self._yaml_status_var,
                  style="Status.TLabel").pack(anchor="w", pady=(0, 4))
        actions = ttk.Frame(parent)
        actions.pack(fill="x", pady=(0, 6))
        self._quick_action_buttons["validate"] = ttk.Button(
            actions, text="Проверить YAML", command=self._cmd_validate_yaml)
        self._quick_action_buttons["validate"].pack(side="left", padx=(0, 4))
        self._quick_action_buttons["build"] = ttk.Button(
            actions, text="Собрать FIT", style="Primary.TButton", command=self._cmd_build)
        self._quick_action_buttons["build"].pack(side="left", padx=4)
        self._quick_action_buttons["upload"] = ttk.Button(
            actions, text="Отправить план в Garmin", style="Success.TButton",
            command=self._cmd_upload)
        self._quick_action_buttons["upload"].pack(side="left", padx=4)
        ttk.Label(actions, text="При совпадении:", style="Muted.TLabel").pack(side="left", padx=(8, 3))
        ttk.Combobox(
            actions, textvariable=self._upload_duplicate_var, state="readonly", width=22,
            values=("Пропустить совпадения", "Заменить назначение", "Создать копию"),
        ).pack(side="left")
        ttk.Label(actions,
                  text="Нажмите тренировку → «Изменить тренировку»; сохранение обновит YAML. "
                       "Перетащите её, чтобы изменить дату.",
                  style="Muted.TLabel").pack(side="left", padx=(12, 0))
        nav = ttk.Frame(parent)
        nav.pack(fill="x", pady=(0, 6))
        ttk.Button(nav, text="◀", command=self._prev_month, width=3).pack(side="left")
        self._month_lbl = tk.Label(nav, text="", bg=BG, fg=PURPLE,
                                   font=("Segoe UI", 12, "bold"))
        self._month_lbl.pack(side="left", padx=10)
        ttk.Button(nav, text="▶", command=self._next_month, width=3).pack(side="left")
        self._calendar_undo = []
        self._calendar_redo = []
        self._calendar_history_context = None
        self._calendar_undo_btn = ttk.Button(nav, text="Отменить", state="disabled",
                                            command=self._calendar_history_move)
        self._calendar_undo_btn.pack(side="right", padx=4)
        self._calendar_redo_btn = ttk.Button(nav, text="Повторить", state="disabled",
                                            command=lambda: self._calendar_history_move(redo=True))
        self._calendar_redo_btn.pack(side="right")
        tk.Label(nav, text=f"  Сегодня: {datetime.date.today().strftime('%d.%m.%Y')}",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=16)

        self._cal_frame = tk.Frame(parent, bg=BG2)
        self._cal_frame.pack(fill="both", expand=True)

        ttk.Label(parent, text="ОБЪЁМ ПО НЕДЕЛЯМ (км)", style="Section.TLabel").pack(
            anchor="w", pady=(6, 2))
        self._chart_canvas = tk.Canvas(parent, bg=BG2, height=64, highlightthickness=0)
        self._chart_canvas.pack(fill="x")
        self._chart_canvas.bind("<Configure>", self._on_chart_canvas_resize)

        detail_bar = ttk.Frame(parent)
        detail_bar.pack(fill="x", pady=(4, 0))
        self._detail_var = tk.StringVar(value="Нажмите на тренировку для подробностей")
        tk.Label(detail_bar, textvariable=self._detail_var,
                 bg=BG3, fg=FG, font=("Segoe UI", 9),
                 anchor="w", padx=8, pady=4).pack(side="left", fill="x", expand=True)
        self._edit_selected_btn = ttk.Button(
            detail_bar, text="Изменить тренировку", state="disabled",
            command=self._edit_selected_workout)
        self._edit_selected_btn.pack(side="right")

        self._draw_calendar()

    def _draw_calendar(self):
        self._calendar_history_buttons()
        for w in self._cal_frame.winfo_children():
            w.destroy()
        self._month_lbl.config(
            text=f"{MONTHS_RU[self.cal_month.month - 1]}  {self.cal_month.year}")
        today = datetime.date.today()

        by_date: dict[str, list[dict]] = {}
        for wo in self.workouts:
            d = wo.get("date")
            if d:
                by_date.setdefault(d, []).append(wo)

        for col, name in enumerate(DAYS_RU):
            tk.Label(self._cal_frame, text=name, bg=BG2, fg=ACCENT,
                     font=("Segoe UI", 9, "bold"), width=18,
                     anchor="center", pady=4).grid(
                row=0, column=col, padx=1, pady=1, sticky="ew")
            self._cal_frame.columnconfigure(col, weight=1)

        weeks = calendar.monthcalendar(self.cal_month.year, self.cal_month.month)
        self._chart_weeks = weeks
        self._chart_by_date = by_date
        self._draw_weekly_chart(weeks, by_date)

        for r, week in enumerate(weeks, start=1):
            self._cal_frame.rowconfigure(r, weight=1)
            for col, day in enumerate(week):
                cell = tk.Frame(self._cal_frame,
                                bg=BG3 if day else BG2, bd=0)
                cell.grid(row=r, column=col, padx=1, pady=1, sticky="nsew")
                if not day:
                    continue
                date = datetime.date(self.cal_month.year, self.cal_month.month, day)
                date_str = date.isoformat()
                cell.calendar_date_str = date_str  # drop-target lookup for drag & drop
                day_fg = RED if date == today else (MUTED if col >= 5 else FG)
                tk.Label(cell, text=str(day), bg=BG3, fg=day_fg,
                         font=("Segoe UI", 8, "bold" if date == today else "normal"),
                         anchor="nw", padx=4, pady=2).pack(fill="x")
                for wo in by_date.get(date_str, []):
                    self._add_chip(cell, wo)

    def _on_chart_canvas_resize(self, _e=None):
        if hasattr(self, "_chart_weeks"):
            self._draw_weekly_chart(self._chart_weeks, self._chart_by_date)

    def _draw_weekly_chart(self, weeks: list[list[int]], by_date: dict[str, list[dict]]):
        """Bar chart of total km per week-row of the currently displayed
        month calendar -- one bar per week, aligned with the grid below it,
        so training-load spikes/gaps are visible at a glance."""
        canvas = self._chart_canvas
        canvas.delete("all")
        canvas.update_idletasks()
        width = canvas.winfo_width() or 900
        height = int(canvas.cget("height"))

        totals = []
        for week in weeks:
            total_km = 0.0
            for day in week:
                if not day:
                    continue
                date_str = datetime.date(self.cal_month.year, self.cal_month.month, day).isoformat()
                for wo in by_date.get(date_str, []):
                    km = wo.get("distance_km")
                    if isinstance(km, (int, float)):
                        total_km += km
            totals.append(total_km)

        if not totals:
            return
        max_km = max(totals) or 1.0
        n = len(totals)
        col_w = width / n
        bar_w = col_w * 0.6
        bottom = height - 4
        top_margin = 16

        for i, total_km in enumerate(totals):
            bar_h = (total_km / max_km) * (height - top_margin - 4) if total_km else 0
            x0 = i * col_w + (col_w - bar_w) / 2
            x1 = x0 + bar_w
            y1 = bottom
            y0 = bottom - bar_h
            color = ACCENT if total_km > 0 else BG3
            canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="")
            label = f"{total_km:.0f}" if total_km else "—"
            canvas.create_text((x0 + x1) / 2, y0 - 8, text=label, fill=MUTED,
                                font=("Segoe UI", 8))

    def _add_chip(self, parent, wo):
        color = WORKOUT_COLORS.get((wo.get("type_code") or "").lower(), DEFAULT_WO_COLOR)
        name  = wo.get("name") or wo.get("filename") or ""
        short = re.sub(r"^W\d+_\d{2}-\d{2}_\w+_", "", name)[:22]
        chip  = tk.Label(parent, text=short, bg=color, fg="#1e1e2e",
                         font=("Segoe UI", 7, "bold"),
                         anchor="w", padx=3, pady=1, wraplength=130, cursor="fleur")
        chip.pack(fill="x", padx=2, pady=1)
        chip.bind("<ButtonPress-1>", lambda e, w=wo: self._calendar_drag_start(e, w))
        chip.bind("<B1-Motion>", self._calendar_drag_motion)
        chip.bind("<ButtonRelease-1>", lambda e, w=wo: self._calendar_drag_release(e, w))

    # ── Calendar drag & drop (move a workout to another day) ─────────────────
    _DRAG_THRESHOLD_PX = 6

    def _calendar_drag_start(self, event, wo):
        self._drag_workout = wo
        self._drag_start_xy = (event.x_root, event.y_root)
        self._drag_moved = False

    def _calendar_drag_motion(self, event):
        if self._drag_start_xy is None:
            return
        sx, sy = self._drag_start_xy
        if abs(event.x_root - sx) > self._DRAG_THRESHOLD_PX or abs(event.y_root - sy) > self._DRAG_THRESHOLD_PX:
            self._drag_moved = True

    def _cell_date_at_root_coords(self, x_root: int, y_root: int) -> str | None:
        widget = self.winfo_containing(x_root, y_root)
        while widget is not None:
            date_str = getattr(widget, "calendar_date_str", None)
            if date_str:
                return date_str
            widget = widget.master
        return None

    # Tk modifier-state bit for the Control key (Windows/X11)
    _CONTROL_STATE_MASK = 0x0004

    def _calendar_drag_release(self, event, wo):
        moved = self._drag_moved
        self._drag_workout = None
        self._drag_start_xy = None
        self._drag_moved = False

        if not moved:
            self._show_detail(wo)  # a plain click, not a drag
            return

        is_copy = bool(event.state & self._CONTROL_STATE_MASK)
        target_date_str = self._cell_date_at_root_coords(event.x_root, event.y_root)
        if not target_date_str:
            return
        if not is_copy and target_date_str == wo.get("date"):
            return  # dropped on its own day -- no-op
        if self._store is None or self._operation_active:
            return

        filename = wo.get("filename") or wo.get("name") or ""
        from garmin_fit.plan_edits import reschedule

        self._calendar_history_buttons()
        try:
            change = reschedule(self._store, filename, target_date_str, copy=is_copy)
        except (ValueError, OSError) as exc:
            messagebox.showerror("?? ??????? ???????? ????", str(exc), parent=self)
            return
        action = "???????????" if is_copy else "??????????"
        self._log(f"[OK] ?{filename}? {action} ?? {target_date_str} ? ?{change.new_name}?")
        self._calendar_undo.append(change)
        del self._calendar_undo[:-50]
        self._calendar_redo.clear()
        self._calendar_history_context = self._current_plan_context()
        self._calendar_refresh_after_edit()

    def _calendar_history_buttons(self):
        if self._calendar_history_context != self._current_plan_context():
            self._calendar_undo.clear()
            self._calendar_redo.clear()
            self._calendar_history_context = None
        for button, stack in ((self._calendar_undo_btn, self._calendar_undo),
                              (self._calendar_redo_btn, self._calendar_redo)):
            button.configure(state="normal" if stack and not self._operation_active else "disabled")

    def _calendar_history_move(self, *, redo=False):
        self._calendar_history_buttons()
        source, destination = self._calendar_undo, self._calendar_redo
        if redo:
            source, destination = destination, source
        if self._operation_active or self._store is None or not source:
            return
        from garmin_fit.plan_edits import replay_reschedule

        try:
            replay_reschedule(self._store, source[-1], redo=redo)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Не удалось применить правку", str(exc), parent=self)
            return
        destination.append(source.pop())
        self._calendar_history_context = self._current_plan_context()
        self._calendar_refresh_after_edit()
        self._log("[OK] Правка повторена" if redo else "[OK] Правка отменена")

    def _calendar_refresh_after_edit(self):
        from garmin_fit.plan_domain import plan_to_data

        self.workouts = self._parse_workouts(plan_to_data(self._store.get_plan()))
        self._selected_workout = None
        self._detail_var.set("")
        self._edit_selected_btn.configure(state="disabled")
        self._draw_calendar()

    def _show_detail(self, wo):
        self._selected_workout = wo
        self._edit_selected_btn.config(state="normal")
        parts = [p for p in [
            wo.get("date"), wo.get("name"),
            f"[{wo['type_code']}]"     if wo.get("type_code")            else None,
            f"{wo['distance_km']} км"  if wo.get("distance_km")          else None,
            f"~{wo['estimated_duration_min']} мин" if wo.get("estimated_duration_min") else None,
        ] if p]
        self._detail_var.set("  " + "   ·   ".join(parts))

    def _edit_selected_workout(self):
        if not self._selected_workout or self._store is None:
            return
        filename = self._selected_workout.get("filename") or self._selected_workout.get("name")
        workout_id = self._store.find_workout_id_by_filename(filename)
        if workout_id is None:
            self._log(f"[ERR] Не удалось найти тренировку «{filename}» в рабочем плане")
            return
        from garmin_fit.plan_domain import step_from_data, step_to_data

        workout = next(
            (item for item in self._store.get_plan().workouts if item.filename == filename),
            None,
        )
        if workout is None:
            return
        self._builder_history_reset()
        self._builder_edit_workout_id = workout_id
        self._builder_edit_context = self._current_plan_context()
        self._builder_garmin_edit_event = None
        self._builder_steps = [step_from_data(step_to_data(step)) for step in workout.steps]
        self._builder_filename_var.set(workout.filename or "")
        self._builder_range_start = self._builder_range_end = self._builder_selected_index = None
        self._builder_render_list()
        self._builder_render_editor()
        self._builder_add_btn.config(
            text="Сохранить в YAML", command=self._builder_save_edit
        )
        self._nb.select(2)

    def _prev_month(self):
        self.cal_month = (self.cal_month - datetime.timedelta(days=1)).replace(day=1)
        self._draw_calendar()

    def _next_month(self):
        m, y = self.cal_month.month, self.cal_month.year
        self.cal_month = datetime.date(y + (m // 12), (m % 12) + 1, 1)
        self._draw_calendar()
