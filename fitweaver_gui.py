#!/usr/bin/env python3
"""FitWeaver Desktop GUI — local calendar, CLI wrapper and LLM generator."""

import calendar
import datetime
import re
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

import json

import yaml

PROJECT_ROOT = Path(__file__).parent
PYTHON = sys.executable
SESSION_FILE = PROJECT_ROOT / ".gui_session.json"

sys.path.insert(0, str(PROJECT_ROOT / "src"))

# ── Colours ──────────────────────────────────────────────────────────────────
BG     = "#1e1e2e"
BG2    = "#181825"
BG3    = "#313244"
FG     = "#cdd6f4"
ACCENT = "#89b4fa"
MUTED  = "#6c7086"
GREEN  = "#a6e3a1"
RED    = "#f38ba8"
PURPLE = "#cba6f7"
YELLOW = "#f9e2af"
ORANGE = "#fab387"

WORKOUT_COLORS = {
    "long":      "#89b4fa",
    "intervals": "#f38ba8",
    "tempo":     "#fab387",
    "aerobic":   "#a6e3a1",
    "recovery":  "#6c7086",
    "sbu":       "#cba6f7",
    "easy":      "#94e2d5",
}
DEFAULT_WO_COLOR = "#89dceb"

MONTHS_RU = ["Январь","Февраль","Март","Апрель","Май","Июнь",
              "Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"]
DAYS_RU   = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]


# ══════════════════════════════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FitWeaver")
        self.geometry("1380x900")
        self.minsize(1060, 660)
        self.configure(bg=BG)

        # Shared state
        self.yaml_path = tk.StringVar()
        self.email_var = tk.StringVar()
        self.pass_var  = tk.StringVar()
        self.from_var  = tk.StringVar()
        self.to_var    = tk.StringVar()
        self.year_var  = tk.StringVar(value=str(datetime.date.today().year))
        self.dry_run   = tk.BooleanVar(value=True)

        # LLM settings
        self.llm_url   = tk.StringVar(value="http://127.0.0.1:1234")
        self.llm_model = tk.StringVar(value="qwen/qwen3.5-9b")
        self.llm_type  = tk.StringVar(value="openai")

        self.workouts: list[dict] = []
        self.cal_month = datetime.date.today().replace(day=1)

        self._setup_style()
        self._build_ui()
        self._load_session()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Session persistence ───────────────────────────────────────────────────
    def _load_session(self):
        try:
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            if data.get("yaml_path") and Path(data["yaml_path"]).exists():
                self.yaml_path.set(data["yaml_path"])
                self._reload_yaml()
            if data.get("email"):
                self.email_var.set(data["email"])
            if data.get("year"):
                self.year_var.set(data["year"])
            if data.get("llm_url"):
                self.llm_url.set(data["llm_url"])
            if data.get("llm_model"):
                self.llm_model.set(data["llm_model"])
            if data.get("llm_type"):
                self.llm_type.set(data["llm_type"])
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

    def _save_session(self):
        data = {
            "yaml_path": self.yaml_path.get(),
            "email":     self.email_var.get(),
            "year":      self.year_var.get(),
            "llm_url":   self.llm_url.get(),
            "llm_model": self.llm_model.get(),
            "llm_type":  self.llm_type.get(),
        }
        SESSION_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                encoding="utf-8")

    def _on_close(self):
        self._save_session()
        self.destroy()

    # ── Style ─────────────────────────────────────────────────────────────────
    def _setup_style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".",              background=BG,  foreground=FG, font=("Segoe UI", 10))
        s.configure("TFrame",         background=BG)
        s.configure("TLabel",         background=BG,  foreground=FG)
        s.configure("Muted.TLabel",   background=BG,  foreground=MUTED, font=("Segoe UI", 9))
        s.configure("TEntry",         fieldbackground=BG3, foreground=FG, insertcolor=FG)
        s.configure("TCheckbutton",   background=BG,  foreground=FG)
        s.map("TCheckbutton",         background=[("active", BG)])
        s.configure("TCombobox",      fieldbackground=BG3, foreground=FG,
                                      selectbackground=BG3, selectforeground=FG)
        s.map("TCombobox",            fieldbackground=[("readonly", BG3)])
        s.configure("TSeparator",     background=BG3)
        s.configure("Title.TLabel",   background=BG,  foreground=PURPLE,
                                      font=("Segoe UI", 14, "bold"))
        s.configure("Section.TLabel", background=BG,  foreground=ACCENT,
                                      font=("Segoe UI", 9, "bold"))
        # Notebook
        s.configure("TNotebook",          background=BG2, borderwidth=0)
        s.configure("TNotebook.Tab",      background=BG3, foreground=MUTED,
                                          padding=(14, 6), font=("Segoe UI", 10))
        s.map("TNotebook.Tab",            background=[("selected", BG)],
                                          foreground=[("selected", FG)])
        # Buttons
        for name, bg, fg in [
            ("TButton",        BG3,    FG),
            ("Primary.TButton", ACCENT, BG),
            ("Danger.TButton",  RED,    BG),
            ("Success.TButton", GREEN,  BG),
        ]:
            s.configure(name, background=bg, foreground=fg,
                        padding=(8, 5), relief="flat", font=("Segoe UI", 10))
            s.map(name, background=[("active", MUTED)])

    # ── Top layout ────────────────────────────────────────────────────────────
    def _build_ui(self):
        top = ttk.Frame(self, padding=(10, 8, 10, 6))
        top.pack(fill="x", side="top")
        ttk.Label(top, text="FitWeaver", style="Title.TLabel").pack(side="left", padx=(0, 20))
        ttk.Label(top, text="YAML план:", style="Muted.TLabel").pack(side="left")
        ttk.Entry(top, textvariable=self.yaml_path, width=55).pack(side="left", padx=4)
        ttk.Button(top, text="Обзор…",  command=self._browse_yaml).pack(side="left", padx=2)
        ttk.Button(top, text="↺",       command=self._reload_yaml, width=3).pack(side="left", padx=2)
        ttk.Separator(self, orient="horizontal").pack(fill="x")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        # Sidebar — scrollable
        sidebar_outer = ttk.Frame(body, width=240)
        sidebar_outer.pack(side="left", fill="y")
        sidebar_outer.pack_propagate(False)

        self._sb_canvas = tk.Canvas(sidebar_outer, bg=BG, highlightthickness=0)
        _sb_scroll = ttk.Scrollbar(sidebar_outer, orient="vertical",
                                   command=self._sb_canvas.yview)
        self._sb_canvas.configure(yscrollcommand=_sb_scroll.set)
        _sb_scroll.pack(side="right", fill="y")
        self._sb_canvas.pack(side="left", fill="both", expand=True)

        sidebar = ttk.Frame(self._sb_canvas, padding=(10, 10, 8, 8))
        _sb_win = self._sb_canvas.create_window((0, 0), window=sidebar, anchor="nw")

        def _sb_resize(e=None):
            self._sb_canvas.configure(scrollregion=self._sb_canvas.bbox("all"))
        def _sb_fit_width(e):
            self._sb_canvas.itemconfig(_sb_win, width=e.width)

        sidebar.bind("<Configure>", _sb_resize)
        self._sb_canvas.bind("<Configure>", _sb_fit_width)

        self._build_sidebar(sidebar)

        ttk.Separator(body, orient="vertical").pack(side="left", fill="y")

        # Right: notebook (calendar + LLM)
        right = ttk.Frame(body, padding=(10, 8))
        right.pack(side="left", fill="both", expand=True)
        self._build_right(right)

    # ── Sidebar ───────────────────────────────────────────────────────────────
    def _build_sidebar(self, p):
        def section(text):
            ttk.Label(p, text=text, style="Section.TLabel").pack(anchor="w", pady=(10, 3))
        def hline():
            ttk.Separator(p).pack(fill="x", pady=6)

        section("GARMIN CONNECT")
        ttk.Label(p, text="Email:",   style="Muted.TLabel").pack(anchor="w")
        ttk.Entry(p, textvariable=self.email_var).pack(fill="x", pady=(0, 4))
        ttk.Label(p, text="Пароль:", style="Muted.TLabel").pack(anchor="w")
        ttk.Entry(p, textvariable=self.pass_var, show="•").pack(fill="x", pady=(0, 4))

        hline(); section("ПЕРИОД")
        ttk.Label(p, text="С (YYYY-MM-DD):", style="Muted.TLabel").pack(anchor="w")
        ttk.Entry(p, textvariable=self.from_var).pack(fill="x", pady=(0, 4))
        ttk.Label(p, text="По (YYYY-MM-DD):", style="Muted.TLabel").pack(anchor="w")
        ttk.Entry(p, textvariable=self.to_var).pack(fill="x", pady=(0, 4))
        ttk.Label(p, text="Год:", style="Muted.TLabel").pack(anchor="w")
        ttk.Entry(p, textvariable=self.year_var, width=10).pack(anchor="w")
        ttk.Checkbutton(p, text="Dry-run (без изменений)",
                        variable=self.dry_run).pack(anchor="w", pady=(6, 0))

        hline(); section("ОСНОВНЫЕ ДЕЙСТВИЯ")
        ttk.Button(p, text="⚙  Собрать FIT-файлы", style="Primary.TButton",
                   command=self._cmd_build).pack(fill="x", pady=2)
        ttk.Button(p, text="↑  Загрузить в Garmin",
                   command=self._cmd_upload).pack(fill="x", pady=2)
        ttk.Button(p, text="✕  Удалить из Garmin", style="Danger.TButton",
                   command=self._cmd_delete).pack(fill="x", pady=2)

        hline(); section("ПРОДВИНУТЫЕ")
        ttk.Button(p, text="✓  Валидировать YAML",   command=self._cmd_validate_yaml).pack(fill="x", pady=2)
        ttk.Button(p, text="✓  Валидировать FIT",    command=self._cmd_validate_fit).pack(fill="x", pady=2)
        ttk.Button(p, text="🔍  Диагностика",         command=self._cmd_doctor).pack(fill="x", pady=2)
        ttk.Button(p, text="📦  Архивировать",        command=self._cmd_archive).pack(fill="x", pady=2)
        ttk.Button(p, text="📋  Список архивов",      command=self._cmd_list_archives).pack(fill="x", pady=2)
        ttk.Button(p, text="🔄  Восстановить архив",  command=self._cmd_restore).pack(fill="x", pady=2)

        # Bind mousewheel on all child widgets so scrolling works anywhere in sidebar
        def _sb_scroll_wheel(e):
            self._sb_canvas.yview_scroll(-1 * (e.delta // 120), "units")

        def _bind_sb_wheel(w):
            w.bind("<MouseWheel>", _sb_scroll_wheel, add="+")
            for child in w.winfo_children():
                _bind_sb_wheel(child)

        self._sb_canvas.bind("<MouseWheel>", _sb_scroll_wheel)
        p.after(100, lambda: _bind_sb_wheel(p))

    # ── Right panel (Notebook) ────────────────────────────────────────────────
    def _build_right(self, parent):
        self._nb = ttk.Notebook(parent)
        self._nb.pack(fill="both", expand=True)

        cal_tab    = ttk.Frame(self._nb, padding=(6, 6))
        llm_tab    = ttk.Frame(self._nb, padding=(6, 6))
        garmin_tab = ttk.Frame(self._nb, padding=(6, 6))
        self._nb.add(cal_tab,    text="📅  Календарь")
        self._nb.add(llm_tab,    text="🤖  LLM Генератор")
        self._nb.add(garmin_tab, text="🏃  Garmin Connect")

        self._build_calendar_tab(cal_tab)
        self._build_llm_tab(llm_tab)
        self._build_garmin_tab(garmin_tab)

    # ── Calendar tab ──────────────────────────────────────────────────────────
    def _build_calendar_tab(self, parent):
        nav = ttk.Frame(parent)
        nav.pack(fill="x", pady=(0, 6))
        ttk.Button(nav, text="◀", command=self._prev_month, width=3).pack(side="left")
        self._month_lbl = tk.Label(nav, text="", bg=BG, fg=PURPLE,
                                   font=("Segoe UI", 12, "bold"))
        self._month_lbl.pack(side="left", padx=10)
        ttk.Button(nav, text="▶", command=self._next_month, width=3).pack(side="left")
        tk.Label(nav, text=f"  Сегодня: {datetime.date.today().strftime('%d.%m.%Y')}",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=16)

        self._cal_frame = tk.Frame(parent, bg=BG2)
        self._cal_frame.pack(fill="both", expand=True)

        self._detail_var = tk.StringVar(value="Нажмите на тренировку для подробностей")
        tk.Label(parent, textvariable=self._detail_var,
                 bg=BG3, fg=FG, font=("Segoe UI", 9),
                 anchor="w", padx=8, pady=4).pack(fill="x", pady=(4, 0))

        ttk.Separator(parent).pack(fill="x", pady=6)
        log_hdr = ttk.Frame(parent)
        log_hdr.pack(fill="x")
        ttk.Label(log_hdr, text="ВЫВОД КОМАНДЫ", style="Section.TLabel").pack(side="left")
        ttk.Button(log_hdr, text="Очистить", command=self._clear_log, width=8).pack(side="right")
        self._log_w = scrolledtext.ScrolledText(
            parent, height=8, bg=BG2, fg=GREEN,
            font=("Consolas", 9), state="disabled",
            insertbackground=FG, relief="flat")
        self._log_w.pack(fill="x", pady=(4, 0))

        self._draw_calendar()

    # ── LLM tab ───────────────────────────────────────────────────────────────
    def _build_llm_tab(self, parent):
        # ── Connection bar ────────────────────────────────────────────────────
        conn = ttk.Frame(parent)
        conn.pack(fill="x", pady=(0, 8))

        ttk.Label(conn, text="URL:", style="Muted.TLabel").pack(side="left")
        ttk.Entry(conn, textvariable=self.llm_url, width=30).pack(side="left", padx=(4, 10))
        ttk.Label(conn, text="Модель:", style="Muted.TLabel").pack(side="left")
        ttk.Entry(conn, textvariable=self.llm_model, width=22).pack(side="left", padx=(4, 10))
        ttk.Label(conn, text="Тип:", style="Muted.TLabel").pack(side="left")
        cb = ttk.Combobox(conn, textvariable=self.llm_type, width=8,
                          values=["openai", "ollama"], state="readonly")
        cb.pack(side="left", padx=(4, 10))
        ttk.Button(conn, text="Проверить связь", command=self._llm_check).pack(side="left", padx=4)
        self._llm_status = tk.Label(conn, text="●", bg=BG, fg=MUTED,
                                    font=("Segoe UI", 14))
        self._llm_status.pack(side="left", padx=4)

        ttk.Separator(parent).pack(fill="x", pady=(0, 8))

        # ── Text areas ────────────────────────────────────────────────────────
        panes = ttk.Frame(parent)
        panes.pack(fill="both", expand=True)
        panes.columnconfigure(0, weight=1)
        panes.columnconfigure(1, weight=1)
        panes.rowconfigure(1, weight=1)

        # Input
        tk.Label(panes, text="Текст плана тренировок", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 9, "bold"), anchor="w").grid(
            row=0, column=0, sticky="w", pady=(0, 4))
        self._plan_text = tk.Text(panes, bg=BG3, fg=FG, font=("Segoe UI", 10),
                                  insertbackground=FG, relief="flat",
                                  wrap="word", undo=True)
        self._plan_text.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        # Explicit Ctrl+V binding (some themes suppress the default)
        self._plan_text.bind("<Control-v>", self._paste_text)
        self._plan_text.bind("<Control-V>", self._paste_text)
        sb1 = ttk.Scrollbar(panes, command=self._plan_text.yview)
        sb1.grid(row=1, column=0, sticky="nse")
        self._plan_text.config(yscrollcommand=sb1.set)

        # Output
        out_hdr = ttk.Frame(panes)
        out_hdr.grid(row=0, column=1, sticky="ew", pady=(0, 4))
        tk.Label(out_hdr, text="Сгенерированный YAML", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 9, "bold"), anchor="w").pack(side="left")
        ttk.Button(out_hdr, text="Скопировать", command=self._copy_yaml,
                   width=12).pack(side="right")

        self._yaml_out = tk.Text(panes, bg=BG2, fg=GREEN, font=("Consolas", 9),
                                 insertbackground=FG, relief="flat",
                                 wrap="none", state="disabled")
        self._yaml_out.grid(row=1, column=1, sticky="nsew")
        sb2 = ttk.Scrollbar(panes, command=self._yaml_out.yview)
        sb2.grid(row=1, column=1, sticky="nse")
        self._yaml_out.config(yscrollcommand=sb2.set)

        # ── Action bar ────────────────────────────────────────────────────────
        actions = ttk.Frame(parent)
        actions.pack(fill="x", pady=(8, 0))

        ttk.Button(actions, text="Пример плана", command=self._insert_example).pack(side="left", padx=2)
        ttk.Button(actions, text="Очистить",     command=self._clear_plan).pack(side="left", padx=2)

        self._gen_btn = ttk.Button(actions, text="🤖  Генерировать YAML",
                                   style="Primary.TButton", command=self._llm_generate)
        self._gen_btn.pack(side="left", padx=(16, 2))

        self._llm_progress = tk.Label(actions, text="", bg=BG, fg=YELLOW,
                                      font=("Segoe UI", 9))
        self._llm_progress.pack(side="left", padx=8)

        ttk.Button(actions, text="💾  Сохранить YAML",
                   command=self._save_yaml).pack(side="right", padx=2)
        ttk.Button(actions, text="📅  Загрузить в Garmin",
                   command=self._yaml_to_garmin).pack(side="right", padx=2)
        ttk.Button(actions, text="⚙  Собрать FIT", style="Success.TButton",
                   command=self._yaml_to_build).pack(side="right", padx=2)

    # ── Calendar drawing ──────────────────────────────────────────────────────
    def _draw_calendar(self):
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

        for r, week in enumerate(
                calendar.monthcalendar(self.cal_month.year, self.cal_month.month), start=1):
            self._cal_frame.rowconfigure(r, weight=1)
            for col, day in enumerate(week):
                cell = tk.Frame(self._cal_frame,
                                bg=BG3 if day else BG2, bd=0)
                cell.grid(row=r, column=col, padx=1, pady=1, sticky="nsew")
                if not day:
                    continue
                date = datetime.date(self.cal_month.year, self.cal_month.month, day)
                date_str = date.isoformat()
                day_fg = RED if date == today else (MUTED if col >= 5 else FG)
                tk.Label(cell, text=str(day), bg=BG3, fg=day_fg,
                         font=("Segoe UI", 8, "bold" if date == today else "normal"),
                         anchor="nw", padx=4, pady=2).pack(fill="x")
                for wo in by_date.get(date_str, []):
                    self._add_chip(cell, wo)

    def _add_chip(self, parent, wo):
        color = WORKOUT_COLORS.get((wo.get("type_code") or "").lower(), DEFAULT_WO_COLOR)
        name  = wo.get("name") or wo.get("filename") or ""
        short = re.sub(r"^W\d+_\d{2}-\d{2}_\w+_", "", name)[:22]
        chip  = tk.Label(parent, text=short, bg=color, fg="#1e1e2e",
                         font=("Segoe UI", 7, "bold"),
                         anchor="w", padx=3, pady=1, wraplength=130)
        chip.pack(fill="x", padx=2, pady=1)
        chip.bind("<Button-1>", lambda e, w=wo: self._show_detail(w))

    def _show_detail(self, wo):
        parts = [p for p in [
            wo.get("date"), wo.get("name"),
            f"[{wo['type_code']}]"     if wo.get("type_code")            else None,
            f"{wo['distance_km']} км"  if wo.get("distance_km")          else None,
            f"~{wo['estimated_duration_min']} мин" if wo.get("estimated_duration_min") else None,
        ] if p]
        self._detail_var.set("  " + "   ·   ".join(parts))

    def _prev_month(self):
        self.cal_month = (self.cal_month - datetime.timedelta(days=1)).replace(day=1)
        self._draw_calendar()

    def _next_month(self):
        m, y = self.cal_month.month, self.cal_month.year
        self.cal_month = datetime.date(y + (m // 12), (m % 12) + 1, 1)
        self._draw_calendar()

    # ── YAML load / save ──────────────────────────────────────────────────────
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
                dated = [w for w in self.workouts if w.get("date")]
                if dated:
                    self.cal_month = datetime.date.fromisoformat(dated[0]["date"]).replace(day=1)
            self._draw_calendar()
            self._log(f"[OK] Загружено {len(self.workouts)} тренировок из {Path(path).name}")
        except Exception as exc:
            self._log(f"[ERR] {exc}")

    def _parse_workouts(self, data):
        from garmin_fit.garmin_step_mapper import extract_date_from_filename
        year_str = self.year_var.get()
        year = int(year_str) if year_str.isdigit() else None
        result = []
        for wo in (data or {}).get("workouts", []):
            filename = wo.get("filename") or wo.get("name") or ""
            result.append({
                "name":     wo.get("name") or filename,
                "filename": filename,
                "date":     extract_date_from_filename(filename, year=year),
                "type_code": wo.get("type_code", ""),
                "distance_km": wo.get("distance_km"),
                "estimated_duration_min": wo.get("estimated_duration_min"),
            })
        return result

    # ── Log ───────────────────────────────────────────────────────────────────
    def _log(self, text):
        self._log_w.config(state="normal")
        self._log_w.insert("end", text + "\n")
        self._log_w.see("end")
        self._log_w.config(state="disabled")

    def _clear_log(self):
        self._log_w.config(state="normal")
        self._log_w.delete("1.0", "end")
        self._log_w.config(state="disabled")

    # ── CLI runner ────────────────────────────────────────────────────────────
    def _run(self, args):
        cmd = [PYTHON, "-m", "garmin_fit.cli"] + args
        self._log(f"\n$ garmin_fit.cli {' '.join(args)}")

        def worker():
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    cwd=PROJECT_ROOT,
                )
                for line in proc.stdout:
                    self.after(0, self._log, line.rstrip())
                proc.wait()
                msg = "[OK] Готово" if proc.returncode == 0 else f"[FAIL] код {proc.returncode}"
                self.after(0, self._log, msg)
            except Exception as exc:
                self.after(0, self._log, f"[ERR] {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _append_garmin_args(self, args):
        if self.email_var.get(): args += ["--email",     self.email_var.get()]
        if self.pass_var.get():  args += ["--password",  self.pass_var.get()]
        if self.year_var.get():  args += ["--year",      self.year_var.get()]
        if self.from_var.get():  args += ["--from-date", self.from_var.get()]
        if self.to_var.get():    args += ["--to-date",   self.to_var.get()]

    # ── CLI commands ──────────────────────────────────────────────────────────
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
            if not messagebox.askyesno("Подтверждение",
                    "Удалить тренировки из Garmin Connect?\nЭто необратимо.", icon="warning"):
                return
        args = ["garmin-calendar-delete"]
        self._append_garmin_args(args)
        args += ["--dry-run"] if self.dry_run.get() else ["--confirm"]
        self._run(args)

    def _cmd_validate_yaml(self):
        args = ["validate-yaml"]
        if self.yaml_path.get():
            args += ["--plan", self.yaml_path.get()]
        self._run(args)

    def _cmd_validate_fit(self):  self._run(["validate-fit"])
    def _cmd_doctor(self):        self._run(["doctor", "--llm"])
    def _cmd_archive(self):       self._run(["archive"])
    def _cmd_list_archives(self): self._run(["list-archives"])

    def _cmd_restore(self):
        name = simpledialog.askstring("Восстановить архив",
                                      "Введите имя архива:", parent=self)
        if name:
            self._run(["restore", name.strip()])

    # ── LLM tab helpers ───────────────────────────────────────────────────────
    def _llm_check(self):
        self._llm_status.config(text="●", fg=YELLOW)
        self.update_idletasks()

        def check():
            try:
                from garmin_fit.llm.client import UnifiedLLMClient
                client = UnifiedLLMClient(
                    model=self.llm_model.get(),
                    base_url=self.llm_url.get(),
                    api_type=self.llm_type.get(),
                )
                ok = client.check_connection()
                color = GREEN if ok else RED
                self.after(0, self._llm_status.config, {"text": "●", "fg": color})
            except Exception as exc:
                self.after(0, self._llm_status.config, {"text": "●", "fg": RED})
                self.after(0, self._set_progress, f"Ошибка: {exc}")

        threading.Thread(target=check, daemon=True).start()

    def _set_progress(self, text, color=YELLOW):
        self._llm_progress.config(text=text, fg=color)

    def _llm_generate(self):
        plan_text = self._plan_text.get("1.0", "end").strip()
        if not plan_text:
            messagebox.showwarning("Пустой план", "Введите текст плана тренировок.")
            return

        self._gen_btn.config(state="disabled")
        self._set_progress("⏳ Генерирую YAML…")
        self._yaml_out.config(state="normal")
        self._yaml_out.delete("1.0", "end")
        self._yaml_out.config(state="disabled")

        def worker():
            try:
                from garmin_fit.llm.client import UnifiedLLMClient
                from garmin_fit.plan_service import build_plan_draft

                client = UnifiedLLMClient(
                    model=self.llm_model.get(),
                    base_url=self.llm_url.get(),
                    api_type=self.llm_type.get(),
                )
                result = build_plan_draft(client, plan_text, max_retries=1)

                yaml_text = result.yaml_text or ""
                warnings  = result.warnings or []
                repairs   = result.repairs or []

                # Count workouts from yaml_text
                try:
                    n = len((yaml.safe_load(yaml_text) or {}).get("workouts", []))
                except Exception:
                    n = 0

                def finish():
                    self._yaml_out.config(state="normal")
                    self._yaml_out.delete("1.0", "end")
                    self._yaml_out.insert("end", yaml_text)
                    self._yaml_out.config(state="disabled")

                    status = f"✅ Готово — {n} тренировок"
                    if repairs:
                        status += f", {len(repairs)} правок"
                    if warnings:
                        status += f", {len(warnings)} предупреждений"
                    self._set_progress(status, GREEN)
                    self._gen_btn.config(state="normal")

                    if repairs:
                        self._log("\n[Авто-правки]")
                        for r in repairs:
                            self._log(f"  {r}")
                    if warnings:
                        self._log("\n[Предупреждения]")
                        for w in warnings:
                            self._log(f"  {w}")

                self.after(0, finish)

            except Exception as exc:
                def on_err():
                    self._set_progress(f"❌ Ошибка: {exc}", RED)
                    self._gen_btn.config(state="normal")
                self.after(0, on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _copy_yaml(self):
        text = self._yaml_out.get("1.0", "end").strip()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)

    def _clear_plan(self):
        self._plan_text.delete("1.0", "end")
        self._yaml_out.config(state="normal")
        self._yaml_out.delete("1.0", "end")
        self._yaml_out.config(state="disabled")
        self._set_progress("")

    def _save_yaml(self):
        text = self._yaml_out.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Нет YAML", "Сначала сгенерируйте YAML.")
            return
        path = filedialog.asksaveasfilename(
            title="Сохранить YAML план",
            defaultextension=".yaml",
            filetypes=[("YAML files", "*.yaml"), ("All files", "*.*")],
            initialdir=PROJECT_ROOT / "Plan",
        )
        if path:
            Path(path).write_text(text, encoding="utf-8")
            self.yaml_path.set(path)
            self._reload_yaml()
            self._set_progress(f"Сохранено: {Path(path).name}", GREEN)
            self._nb.select(0)

    def _paste_text(self, event):
        try:
            text = self.clipboard_get()
            self._plan_text.insert(tk.INSERT, text)
        except tk.TclError:
            pass
        return "break"  # prevent default handler from doubling the paste

    def _yaml_save_temp(self) -> str | None:
        text = self._yaml_out.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Нет YAML", "Сначала сгенерируйте YAML.")
            return None
        plan_dir = PROJECT_ROOT / "Plan"
        plan_dir.mkdir(exist_ok=True)
        tmp = plan_dir / f"_gui_draft_{datetime.datetime.now().strftime('%H%M%S')}.yaml"
        tmp.write_text(text, encoding="utf-8")
        self.yaml_path.set(str(tmp))
        self._reload_yaml()
        return str(tmp)

    def _yaml_to_build(self):
        path = self._yaml_save_temp()
        if path:
            self._nb.select(0)
            self._cmd_build()

    def _yaml_to_garmin(self):
        path = self._yaml_save_temp()
        if path:
            self._nb.select(0)
            self._cmd_upload()

    # ── Garmin Connect tab ────────────────────────────────────────────────────
    def _build_garmin_tab(self, parent):
        # Top bar
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="🔄  Загрузить из Garmin",
                   style="Primary.TButton",
                   command=self._gc_load).pack(side="left", padx=(0, 8))
        ttk.Label(bar, text="Лимит:", style="Muted.TLabel").pack(side="left")
        self._gc_limit = tk.StringVar(value="200")
        ttk.Entry(bar, textvariable=self._gc_limit, width=6).pack(side="left", padx=(4, 16))
        self._gc_del_btn = ttk.Button(bar, text="🗑  Удалить выбранные (0)",
                                      style="Danger.TButton",
                                      state="disabled",
                                      command=self._gc_delete_selected)
        self._gc_del_btn.pack(side="left", padx=(0, 8))
        self._gc_status = tk.Label(bar, text="Нажмите «Загрузить» для получения данных",
                                   bg=BG, fg=MUTED, font=("Segoe UI", 9))
        self._gc_status.pack(side="left")

        ttk.Separator(parent).pack(fill="x", pady=(0, 6))

        # Scrollable list
        container = ttk.Frame(parent)
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

        # Bottom summary
        self._gc_summary = tk.Label(parent, text="", bg=BG3, fg=MUTED,
                                    font=("Segoe UI", 9), anchor="w", padx=8, pady=3)
        self._gc_summary.pack(fill="x", side="bottom", pady=(4, 0))

        self._gc_workouts: list[dict] = []
        self._gc_checks:   dict[str, tk.BooleanVar] = {}
        self._gc_month_ids: dict[str, list[str]] = {}

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

    def _gc_load(self):
        if not self.email_var.get():
            messagebox.showwarning("Нет email", "Введите email в левой панели.")
            return
        self._gc_status.config(text="⏳ Подключаюсь к Garmin Connect…", fg=YELLOW)
        self._gc_clear_list()

        def worker():
            try:
                from garmin_fit.workflow import _connect_garmin_cli_client
                client = _connect_garmin_cli_client(
                    email=self.email_var.get() or None,
                    password=self.pass_var.get() or None,
                )
                limit = int(self._gc_limit.get() or 200)
                workouts = client.get_workouts(0, limit)
                self.after(0, self._gc_render, workouts)
            except Exception as exc:
                self.after(0, self._gc_status.config,
                           {"text": f"❌ {exc}", "fg": RED})

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
            text=f"✅ {total} тренировок ({fitweaver} с датой FitWeaver)", fg=GREEN)
        self._gc_summary.config(
            text=f"Всего: {total}  |  FitWeaver: {fitweaver}  |  Без даты: {len(no_date)}")

    def _gc_render_month(self, month_key: str, workouts: list[dict]):
        ids = [str(wo.get("workoutId") or wo.get("id") or "") for wo in workouts]
        self._gc_month_ids[month_key] = ids

        if month_key != "no_date":
            try:
                dt = datetime.date.fromisoformat(month_key + "-01")
                label = f"{MONTHS_RU[dt.month - 1]} {dt.year}  ({len(workouts)})"
            except ValueError:
                label = f"{month_key}  ({len(workouts)})"
        else:
            label = f"Без даты  ({len(workouts)})"

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

    def _gc_friendly_error(self, exc: Exception) -> str:
        msg = str(exc)
        if "400" in msg and "ATP" in msg:
            return "Тренировка привязана к Garmin ATP Plan — удалить через API невозможно.\nУдалите вручную в приложении Garmin Connect."
        if "400" in msg:
            return "Garmin отклонил удаление (400). Возможно, тренировка защищена или уже удалена."
        if "401" in msg or "403" in msg:
            return "Нет прав на удаление. Проверьте email/пароль."
        return f"Ошибка: {exc}"

    def _gc_delete_one(self, workout_id: str, row_widget: tk.Frame):
        def worker():
            try:
                from garmin_fit.workflow import _connect_garmin_cli_client
                client = _connect_garmin_cli_client(
                    email=self.email_var.get() or None,
                    password=self.pass_var.get() or None,
                )
                client.delete_workout(workout_id)
                self.after(0, row_widget.destroy)
                self.after(0, self._gc_update_del_btn)
                self.after(0, self._gc_status.config,
                           {"text": f"✅ Удалено {workout_id}", "fg": GREEN})
            except Exception as exc:
                self.after(0, messagebox.showerror,
                           "Не удалось удалить", self._gc_friendly_error(exc))
                self.after(0, self._gc_status.config,
                           {"text": "❌ Ошибка удаления", "fg": RED})

        threading.Thread(target=worker, daemon=True).start()

    def _gc_delete_selected(self):
        to_delete = [(wid, v) for wid, v in self._gc_checks.items() if v.get()]
        if not to_delete:
            return
        if not messagebox.askyesno(
                "Удалить выбранные",
                f"Удалить {len(to_delete)} тренировок из Garmin Connect?\n\nЭто необратимо.",
                icon="warning"):
            return

        self._gc_del_btn.config(state="disabled")
        self._gc_status.config(text=f"⏳ Удаляю {len(to_delete)} тренировок…", fg=YELLOW)

        def worker():
            try:
                from garmin_fit.workflow import _connect_garmin_cli_client
                client = _connect_garmin_cli_client(
                    email=self.email_var.get() or None,
                    password=self.pass_var.get() or None,
                )
            except Exception as exc:
                self.after(0, self._gc_status.config,
                           {"text": f"❌ {exc}", "fg": RED})
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
                self._gc_load()   # refresh list
                parts = [f"✅ Удалено: {deleted}"]
                if atp:    parts.append(f"ATP (пропущено): {atp}")
                if failed: parts.append(f"Ошибок: {failed}")
                self._gc_status.config(text="  |  ".join(parts),
                                       fg=GREEN if not failed else YELLOW)

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    # ── LLM example ───────────────────────────────────────────────────────────
    def _insert_example(self):
        example = (
            "01.05.2026 (Чт) — Длинный бег\n"
            "20 км, пульс 125–140 уд/мин\n\n"
            "03.05.2026 (Сб) — Интервалы\n"
            "Разминка 2 км, 6×800 м пульс 160–170 / 400 м пульс 120–130, заминка 1.5 км\n\n"
            "05.05.2026 (Пн) — Темповый бег\n"
            "Разминка 2 км, основная часть 5 км пульс 155–165, заминка 1 км\n"
        )
        self._plan_text.delete("1.0", "end")
        self._plan_text.insert("1.0", example)


if __name__ == "__main__":
    app = App()
    app.mainloop()
