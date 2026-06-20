#!/usr/bin/env python3
"""FitWeaver Desktop GUI — local calendar + CLI wrapper."""

import calendar
import datetime
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import yaml

PROJECT_ROOT = Path(__file__).parent
PYTHON = sys.executable

# Add src/ so we can import garmin_fit directly
sys.path.insert(0, str(PROJECT_ROOT / "src"))

WORKOUT_COLORS = {
    "long":      "#89b4fa",
    "intervals": "#f38ba8",
    "tempo":     "#fab387",
    "aerobic":   "#a6e3a1",
    "recovery":  "#6c7086",
    "sbu":       "#cba6f7",
    "easy":      "#94e2d5",
}
DEFAULT_WORKOUT_COLOR = "#89dceb"

MONTHS_RU = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]
DAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

BG      = "#1e1e2e"
BG2     = "#181825"
BG3     = "#313244"
FG      = "#cdd6f4"
ACCENT  = "#89b4fa"
MUTED   = "#6c7086"
GREEN   = "#a6e3a1"
RED     = "#f38ba8"
PURPLE  = "#cba6f7"
YELLOW  = "#f9e2af"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FitWeaver")
        self.geometry("1340x860")
        self.minsize(1000, 640)
        self.configure(bg=BG)

        self.yaml_path  = tk.StringVar()
        self.email_var  = tk.StringVar()
        self.pass_var   = tk.StringVar()
        self.from_var   = tk.StringVar()
        self.to_var     = tk.StringVar()
        self.year_var   = tk.StringVar(value=str(datetime.date.today().year))
        self.dry_run    = tk.BooleanVar(value=True)

        self.workouts: list[dict] = []
        self.cal_month  = datetime.date.today().replace(day=1)

        self._setup_style()
        self._build_ui()

    # ------------------------------------------------------------------ style

    def _setup_style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".",               background=BG,  foreground=FG,  font=("Segoe UI", 10))
        s.configure("TFrame",          background=BG)
        s.configure("Dark.TFrame",     background=BG2)
        s.configure("TLabel",          background=BG,  foreground=FG)
        s.configure("Dark.TLabel",     background=BG2, foreground=FG)
        s.configure("Muted.TLabel",    background=BG,  foreground=MUTED, font=("Segoe UI", 9))
        s.configure("TEntry",          fieldbackground=BG3, foreground=FG, insertcolor=FG)
        s.configure("TCheckbutton",    background=BG,  foreground=FG)
        s.map("TCheckbutton",          background=[("active", BG)])

        s.configure("Title.TLabel",    background=BG,  foreground=PURPLE,
                                       font=("Segoe UI", 14, "bold"))
        s.configure("Section.TLabel",  background=BG,  foreground=ACCENT,
                                       font=("Segoe UI", 9, "bold"))

        # Buttons
        for name, bg, fg in [
            ("TButton",       BG3,     FG),
            ("Primary.TButton", ACCENT, BG),
            ("Danger.TButton",  RED,    BG),
            ("Warn.TButton",    YELLOW, BG),
        ]:
            s.configure(name, background=bg, foreground=fg, padding=(8, 5), relief="flat",
                        font=("Segoe UI", 10))
            s.map(name, background=[("active", MUTED)])

        # Separator
        s.configure("TSeparator", background=BG3)

        # Scrolledtext is a tk widget, styled separately in _build_ui

    # ------------------------------------------------------------------ layout

    def _build_ui(self):
        # ── Top bar ──────────────────────────────────────────────────────────
        top = ttk.Frame(self, padding=(10, 8, 10, 6))
        top.pack(fill="x", side="top")

        ttk.Label(top, text="FitWeaver", style="Title.TLabel").pack(side="left", padx=(0, 20))
        ttk.Label(top, text="YAML план:", style="Muted.TLabel").pack(side="left")
        ttk.Entry(top, textvariable=self.yaml_path, width=55).pack(side="left", padx=4)
        ttk.Button(top, text="Обзор…", command=self._browse_yaml).pack(side="left", padx=2)
        ttk.Button(top, text="↺", command=self._reload_yaml, width=3).pack(side="left", padx=2)

        ttk.Separator(self, orient="horizontal").pack(fill="x")

        # ── Body ──────────────────────────────────────────────────────────────
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        # Left sidebar (fixed width)
        sidebar = ttk.Frame(body, width=240, padding=(10, 10, 8, 8))
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self._build_sidebar(sidebar)

        ttk.Separator(body, orient="vertical").pack(side="left", fill="y")

        # Right: calendar + log
        right = ttk.Frame(body, padding=(10, 8))
        right.pack(side="left", fill="both", expand=True)
        self._build_right(right)

    # ------------------------------------------------------------------ sidebar

    def _build_sidebar(self, parent):
        def section(text):
            ttk.Label(parent, text=text, style="Section.TLabel").pack(anchor="w", pady=(10, 3))

        def hline():
            ttk.Separator(parent).pack(fill="x", pady=6)

        # Credentials
        section("GARMIN CONNECT")
        ttk.Label(parent, text="Email:", style="Muted.TLabel").pack(anchor="w")
        ttk.Entry(parent, textvariable=self.email_var).pack(fill="x", pady=(0, 4))
        ttk.Label(parent, text="Пароль:", style="Muted.TLabel").pack(anchor="w")
        ttk.Entry(parent, textvariable=self.pass_var, show="•").pack(fill="x", pady=(0, 4))

        hline()
        section("ПЕРИОД")
        ttk.Label(parent, text="С (YYYY-MM-DD):", style="Muted.TLabel").pack(anchor="w")
        ttk.Entry(parent, textvariable=self.from_var).pack(fill="x", pady=(0, 4))
        ttk.Label(parent, text="По (YYYY-MM-DD):", style="Muted.TLabel").pack(anchor="w")
        ttk.Entry(parent, textvariable=self.to_var).pack(fill="x", pady=(0, 4))
        ttk.Label(parent, text="Год:", style="Muted.TLabel").pack(anchor="w")
        ttk.Entry(parent, textvariable=self.year_var, width=10).pack(anchor="w")
        ttk.Checkbutton(parent, text="Dry-run (без изменений)",
                        variable=self.dry_run).pack(anchor="w", pady=(6, 0))

        hline()
        section("ОСНОВНЫЕ ДЕЙСТВИЯ")
        ttk.Button(parent, text="⚙  Собрать FIT-файлы", style="Primary.TButton",
                   command=self._cmd_build).pack(fill="x", pady=2)
        ttk.Button(parent, text="↑  Загрузить в Garmin",
                   command=self._cmd_upload).pack(fill="x", pady=2)
        ttk.Button(parent, text="✕  Удалить из Garmin", style="Danger.TButton",
                   command=self._cmd_delete).pack(fill="x", pady=2)

        hline()
        section("ПРОДВИНУТЫЕ")
        ttk.Button(parent, text="✓  Валидировать YAML",
                   command=self._cmd_validate_yaml).pack(fill="x", pady=2)
        ttk.Button(parent, text="✓  Валидировать FIT",
                   command=self._cmd_validate_fit).pack(fill="x", pady=2)
        ttk.Button(parent, text="🔍  Диагностика (doctor)",
                   command=self._cmd_doctor).pack(fill="x", pady=2)
        ttk.Button(parent, text="📦  Архивировать",
                   command=self._cmd_archive).pack(fill="x", pady=2)
        ttk.Button(parent, text="📋  Список архивов",
                   command=self._cmd_list_archives).pack(fill="x", pady=2)
        ttk.Button(parent, text="🔄  Восстановить архив",
                   command=self._cmd_restore).pack(fill="x", pady=2)

    # ------------------------------------------------------------------ right panel

    def _build_right(self, parent):
        # Calendar navigation
        nav = ttk.Frame(parent)
        nav.pack(fill="x", pady=(0, 6))
        ttk.Button(nav, text="◀", command=self._prev_month, width=3).pack(side="left")
        self._month_lbl = ttk.Label(nav, text="", font=("Segoe UI", 12, "bold"),
                                    foreground=PURPLE, background=BG)
        self._month_lbl.pack(side="left", padx=10)
        ttk.Button(nav, text="▶", command=self._next_month, width=3).pack(side="left")
        ttk.Label(nav, text="  Сегодня:", style="Muted.TLabel").pack(side="left", padx=(20, 4))
        ttk.Label(nav, text=datetime.date.today().strftime("%d.%m.%Y"),
                  foreground=ACCENT, background=BG).pack(side="left")

        # Calendar grid
        self._cal_frame = tk.Frame(parent, bg=BG2)
        self._cal_frame.pack(fill="both", expand=True)

        # Workout detail tooltip label
        self._detail_var = tk.StringVar(value="Нажмите на тренировку для подробностей")
        detail_lbl = tk.Label(parent, textvariable=self._detail_var,
                               bg=BG3, fg=FG, font=("Segoe UI", 9),
                               anchor="w", padx=8, pady=4)
        detail_lbl.pack(fill="x", pady=(4, 0))

        # Log
        ttk.Separator(parent).pack(fill="x", pady=6)
        log_hdr = ttk.Frame(parent)
        log_hdr.pack(fill="x")
        ttk.Label(log_hdr, text="ВЫВОД КОМАНДЫ", style="Section.TLabel").pack(side="left")
        ttk.Button(log_hdr, text="Очистить", command=self._clear_log,
                   width=8).pack(side="right")
        self._log_widget = scrolledtext.ScrolledText(
            parent, height=9, bg=BG2, fg=GREEN,
            font=("Consolas", 9), state="disabled",
            insertbackground=FG, relief="flat", bd=1,
        )
        self._log_widget.pack(fill="x", pady=(4, 0))

        self._draw_calendar()

    # ------------------------------------------------------------------ calendar

    def _draw_calendar(self):
        for w in self._cal_frame.winfo_children():
            w.destroy()

        self._month_lbl.config(
            text=f"{MONTHS_RU[self.cal_month.month - 1]}  {self.cal_month.year}"
        )
        today = datetime.date.today()

        # Index workouts by date
        by_date: dict[str, list[dict]] = {}
        for wo in self.workouts:
            d = wo.get("date")
            if d:
                by_date.setdefault(d, []).append(wo)

        # Day-of-week headers
        for col, name in enumerate(DAYS_RU):
            lbl = tk.Label(self._cal_frame, text=name, bg=BG2, fg=ACCENT,
                           font=("Segoe UI", 9, "bold"), width=18, anchor="center",
                           pady=4)
            lbl.grid(row=0, column=col, padx=1, pady=1, sticky="ew")
            self._cal_frame.columnconfigure(col, weight=1)

        # Weeks
        weeks = calendar.monthcalendar(self.cal_month.year, self.cal_month.month)
        for r, week in enumerate(weeks, start=1):
            self._cal_frame.rowconfigure(r, weight=1)
            for col, day in enumerate(week):
                cell = tk.Frame(self._cal_frame, bg=BG3 if day else BG2,
                                bd=1, relief="flat")
                cell.grid(row=r, column=col, padx=1, pady=1, sticky="nsew")

                if day == 0:
                    continue

                date = datetime.date(self.cal_month.year, self.cal_month.month, day)
                date_str = date.isoformat()

                day_fg = RED if date == today else (MUTED if col >= 5 else FG)
                tk.Label(cell, text=str(day), bg=BG3, fg=day_fg,
                         font=("Segoe UI", 8, "bold" if date == today else "normal"),
                         anchor="nw", padx=4, pady=2).pack(fill="x")

                for wo in by_date.get(date_str, []):
                    self._add_workout_chip(cell, wo)

    def _add_workout_chip(self, parent: tk.Frame, wo: dict):
        type_code = wo.get("type_code", "").lower()
        color = WORKOUT_COLORS.get(type_code, DEFAULT_WORKOUT_COLOR)
        name = (wo.get("name") or wo.get("filename") or "")
        # Shorten name for display: strip prefix Wxx_MM-DD_Day_
        import re
        short = re.sub(r"^W\d+_\d{2}-\d{2}_\w+_", "", name)
        short = short[:22]

        chip = tk.Label(parent, text=short, bg=color, fg="#1e1e2e",
                        font=("Segoe UI", 7, "bold"),
                        anchor="w", padx=3, pady=1, wraplength=130)
        chip.pack(fill="x", padx=2, pady=1)
        chip.bind("<Button-1>", lambda e, w=wo: self._show_detail(w))

    def _show_detail(self, wo: dict):
        parts = []
        if wo.get("date"):
            parts.append(wo["date"])
        parts.append(wo.get("name", ""))
        if wo.get("type_code"):
            parts.append(f"[{wo['type_code']}]")
        if wo.get("distance_km"):
            parts.append(f"{wo['distance_km']} км")
        if wo.get("estimated_duration_min"):
            parts.append(f"~{wo['estimated_duration_min']} мин")
        self._detail_var.set("  " + "   ·   ".join(parts))

    def _prev_month(self):
        self.cal_month = (self.cal_month - datetime.timedelta(days=1)).replace(day=1)
        self._draw_calendar()

    def _next_month(self):
        m, y = self.cal_month.month, self.cal_month.year
        self.cal_month = datetime.date(y + (m // 12), (m % 12) + 1, 1)
        self._draw_calendar()

    # ------------------------------------------------------------------ YAML

    def _browse_yaml(self):
        path = filedialog.askopenfilename(
            title="Выберите YAML план",
            filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")],
            initialdir=PROJECT_ROOT / "Plan",
        )
        if path:
            self.yaml_path.set(path)
            self._reload_yaml()

    def _reload_yaml(self):
        path = self.yaml_path.get()
        if not path or not Path(path).exists():
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self.workouts = self._parse_workouts(data)
            if self.workouts:
                # Navigate to month of first workout with a date
                dated = [w for w in self.workouts if w.get("date")]
                if dated:
                    first_date = datetime.date.fromisoformat(dated[0]["date"])
                    self.cal_month = first_date.replace(day=1)
            self._draw_calendar()
            self._log(f"[OK] Загружено {len(self.workouts)} тренировок из {Path(path).name}")
        except Exception as exc:
            self._log(f"[ERR] Не удалось загрузить YAML: {exc}")

    def _parse_workouts(self, data: dict) -> list[dict]:
        from garmin_fit.garmin_step_mapper import extract_date_from_filename
        year_str = self.year_var.get()
        year = int(year_str) if year_str.isdigit() else None
        result = []
        for wo in (data or {}).get("workouts", []):
            filename = wo.get("filename") or wo.get("name") or ""
            date_str = extract_date_from_filename(filename, year=year)
            result.append({
                "name":                 wo.get("name") or filename,
                "filename":             filename,
                "date":                 date_str,
                "type_code":            wo.get("type_code", ""),
                "distance_km":          wo.get("distance_km"),
                "estimated_duration_min": wo.get("estimated_duration_min"),
            })
        return result

    # ------------------------------------------------------------------ log

    def _log(self, text: str):
        self._log_widget.config(state="normal")
        self._log_widget.insert("end", text + "\n")
        self._log_widget.see("end")
        self._log_widget.config(state="disabled")

    def _clear_log(self):
        self._log_widget.config(state="normal")
        self._log_widget.delete("1.0", "end")
        self._log_widget.config(state="disabled")

    # ------------------------------------------------------------------ CLI runner

    def _run(self, args: list[str]):
        cmd = [PYTHON, "-m", "garmin_fit.cli"] + args
        self._log(f"\n$ garmin_fit.cli {' '.join(args)}")

        def worker():
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    cwd=PROJECT_ROOT,
                )
                for line in proc.stdout:
                    self.after(0, self._log, line.rstrip())
                proc.wait()
                status = "[OK] Готово" if proc.returncode == 0 else f"[FAIL] код возврата {proc.returncode}"
                self.after(0, self._log, status)
            except Exception as exc:
                self.after(0, self._log, f"[ERR] {exc}")

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ command handlers

    def _cmd_build(self):
        args = ["run"]
        if self.yaml_path.get():
            args += ["--plan", self.yaml_path.get()]
        self._run(args)

    def _cmd_upload(self):
        args = ["garmin-calendar"]
        if self.yaml_path.get():
            args += ["--plan", self.yaml_path.get()]
        self._append_garmin_args(args)
        if self.dry_run.get():
            args += ["--dry-run"]
        self._run(args)

    def _cmd_delete(self):
        if not self.dry_run.get():
            ok = messagebox.askyesno(
                "Подтверждение удаления",
                "Удалить тренировки из Garmin Connect?\n\nЭто действие необратимо.",
                icon="warning",
            )
            if not ok:
                return
        args = ["garmin-calendar-delete"]
        self._append_garmin_args(args)
        if self.dry_run.get():
            args += ["--dry-run"]
        else:
            args += ["--confirm"]
        self._run(args)

    def _append_garmin_args(self, args: list):
        if self.email_var.get():
            args += ["--email", self.email_var.get()]
        if self.pass_var.get():
            args += ["--password", self.pass_var.get()]
        if self.year_var.get():
            args += ["--year", self.year_var.get()]
        if self.from_var.get():
            args += ["--from-date", self.from_var.get()]
        if self.to_var.get():
            args += ["--to-date", self.to_var.get()]

    def _cmd_validate_yaml(self):
        args = ["validate-yaml"]
        if self.yaml_path.get():
            args += ["--plan", self.yaml_path.get()]
        self._run(args)

    def _cmd_validate_fit(self):
        self._run(["validate-fit"])

    def _cmd_doctor(self):
        self._run(["doctor", "--llm"])

    def _cmd_archive(self):
        self._run(["archive"])

    def _cmd_list_archives(self):
        self._run(["list-archives"])

    def _cmd_restore(self):
        name = tk.simpledialog.askstring(
            "Восстановить архив",
            "Введите имя архива (из списка архивов):",
            parent=self,
        )
        if name:
            self._run(["restore", name.strip()])


# Need simpledialog for restore
from tkinter import simpledialog  # noqa: E402

if __name__ == "__main__":
    app = App()
    app.mainloop()
