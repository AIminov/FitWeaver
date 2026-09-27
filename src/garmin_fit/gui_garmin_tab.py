"""Garmin Connect tab methods for the desktop application."""

from __future__ import annotations

import calendar
import datetime
import json
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .gui_messages import garmin_error_message, ru_workouts
from .gui_palette import (
    ACCENT,
    BG,
    BG2,
    BG3,
    DAYS_RU,
    DEFAULT_WO_COLOR,
    FG,
    GREEN,
    MONTHS_RU,
    MUTED,
    PURPLE,
    RED,
    WORKOUT_COLORS,
    YELLOW,
)


class GarminTabMixin:
    # ── Garmin Connect tab ────────────────────────────────────────────────────
    def _build_garmin_tab(self, parent):
        self._build_page_header(
            parent, "Garmin Connect", "Календарь аккаунта и сохранённые тренировки")

        self._gc_views = ttk.Notebook(parent)
        self._gc_views.pack(fill="both", expand=True)
        calendar_tab = ttk.Frame(self._gc_views, padding=(6, 6))
        library_tab = ttk.Frame(self._gc_views, padding=(6, 6))
        self._gc_views.add(calendar_tab, text="Календарь Garmin")
        self._gc_views.add(library_tab, text="Библиотека тренировок")

        calendar_bar = ttk.Frame(calendar_tab)
        calendar_bar.pack(fill="x", pady=(0, 6))
        ttk.Button(calendar_bar, text="◀", command=self._gc_calendar_prev, width=3).pack(side="left")
        self._gc_calendar_month_lbl = tk.Label(
            calendar_bar, text="", bg=BG, fg=PURPLE, font=("Segoe UI", 12, "bold"))
        self._gc_calendar_month_lbl.pack(side="left", padx=10)
        ttk.Button(calendar_bar, text="▶", command=self._gc_calendar_next, width=3).pack(side="left")
        ttk.Button(calendar_bar, text="Обновить календарь",
                   style="Primary.TButton", command=self._gc_calendar_load).pack(
                       side="left", padx=(14, 8))
        self._gc_calendar_status_var = tk.StringVar(value="Нажмите «Обновить календарь Garmin»")
        ttk.Label(calendar_bar, textvariable=self._gc_calendar_status_var,
                  style="Muted.TLabel").pack(side="left", padx=4)
        self._gc_calendar_frame = tk.Frame(calendar_tab, bg=BG2)
        self._gc_calendar_frame.pack(fill="both", expand=True)
        self._gc_calendar_detail_var = tk.StringVar(value="")
        ttk.Label(calendar_tab, textvariable=self._gc_calendar_detail_var,
                  style="Status.TLabel").pack(fill="x", pady=(4, 0))
        self._gc_edit_event_btn = ttk.Button(
            calendar_tab, text="Изменить выбранную тренировку Garmin",
            command=self._gc_edit_selected_event, state="disabled")
        self._gc_edit_event_btn.pack(anchor="e", pady=(4, 0))
        self._gc_calendar_render()

        bar = ttk.Frame(library_tab)
        bar.pack(fill="x", pady=(0, 6))
        self._gc_check_btn = ttk.Button(
            bar, text="✓  Проверить подключение", command=self._gc_check_connection)
        self._gc_check_btn.pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="⇩  Экспорт диагностики",
                   command=self._export_gc_diagnostics).pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="🔄  Загрузить из Garmin",
                   style="Primary.TButton",
                   command=self._gc_load).pack(side="left", padx=(0, 8))
        self._gc_limit_frame = ttk.Frame(bar)
        self._gc_limit_frame.pack(side="left")
        ttk.Label(self._gc_limit_frame, text="Лимит:", style="Muted.TLabel").pack(side="left")
        self._gc_limit = tk.StringVar(value="200")
        ttk.Entry(self._gc_limit_frame, textvariable=self._gc_limit, width=6).pack(
            side="left", padx=(4, 16))
        self._gc_del_btn = ttk.Button(bar, text="🗑  Удалить выбранные (0)",
                                      style="Danger.TButton",
                                      state="disabled",
                                      command=self._gc_delete_selected)
        self._gc_del_btn.pack(side="left", padx=(0, 8))
        self._gc_status = tk.Label(bar, text="Подключение ещё не проверено",
                                   bg=BG, fg=MUTED, font=("Segoe UI", 9))
        self._gc_status.pack(side="left")

        ttk.Separator(library_tab).pack(fill="x", pady=(0, 6))

        container = ttk.Frame(library_tab)
        container.pack(fill="both", expand=True)

        self._gc_canvas = tk.Canvas(container, bg=BG2, highlightthickness=0)
        vsb = ttk.Scrollbar(container, orient="vertical",
                            command=self._gc_canvas.yview)
        self._gc_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._gc_canvas.pack(side="left", fill="both", expand=True)

        self._gc_list_frame = tk.Frame(self._gc_canvas, bg=BG2)
        self._gc_list_win = self._gc_canvas.create_window(
            (0, 0), window=self._gc_list_frame, anchor="nw")
        self._gc_list_frame.bind("<Configure>", self._gc_on_frame_resize)
        self._gc_canvas.bind("<Configure>", self._gc_on_canvas_resize)
        self._gc_canvas.bind("<MouseWheel>", self._gc_scroll)

        self._gc_summary = tk.Label(library_tab, text="", bg=BG3, fg=MUTED,
                                    font=("Segoe UI", 9), anchor="w", padx=8, pady=3)
        self._gc_summary.pack(fill="x", side="bottom", pady=(4, 0))

        self._gc_workouts: list[dict] = []
        self._gc_history: list[dict] = []
        self._gc_checks:   dict[str, tk.BooleanVar] = {}
        self._gc_month_ids: dict[str, list[str]] = {}

        history_box = ttk.LabelFrame(library_tab, text="Последние операции", padding=4)
        history_box.pack(fill="x", side="bottom", pady=(4, 0))
        self._gc_history_tree = ttk.Treeview(
            history_box, columns=("time", "action", "result"),
            show="headings", height=4)
        self._gc_history_tree.heading("time", text="Время")
        self._gc_history_tree.heading("action", text="Операция")
        self._gc_history_tree.heading("result", text="Результат")
        self._gc_history_tree.column("time", width=58, stretch=False)
        self._gc_history_tree.column("action", width=180, stretch=True)
        self._gc_history_tree.column("result", width=210, stretch=True)
        self._gc_history_tree.pack(fill="x")

    def _gc_calendar_shift(self, months: int) -> None:
        year = self._gc_calendar_month.year
        month = self._gc_calendar_month.month + months
        if month < 1:
            year -= 1
            month = 12
        elif month > 12:
            year += 1
            month = 1
        self._gc_calendar_month = self._gc_calendar_month.replace(year=year, month=month, day=1)
        self._gc_scheduled_workouts = []
        self._gc_selected_event = None
        if hasattr(self, "_gc_edit_event_btn"):
            self._gc_edit_event_btn.configure(state="disabled")
        self._gc_calendar_detail_var.set("")
        self._gc_calendar_render()
        if self._active_profile_email:
            self._gc_calendar_load()
        else:
            self._gc_calendar_status_var.set("Выберите профиль Garmin, чтобы загрузить календарь")

    def _gc_calendar_prev(self) -> None:
        self._gc_calendar_shift(-1)

    def _gc_calendar_next(self) -> None:
        self._gc_calendar_shift(1)

    def _gc_calendar_render(self) -> None:
        if not hasattr(self, "_gc_calendar_frame"):
            return
        for child in self._gc_calendar_frame.winfo_children():
            child.destroy()
        month = self._gc_calendar_month
        self._gc_calendar_month_lbl.config(text=f"{MONTHS_RU[month.month - 1]} {month.year}")
        by_date: dict[str, list[dict[str, str]]] = {}
        for event in self._gc_scheduled_workouts:
            by_date.setdefault(event["date"], []).append(event)
        for col, day_name in enumerate(DAYS_RU):
            tk.Label(self._gc_calendar_frame, text=day_name, bg=BG2, fg=ACCENT,
                     font=("Segoe UI", 9, "bold"), pady=4).grid(
                         row=0, column=col, sticky="ew", padx=1, pady=1)
            self._gc_calendar_frame.columnconfigure(col, weight=1, uniform="gc_day")
        weeks = calendar.monthcalendar(month.year, month.month)
        for row_index, week in enumerate(weeks, start=1):
            self._gc_calendar_frame.rowconfigure(row_index, weight=1, uniform="gc_week")
            for col, day in enumerate(week):
                cell = tk.Frame(self._gc_calendar_frame, bg=BG3 if day else BG2)
                cell.grid(row=row_index, column=col, sticky="nsew", padx=1, pady=1)
                if not day:
                    continue
                event_date = datetime.date(month.year, month.month, day).isoformat()
                tk.Label(cell, text=str(day), bg=BG3, fg=FG,
                         font=("Segoe UI", 8, "bold"), anchor="nw", padx=4).pack(fill="x")
                for event in by_date.get(event_date, []):
                    name = event["name"]
                    color = WORKOUT_COLORS.get(self._infer_type(name), DEFAULT_WO_COLOR)
                    chip = tk.Label(cell, text=name, bg=color, fg=BG,
                                    font=("Segoe UI", 8, "bold"), anchor="w",
                                    padx=4, pady=2, wraplength=145, justify="left")
                    chip.pack(fill="x", padx=2, pady=1)
                    chip.bind("<Button-1>", lambda _e, item=event: self._gc_calendar_show_event(item))

    def _gc_calendar_show_event(self, event: dict[str, str]) -> None:
        self._gc_selected_event = event
        editable = bool(event.get("schedule_id"))
        detail = f"Garmin Connect · {event['date']} · {event['name']}"
        if not editable:
            detail += " · Garmin не передал ID записи; обновите календарь, чтобы редактировать"
        self._gc_calendar_detail_var.set(detail)
        self._gc_edit_event_btn.configure(
            state="normal" if editable else "disabled")

    def _gc_edit_selected_event(self) -> None:
        event = self._gc_selected_event
        if not event or not event.get("schedule_id"):
            return
        if not self._active_profile_email:
            messagebox.showwarning("Нет профиля", "Сначала выберите профиль Garmin.", parent=self)
            return
        profile_email = self._active_profile_email
        password = self.pass_var.get() or None
        if not self._begin_operation("Загрузка тренировки Garmin для редактирования"):
            return
        self._gc_calendar_status_var.set("Загружаю шаги тренировки Garmin…")

        def worker() -> None:
            try:
                from garmin_fit.garmin_workout_import import workout_from_garmin
                from garmin_fit.workflow import _connect_garmin_cli_client

                client = _connect_garmin_cli_client(
                    email=profile_email,
                    password=password,
                    prompt_mfa=self._gui_mfa_prompt,
                )
                schedule = client.get_scheduled_workout_by_id(event["schedule_id"])
                if not isinstance(schedule, dict):
                    raise RuntimeError("Garmin вернул неожиданный формат назначения")
                workout_id = event.get("workout_id") or schedule.get("workoutId")
                if not workout_id and isinstance(schedule.get("workout"), dict):
                    workout_id = schedule["workout"].get("workoutId")
                if not workout_id:
                    raise RuntimeError("Garmin не вернул ID шаблона тренировки")
                payload = client.get_workout_by_id(str(workout_id))
                workout = workout_from_garmin(payload, date=event["date"])
                resolved_event = dict(
                    event, workout_id=str(workout_id),
                    description=str(payload.get("description") or ""),
                    profile_email=profile_email or "")
                self.after(0, self._builder_load_garmin_event, workout, resolved_event)
                self.after(0, self._record_gc_operation,
                           "Открытие тренировки Garmin", True, workout.name or "")
                self.after(0, self._end_operation, True)
            except Exception as exc:
                detail = self._gc_friendly_error(exc, "чтение тренировки")
                self.after(0, self._gc_calendar_status_var.set,
                           f"Не удалось открыть для редактирования: {detail}")
                self.after(0, self._record_gc_operation,
                           "Открытие тренировки Garmin", False, detail)
                self.after(0, self._log, f"[ERR] Редактирование Garmin: {detail}")
                self.after(0, self._end_operation, False)

        threading.Thread(target=worker, daemon=True).start()

    def _builder_load_garmin_event(self, workout, event: dict[str, str]) -> None:
        from garmin_fit.plan_domain import step_from_data, step_to_data

        self._builder_clear()
        self._builder_garmin_edit_event = event
        self._builder_filename_var.set(workout.name or event["name"])
        self._builder_steps = [step_from_data(step_to_data(step)) for step in workout.steps]
        self._builder_range_start = self._builder_range_end = self._builder_selected_index = None
        self._builder_add_btn.configure(
            text="Сохранить в Garmin Connect", command=self._builder_replace_garmin_event)
        self._builder_render_list()
        self._builder_render_editor()
        self._builder_update_validation()
        self._nb.select(2)
        self._result_var.set(
            f"Открыта тренировка Garmin · {event['date']} · {len(self._builder_steps)} шагов")

    def _gc_calendar_load(self) -> None:
        if not self._active_profile_email:
            messagebox.showwarning("Нет профиля", "Сначала выберите профиль Garmin.", parent=self)
            return
        month = self._gc_calendar_month
        if not self._begin_operation("Загрузка календаря Garmin"):
            return
        self._gc_selected_event = None
        self._gc_edit_event_btn.configure(state="disabled")
        self._gc_calendar_detail_var.set("")
        self._gc_calendar_status_var.set("Загружаю события Garmin Connect…")

        def worker():
            try:
                from garmin_fit.garmin_calendar_view import normalize_scheduled_workouts
                from garmin_fit.workflow import _connect_garmin_cli_client

                client = _connect_garmin_cli_client(
                    email=self.email_var.get() or None,
                    password=self.pass_var.get() or None,
                    prompt_mfa=self._gui_mfa_prompt,
                )
                get_month = getattr(client, "get_scheduled_workouts", None)
                if not callable(get_month):
                    raise RuntimeError(
                        "Установленная версия garminconnect не поддерживает чтение календаря. "
                        "Обновите Garmin-компонент приложения."
                    )
                events = normalize_scheduled_workouts(get_month(month.year, month.month))
                stamp = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
                self.after(0, self._gc_calendar_set_events, events, stamp)
                self.after(0, self._record_gc_operation,
                           "Календарь Garmin", True, f"Получено событий: {len(events)}")
                self.after(0, self._end_operation, True)
            except Exception as exc:
                detail = self._gc_friendly_error(exc, "чтение календаря")
                self.after(0, self._gc_calendar_status_var.set, f"Не удалось загрузить: {detail}")
                self.after(0, self._record_gc_operation, "Календарь Garmin", False, detail)
                self.after(0, self._log, f"[ERR] Календарь Garmin: {detail}")
                self.after(0, self._end_operation, False)

        threading.Thread(target=worker, daemon=True).start()

    def _gc_calendar_set_events(self, events: list[dict[str, str]], stamp: str) -> None:
        self._gc_scheduled_workouts = events
        self._gc_calendar_render()
        self._gc_calendar_status_var.set(
            f"{ru_workouts(len(events))} · обновлено {stamp} · источник: Garmin Connect"
        )
        self._result_var.set(f"Календарь Garmin обновлён: {ru_workouts(len(events))}")

    def _refresh_gc_history(self) -> None:
        if not hasattr(self, "_gc_history_tree"):
            return
        for item in self._gc_history_tree.get_children():
            self._gc_history_tree.delete(item)
        for entry in self._gc_history[-8:][::-1]:
            self._gc_history_tree.insert(
                "", "end",
                values=(entry.get("time", ""), entry.get("action", ""),
                        entry.get("result", "")),
            )

    def _record_gc_operation(self, action: str, success: bool, result: str) -> None:
        self._gc_history.append({
            "time": datetime.datetime.now().strftime("%H:%M"),
            "action": action,
            "result": result,
        })
        self._gc_history = self._gc_history[-8:]
        self._refresh_gc_history()
        self._save_current_profile_session()

    def _gc_scroll(self, e):
        self._gc_canvas.yview_scroll(-1 * (e.delta // 120), "units")

    def _gc_bind_wheel(self, widget):
        widget.bind("<MouseWheel>", self._gc_scroll)
        for child in widget.winfo_children():
            self._gc_bind_wheel(child)

    def _gc_on_frame_resize(self, _e=None):
        self._gc_canvas.configure(scrollregion=self._gc_canvas.bbox("all"))

    def _gc_on_canvas_resize(self, e):
        self._gc_canvas.itemconfig(self._gc_list_win, width=e.width)

    def _gc_check_connection(self):
        if not self.email_var.get():
            messagebox.showwarning("Нет email", "Сначала выберите профиль Garmin слева.")
            return
        if not self._begin_operation("Проверка подключения к Garmin"):
            return
        self._gc_status.config(text="⏳ Проверяю авторизацию Garmin Connect…", fg=YELLOW)

        def worker():
            try:
                from garmin_fit.workflow import _connect_garmin_cli_client
                client = _connect_garmin_cli_client(
                    email=self.email_var.get() or None,
                    password=self.pass_var.get() or None,
                    prompt_mfa=self._gui_mfa_prompt,
                )
                # A small read request verifies both authentication and API access.
                client.get_workouts(0, 1)
                self.after(0, self._gc_status.config,
                           {"text": "✅ Garmin Connect подключён", "fg": GREEN})
                self.after(0, self._record_gc_operation,
                           "Проверка подключения", True, "Подключено")
                self.after(0, self._end_operation, True)
            except Exception as exc:
                self.after(0, self._gc_status.config,
                           {"text": f"❌ {self._gc_friendly_error(exc, 'вход')}", "fg": RED})
                self.after(0, self._record_gc_operation,
                           "Проверка подключения", False, self._gc_friendly_error(exc, "вход"))
                self.after(0, self._end_operation, False)

        threading.Thread(target=worker, daemon=True).start()

    def _export_gc_diagnostics(self):
        path = filedialog.asksaveasfilename(
            title="Сохранить диагностику Garmin",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="fitweaver_garmin_diagnostics.json",
        )
        if not path:
            return
        payload = {
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "profile_email": self.email_var.get().strip(),
            "yaml_file": Path(self.yaml_path.get()).name if self.yaml_path.get() else "",
            "history": self._gc_history[-8:],
        }
        try:
            Path(path).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._gc_status.config(text=f"Диагностика сохранена: {Path(path).name}", fg=GREEN)
            self._log(f"[OK] Диагностика Garmin сохранена: {Path(path).name}")
        except OSError as exc:
            messagebox.showerror("Не удалось сохранить диагностику", str(exc), parent=self)

    def _gc_load(self):
        if not self.email_var.get():
            messagebox.showwarning("Нет email", "Введите email в левой панели.")
            return
        if not self._begin_operation("Загрузка тренировок из Garmin"):
            return
        self._gc_status.config(text="⏳ Подключаюсь к Garmin Connect…", fg=YELLOW)
        self._gc_clear_list()

        def worker():
            try:
                from garmin_fit.workflow import _connect_garmin_cli_client
                client = _connect_garmin_cli_client(
                    email=self.email_var.get() or None,
                    password=self.pass_var.get() or None,
                    prompt_mfa=self._gui_mfa_prompt,
                )
                limit = int(self._gc_limit.get() or 200)
                workouts = client.get_workouts(0, limit)
                self.after(0, self._gc_render, workouts)
                self.after(0, self._record_gc_operation,
                           "Загрузка тренировок", True, f"Получено: {len(workouts)}")
                self.after(0, self._end_operation, True)
                self.after(0, self._gc_update_del_btn)
            except Exception as exc:
                self.after(0, self._gc_status.config,
                           {"text": f"❌ {exc}", "fg": RED})
                self.after(0, self._record_gc_operation,
                           "Загрузка тренировок", False, str(exc))
                self.after(0, self._end_operation, False)

        threading.Thread(target=worker, daemon=True).start()

    def _gc_clear_list(self):
        self._gc_checks.clear()
        self._gc_month_ids.clear()
        for w in self._gc_list_frame.winfo_children():
            w.destroy()
        self._gc_update_del_btn()

    def _gc_render(self, workouts: list[dict]):
        self._gc_workouts = workouts
        self._gc_clear_list()

        from garmin_fit.garmin_step_mapper import extract_date_from_filename
        year_str = self.year_var.get()
        year = int(year_str) if year_str.isdigit() else None

        by_month: dict[str, list[dict]] = {}
        no_date:  list[dict] = []
        for wo in workouts:
            name = (wo.get("workoutName") or wo.get("name") or wo.get("title") or "")
            date_str = extract_date_from_filename(name, year=year)
            wo["_date"] = date_str
            wo["_name"] = name
            if date_str:
                mk = date_str[:7]
                by_month.setdefault(mk, []).append(wo)
            else:
                no_date.append(wo)

        for mk in sorted(by_month.keys(), reverse=True):
            self._gc_render_month(mk, sorted(by_month[mk],
                                             key=lambda w: w["_date"], reverse=True))
        if no_date:
            self._gc_render_month("no_date", no_date)

        # Bind wheel to all newly created widgets
        self._gc_bind_wheel(self._gc_list_frame)

        total     = len(workouts)
        fitweaver = sum(1 for w in workouts if w.get("_date"))
        self._gc_status.config(
            text=f"✅ {ru_workouts(total)} · {fitweaver} с датой в имени", fg=GREEN)
        self._gc_summary.config(
            text=f"Сохранено: {total}  |  Дата указана в имени: {fitweaver}  |  Без метки даты: {len(no_date)}")

    def _gc_render_month(self, month_key: str, workouts: list[dict]):
        ids = [str(wo.get("workoutId") or wo.get("id") or "") for wo in workouts]
        self._gc_month_ids[month_key] = ids

        if month_key != "no_date":
            try:
                dt = datetime.date.fromisoformat(month_key + "-01")
                label = f"В имени: {MONTHS_RU[dt.month - 1]} {dt.year}  ({len(workouts)})"
            except ValueError:
                label = f"{month_key}  ({len(workouts)})"
        else:
            label = f"Без метки даты в имени  ({len(workouts)})"

        hdr = tk.Frame(self._gc_list_frame, bg=BG3)
        hdr.pack(fill="x", pady=(10, 2), padx=4)
        tk.Label(hdr, text=label, bg=BG3, fg=ACCENT,
                 font=("Segoe UI", 10, "bold"), anchor="w",
                 padx=8, pady=4).pack(side="left")

        # "Select all" toggle for this section
        sel_var = tk.BooleanVar(value=False)
        def toggle_month(v=sel_var, section_ids=ids):
            state = v.get()
            for wid in section_ids:
                if wid in self._gc_checks:
                    self._gc_checks[wid].set(state)
            self._gc_update_del_btn()

        tk.Checkbutton(hdr, text="Все", variable=sel_var,
                       bg=BG3, fg=MUTED, selectcolor=BG3,
                       activebackground=BG3, font=("Segoe UI", 8),
                       command=toggle_month).pack(side="right", padx=8)

        for wo in workouts:
            self._gc_render_row(wo)

    def _gc_render_row(self, wo: dict):
        row = tk.Frame(self._gc_list_frame, bg=BG2, pady=1)
        row.pack(fill="x", padx=4, pady=1)

        date_str = wo.get("_date") or ""
        name     = wo.get("_name") or ""
        wo_id    = str(wo.get("workoutId") or wo.get("id") or "")

        # Checkbox
        var = tk.BooleanVar(value=False)
        self._gc_checks[wo_id] = var
        tk.Checkbutton(row, variable=var, bg=BG2, selectcolor=BG3,
                       activebackground=BG2,
                       command=self._gc_update_del_btn).pack(side="left", padx=(4, 2))

        # Date chip
        date_lbl = date_str[5:] if date_str else "——"
        tk.Label(row, text=date_lbl, bg=BG3, fg=MUTED,
                 font=("Consolas", 9), width=6, anchor="center",
                 padx=4, pady=3).pack(side="left", padx=(0, 6))

        # Type colour badge
        color = WORKOUT_COLORS.get(self._infer_type(name), DEFAULT_WO_COLOR)
        tk.Label(row, text=" ", bg=color, width=2).pack(side="left", padx=(0, 6))

        # Short name
        short = re.sub(r"^W\d+_\d{2}-\d{2}_\w+_", "", name)
        tk.Label(row, text=short or name, bg=BG2, fg=FG,
                 font=("Segoe UI", 9), anchor="w").pack(side="left", fill="x", expand=True)

        # Delete single
        def _delete(wid=wo_id, wname=name, r=row):
            if messagebox.askyesno("Удалить тренировку",
                                   f"Удалить из Garmin Connect?\n\n{wname}",
                                   icon="warning"):
                self._gc_checks.pop(wid, None)
                self._gc_delete_one(wid, r)

        tk.Button(row, text="✕", bg=BG2, fg=RED, font=("Segoe UI", 9),
                  relief="flat", cursor="hand2", bd=0, padx=6,
                  command=_delete).pack(side="right", padx=4)

    def _gc_update_del_btn(self):
        n = sum(1 for v in self._gc_checks.values() if v.get())
        if n:
            self._gc_del_btn.config(text=f"🗑  Удалить выбранные ({n})",
                                    state="normal")
        else:
            self._gc_del_btn.config(text="🗑  Удалить выбранные (0)",
                                    state="disabled")

    def _infer_type(self, name: str) -> str:
        n = name.lower()
        if "long"      in n or "длинн" in n: return "long"
        if "interval"  in n or "интерв" in n: return "intervals"
        if "tempo"     in n or "темп"  in n: return "tempo"
        if "recovery"  in n or "восст" in n: return "recovery"
        if "sbu"       in n or "сбу"   in n: return "sbu"
        if "aerobic"   in n or "аэроб" in n: return "aerobic"
        return ""

    def _gc_friendly_error(self, exc: Exception, action: str = "операцию") -> str:
        return garmin_error_message(exc, action)

    def _gc_delete_one(self, workout_id: str, row_widget: tk.Frame):
        if not self._begin_operation("Удаление тренировки из Garmin"):
            return

        def worker():
            try:
                from garmin_fit.workflow import _connect_garmin_cli_client
                client = _connect_garmin_cli_client(
                    email=self.email_var.get() or None,
                    password=self.pass_var.get() or None,
                    prompt_mfa=self._gui_mfa_prompt,
                )
                client.delete_workout(workout_id)
                self.after(0, row_widget.destroy)
                self.after(0, self._gc_update_del_btn)
                self.after(0, self._gc_status.config,
                           {"text": f"✅ Удалено {workout_id}, обновляю список…", "fg": GREEN})
                self.after(0, self._record_gc_operation,
                           "Удаление тренировки", True, f"Удалено: {workout_id}")
                self.after(0, self._end_operation, True)
                self.after(0, self._gc_load)
            except Exception as exc:
                self.after(0, messagebox.showerror,
                           "Не удалось удалить", self._gc_friendly_error(exc, "удаление"))
                self.after(0, self._gc_status.config,
                           {"text": "❌ Ошибка удаления", "fg": RED})
                self.after(0, self._record_gc_operation,
                           "Удаление тренировки", False, self._gc_friendly_error(exc, "удаление"))
                self.after(0, self._end_operation, False)

        threading.Thread(target=worker, daemon=True).start()

    def _gc_delete_selected(self):
        to_delete = [(wid, v) for wid, v in self._gc_checks.items() if v.get()]
        if not to_delete:
            return
        if not messagebox.askyesno(
                "Удалить выбранные",
                f"Удалить {ru_workouts(len(to_delete))} из Garmin Connect?\n\nЭто необратимо.",
                icon="warning"):
            return

        if not self._begin_operation("Удаление выбранных тренировок"):
            return

        self._gc_del_btn.config(state="disabled")
        self._gc_status.config(text=f"⏳ Удаляю {len(to_delete)} тренировок…", fg=YELLOW)

        def worker():
            try:
                from garmin_fit.workflow import _connect_garmin_cli_client
                client = _connect_garmin_cli_client(
                    email=self.email_var.get() or None,
                    password=self.pass_var.get() or None,
                    prompt_mfa=self._gui_mfa_prompt,
                )
            except Exception as exc:
                self.after(0, self._gc_status.config,
                           {"text": f"❌ {exc}", "fg": RED})
                self.after(0, self._record_gc_operation,
                           "Удаление выбранных", False, str(exc))
                self.after(0, self._end_operation, False)
                return

            deleted, failed, atp = 0, 0, 0
            for wid, _var in to_delete:
                try:
                    client.delete_workout(wid)
                    deleted += 1
                except Exception as exc:
                    msg = str(exc)
                    if "ATP" in msg:
                        atp += 1
                    else:
                        failed += 1

            def finish():
                parts = [f"✅ Удалено: {deleted}"]
                if atp:    parts.append(f"ATP (пропущено): {atp}")
                if failed: parts.append(f"Ошибок: {failed}")
                self._gc_status.config(text="  |  ".join(parts),
                                       fg=GREEN if not failed else YELLOW)
                self._record_gc_operation(
                    "Удаление выбранных", not failed,
                    f"Удалено: {deleted}; ошибок: {failed}; ATP: {atp}",
                )
                self._end_operation(not failed)
                self._gc_load()   # refresh list from Garmin after the batch

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

