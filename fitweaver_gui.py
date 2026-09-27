#!/usr/bin/env python3
"""FitWeaver Desktop GUI — local calendar, CLI wrapper and LLM generator."""

import calendar
import datetime
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import urllib.request
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

import yaml

from garmin_fit.fileio import atomic_write_text
from garmin_fit.gui_builder_tab import BuilderTabMixin
from garmin_fit.gui_garmin_tab import GarminTabMixin
from garmin_fit.gui_messages import (
    hint_for_line,
    ru_count,
    ru_workouts,
)
from garmin_fit.gui_palette import (
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
    WEEKDAY_ABBR_EN,
    WORKOUT_COLORS,
    YELLOW,
)
from garmin_fit.gui_theme import configure_customtkinter, configure_ttk, load_customtkinter

if getattr(sys, "frozen", False):
    # PyInstaller-frozen exe: treat the exe's own folder as a portable app
    # directory, so Plan/profiles/.gui_session.json persist next to it
    # across launches instead of vanishing with the temp extraction folder.
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent
SESSION_FILE = PROJECT_ROOT / ".gui_session.json"
APP_VERSION = "10.5.0"
LATEST_RELEASE_URL = "https://api.github.com/repos/AIminov/FitWeaver/releases/latest"

sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Optional modern root toolkit. All existing native widgets remain supported;
# the fallback keeps the source checkout usable without the GUI extra.
_CTK = load_customtkinter()
if _CTK is not None:
    configure_customtkinter(_CTK)
_AppBase = _CTK.CTk if _CTK is not None else tk.Tk

# ══════════════════════════════════════════════════════════════════════════════
class App(BuilderTabMixin, GarminTabMixin, _AppBase):
    def __init__(self):
        super().__init__()
        self._project_root = PROJECT_ROOT
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
        self._upload_duplicate_var = tk.StringVar(value="Пропустить совпадения")
        self.year_var  = tk.StringVar(value=str(datetime.date.today().year))
        self._shell_status_var = tk.StringVar(value="Готово")
        self._yaml_status_var = tk.StringVar(value="План не выбран")
        self._yaml_loaded = False
        self._yaml_ready = False
        self._yaml_validation_running = False
        self._operation_active = False
        self._operation_label = ""
        self._operation_button_states: dict[object, str] = {}
        self._quick_action_buttons: dict[str, ttk.Button] = {}

        # LLM settings ("own" mode — direct connection to a local LLM)
        self.llm_url     = tk.StringVar(value="http://127.0.0.1:1234")
        self.llm_model   = tk.StringVar(value="qwen3.8-27b@iq3_xxs")
        self.llm_type    = tk.StringVar(value="openai")
        self.llm_output_format = tk.StringVar(value="yaml")
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
        self._profile_settings_expanded = False
        self._period_expanded = False  # simple mode: Garmin date options collapsed
        self._log_expanded = False  # simple mode: raw command output collapsed by default

        self.workouts: list[dict] = []
        self.cal_month = datetime.date.today().replace(day=1)
        self._gc_calendar_month = datetime.date.today().replace(day=1)
        self._gc_scheduled_workouts: list[dict[str, str]] = []
        self._store = None  # PlanStore | None — internal staging layer, YAML stays canonical
        self._active_profile_email: str | None = None
        self._profile_status_var = tk.StringVar(value="Профиль не выбран")
        self._selected_workout: dict | None = None
        self._builder_edit_workout_id: int | None = None
        self._builder_garmin_edit_event: dict[str, str] | None = None
        self._gc_selected_event: dict[str, str] | None = None

        # Visual builder draft stays in memory until saved to a plan or file.
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
        self._gui_log_path = None
        try:
            from garmin_fit.logging_utils import setup_file_logging

            self._gui_log_path = setup_file_logging(
                prefix="gui", run_id=datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        except OSError:
            pass
        self._build_ui()
        self.yaml_path.trace_add("write", lambda *_: self._on_yaml_path_change())
        self._update_yaml_context()
        self._setup_text_bindings()
        self._load_session()
        self.after(1500, self._check_for_updates)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Session persistence ───────────────────────────────────────────────────
    @staticmethod
    def _version_tuple(value: str) -> tuple[int, ...]:
        parts = re.findall(r"\d+", value or "")
        return tuple(int(part) for part in parts[:3]) or (0,)

    def _check_for_updates(self, manual: bool = False) -> None:
        """Check GitHub release metadata without downloading or installing anything."""
        if manual:
            self._shell_status_var.set("Проверяю обновления…")

        def worker():
            try:
                request = urllib.request.Request(
                    LATEST_RELEASE_URL,
                    headers={"User-Agent": f"FitWeaver/{APP_VERSION}", "Accept": "application/vnd.github+json"},
                )
                with urllib.request.urlopen(request, timeout=4) as response:
                    data = json.loads(response.read().decode("utf-8"))
                tag = str(data.get("tag_name") or "").lstrip("v")
                url = str(data.get("html_url") or "https://github.com/AIminov/FitWeaver/releases")
                newer = self._version_tuple(tag) > self._version_tuple(APP_VERSION)
                self.after(0, self._finish_update_check, newer, tag, url, manual)
            except Exception:
                self.after(0, self._finish_update_check, False, "", "", manual)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_update_check(self, newer: bool, tag: str, url: str, manual: bool) -> None:
        self._shell_status_var.set("Готово")
        if not tag:
            if manual:
                messagebox.showwarning(
                    "Не удалось проверить обновления",
                    "Проверьте подключение к интернету и попробуйте ещё раз.",
                    parent=self,
                )
            return
        if newer:
            self._show_toast(
                f"Доступна новая версия FitWeaver v{tag}. Скачивание не выполняется автоматически.",
                YELLOW, duration_ms=7000,
            )
            if manual:
                messagebox.showinfo(
                    "Доступно обновление",
                    f"Доступна версия FitWeaver v{tag}.\n\nОткройте релизы проекта:\n{url}",
                    parent=self,
                )
        elif manual:
            self._show_toast("Установлена последняя доступная версия FitWeaver.", GREEN)

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
        if data.get("llm_output_format") in ("yaml", "compact"):
            self.llm_output_format.set(data["llm_output_format"])
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
        if data.get("upload_duplicate_action") in (
            "Пропустить совпадения", "Заменить назначение", "Создать копию"
        ):
            self._upload_duplicate_var.set(data["upload_duplicate_action"])
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
        """Ask for max HR to calculate the personal HR zones used by the LLM and builder."""
        dialog = tk.Toplevel(self)
        dialog.title("Новый профиль")
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.resizable(False, False)

        tk.Label(dialog, text=f"Профиль {email} создан впервые",
                 bg=BG, fg=ACCENT, font=("Segoe UI", 10, "bold"),
                 padx=16, anchor="w").pack(fill="x", pady=(16, 4))
        tk.Label(dialog,
                 text="Максимальный пульс используется для расчёта зон Z1–Z5.\n"
                      "Эти зоны доступны в LLM и в Конструкторе тренировок.\n"
                      "Можно пропустить и задать свои диапазоны позже в user_profile.yaml.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9), justify="left",
                 padx=16, anchor="w").pack(fill="x", pady=(0, 8))

        form = ttk.Frame(dialog, padding=(16, 0))
        form.pack(fill="x")
        max_hr_var = tk.StringVar()
        ttk.Label(form, text="Максимальный пульс (уд/мин):", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=max_hr_var, width=10).grid(row=0, column=1, padx=(8, 0))

        def _save():
            from garmin_fit.profile_store import activate_user_profile, write_user_profile
            try:
                max_hr = int(max_hr_var.get())
            except ValueError:
                messagebox.showwarning(
                    "Некорректные данные",
                    "Введите максимальный пульс числом, либо нажмите «Пропустить».",
                    parent=dialog)
                return
            if not 100 <= max_hr <= 240:
                messagebox.showwarning(
                    "Некорректные данные",
                    "Максимальный пульс должен быть в диапазоне 100–240 уд/мин.", parent=dialog)
                return
            write_user_profile(email, max_hr=max_hr)
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
        if hasattr(self, "_top_profile_var"):
            self._top_profile_var.set(f"Профиль Garmin: {email or 'не выбран'}")
        if hasattr(self, "_builder_send_garmin_btn"):
            self._builder_update_action_availability(
                str(self._builder_save_yaml_btn.cget("state")) == "normal")
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
        dialog = tk.Toplevel(self)
        dialog.title("Новый профиль Garmin")
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.resizable(False, False)

        tk.Label(dialog, text="Подключение профиля Garmin", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 10, "bold"), padx=16, anchor="w").pack(
                     fill="x", pady=(16, 6))
        tk.Label(
            dialog,
            text="Введите email Garmin и пароль для следующего подключения. Пароль\n"
                 "останется в памяти приложения до переключения профиля или закрытия.\n"
                 "Если Garmin Connect уже авторизован, пароль можно пропустить.",
            bg=BG, fg=MUTED, font=("Segoe UI", 9), justify="left", padx=16,
            anchor="w",
        ).pack(fill="x", pady=(0, 8))

        form = ttk.Frame(dialog, padding=(16, 0))
        form.pack(fill="x")
        email_var = tk.StringVar()
        password_var = tk.StringVar()
        ttk.Label(form, text="Email Garmin:", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", pady=4)
        email_entry = ttk.Entry(form, textvariable=email_var, width=34)
        email_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=4)
        ttk.Label(form, text="Пароль Garmin:", style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", pady=4)
        password_entry = ttk.Entry(form, textvariable=password_var, show="•", width=34)
        password_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=4)
        form.columnconfigure(1, weight=1)

        result: dict[str, str] = {}

        def _submit():
            email = email_var.get().strip()
            if not email or "@" not in email:
                messagebox.showwarning(
                    "Некорректный email",
                    "Введите email в формате user@example.com.", parent=dialog)
                return
            result["email"] = email
            result["password"] = password_var.get()
            dialog.destroy()

        actions = ttk.Frame(dialog, padding=16)
        actions.pack(fill="x")
        ttk.Button(actions, text="Отмена", command=dialog.destroy).pack(side="left")
        ttk.Button(actions, text="Создать профиль", style="Primary.TButton",
                   command=_submit).pack(side="right")
        dialog.bind("<Return>", lambda _event: _submit())
        dialog.grab_set()
        email_entry.focus_set()
        self.wait_window(dialog)
        if not result:
            return
        self.email_var.set(result["email"])
        self._on_email_change()
        # `_on_email_change` clears credentials when switching accounts.
        # Apply the new password afterwards; it is never written to disk.
        self.pass_var.set(result["password"])

    def _save_session(self):
        self._save_current_profile_session()
        data = {
            "yaml_path":         self.yaml_path.get(),
            "last_active_email": self.email_var.get(),
            "year":              self.year_var.get(),
            "llm_url":           self.llm_url.get(),
            "llm_model":         self.llm_model.get(),
            "llm_type":          self.llm_type.get(),
            "llm_output_format": self.llm_output_format.get(),
            "llm_timeout":       self.llm_timeout.get(),
            "llm_conn_mode":     self.llm_conn_mode.get(),
            "upload_duplicate_action": self._upload_duplicate_var.get(),
            "api_url":           self.api_url.get(),
            # Plaintext, same as bot_config.yaml/api_config.yaml -- acceptable
            # for a single-user local desktop app, not a new risk class.
            "api_token":         self.api_token.get(),
            "ui_mode":           self.ui_mode.get(),
        }
        atomic_write_text(SESSION_FILE, json.dumps(data, ensure_ascii=False, indent=2))

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
        version_row = ttk.Frame(title_block)
        version_row.pack(anchor="w")
        ttk.Label(version_row, text=f"v{APP_VERSION} · Garmin workout workspace",
                  style="Muted.TLabel").pack(side="left")
        ttk.Button(version_row, text="Проверить обновления",
                   command=lambda: self._check_for_updates(manual=True)).pack(
                       side="left", padx=(8, 0))

        self._top_profile_var = tk.StringVar(value="Профиль Garmin: не выбран")
        ttk.Label(header, textvariable=self._top_profile_var,
                  style="Muted.TLabel").pack(anchor="w")

        ttk.Label(header, textvariable=self._shell_status_var,
                  style="Muted.TLabel").pack(side="right", padx=(14, 4))
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

        body.add(sidebar_outer, weight=0)
        body.add(right, weight=3)

        self._footer = ttk.Frame(self, padding=(10, 4))
        self._footer.pack(fill="x", side="bottom")
        self._result_var = tk.StringVar(value="Здесь появится результат последней операции")
        self._result_action_buttons = {
            "open_fit": ttk.Button(self._footer, text="Открыть FIT",
                                    command=self._open_fit_folder, state="disabled"),
            "go_garmin": ttk.Button(self._footer, text="Garmin Connect",
                                     command=lambda: self._nb.select(3), state="disabled"),
        }
        ttk.Label(self._footer, textvariable=self._result_var,
                  style="Status.TLabel", wraplength=760, justify="left").pack(
                      side="left", fill="x", expand=True)
        for button in self._result_action_buttons.values():
            button.pack(side="left", padx=(0, 4))
        self._log_toggle_btn = ttk.Button(
            self._footer, text="Подробности", command=self._toggle_log)
        self._log_toggle_btn.pack(side="right")
        self._log_panel = ttk.Frame(self, padding=(10, 4))
        self._build_log_panel(self._log_panel)
        self._apply_log_visibility()

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
        ttk.Label(p, text="Пароль Garmin (не сохраняется):",
                  style="Muted.TLabel").pack(anchor="w", pady=(5, 0))
        ttk.Entry(p, textvariable=self.pass_var, show="•").pack(fill="x", pady=(0, 4))

        self._profile_settings_toggle_btn = ttk.Button(
            p, text="▸  Настройки профиля", command=self._toggle_profile_settings)
        self._profile_settings_toggle_btn.pack(fill="x", pady=(4, 0))
        self._profile_settings_frame = ttk.Frame(p)
        ttk.Button(self._profile_settings_frame, text="⚙  Настроить HR-профиль",
                   command=self._edit_hr_profile).pack(fill="x", pady=(4, 2))
        ttk.Button(self._profile_settings_frame, text="⌫  Выйти из Garmin",
                   command=self._clear_garmin_auth).pack(fill="x", pady=(2, 0))

        self._period_toggle_btn = ttk.Button(
            p, text="▸  Параметры периода", command=self._toggle_period_settings)
        self._period_toggle_btn.pack(fill="x", pady=(10, 2))
        self._period_frame = ttk.Frame(p)
        self._period_frame.pack(fill="x")
        ttk.Label(self._period_frame, text="ПЕРИОД", style="Section.TLabel").pack(
            anchor="w", pady=(4, 3))
        ttk.Label(self._period_frame, text="С (YYYY-MM-DD) — фильтр Garmin:",
                  style="Muted.TLabel").pack(anchor="w")
        ttk.Entry(self._period_frame, textvariable=self.from_var).pack(
            fill="x", pady=(0, 4))
        ttk.Label(self._period_frame, text="По (YYYY-MM-DD) — фильтр Garmin:",
                  style="Muted.TLabel").pack(anchor="w")
        ttk.Entry(self._period_frame, textvariable=self.to_var).pack(
            fill="x", pady=(0, 4))
        ttk.Label(self._period_frame, text="Год плана — для расстановки дат:",
                  style="Muted.TLabel").pack(anchor="w")
        ttk.Entry(self._period_frame, textvariable=self.year_var, width=10).pack(anchor="w")
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
                # Let Tk's native Text binding handle the clipboard.  It is
                # Unicode-safe on Windows and also preserves the widget's
                # undo/selection semantics.  The explicit KeyPress binding
                # below is needed for frozen builds where the class binding
                # can differ between Tk versions.
                w.event_generate("<<Paste>>")
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
            for seq in ("<Control-v>", "<Control-V>", "<Control-KeyPress-v>", "<Control-KeyPress-V>"):
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
        self._nb.add(cal_tab,     text="План")
        self._nb.add(llm_tab,     text="LLM")
        self._nb.add(builder_tab, text="Конструктор")
        self._nb.add(garmin_tab,  text="Garmin Connect")
        self._nb.bind("<<NotebookTabChanged>>", self._on_tab_changed, add="+")

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

    # ── Detailed log drawer ───────────────────────────────────────────────────
    def _build_log_panel(self, parent):
        log_hdr = ttk.Frame(parent)
        log_hdr.pack(fill="x")
        ttk.Label(log_hdr, text="ПОДРОБНЫЙ ЖУРНАЛ", style="Section.TLabel").pack(side="left")
        ttk.Button(log_hdr, text="Открыть файл", command=self._open_log_file).pack(
            side="right", padx=(4, 0))
        ttk.Button(log_hdr, text="Очистить", command=self._clear_log, width=8).pack(side="right")
        self._log_body = ttk.Frame(parent)
        self._log_body.pack(fill="both", expand=True)
        self._log_w = scrolledtext.ScrolledText(
            self._log_body, height=10, bg=BG2, fg=GREEN,
            font=("Consolas", 9), state="disabled",
            insertbackground=FG, relief="flat")
        self._log_w.pack(fill="both", expand=True, pady=(4, 0))
        self._log_w.tag_config("hint", foreground=YELLOW)

    def _toggle_log(self) -> None:
        self._log_expanded = not self._log_expanded
        self._apply_log_visibility()

    def _apply_log_visibility(self) -> None:
        if not hasattr(self, "_log_panel"):
            return
        show = self._log_expanded
        if show:
            self._log_panel.pack(fill="x", before=self._footer)
        else:
            self._log_panel.pack_forget()
        if hasattr(self, "_log_toggle_btn"):
            self._log_toggle_btn.configure(
                text="Скрыть журнал" if show else "Подробности")

    # ── LLM tab ───────────────────────────────────────────────────────────────
    def _build_llm_tab(self, parent):
        self._build_page_header(
            parent, "Генератор тренировок", "Текст плана → YAML → FIT или Garmin Connect")
        # ── Mode toggle ───────────────────────────────────────────────────────
        mode_bar = ttk.Frame(parent)
        mode_bar.pack(fill="x", pady=(0, 4))
        ttk.Radiobutton(mode_bar, text="Своя модель (локально)", variable=self.llm_conn_mode,
                       value="own", command=self._on_llm_mode_change).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(mode_bar, text="Общий сервер (URL и токен)", variable=self.llm_conn_mode,
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
        ttk.Label(self._conn_own, text="Вывод:", style="Muted.TLabel").pack(side="left")
        ttk.Combobox(
            self._conn_own, textvariable=self.llm_output_format, width=8,
            values=("yaml", "compact"), state="readonly",
        ).pack(side="left", padx=(4, 0))

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
        self._out_title = tk.Label(out_hdr, text="Сгенерированный YAML", bg=BG, fg=ACCENT,
                                   font=("Segoe UI", 9, "bold"), anchor="w")
        self._out_title.pack(side="left")
        ttk.Button(out_hdr, text="Скопировать", command=self._copy_yaml,
                   width=12).pack(side="right")
        # Generated YAML is kept here; the panel shows it either as YAML or as
        # marked text, which is easier to check and can be edited and re-run
        # without the LLM.
        self._generated_yaml = ""
        self._out_view = "yaml"
        self._to_editor_btn = ttk.Button(out_hdr, text="Править как текст",
                                         command=self._generated_to_editor, state="disabled")
        self._to_editor_btn.pack(side="right", padx=(0, 4))
        self._view_btn = ttk.Button(out_hdr, text="Показать как текст",
                                    command=self._toggle_out_view, state="disabled")
        self._view_btn.pack(side="right", padx=(0, 4))

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
        self._cancel_btn = ttk.Button(actions, text="Отменить", command=self._llm_cancel,
                                      state="disabled")
        self._cancel_btn.pack(side="left", padx=2)

        self._llm_progress = tk.Label(actions, text="", bg=BG, fg=YELLOW,
                                      font=("Segoe UI", 9))
        self._llm_progress.pack(side="left", padx=8)

        ttk.Button(actions, text="💾  Сохранить как текущий план",
                   command=self._save_yaml).pack(side="right", padx=2)

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

    def _toggle_profile_settings(self):
        self._profile_settings_expanded = not self._profile_settings_expanded
        self._on_ui_mode_change()

    def _on_ui_mode_change(self):
        simple = self.ui_mode.get() == "simple"

        self._apply_log_visibility()

        if hasattr(self, "_advanced_actions_frame"):
            if simple:
                self._advanced_actions_frame.pack_forget()
                self._advanced_hline.pack_forget()
            else:
                self._advanced_hline.pack(fill="x", pady=6)
                self._advanced_actions_frame.pack(fill="x")

        if hasattr(self, "_profile_settings_frame"):
            if simple:
                self._profile_settings_toggle_btn.pack(
                    fill="x", pady=(4, 0), before=self._period_toggle_btn)
                self._profile_settings_toggle_btn.configure(
                    text=("▾  Настройки профиля" if self._profile_settings_expanded
                          else "▸  Настройки профиля"))
                if self._profile_settings_expanded:
                    self._profile_settings_frame.pack(fill="x", before=self._period_toggle_btn)
                else:
                    self._profile_settings_frame.pack_forget()
            else:
                self._profile_settings_toggle_btn.pack_forget()
                self._profile_settings_frame.pack(fill="x", before=self._period_toggle_btn)

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
        self._builder_edit_workout_id = workout_id
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

    # ── YAML load / save ──────────────────────────────────────────────────────
    def _on_yaml_path_change(self) -> None:
        self._yaml_loaded = False
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
            self._set_yaml_status("Файл выбран · нажмите «Обновить» для загрузки", ready=False)
        else:
            self._update_yaml_action_availability()
        self._update_yaml_action_availability()

    def _set_yaml_status(self, text: str, *, ready: bool) -> None:
        self._yaml_ready = ready
        self._yaml_status_var.set(text)
        self._update_yaml_action_availability()

    def _update_yaml_action_availability(self) -> None:
        if not self._quick_action_buttons:
            return
        has_file = bool(self.yaml_path.get().strip()) and Path(self.yaml_path.get()).is_file()
        states = {
            "validate": "normal" if has_file else "disabled",
            "build": "normal" if self._yaml_ready else "disabled",
            "upload": "normal" if self._yaml_ready and self._active_profile_email else "disabled",
        }
        for name, state in states.items():
            button = self._quick_action_buttons.get(name)
            if button is not None:
                button.configure(state=state)

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
            self._yaml_loaded = False
            self._set_yaml_status("План не выбран · выберите YAML", ready=False)
            return
        try:
            from garmin_fit.plan_domain import plan_to_data
            from garmin_fit.plan_store import PlanStore

            if self._store is not None:
                self._store.close()

            legacy_workdb = Path(str(path) + ".workdb")
            if legacy_workdb.exists():
                # Staging cache that older versions kept beside the plan.
                legacy_workdb.unlink(missing_ok=True)
            self._store = PlanStore.open(PlanStore.workdb_path_for(Path(path)))
            repairs = self._store.load_from_yaml(Path(path))

            data = plan_to_data(self._store.get_plan())
            self.workouts = self._parse_workouts(data)
            if self.workouts:
                dated = [w for w in self.workouts if w.get("date")]
                if dated:
                    self.cal_month = datetime.date.fromisoformat(dated[0]["date"]).replace(day=1)
            self._draw_calendar()
            self._yaml_loaded = True
            self._set_yaml_status(
                f"План загружен · {ru_workouts(len(self.workouts))} · проверяю YAML…", ready=False
            )
            self._log(f"[OK] Загружено: {ru_workouts(len(self.workouts))} из {Path(path).name}")
            if repairs:
                self._log("[Авто-правки]")
                for r in repairs:
                    self._log(f"  {r}")
            self.after(50, self._cmd_validate_yaml)
        except Exception as exc:
            self._yaml_loaded = False
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
        level = logging.ERROR if stripped.startswith(("[ERR]", "[FAIL]")) else logging.INFO
        logging.getLogger("garmin_fit.gui").log(level, stripped)
        if stripped.startswith(("[ERR]", "[FAIL]")):
            self._shell_status_var.set("Ошибка")
            if hasattr(self, "_result_var"):
                self._result_var.set(stripped)
        elif stripped.startswith("[OK]"):
            self._shell_status_var.set("Готово")
            if hasattr(self, "_result_var"):
                self._result_var.set(stripped)
        elif stripped.startswith(("[WARN]", "⏳")):
            self._shell_status_var.set("Выполняется")
            if hasattr(self, "_result_var"):
                self._result_var.set(stripped)
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
        self._update_yaml_action_availability()
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
        self._update_yaml_action_availability()

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
        hint = hint_for_line(text.strip())
        if hint:
            self._log_w.config(state="normal")
            self._log_w.insert("end", f"   💡 {hint}\n", ("hint",))
            self._log_w.see("end")
            self._log_w.config(state="disabled")
            self._show_toast(hint, YELLOW, duration_ms=6000)

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

    def _open_log_file(self) -> None:
        if not self._gui_log_path or not Path(self._gui_log_path).exists():
            self._log("[WARN] Файл журнала ещё не создан")
            return
        try:
            if os.name == "nt":
                os.startfile(str(self._gui_log_path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(self._gui_log_path)])
            else:
                subprocess.Popen(["xdg-open", str(self._gui_log_path)])
        except OSError as exc:
            self._log(f"[ERR] Не удалось открыть журнал: {exc}")

    def _set_result_actions(self, *enabled: str) -> None:
        for name, button in getattr(self, "_result_action_buttons", {}).items():
            if name in enabled:
                button.configure(state="normal")
                button.pack(side="left", padx=(0, 4))
            else:
                button.configure(state="disabled")
                button.pack_forget()

    def _open_fit_folder(self) -> None:
        output_dir = PROJECT_ROOT / "Output_fit"
        output_dir.mkdir(exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(str(output_dir))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(output_dir)])
            else:
                subprocess.Popen(["xdg-open", str(output_dir)])
        except OSError as exc:
            self._log(f"[ERR] Не удалось открыть папку FIT: {exc}")

    # ── CLI runner ────────────────────────────────────────────────────────────
    def _run(self, args):
        """Run a garmin_fit.cli command in-process on a worker thread.

        In-process instead of a child process: the packaged onefile CLI exe
        needed ~4.5 s just to unpack before every action, and secrets never
        have to appear on a command line.
        """
        if not self._begin_operation("Выполняется команда"):
            return
        from garmin_fit.cli_runner import redact_args, run_cli_captured

        run_args = list(args)
        if run_args and run_args[0].startswith("garmin-calendar") and self.pass_var.get():
            run_args += ["--password", self.pass_var.get()]
        self._log(f"\n$ garmin_fit.cli {' '.join(redact_args(run_args))}")

        def worker():
            code = run_cli_captured(run_args, lambda line: self.after(0, self._log, line))
            ok = code == 0
            self.after(0, self._log, "[OK] Готово" if ok else f"[FAIL] код {code}")
            self.after(0, self._handle_cli_result, args, ok)
            self.after(0, self._end_operation, ok)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_cli_result(self, args, ok: bool) -> None:
        if args and args[0] == "validate-yaml":
            self._yaml_validation_running = False
            if ok:
                self._set_yaml_status("YAML валиден · готово к сборке", ready=True)
                self._result_var.set("YAML проверен: план готов к сборке FIT")
            else:
                self._set_yaml_status(
                    "YAML содержит ошибки · см. вывод команды", ready=False
                )
                self._result_var.set("YAML не прошёл проверку. Подробности — в логе ниже.")
                self._set_result_actions()
        elif args and args[0] == "run" and ok:
            self._result_var.set("FIT-файлы собраны. Их можно открыть в папке Output_fit.")
            self._set_result_actions("open_fit", "go_garmin")
        elif args and args[0] == "garmin-calendar" and ok:
            self._result_var.set("Изменения применены в Garmin Connect.")
            self._set_result_actions("go_garmin")
        elif args and args[0] in ("archive", "restore") and ok:
            # "archive" moves plans out of Plan/: forget a plan that is no longer there.
            current = self.yaml_path.get().strip()
            if current and not Path(current).exists():
                self.yaml_path.set("")
                self._result_var.set("План перенесён в архив (Plan/plan_done). Выберите следующий план.")
            elif args[0] == "restore":
                self._result_var.set("FIT-файлы восстановлены из архива в Output_fit.")
                self._set_result_actions("open_fit")

    def _append_garmin_args(self, args):
        if self.email_var.get(): args += ["--email",     self.email_var.get()]
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
        if not self._active_profile_email:
            messagebox.showwarning("Нет профиля", "Сначала выберите профиль Garmin.", parent=self)
            return
        count = len(self.workouts)
        duplicate_action = self._upload_duplicate_var.get()
        period = f"{self.from_var.get() or 'начало не задано'} — {self.to_var.get() or 'конец не задан'}"
        if not messagebox.askyesno(
                "Отправить план в Garmin Connect",
                f"Сейчас будут отправлены реальные изменения.\n\n"
                f"План: {Path(self.yaml_path.get()).name}\n"
                f"Профиль: {self._active_profile_email}\n"
                f"Период: {period}\n"
                f"Тренировок в плане: {count}\n"
                f"При совпадении имени и даты: {duplicate_action.lower()}\n\nПродолжить?",
                icon="warning", parent=self):
            return
        args = ["garmin-calendar"]
        if duplicate_action == "Заменить назначение":
            args.append("--replace-duplicates")
        elif duplicate_action == "Создать копию":
            args.append("--allow-duplicates")
        if self.yaml_path.get():
            args += ["--plan", self.yaml_path.get()]
        self._append_garmin_args(args)
        self._run(args)

    def _cmd_delete(self):
        if not self._active_profile_email:
            messagebox.showwarning("Нет профиля", "Сначала выберите профиль Garmin.", parent=self)
            return
        if not messagebox.askyesno(
                "Удалить тренировки из Garmin",
                f"Профиль: {self._active_profile_email}\n"
                f"Период: {self.from_var.get() or 'начало не задано'} — "
                f"{self.to_var.get() or 'конец не задан'}\n\n"
                "Удаление необратимо.\nПродолжить?",
                icon="warning", parent=self):
            return
        args = ["garmin-calendar-delete"]
        self._append_garmin_args(args)
        args += ["--confirm"]
        self._run(args)

    def _cmd_validate_yaml(self):
        if self.yaml_path.get().strip():
            self._set_yaml_status("Проверка YAML…", ready=False)
            self._yaml_validation_running = True
        args = ["validate-yaml"]
        if self.yaml_path.get():
            args += ["--plan", self.yaml_path.get()]
        self._run(args)

    def _cmd_validate_fit(self):  self._run(["validate-fit"])
    def _cmd_doctor(self):        self._run(["doctor", "--llm"])
    def _cmd_archive(self):
        if messagebox.askyesno(
            "Архивировать план",
            "Переместить текущий план и FIT-файлы в архив? Output_fit/ будет очищен.",
            parent=self,
        ):
            self._run(["archive", "--yes"])
    def _cmd_list_archives(self): self._run(["list-archives"])

    def _cmd_restore(self):
        name = simpledialog.askstring("Восстановить архив",
                                      "Введите имя архива:", parent=self)
        if name and messagebox.askyesno(
            "Восстановить архив",
            f"Восстановить «{name.strip()}»? Текущие FIT-файлы будут перезаписаны.",
            parent=self,
        ):
            self._run(["restore", name.strip(), "--yes"])

    # ── LLM tab helpers ───────────────────────────────────────────────────────
    def _make_llm_client(self, *, for_generation: bool = False):
        """Return either a direct UnifiedLLMClient ("own" mode) or a
        PlanApiClient talking to a hosted FitWeaver Plan API ("api" mode)."""
        if self.llm_conn_mode.get() == "api":
            from garmin_fit.api_client import PlanApiClient
            timeout = max(60, self.llm_timeout.get()) if for_generation else 300
            return PlanApiClient(self.api_url.get(), self.api_token.get(), timeout_sec=timeout)

        from garmin_fit.config import ARTIFACTS_DIR
        from garmin_fit.llm.client import UnifiedLLMClient

        # "auto" tries /v1/chat/completions first, which is the only path that
        # actually sends enable_thinking=False / thinking:disabled -- forcing
        # "completions" (the raw-text endpoint) skips that entirely, letting
        # reasoning models like Qwen3 leak "Wait, let me reconsider..." style
        # thinking text straight into the YAML output. auto still falls back
        # to raw completions if chat fails or returns unusable content.
        kwargs = {"model": self.llm_model.get(), "base_url": self.llm_url.get(),
                  "api_type": self.llm_type.get(), "openai_mode": "auto",
                  "output_format": self.llm_output_format.get(),
                  # Re-running an edited plan regenerates only the changed workouts.
                  "segment_cache_dir": ARTIFACTS_DIR / "llm_segment_cache"}
        if for_generation:
            kwargs["request_timeout_sec"] = max(60, self.llm_timeout.get())
        return UnifiedLLMClient(**kwargs)

    def _on_tab_changed(self, _event=None):
        try:
            is_llm_tab = self._nb.index(self._nb.select()) == 1
        except tk.TclError:
            return
        if is_llm_tab:
            self._warm_up_llm()

    def _warm_up_llm(self):
        """Load the local Ollama model in the background before the first request."""
        if self.llm_conn_mode.get() != "own" or self.llm_type.get() != "ollama":
            return
        key = (self.llm_url.get(), self.llm_model.get())
        if getattr(self, "_warmed_llm", None) == key:
            return
        self._warmed_llm = key

        def worker():
            try:
                self._make_llm_client().warm_up()
            except Exception:
                pass  # best effort: generation will load the model anyway

        threading.Thread(target=worker, daemon=True).start()

    def _llm_cancel(self):
        event = getattr(self, "_llm_cancel_event", None)
        if event is not None:
            event.set()
            self._cancel_btn.config(state="disabled")
            self._set_progress("⏳ Отменяю…")

    def _on_llm_progress(self, info):
        stage = info.get("stage")
        if stage == "segment" and info.get("total", 1) > 1:
            self._llm_segment_label = f"тренировка {info['segment']}/{info['total']}"
            self._set_progress(f"⏳ Генерирую YAML: {self._llm_segment_label}…")
        elif stage == "generating":
            label = getattr(self, "_llm_segment_label", "")
            prefix = f"{label}, " if label else ""
            self._set_progress(f"⏳ Генерирую YAML: {prefix}{info.get('tokens', 0)} фрагм. ответа…")
        elif stage == "cached":
            self._set_progress(f"⏳ Тренировка {info.get('segment')}: взята из кэша")

    def _llm_ui_idle(self):
        self._gen_btn.config(state="normal")
        self._cancel_btn.config(state="disabled")
        self._llm_cancel_event = None
        self._llm_segment_label = ""

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
        self._llm_cancel_event = threading.Event()
        cancel_event = self._llm_cancel_event
        self._llm_segment_label = ""
        self._set_progress("⏳ Генерирую YAML…")
        self._show_generated("")

        from garmin_fit.marked_plan import is_marked_plan
        marked = is_marked_plan(plan_text)
        hr_zones = self._builder_hr_zones()
        if marked:
            self._set_progress("⏳ Разбираю размеченный план (без LLM)…")
        else:
            self._cancel_btn.config(state="normal")

        def worker():
            from garmin_fit.api_client import PlanApiError
            from garmin_fit.llm.client import GenerationCancelled
            try:
                if marked:
                    # Marked text is compiled deterministically: no LLM, no network.
                    from garmin_fit.plan_service import build_marked_plan_draft
                    result = build_marked_plan_draft(plan_text, hr_zones=hr_zones)
                elif self.llm_conn_mode.get() == "api":
                    client = self._make_llm_client(for_generation=True)
                    result = client.build_plan_draft(plan_text, max_retries=1)
                else:
                    from garmin_fit.plan_service import build_plan_draft
                    client = self._make_llm_client(for_generation=True)
                    client.cancel_event = cancel_event
                    client.progress_callback = lambda info: self.after(0, self._on_llm_progress, info)
                    result = build_plan_draft(
                        client, plan_text, max_retries=1, hr_zones=hr_zones,
                    )
                if cancel_event.is_set():
                    raise GenerationCancelled("cancelled")  # API mode cannot abort mid-request

                yaml_text = result.yaml_text or ""
                warnings  = result.warnings or []
                repairs   = result.repairs or []
                errors = result.validation_errors or []
                failed_segments = getattr(result, "failed_segments", None) or []

                # Count workouts from yaml_text
                try:
                    n = len((yaml.safe_load(yaml_text) or {}).get("workouts", []))
                except Exception:
                    n = 0

                def finish():
                    if errors:
                        self._show_generated("")
                        self._set_progress(f"❌ YAML не создан: {errors[0]}", RED)
                        self._llm_ui_idle()
                        self._end_operation(False)
                        self._log("\n[Ошибки генерации]")
                        for error in errors:
                            self._log(f"  {error}")
                        return

                    self._show_generated(yaml_text)

                    status = f"✅ {'Разобрано без LLM' if marked else 'Готово'} — {ru_workouts(n)}"
                    color = GREEN
                    if failed_segments:
                        status = (f"⚠ Готово {n} из {ru_workouts(n + len(failed_segments))}; "
                                  "остальные не распознаны — см. лог")
                        color = YELLOW
                    if repairs:
                        status += ", " + ru_count(len(repairs), "правка", "правки", "правок")
                    if warnings:
                        status += ", " + ru_count(len(warnings), "предупреждение", "предупреждения", "предупреждений")
                    self._set_progress(status, color)
                    self._llm_ui_idle()
                    self._end_operation(True)

                    if failed_segments:
                        self._log("\n[Не удалось сгенерировать — исправьте текст или впишите вручную]")
                        for item in failed_segments:
                            self._log(f"  {item.get('header', '')}: {item.get('error', '')}")

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
                    self._llm_ui_idle()
                    self._end_operation(False)
                self.after(0, on_api_err)

            except GenerationCancelled:
                def on_cancel():
                    self._set_progress("⏹ Генерация отменена", MUTED)
                    self._llm_ui_idle()
                    self._end_operation(False)
                self.after(0, on_cancel)

            except Exception as exc:
                msg = str(exc)  # capture before Python clears exc at end of except block
                def on_err():
                    self._set_progress(f"❌ Ошибка: {msg}", RED)
                    self._llm_ui_idle()
                    self._end_operation(False)
                self.after(0, on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _copy_yaml(self):
        text = self._yaml_out.get("1.0", "end").strip()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)

    def _marked_view_text(self) -> str:
        from garmin_fit.marked_plan import plan_data_to_marked_text
        try:
            return plan_data_to_marked_text(yaml.safe_load(self._generated_yaml) or {})
        except Exception as exc:  # show YAML rather than nothing
            self._log(f"[WARN] Не удалось показать план как текст: {exc}")
            return ""

    def _show_generated(self, yaml_text: str) -> None:
        self._generated_yaml = yaml_text or ""
        if not self._generated_yaml:
            self._out_view = "yaml"
        shown = self._generated_yaml
        if self._out_view == "text" and self._generated_yaml:
            shown = self._marked_view_text() or self._generated_yaml
        self._yaml_out.config(state="normal")
        self._yaml_out.delete("1.0", "end")
        self._yaml_out.insert("end", shown)
        self._yaml_out.config(state="disabled")
        has_plan = bool(self._generated_yaml)
        self._view_btn.config(state="normal" if has_plan else "disabled",
                              text="Показать YAML" if self._out_view == "text" else "Показать как текст")
        self._to_editor_btn.config(state="normal" if has_plan else "disabled")
        self._out_title.config(text="План текстом (для проверки)" if self._out_view == "text"
                               else "Сгенерированный YAML")

    def _toggle_out_view(self):
        self._out_view = "yaml" if self._out_view == "text" else "text"
        self._show_generated(self._generated_yaml)

    def _generated_to_editor(self):
        """Put the generated plan into the input as marked text: fix it there and
        press Generate again -- marked text compiles instantly without the LLM."""
        text = self._marked_view_text()
        if not text:
            return
        current = self._plan_text.get("1.0", "end").strip()
        if current and not messagebox.askyesno(
            "Заменить текст плана",
            "Заменить текст плана размеченной версией результата? Её можно поправить и "
            "сгенерировать заново — без LLM и мгновенно.",
            parent=self,
        ):
            return
        self._plan_text.delete("1.0", "end")
        self._plan_text.insert("1.0", text)
        self._set_progress("Правьте текст и нажмите «Генерировать YAML» — разбор без LLM", ACCENT)

    def _clear_plan(self):
        self._plan_text.delete("1.0", "end")
        self._show_generated("")
        self._set_progress("")

    def _save_yaml(self):
        text = self._generated_yaml.strip()
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
            atomic_write_text(path, text)
            self.yaml_path.set(path)
            self._reload_yaml()
            self._set_progress(f"Сохранено: {Path(path).name}", GREEN)
            self._nb.select(0)

    # ── LLM example ───────────────────────────────────────────────────────────
    def _insert_example(self):
        example = (
            "01.10.2026 (Чт) — Длинный бег\n"
            "20 км, пульс 125–140 уд/мин\n\n"
            "03.10.2026 (Сб) — Интервалы\n"
            "Разминка 2 км, 6×800 м пульс 160–170 / 400 м пульс 120–130, заминка 1.5 км\n\n"
            "05.10.2026 (Пн) — Темповый бег\n"
            "Разминка 2 км, основная часть 5 км пульс 155–165, заминка 1 км\n"
        )
        self._plan_text.delete("1.0", "end")
        self._plan_text.insert("1.0", example)


if __name__ == "__main__":
    app = App()
    app.mainloop()
