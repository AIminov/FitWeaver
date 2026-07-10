#!/usr/bin/env python3
"""FitWeaver Desktop GUI — local calendar, CLI wrapper and LLM generator."""

import calendar
import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

import json

import yaml

from garmin_fit.gui_theme import configure_customtkinter, configure_ttk, load_customtkinter
from garmin_fit.gui_validation import parse_builder_value, parse_repeat_count

if getattr(sys, "frozen", False):
    # PyInstaller-frozen exe: treat the exe's own folder as a portable app
    # directory, so Plan/profiles/.gui_session.json persist next to it
    # across launches instead of vanishing with the temp extraction folder.
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
SESSION_FILE = PROJECT_ROOT / ".gui_session.json"

sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Optional modern root toolkit. All existing native widgets remain supported;
# the fallback keeps the source checkout usable without the GUI extra.
_CTK = load_customtkinter()
if _CTK is not None:
    configure_customtkinter(_CTK)
_AppBase = _CTK.CTk if _CTK is not None else tk.Tk

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
WEEKDAY_ABBR_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

STEP_INTENSITY_COLORS = {
    "warmup":   "#94e2d5",
    "active":   "#f38ba8",
    "recovery": "#6c7086",
    "cooldown": "#89b4fa",
}

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
}

MONTHS_RU = ["Январь","Февраль","Март","Апрель","Май","Июнь",
              "Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"]
DAYS_RU   = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]

# Friendly-language hints shown under recognized CLI/subprocess error lines in
# the log panel -- purely a GUI-side presentation layer, doesn't touch the
# underlying CLI error text (power users running `python -m garmin_fit.cli`
# directly still see the raw messages). Checked in order; first match wins.
_ERROR_HINTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"YAML (plan|file) not found", re.I),
     "Проверьте путь к файлу — убедитесь, что он указан верно и файл существует."),
    (re.compile(r"No YAML training plan found in"),
     "В папке Plan рядом с программой нет ни одного .yaml-файла. "
     "Выберите план через «Обзор…» или сначала сохраните его."),
    (re.compile(r"Connection check failed|Cannot connect to (Ollama|OpenAI-compatible|API at)", re.I),
     "Не удаётся подключиться к LLM. Проверьте, что сервер запущен, "
     "и что адрес/порт в настройках подключения указаны верно."),
    (re.compile(r"Timeout waiting for.*response", re.I),
     "LLM слишком долго не отвечает. Попробуйте план покороче или проверьте, что модель загружена."),
    (re.compile(r"Authentication failed", re.I),
     "Не удалось войти в Garmin Connect — проверьте логин и пароль."),
    (re.compile(r"(garmin-auth|garminconnect) not installed", re.I),
     "Не хватает модуля для работы с Garmin Connect. Переустановите приложение "
     "или сообщите разработчику."),
    (re.compile(r"YAML validation errors found|VALIDATION ERRORS"),
     "В плане есть ошибки — прокрутите лог немного выше, там подробности по каждой."),
    (re.compile(r"No FIT files (found|generated)"),
     "FIT-файлы не были созданы. Проверьте, что план прошёл валидацию без ошибок."),
    (re.compile(r"temp directory is not writable"),
     "Нет прав на запись во временную папку Windows — проверьте права доступа."),
]


# ══════════════════════════════════════════════════════════════════════════════
class App(_AppBase):
    def __init__(self):
        super().__init__()
        self.title("FitWeaver")
        self.geometry("1440x920")
        self.minsize(1180, 720)
        if _CTK is not None:
            self.configure(fg_color=BG)
        else:
            self.configure(bg=BG)

        # Shared state
        self.yaml_path = tk.StringVar()
        self.email_var = tk.StringVar()
        self.pass_var  = tk.StringVar()
        self.from_var  = tk.StringVar()
        self.to_var    = tk.StringVar()
        self.year_var  = tk.StringVar(value=str(datetime.date.today().year))
        self.dry_run   = tk.BooleanVar(value=True)
        self._shell_status_var = tk.StringVar(value="Готово")
        self._yaml_status_var = tk.StringVar(value="План не выбран")
        self._yaml_ready = False
        self._operation_active = False
        self._operation_label = ""
        self._operation_button_states: dict[object, str] = {}
        self._quick_action_buttons: dict[str, ttk.Button] = {}

        # LLM settings ("own" mode — direct connection to a local LLM)
        self.llm_url     = tk.StringVar(value="http://127.0.0.1:1234")
        self.llm_model   = tk.StringVar(value="qwen/qwen3.5-9b")
        self.llm_type    = tk.StringVar(value="openai")
        self.llm_timeout = tk.IntVar(value=900)

        # Plan API settings ("api" mode — hosted FitWeaver Plan API, e.g. someone
        # else's LLM, no local LLM setup required)
        self.llm_conn_mode = tk.StringVar(value="own")   # "own" | "api"
        self.api_url        = tk.StringVar(value="http://127.0.0.1:8008")
        self.api_token       = tk.StringVar(value="")

        # UI mode ("simple" hides advanced/technical controls; "expert" shows
        # everything) -- machine-wide preference, same tier as llm_conn_mode.
        self.ui_mode = tk.StringVar(value="simple")   # "simple" | "expert"
        self._llm_conn_expanded = False  # simple mode: connection details collapsed by default
        self._period_expanded = False  # simple mode: Garmin date/dry-run options collapsed

        self.workouts: list[dict] = []
        self.cal_month = datetime.date.today().replace(day=1)
        self._store = None  # PlanStore | None — internal staging layer, YAML stays canonical
        self._active_profile_email: str | None = None
        self._profile_status_var = tk.StringVar(value="Профиль не выбран")

        # Visual builder draft state (pre-commit, plain Python — no PlanStore
        # writes happen until "Добавить в план")
        self._builder_steps: list = []
        self._builder_selected_index: int | None = None
        self._builder_range_start: int | None = None
        self._builder_range_end: int | None = None
        self._builder_input_errors: set[tuple[int, str]] = set()

        # Calendar drag & drop (move a workout to another day)
        self._drag_workout: dict | None = None
        self._drag_start_xy: tuple[int, int] | None = None
        self._drag_moved = False

        # Toast notifications (stacked, auto-dismiss)
        self._active_toasts: list[tk.Toplevel] = []

        self._setup_style()
        self._build_ui()
        self.yaml_path.trace_add("write", lambda *_: self._on_yaml_path_change())
        self._update_yaml_context()
        self._setup_text_bindings()
        self._load_session()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Session persistence ───────────────────────────────────────────────────
    # LLM connection settings (url/model/type/timeout) describe the local LLM
    # server on this machine, not the person using it — they stay in the one
    # global SESSION_FILE, shared across every profile. yaml_path/year are
    # remembered per-profile (see profile_store.py) so several people can
    # share one PC; the copies in SESSION_FILE are only a legacy fallback for
    # when no profile/email has been set yet.
    def _load_session(self):
        try:
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}

        if data.get("llm_url"):
            self.llm_url.set(data["llm_url"])
        if data.get("llm_model"):
            self.llm_model.set(data["llm_model"])
        if data.get("llm_type"):
            self.llm_type.set(data["llm_type"])
        if data.get("llm_timeout"):
            try:
                self.llm_timeout.set(int(data["llm_timeout"]))
            except (TypeError, ValueError):
                pass
        if data.get("llm_conn_mode") in ("own", "api"):
            self.llm_conn_mode.set(data["llm_conn_mode"])
        if data.get("api_url"):
            self.api_url.set(data["api_url"])
        if data.get("api_token"):
            self.api_token.set(data["api_token"])
        if data.get("ui_mode") in ("simple", "expert"):
            self.ui_mode.set(data["ui_mode"])
        self._on_ui_mode_change()

        if data.get("yaml_path"):
            self.yaml_path.set(data["yaml_path"])
        if data.get("year"):
            self.year_var.set(data["year"])

        self._refresh_profile_list()

        email = data.get("last_active_email") or data.get("email") or ""
        if email:
            self.email_var.set(email)
            self._activate_profile(email)

        if self.yaml_path.get() and Path(self.yaml_path.get()).exists():
            self._reload_yaml()

    def _activate_profile(self, email: str, *, reset_if_missing: bool = False) -> None:
        """Switch GUI-local state (plan path, year, HR zones) to this profile.

        reset_if_missing=True clears yaml_path/year when the target profile
        has no saved session of its own — used on a live runtime switch, so
        a second person never inherits the previous person's in-memory plan
        path. On initial startup (reset_if_missing=False) whatever the
        legacy global session fallback already populated is left in place,
        so a pre-existing single-user setup migrates smoothly into its
        first named profile instead of being wiped.
        """
        from garmin_fit.profile_store import (
            activate_user_profile,
            has_user_profile,
            load_session,
            migrate_legacy_user_profile,
        )

        self._active_profile_email = email
        profile_data = load_session(email)
        if profile_data.get("yaml_path"):
            self.yaml_path.set(profile_data["yaml_path"])
        elif reset_if_missing:
            self.yaml_path.set("")
        if profile_data.get("year"):
            self.year_var.set(profile_data["year"])
        elif reset_if_missing:
            self.year_var.set(str(datetime.date.today().year))
        self._gc_history = list(profile_data.get("garmin_history", []))[-8:]
        self._refresh_gc_history()

        if not has_user_profile(email):
            if migrate_legacy_user_profile(email):
                self._log(f"[OK] Найден существующий user_profile.yaml — перенесён в профиль {email}")
            else:
                self._prompt_hr_profile(email)

        try:
            activate_user_profile(email)
        except OSError as exc:
            self._log(f"[ERR] Не удалось применить профиль {email}: {exc}")

        self._builder_refresh_my_templates()
        self._refresh_profile_status()

    def _prompt_hr_profile(self, email: str) -> None:
        """First-run onboarding: ask for max/resting HR so the LLM prompt can
        use personal zones. Not required — has a Skip button — since this
        data is low-stakes and can be hand-edited in the profile's
        user_profile.yaml at any time."""
        dialog = tk.Toplevel(self)
        dialog.title("Новый профиль")
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.resizable(False, False)

        tk.Label(dialog, text=f"Профиль {email} создан впервые",
                 bg=BG, fg=ACCENT, font=("Segoe UI", 10, "bold"),
                 padx=16, anchor="w").pack(fill="x", pady=(16, 4))
        tk.Label(dialog,
                 text="Пульсовые данные помогают LLM точнее строить тренировки.\n"
                      "Зоны рассчитаются автоматически из максимального пульса.\n"
                      "Не обязательно — можно пропустить и настроить позже вручную\n"
                      "в profiles/.../user_profile.yaml.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9), justify="left",
                 padx=16, anchor="w").pack(fill="x", pady=(0, 8))

        form = ttk.Frame(dialog, padding=(16, 0))
        form.pack(fill="x")
        max_hr_var = tk.StringVar()
        resting_hr_var = tk.StringVar()
        ttk.Label(form, text="Максимальный пульс (уд/мин):", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=max_hr_var, width=10).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(form, text="Пульс покоя (уд/мин):", style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=resting_hr_var, width=10).grid(row=1, column=1, padx=(8, 0))

        def _save():
            from garmin_fit.profile_store import activate_user_profile, write_user_profile
            try:
                max_hr = int(max_hr_var.get())
                resting_hr = int(resting_hr_var.get())
            except ValueError:
                messagebox.showwarning(
                    "Некорректные данные",
                    "Введите пульс числом, либо нажмите «Пропустить».", parent=dialog)
                return
            if not (100 <= max_hr <= 240) or not (30 <= resting_hr <= 150):
                messagebox.showwarning(
                    "Некорректные данные",
                    "Проверьте диапазоны: макс. пульс 100–240, пульс покоя 30–150.",
                    parent=dialog)
                return
            write_user_profile(email, max_hr=max_hr, resting_hr=resting_hr)
            activate_user_profile(email)
            self._log(f"[OK] Пульсовой профиль сохранён для {email}")
            dialog.destroy()

        def _skip():
            from garmin_fit.profile_store import mark_user_profile_skipped
            mark_user_profile_skipped(email)
            dialog.destroy()

        actions = ttk.Frame(dialog, padding=16)
        actions.pack(fill="x")
        ttk.Button(actions, text="Пропустить", command=_skip).pack(side="left")
        ttk.Button(actions, text="Сохранить", style="Primary.TButton",
                   command=_save).pack(side="right")

        dialog.protocol("WM_DELETE_WINDOW", _skip)
        dialog.grab_set()
        dialog.wait_window()

    def _refresh_profile_list(self) -> None:
        from garmin_fit.profile_store import list_profiles
        self._profile_combo["values"] = list_profiles()

    def _refresh_profile_status(self) -> None:
        if not hasattr(self, "_profile_status_var"):
            return
        email = self._active_profile_email
        if not email:
            self._profile_status_var.set("Профиль не выбран")
            return
        from garmin_fit.profile_store import user_profile_yaml_path

        path = user_profile_yaml_path(email)
        if not path.exists():
            self._profile_status_var.set("HR-профиль ещё не настроен")
            return
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            self._profile_status_var.set("HR-профиль повреждён · настройте заново")
            return
        if isinstance(data, dict) and data.get("max_hr"):
            self._profile_status_var.set(
                f"HR-профиль настроен · макс. пульс {data['max_hr']}"
            )
        else:
            self._profile_status_var.set("HR-профиль пропущен · можно настроить")

    def _edit_hr_profile(self):
        if not self._active_profile_email:
            messagebox.showwarning("Нет профиля", "Сначала выберите или создайте профиль.", parent=self)
            return
        self._prompt_hr_profile(self._active_profile_email)
        self._refresh_profile_status()

    def _clear_garmin_auth(self):
        """Remove only the cached Garmin token for the active email."""
        email = self._active_profile_email or self.email_var.get().strip()
        if not email:
            messagebox.showwarning("Нет профиля", "Сначала выберите профиль Garmin.", parent=self)
            return
        from garmin_fit.workflow import _resolve_garmin_token_dir

        token_dir = _resolve_garmin_token_dir(email=email)
        if not token_dir or not token_dir.exists():
            self.pass_var.set("")
            self._gc_status.config(text="Сохранённой авторизации нет", fg=MUTED)
            return
        if not messagebox.askyesno(
                "Выйти из Garmin",
                f"Очистить сохранённую авторизацию только для {email}?\n\n"
                "План и настройки профиля не будут удалены.",
                icon="warning", parent=self):
            return
        try:
            shutil.rmtree(token_dir)
            self.pass_var.set("")
            self._gc_status.config(text="Авторизация очищена · войдите заново", fg=YELLOW)
            self._log(f"[OK] Сохранённая авторизация очищена для {email}")
        except OSError as exc:
            self._gc_status.config(text=f"Не удалось очистить авторизацию: {exc}", fg=RED)

    def _gui_mfa_prompt(self, prompt: str = "Код Garmin MFA") -> str:
        """Ask for MFA on the GUI thread while auth continues in a worker."""
        result: dict[str, str] = {}
        completed = threading.Event()

        def ask() -> None:
            try:
                value = simpledialog.askstring(
                    "Подтверждение Garmin",
                    "Введите код MFA из приложения или email Garmin:",
                    parent=self,
                )
                result["value"] = (value or "").strip()
            finally:
                completed.set()

        self.after(0, ask)
        if not completed.wait(120):
            raise TimeoutError("Код MFA не введён за 120 секунд.")
        return result.get("value", "")

    def _save_current_profile_session(self) -> None:
        if not self._active_profile_email:
            return
        from garmin_fit.profile_store import save_session
        save_session(self._active_profile_email, {
            "yaml_path": self.yaml_path.get(),
            "year":      self.year_var.get(),
            "garmin_history": self._gc_history[-8:],
        })

    def _on_email_change(self, event=None):
        new_email = self.email_var.get().strip()
        if not new_email or new_email == self._active_profile_email:
            return
        self._save_current_profile_session()
        # Пароль не сохраняется в профиле и не должен переноситься между email.
        self.pass_var.set("")
        self._activate_profile(new_email, reset_if_missing=True)
        self._refresh_profile_list()
        if self.yaml_path.get() and Path(self.yaml_path.get()).exists():
            self._reload_yaml()
        else:
            self.workouts = []
            self._draw_calendar()
        self._log(f"[OK] Профиль переключён: {new_email}")

    def _create_profile(self):
        email = simpledialog.askstring(
            "Новый профиль",
            "Введите email Garmin для нового профиля:",
            parent=self,
        )
        email = (email or "").strip()
        if not email:
            return
        if "@" not in email:
            messagebox.showwarning(
                "Некорректный email",
                "Введите email в формате user@example.com.",
                parent=self,
            )
            return
        self.email_var.set(email)
        self._on_email_change()

    def _save_session(self):
        self._save_current_profile_session()
        data = {
            "yaml_path":         self.yaml_path.get(),
            "last_active_email": self.email_var.get(),
            "year":              self.year_var.get(),
            "llm_url":           self.llm_url.get(),
            "llm_model":         self.llm_model.get(),
            "llm_type":          self.llm_type.get(),
            "llm_timeout":       self.llm_timeout.get(),
            "llm_conn_mode":     self.llm_conn_mode.get(),
            "api_url":           self.api_url.get(),
            # Plaintext, same as bot_config.yaml/api_config.yaml -- acceptable
            # for a single-user local desktop app, not a new risk class.
            "api_token":         self.api_token.get(),
            "ui_mode":           self.ui_mode.get(),
        }
        SESSION_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                encoding="utf-8")

    def _on_close(self):
        self._save_session()
        if self._store is not None:
            self._store.close()
        self.destroy()

    # ── Style ─────────────────────────────────────────────────────────────────
    def _setup_style(self):
        s = ttk.Style(self)
        configure_ttk(s)

    # ── Top layout ────────────────────────────────────────────────────────────
    def _build_ui(self):
        if _CTK is not None:
            top = _CTK.CTkFrame(self, fg_color=BG2, corner_radius=12)
        else:
            top = ttk.Frame(self, style="Card.TFrame", padding=(10, 8, 10, 6))
        top.pack(fill="x", side="top", padx=10, pady=(10, 6))

        header = ttk.Frame(top, padding=(10, 8, 10, 6))
        header.pack(fill="x")
        title_block = ttk.Frame(header)
        title_block.pack(side="left", padx=(0, 20))
        ttk.Label(title_block, text="FitWeaver", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_block, text="Garmin workout workspace", style="Muted.TLabel").pack(anchor="w")

        plan_block = ttk.Frame(header)
        plan_block.pack(side="left", fill="x", expand=True)
        ttk.Label(plan_block, text="Текущий план", style="Muted.TLabel").pack(anchor="w")
        plan_row = ttk.Frame(plan_block)
        plan_row.pack(fill="x")
        ttk.Entry(plan_row, textvariable=self.yaml_path, width=55).pack(
            side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(plan_row, text="Обзор…", command=self._browse_yaml).pack(side="left", padx=2)
        ttk.Button(plan_row, text="↺", command=self._reload_yaml, width=3).pack(side="left", padx=2)
        ttk.Label(plan_block, textvariable=self._yaml_status_var,
                  style="Status.TLabel").pack(anchor="w", pady=(3, 0))

        ttk.Label(header, textvariable=self._shell_status_var,
                  style="Muted.TLabel").pack(side="right", padx=(14, 4))

        quick_actions = ttk.Frame(top, padding=(10, 0, 10, 10))
        quick_actions.pack(fill="x")
        ttk.Label(quick_actions, text="Быстрые действия", style="Section.TLabel").pack(
            side="left", padx=(0, 10))
        self._quick_action_buttons["validate"] = ttk.Button(
            quick_actions, text="Проверить YAML", command=self._cmd_validate_yaml)
        self._quick_action_buttons["validate"].pack(side="left", padx=2)
        self._quick_action_buttons["build"] = ttk.Button(
            quick_actions, text="Собрать FIT", style="Primary.TButton", command=self._cmd_build)
        self._quick_action_buttons["build"].pack(side="left", padx=2)
        self._quick_action_buttons["upload"] = ttk.Button(
            quick_actions, text="Загрузить в Garmin", style="Success.TButton", command=self._cmd_upload)
        self._quick_action_buttons["upload"].pack(side="left", padx=2)
        self._quick_action_buttons["delete"] = ttk.Button(
            quick_actions, text="Удалить из Garmin", style="Danger.TButton", command=self._cmd_delete)
        self._quick_action_buttons["delete"].pack(side="left", padx=2)
        ttk.Separator(self, orient="horizontal").pack(fill="x")

        # Horizontal split: sidebar | notebook | log panel. A real ttk.PanedWindow
        # (not plain pack(side="left")) so the log panel is drag-resizable --
        # long command output needs more room than a fixed-width column gives.
        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)

        # Sidebar — scrollable
        sidebar_outer = ttk.Frame(body, width=240)
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

        # Right: notebook (calendar + LLM)
        right = ttk.Frame(body, padding=(10, 8))
        self._build_right(right)

        # Log panel: always visible regardless of active tab, unlike the old
        # Calendar-tab-only version -- long command output needs its own room.
        log_panel = ttk.Frame(body, width=380, padding=(10, 8))
        log_panel.pack_propagate(False)
        self._build_log_panel(log_panel)

        body.add(sidebar_outer, weight=0)
        body.add(right, weight=3)
        body.add(log_panel, weight=1)

    # ── Sidebar ───────────────────────────────────────────────────────────────
    def _build_sidebar(self, p):
        def section(text):
            ttk.Label(p, text=text, style="Section.TLabel").pack(anchor="w", pady=(10, 3))
        def hline():
            ttk.Separator(p).pack(fill="x", pady=6)

        ttk.Checkbutton(p, text="Экспертный режим", variable=self.ui_mode,
                        onvalue="expert", offvalue="simple",
                        command=self._on_ui_mode_change).pack(anchor="w", pady=(0, 6))
        hline()

        section("ПРОФИЛЬ GARMIN")
        ttk.Label(
            p,
            text="Выберите существующий или создайте новый профиль:",
            style="Muted.TLabel",
            wraplength=215,
            justify="left",
        ).pack(anchor="w")
        profile_row = ttk.Frame(p)
        profile_row.pack(fill="x", pady=(3, 4))
        self._profile_combo = ttk.Combobox(profile_row, textvariable=self.email_var)
        self._profile_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(profile_row, text="＋ Новый", command=self._create_profile).pack(
            side="left", padx=(4, 0)
        )
        self._profile_combo.bind("<<ComboboxSelected>>", self._on_email_change)
        self._profile_combo.bind("<FocusOut>", self._on_email_change)
        self._profile_combo.bind("<Return>", self._on_email_change)
        ttk.Label(p, textvariable=self._profile_status_var,
                  style="Status.TLabel", wraplength=215, justify="left").pack(anchor="w")
        ttk.Button(p, text="⚙  Настроить HR-профиль",
                   command=self._edit_hr_profile).pack(fill="x", pady=(4, 2))
        ttk.Label(p, text="Пароль:", style="Muted.TLabel").pack(anchor="w")
        ttk.Entry(p, textvariable=self.pass_var, show="•").pack(fill="x", pady=(0, 4))
        ttk.Button(p, text="⌫  Выйти из Garmin",
                   command=self._clear_garmin_auth).pack(fill="x", pady=(2, 0))

        self._period_toggle_btn = ttk.Button(
            p, text="▸  Параметры периода", command=self._toggle_period_settings)
        self._period_toggle_btn.pack(fill="x", pady=(10, 2))
        self._period_frame = ttk.Frame(p)
        self._period_frame.pack(fill="x")
        ttk.Label(self._period_frame, text="ПЕРИОД", style="Section.TLabel").pack(
            anchor="w", pady=(4, 3))
        ttk.Label(self._period_frame, text="С (YYYY-MM-DD):",
                  style="Muted.TLabel").pack(anchor="w")
        ttk.Entry(self._period_frame, textvariable=self.from_var).pack(
            fill="x", pady=(0, 4))
        ttk.Label(self._period_frame, text="По (YYYY-MM-DD):",
                  style="Muted.TLabel").pack(anchor="w")
        ttk.Entry(self._period_frame, textvariable=self.to_var).pack(
            fill="x", pady=(0, 4))
        ttk.Label(self._period_frame, text="Год:", style="Muted.TLabel").pack(anchor="w")
        ttk.Entry(self._period_frame, textvariable=self.year_var, width=10).pack(anchor="w")
        ttk.Checkbutton(self._period_frame, text="Dry-run (без изменений)",
                        variable=self.dry_run).pack(anchor="w", pady=(6, 0))

        self._advanced_hline = ttk.Separator(p)
        self._advanced_hline.pack(fill="x", pady=6)
        self._advanced_actions_frame = ttk.Frame(p)
        self._advanced_actions_frame.pack(fill="x")
        section_adv = self._advanced_actions_frame
        ttk.Label(section_adv, text="ПРОДВИНУТЫЕ", style="Section.TLabel").pack(anchor="w", pady=(4, 3))
        ttk.Button(section_adv, text="✓  Валидировать YAML",   command=self._cmd_validate_yaml).pack(fill="x", pady=2)
        ttk.Button(section_adv, text="✓  Валидировать FIT",    command=self._cmd_validate_fit).pack(fill="x", pady=2)
        ttk.Button(section_adv, text="🔍  Диагностика",         command=self._cmd_doctor).pack(fill="x", pady=2)
        ttk.Button(section_adv, text="📦  Архивировать",        command=self._cmd_archive).pack(fill="x", pady=2)
        ttk.Button(section_adv, text="📋  Список архивов",      command=self._cmd_list_archives).pack(fill="x", pady=2)
        ttk.Button(section_adv, text="🔄  Восстановить архив",  command=self._cmd_restore).pack(fill="x", pady=2)

        # Bind mousewheel on all child widgets so scrolling works anywhere in sidebar
        def _sb_scroll_wheel(e):
            self._sb_canvas.yview_scroll(-1 * (e.delta // 120), "units")

        def _bind_sb_wheel(w):
            w.bind("<MouseWheel>", _sb_scroll_wheel, add="+")
            for child in w.winfo_children():
                _bind_sb_wheel(child)

        self._sb_canvas.bind("<MouseWheel>", _sb_scroll_wheel)
        p.after(100, lambda: _bind_sb_wheel(p))

    # ── Global text-widget bindings (clipboard + scroll) ─────────────────────
    def _setup_text_bindings(self):
        """Apply Ctrl+C/V/X/A and mousewheel to every tk.Text area in the app."""

        def _paste(e):
            w = e.widget
            if str(w.cget("state")) == "disabled":
                return "break"
            try:
                if w.tag_ranges("sel"):
                    w.delete("sel.first", "sel.last")
                w.insert(tk.INSERT, self.clipboard_get())
            except tk.TclError:
                pass
            return "break"

        def _copy(e):
            w = e.widget
            try:
                self.clipboard_clear()
                self.clipboard_append(w.get("sel.first", "sel.last"))
            except tk.TclError:
                pass
            return "break"

        def _cut(e):
            w = e.widget
            if str(w.cget("state")) == "disabled":
                return "break"
            try:
                self.clipboard_clear()
                self.clipboard_append(w.get("sel.first", "sel.last"))
                w.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            return "break"

        def _select_all(e):
            e.widget.tag_add("sel", "1.0", "end-1c")
            return "break"

        def _wheel(e):
            e.widget.yview_scroll(-1 * (e.delta // 120), "units")
            return "break"

        text_widgets = (self._plan_text, self._yaml_out, self._log_w)
        for w in text_widgets:
            for seq in ("<Control-v>", "<Control-V>", "<<Paste>>"):
                w.bind(seq, _paste)
            for seq in ("<Control-c>", "<Control-C>", "<<Copy>>"):
                w.bind(seq, _copy)
            for seq in ("<Control-x>", "<Control-X>", "<<Cut>>"):
                w.bind(seq, _cut)
            for seq in ("<Control-a>", "<Control-A>"):
                w.bind(seq, _select_all)
            w.bind("<MouseWheel>", _wheel)

        # Ctrl+A select-all for single-line Entry widgets (not default on Windows)
        def _entry_select_all(e):
            w = e.widget
            try:
                w.select_range(0, "end")
                w.icursor("end")
            except (AttributeError, tk.TclError):
                pass
            # don't return "break" — let focus and other events continue

        self.bind_all("<Control-a>", _entry_select_all, add="+")
        self.bind_all("<Control-A>", _entry_select_all, add="+")

    # ── Right panel (Notebook) ────────────────────────────────────────────────
    def _build_right(self, parent):
        self._nb = ttk.Notebook(parent)
        self._nb.pack(fill="both", expand=True)

        cal_tab     = ttk.Frame(self._nb, padding=(6, 6))
        llm_tab     = ttk.Frame(self._nb, padding=(6, 6))
        builder_tab = ttk.Frame(self._nb, padding=(6, 6))
        garmin_tab  = ttk.Frame(self._nb, padding=(6, 6))
        self._nb.add(cal_tab,     text="📅  Календарь")
        self._nb.add(llm_tab,     text="🤖  LLM Генератор")
        self._nb.add(builder_tab, text="🧱  Конструктор")
        self._nb.add(garmin_tab,  text="🏃  Garmin Connect")

        self._build_calendar_tab(cal_tab)
        self._build_llm_tab(llm_tab)
        self._build_builder_tab(builder_tab)
        self._build_garmin_tab(garmin_tab)

    def _build_page_header(self, parent, title: str, subtitle: str) -> None:
        """Render one consistent header for each workspace page."""
        card = tk.Frame(parent, bg=BG3, padx=12, pady=9)
        card.pack(fill="x", pady=(0, 8))
        tk.Frame(card, bg=ACCENT, width=4).pack(side="left", fill="y", padx=(0, 10))
        text_box = tk.Frame(card, bg=BG3)
        text_box.pack(side="left", fill="x", expand=True)
        tk.Label(text_box, text=title, bg=BG3, fg=FG,
                 font=("Segoe UI", 12, "bold"), anchor="w").pack(anchor="w")
        tk.Label(text_box, text=subtitle, bg=BG3, fg=MUTED,
                 font=("Segoe UI", 9), anchor="w").pack(anchor="w", pady=(2, 0))

    # ── Calendar tab ──────────────────────────────────────────────────────────
    def _build_calendar_tab(self, parent):
        self._build_page_header(
            parent, "Календарь тренировок", "Просмотр плана, дат и недельного объёма")
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

        ttk.Label(parent, text="ОБЪЁМ ПО НЕДЕЛЯМ (км)", style="Section.TLabel").pack(
            anchor="w", pady=(6, 2))
        self._chart_canvas = tk.Canvas(parent, bg=BG2, height=64, highlightthickness=0)
        self._chart_canvas.pack(fill="x")
        self._chart_canvas.bind("<Configure>", self._on_chart_canvas_resize)

        self._detail_var = tk.StringVar(value="Нажмите на тренировку для подробностей")
        tk.Label(parent, textvariable=self._detail_var,
                 bg=BG3, fg=FG, font=("Segoe UI", 9),
                 anchor="w", padx=8, pady=4).pack(fill="x", pady=(4, 0))

        self._draw_calendar()

    # ── Log panel (side pane, visible regardless of active tab) ────────────────
    def _build_log_panel(self, parent):
        log_hdr = ttk.Frame(parent)
        log_hdr.pack(fill="x")
        ttk.Label(log_hdr, text="ВЫВОД КОМАНДЫ", style="Section.TLabel").pack(side="left")
        ttk.Button(log_hdr, text="Очистить", command=self._clear_log, width=8).pack(side="right")
        self._log_w = scrolledtext.ScrolledText(
            parent, height=10, bg=BG2, fg=GREEN,
            font=("Consolas", 9), state="disabled",
            insertbackground=FG, relief="flat")
        self._log_w.pack(fill="both", expand=True, pady=(4, 0))
        self._log_w.tag_config("hint", foreground=YELLOW)

    # ── LLM tab ───────────────────────────────────────────────────────────────
    def _build_llm_tab(self, parent):
        self._build_page_header(
            parent, "Генератор тренировок", "Текст плана → YAML → FIT или Garmin Connect")
        # ── Mode toggle ───────────────────────────────────────────────────────
        mode_bar = ttk.Frame(parent)
        mode_bar.pack(fill="x", pady=(0, 4))
        ttk.Radiobutton(mode_bar, text="Своя LLM", variable=self.llm_conn_mode,
                       value="own", command=self._on_llm_mode_change).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(mode_bar, text="LLM автора", variable=self.llm_conn_mode,
                       value="api", command=self._on_llm_mode_change).pack(side="left")

        # ── "Своя LLM" connection bar ─────────────────────────────────────────
        self._conn_own = ttk.Frame(parent)

        ttk.Label(self._conn_own, text="URL:", style="Muted.TLabel").pack(side="left")
        ttk.Entry(self._conn_own, textvariable=self.llm_url, width=30).pack(side="left", padx=(4, 10))
        ttk.Label(self._conn_own, text="Модель:", style="Muted.TLabel").pack(side="left")
        ttk.Entry(self._conn_own, textvariable=self.llm_model, width=22).pack(side="left", padx=(4, 10))
        ttk.Label(self._conn_own, text="Тип:", style="Muted.TLabel").pack(side="left")
        cb = ttk.Combobox(self._conn_own, textvariable=self.llm_type, width=8,
                          values=["openai", "ollama"], state="readonly")
        cb.pack(side="left", padx=(4, 10))
        ttk.Label(self._conn_own, text="Таймаут (с):", style="Muted.TLabel").pack(side="left")
        ttk.Entry(self._conn_own, textvariable=self.llm_timeout, width=6).pack(side="left", padx=(4, 10))

        # ── "LLM автора" connection bar ───────────────────────────────────────
        self._conn_api = ttk.Frame(parent)

        ttk.Label(self._conn_api, text="API URL:", style="Muted.TLabel").pack(side="left")
        ttk.Entry(self._conn_api, textvariable=self.api_url, width=30).pack(side="left", padx=(4, 10))
        ttk.Label(self._conn_api, text="Токен:", style="Muted.TLabel").pack(side="left")
        ttk.Entry(self._conn_api, textvariable=self.api_token, width=22, show="*").pack(
            side="left", padx=(4, 10))

        # ── Shared "check connection" row (created before _on_llm_mode_change
        #    so conn frames can always be re-inserted right before it via
        #    before=self._llm_check_row, regardless of pack_forget/pack order) ──
        self._llm_check_row = ttk.Frame(parent)
        self._llm_check_row.pack(fill="x", pady=(0, 8))
        self._conn_check_btn = ttk.Button(self._llm_check_row, text="Проверить связь", command=self._llm_check)
        self._conn_check_btn.pack(side="left", padx=4)
        self._llm_status = tk.Label(self._llm_check_row, text="●", bg=BG, fg=MUTED, font=("Segoe UI", 14))
        self._llm_status.pack(side="left", padx=4)
        self._llm_conn_toggle_btn = ttk.Button(self._llm_check_row, text="Настроить подключение",
                                               command=self._toggle_llm_conn_expanded)
        self._llm_conn_toggle_btn.pack(side="left", padx=4)

        self._on_llm_mode_change()  # pack whichever connection sub-frame is active

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
        ttk.Button(actions, text="📅  Загрузить этот YAML",
                   command=self._yaml_to_garmin).pack(side="right", padx=2)
        ttk.Button(actions, text="⚙  Собрать этот YAML в FIT", style="Success.TButton",
                   command=self._yaml_to_build).pack(side="right", padx=2)

    def _on_llm_mode_change(self):
        self._conn_own.pack_forget()
        self._conn_api.pack_forget()
        show_conn = self.ui_mode.get() == "expert" or self._llm_conn_expanded
        if show_conn:
            target = self._conn_api if self.llm_conn_mode.get() == "api" else self._conn_own
            target.pack(fill="x", pady=(0, 4), before=self._llm_check_row)
        if hasattr(self, "_llm_conn_toggle_btn"):
            self._llm_conn_toggle_btn.config(
                text="Скрыть настройки подключения" if show_conn else "Настроить подключение")
        if hasattr(self, "_llm_status"):
            self._llm_status.config(text="●", fg=MUTED)

    def _toggle_llm_conn_expanded(self):
        self._llm_conn_expanded = not self._llm_conn_expanded
        self._on_llm_mode_change()

    def _toggle_period_settings(self):
        self._period_expanded = not self._period_expanded
        self._on_ui_mode_change()

    def _on_ui_mode_change(self):
        simple = self.ui_mode.get() == "simple"

        if hasattr(self, "_advanced_actions_frame"):
            if simple:
                self._advanced_actions_frame.pack_forget()
                self._advanced_hline.pack_forget()
            else:
                self._advanced_hline.pack(fill="x", pady=6)
                self._advanced_actions_frame.pack(fill="x")

        if simple:
            self._llm_conn_expanded = False
        if hasattr(self, "_conn_own"):
            self._on_llm_mode_change()
        if hasattr(self, "_llm_conn_toggle_btn"):
            if simple:
                self._llm_conn_toggle_btn.pack(side="left", padx=4)
            else:
                self._llm_conn_toggle_btn.pack_forget()

        if hasattr(self, "_gc_limit_frame"):
            if simple:
                self._gc_limit_frame.pack_forget()
            else:
                self._gc_limit_frame.pack(side="left", before=self._gc_del_btn)

        if hasattr(self, "_period_frame"):
            if simple:
                self._period_toggle_btn.pack(fill="x", pady=(10, 2))
                self._period_toggle_btn.config(
                    text=("▾  Параметры периода" if self._period_expanded
                          else "▸  Параметры периода"))
                if self._period_expanded:
                    # Разделитель скрыт в simple mode, поэтому он не может быть
                    # якорем для pack на всех версиях Tk.
                    self._period_frame.pack(fill="x")
                else:
                    self._period_frame.pack_forget()
            else:
                self._period_toggle_btn.pack_forget()
                self._period_frame.pack(fill="x", before=self._advanced_hline)

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
        if self._store is None:
            return

        filename = wo.get("filename") or wo.get("name") or ""
        workout_id = self._store.find_workout_id_by_filename(filename)
        if workout_id is None:
            self._log(f"[ERR] Не удалось найти тренировку «{filename}»")
            return

        new_date = datetime.date.fromisoformat(target_date_str)
        new_filename = self._compute_renamed_filename(filename, new_date)

        if is_copy:
            new_id = self._store.duplicate_workout(workout_id)
            new_filename = self._dedupe_filename(new_filename, exclude_workout_id=new_id)
            self._store.rename_workout_filename(new_id, new_filename)
            self._log(f"[OK] «{filename}» скопирована на {target_date_str} → «{new_filename}»")
        else:
            self._store.rename_workout_filename(workout_id, new_filename)
            self._log(f"[OK] «{filename}» перенесена на {target_date_str} → «{new_filename}»")

        from garmin_fit.plan_domain import plan_to_data
        data = plan_to_data(self._store.get_plan())
        self.workouts = self._parse_workouts(data)
        self._draw_calendar()

    def _dedupe_filename(self, filename: str, exclude_workout_id: int) -> str:
        """Append _copy / _copy2 / ... if filename collides with another
        workout already in the plan (e.g. copying onto the same day the
        source workout is already on recomputes an identical name)."""
        candidate = filename
        suffix = 1
        while True:
            existing_id = self._store.find_workout_id_by_filename(candidate)
            if existing_id is None or existing_id == exclude_workout_id:
                return candidate
            suffix += 1
            candidate = f"{filename}_copy{'' if suffix == 2 else suffix}"

    def _compute_renamed_filename(self, old_filename: str, new_date: datetime.date) -> str:
        """Rewrite the W{week}_{MM-DD}_{Day}_... prefix for a new date,
        reusing plan_processing.normalize_workout_identifier to recompute
        the ISO calendar week (it does not re-derive the weekday token, so
        that's computed here from new_date directly)."""
        from garmin_fit.plan_processing import normalize_workout_identifier

        weekday = WEEKDAY_ABBR_EN[new_date.weekday()]
        date_token = f"{new_date.month:02d}-{new_date.day:02d}"
        candidate, n = re.subn(
            r"_\d{2}-\d{2}_[A-Za-z]+_", f"_{date_token}_{weekday}_", old_filename, count=1)
        if n == 0:
            candidate = f"W00_{date_token}_{weekday}_{old_filename}"
        return normalize_workout_identifier(
            candidate, workout_index=0, inferred_year=new_date.year)

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
    def _on_yaml_path_change(self) -> None:
        self._yaml_ready = False
        self._update_yaml_context()

    def _update_yaml_context(self) -> None:
        """Keep the top status and plan-dependent actions in sync."""
        path_text = self.yaml_path.get().strip()
        path = Path(path_text) if path_text else None
        if path is None:
            self._set_yaml_status("План не выбран · выберите YAML", ready=False)
        elif not path.is_file():
            self._set_yaml_status("Файл не найден · проверьте путь", ready=False)
        elif not self._yaml_ready:
            self._set_yaml_status("Файл выбран · нажмите ↺ для загрузки", ready=False)
        else:
            self._update_yaml_action_availability()

    def _set_yaml_status(self, text: str, *, ready: bool) -> None:
        self._yaml_ready = ready
        self._yaml_status_var.set(text)
        self._update_yaml_action_availability()

    def _update_yaml_action_availability(self) -> None:
        if not hasattr(self, "_quick_action_buttons"):
            return
        has_file = bool(self.yaml_path.get().strip()) and Path(self.yaml_path.get()).is_file()
        states = {
            "validate": "normal" if has_file else "disabled",
            "build": "normal" if self._yaml_ready else "disabled",
            "upload": "normal" if self._yaml_ready else "disabled",
        }
        for name, state in states.items():
            self._quick_action_buttons[name].configure(state=state)

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
            self._set_yaml_status("План не выбран · выберите YAML", ready=False)
            return
        try:
            from garmin_fit.plan_domain import plan_to_data
            from garmin_fit.plan_store import PlanStore

            if self._store is not None:
                self._store.close()

            workdb_path = Path(str(path) + ".workdb")
            self._store = PlanStore.open(workdb_path)
            repairs = self._store.load_from_yaml(Path(path))

            data = plan_to_data(self._store.get_plan())
            self.workouts = self._parse_workouts(data)
            if self.workouts:
                dated = [w for w in self.workouts if w.get("date")]
                if dated:
                    self.cal_month = datetime.date.fromisoformat(dated[0]["date"]).replace(day=1)
            self._draw_calendar()
            self._set_yaml_status(
                f"План загружен · {len(self.workouts)} тренировок", ready=bool(self.workouts)
            )
            self._log(f"[OK] Загружено {len(self.workouts)} тренировок из {Path(path).name}")
            if repairs:
                self._log("[Авто-правки]")
                for r in repairs:
                    self._log(f"  {r}")
        except Exception as exc:
            self._set_yaml_status("Ошибка чтения YAML · проверьте файл", ready=False)
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
        stripped = text.strip()
        if stripped.startswith(("[ERR]", "[FAIL]")):
            self._shell_status_var.set("Ошибка")
        elif stripped.startswith("[OK]"):
            self._shell_status_var.set("Готово")
        elif stripped.startswith(("[WARN]", "⏳")):
            self._shell_status_var.set("Выполняется")
        self._log_w.config(state="normal")
        self._log_w.insert("end", text + "\n")
        self._log_w.see("end")
        self._log_w.config(state="disabled")
        self._maybe_toast(text)
        self._maybe_hint(text)

    # ── Operation state ─────────────────────────────────────────────────────
    def _iter_buttons(self):
        """Yield buttons in the main window for operation-level locking."""
        pending = [self]
        while pending:
            parent = pending.pop()
            children = parent.winfo_children()
            pending.extend(children)
            for widget in children:
                if isinstance(widget, (ttk.Button, tk.Button)):
                    yield widget

    def _begin_operation(self, label: str) -> bool:
        if self._operation_active:
            self._log(f"[WARN] Уже выполняется: {self._operation_label}")
            return False
        self._operation_active = True
        self._operation_label = label
        self._operation_button_states = {}
        for button in self._iter_buttons():
            try:
                current = str(button.cget("state"))
                if current != "disabled":
                    self._operation_button_states[button] = current
                    button.configure(state="disabled")
            except tk.TclError:
                continue
        self._shell_status_var.set(label)
        return True

    def _end_operation(self, success: bool | None = None) -> None:
        for button, state in self._operation_button_states.items():
            try:
                button.configure(state=state)
            except tk.TclError:
                pass
        self._operation_button_states = {}
        self._operation_active = False
        self._operation_label = ""
        if success is True:
            self._shell_status_var.set("Готово")
        elif success is False:
            self._shell_status_var.set("Ошибка")
        else:
            self._shell_status_var.set("Готово")

    # ── Toast notifications ────────────────────────────────────────────────
    # Piggybacks on the existing "[OK]"/"[ERR]"/"[WARN]"/"[FAIL]" prefix
    # convention already used by every _log() call site across the app, so
    # every existing status message gets a toast for free -- visible no
    # matter which tab is currently open, unlike the log box (Calendar tab only).
    def _maybe_toast(self, text: str) -> None:
        stripped = text.strip()
        for prefix, color in (("[OK]", GREEN), ("[ERR]", RED),
                              ("[FAIL]", RED), ("[WARN]", YELLOW)):
            if stripped.startswith(prefix):
                message = stripped[len(prefix):].strip()
                if message:
                    self._show_toast(message, color)
                return

    # ── Friendly error hints ──────────────────────────────────────────────
    # A second, independent pass over the same streamed lines as _maybe_toast
    # -- doesn't replace the [OK]/[ERR]/[FAIL]/[WARN] toasts, just adds a
    # plain-language explanation + suggested next step for recognized
    # failures, for users who don't want to parse raw CLI/Python output.
    def _maybe_hint(self, text: str) -> None:
        stripped = text.strip()
        for pattern, hint in _ERROR_HINTS:
            if pattern.search(stripped):
                self._log_w.config(state="normal")
                self._log_w.insert("end", f"   💡 {hint}\n", ("hint",))
                self._log_w.see("end")
                self._log_w.config(state="disabled")
                self._show_toast(hint, YELLOW, duration_ms=6000)
                return

    def _show_toast(self, message: str, color: str = GREEN, duration_ms: int = 3000) -> None:
        toast = tk.Toplevel(self)
        toast.overrideredirect(True)
        try:
            toast.attributes("-topmost", True)
        except tk.TclError:
            pass
        label = tk.Label(toast, text=message, bg=color, fg=BG,
                         font=("Segoe UI", 9, "bold"), padx=14, pady=8,
                         wraplength=380, justify="left")
        label.pack()

        self.update_idletasks()
        x = self.winfo_rootx() + self.winfo_width() - label.winfo_reqwidth() - 24
        y = self.winfo_rooty() + 44 + len(self._active_toasts) * 48
        toast.geometry(f"+{max(x, self.winfo_rootx() + 10)}+{y}")

        self._active_toasts.append(toast)

        def _dismiss(_e=None):
            if toast in self._active_toasts:
                self._active_toasts.remove(toast)
            try:
                toast.destroy()
            except tk.TclError:
                pass

        label.bind("<Button-1>", _dismiss)
        toast.after(duration_ms, _dismiss)

    def _clear_log(self):
        self._log_w.config(state="normal")
        self._log_w.delete("1.0", "end")
        self._log_w.config(state="disabled")

    # ── CLI runner ────────────────────────────────────────────────────────────
    def _cli_command(self, args):
        if getattr(sys, "frozen", False):
            # Packaged exe: sys.executable is FitWeaver.exe itself, not a
            # Python interpreter -- shell out to the sibling CLI exe instead.
            return [str(PROJECT_ROOT / "garmin-fit-cli.exe")] + args
        return [PYTHON, "-m", "garmin_fit.cli"] + args

    def _run(self, args):
        if not self._begin_operation("Выполняется команда"):
            return
        cmd = self._cli_command(args)
        self._log(f"\n$ garmin_fit.cli {' '.join(args)}")

        def worker():
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    cwd=PROJECT_ROOT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                for line in proc.stdout:
                    self.after(0, self._log, line.rstrip())
                proc.wait()
                ok = proc.returncode == 0
                msg = "[OK] Готово" if ok else f"[FAIL] код {proc.returncode}"
                self.after(0, self._log, msg)
                self.after(0, self._handle_cli_result, args, ok)
                self.after(0, self._end_operation, ok)
            except Exception as exc:
                self.after(0, self._log, f"[ERR] {exc}")
                self.after(0, self._handle_cli_result, args, False)
                self.after(0, self._end_operation, False)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_cli_result(self, args, ok: bool) -> None:
        if args and args[0] == "validate-yaml":
            if ok:
                self._set_yaml_status("YAML валиден · готово к сборке", ready=True)
            else:
                self._set_yaml_status(
                    "YAML не прошёл проверку · см. вывод команды", ready=False
                )

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
        if self.yaml_path.get().strip():
            self._set_yaml_status("Проверка YAML…", ready=False)
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
    def _make_llm_client(self, *, for_generation: bool = False):
        """Return either a direct UnifiedLLMClient ("own" mode) or a
        PlanApiClient talking to a hosted FitWeaver Plan API ("api" mode)."""
        if self.llm_conn_mode.get() == "api":
            from garmin_fit.api_client import PlanApiClient
            timeout = max(60, self.llm_timeout.get()) if for_generation else 300
            return PlanApiClient(self.api_url.get(), self.api_token.get(), timeout_sec=timeout)

        from garmin_fit.llm.client import UnifiedLLMClient
        kwargs = {"model": self.llm_model.get(), "base_url": self.llm_url.get(),
                  "api_type": self.llm_type.get()}
        if for_generation:
            kwargs["request_timeout_sec"] = max(60, self.llm_timeout.get())
        return UnifiedLLMClient(**kwargs)

    def _llm_check(self):
        if not self._begin_operation("Проверка подключения"):
            return
        self._llm_status.config(text="●", fg=YELLOW)
        self.update_idletasks()

        def check():
            try:
                client = self._make_llm_client()
                ok = client.check_connection()
                color = GREEN if ok else RED
                self.after(0, self._llm_status.config, {"text": "●", "fg": color})
                self.after(0, self._end_operation, ok)
            except Exception as exc:
                self.after(0, self._llm_status.config, {"text": "●", "fg": RED})
                self.after(0, self._set_progress, f"Ошибка: {exc}")
                self.after(0, self._end_operation, False)

        threading.Thread(target=check, daemon=True).start()

    def _set_progress(self, text, color=YELLOW):
        self._llm_progress.config(text=text, fg=color)

    def _llm_generate(self):
        plan_text = self._plan_text.get("1.0", "end").strip()
        if not plan_text:
            messagebox.showwarning("Пустой план", "Введите текст плана тренировок.")
            return

        if not self._begin_operation("Генерация YAML"):
            return

        self._gen_btn.config(state="disabled")
        self._set_progress("⏳ Генерирую YAML…")
        self._yaml_out.config(state="normal")
        self._yaml_out.delete("1.0", "end")
        self._yaml_out.config(state="disabled")

        def worker():
            from garmin_fit.api_client import PlanApiError
            try:
                client = self._make_llm_client(for_generation=True)
                if self.llm_conn_mode.get() == "api":
                    result = client.build_plan_draft(plan_text, max_retries=1)
                else:
                    from garmin_fit.plan_service import build_plan_draft
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
                    self._end_operation(True)

                    if repairs:
                        self._log("\n[Авто-правки]")
                        for r in repairs:
                            self._log(f"  {r}")
                    if warnings:
                        self._log("\n[Предупреждения]")
                        for w in warnings:
                            self._log(f"  {w}")

                self.after(0, finish)

            except PlanApiError as exc:
                messages = {
                    401: "Неверный токен доступа к API",
                    429: "Превышен лимит запросов, попробуйте позже",
                }
                msg = messages.get(exc.status_code, f"Ошибка API: {exc}")

                def on_api_err():
                    self._set_progress(f"❌ {msg}", RED)
                    self._gen_btn.config(state="normal")
                    self._end_operation(False)
                self.after(0, on_api_err)

            except Exception as exc:
                def on_err():
                    self._set_progress(f"❌ Ошибка: {exc}", RED)
                    self._gen_btn.config(state="normal")
                    self._end_operation(False)
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
        self._builder_add_btn = ttk.Button(bottom, text="➕  Добавить в план",
                                            style="Primary.TButton", state="disabled",
                                            command=self._builder_commit)
        self._builder_add_btn.pack(side="right")

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
        _label, factory = TEMPLATES[key]
        self._builder_steps = factory()
        self._builder_range_start = self._builder_range_end = self._builder_selected_index = None
        self._builder_render_list()
        self._builder_render_editor()

    def _builder_clear(self):
        self._builder_steps = []
        self._builder_filename_var.set("")
        self._builder_range_start = self._builder_range_end = self._builder_selected_index = None
        self._builder_render_list()
        self._builder_render_editor()

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
        step = self._builder_steps[idx]
        if step.step_type != "repeat" and self._builder_has_repeat():
            messagebox.showinfo(
                "Нельзя удалить",
                "В тренировке уже есть блок повтора. Сначала удалите его, "
                "чтобы менять остальные шаги.")
            return
        del self._builder_steps[idx]
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
        from garmin_fit.workout_builder import compute_repeat_step
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
            repeat_step = compute_repeat_step(self._builder_steps, lo, hi, count)
        except ValueError as exc:
            messagebox.showwarning("Нельзя повторить", str(exc))
            return
        self._builder_steps.insert(hi + 1, repeat_step)
        self._builder_range_start = self._builder_range_end = self._builder_selected_index = None
        self._builder_render_list()
        self._builder_render_editor()

    def _builder_update_repeat_button_state(self):
        start, end = self._builder_range_start, self._builder_range_end
        valid = False
        if start is not None and end is not None and self._builder_steps:
            lo, hi = min(start, end), max(start, end)
            valid = all(self._builder_steps[i].step_type != "repeat" for i in range(lo, hi + 1))
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
            return
        filename = self._builder_filename_var.get().strip()
        if not self._builder_steps:
            self._builder_validation_lbl.config(text="Добавьте хотя бы один блок", fg=MUTED)
            self._builder_add_btn.config(state="disabled")
            return
        if not filename:
            self._builder_validation_lbl.config(text="Укажите имя тренировки", fg=YELLOW)
            self._builder_add_btn.config(state="disabled")
            return
        errors, warnings = validate_draft(filename, filename, self._builder_steps)
        if errors:
            self._builder_validation_lbl.config(text=f"Ошибка: {errors[0]}", fg=RED)
            self._builder_add_btn.config(state="disabled")
        elif warnings:
            self._builder_validation_lbl.config(
                text=f"Готово, {len(warnings)} предупреждений", fg=YELLOW)
            self._builder_add_btn.config(state="normal")
        else:
            self._builder_validation_lbl.config(text="Готово к добавлению ✓", fg=GREEN)
            self._builder_add_btn.config(state="normal")

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

    # ── Garmin Connect tab ────────────────────────────────────────────────────
    def _build_garmin_tab(self, parent):
        self._build_page_header(
            parent, "Garmin Connect", "Просмотр и управление тренировками в аккаунте Garmin")
        # Top bar
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(0, 6))
        self._gc_check_btn = ttk.Button(
            bar, text="✓  Проверить подключение", command=self._gc_check_connection)
        self._gc_check_btn.pack(side="left", padx=(0, 8))
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
        self._gc_history: list[dict] = []
        self._gc_checks:   dict[str, tk.BooleanVar] = {}
        self._gc_month_ids: dict[str, list[str]] = {}

        history_box = ttk.LabelFrame(parent, text="Последние операции", padding=4)
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
                           {"text": f"❌ {self._gc_friendly_error(exc)}", "fg": RED})
                self.after(0, self._record_gc_operation,
                           "Проверка подключения", False, self._gc_friendly_error(exc))
                self.after(0, self._end_operation, False)

        threading.Thread(target=worker, daemon=True).start()

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
                           "Не удалось удалить", self._gc_friendly_error(exc))
                self.after(0, self._gc_status.config,
                           {"text": "❌ Ошибка удаления", "fg": RED})
                self.after(0, self._record_gc_operation,
                           "Удаление тренировки", False, self._gc_friendly_error(exc))
                self.after(0, self._end_operation, False)

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
