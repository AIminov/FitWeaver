"""Shared visual system for the FitWeaver desktop GUI.

The GUI keeps a Tkinter fallback so source checkouts remain usable without the
optional visual dependency. When ``customtkinter`` is installed, the app root
uses its dark rendering while the existing Canvas/Text widgets continue to
work unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GuiPalette:
    background: str = "#1e1e2e"
    surface: str = "#181825"
    surface_raised: str = "#313244"
    text: str = "#cdd6f4"
    text_muted: str = "#9399b2"
    accent: str = "#89b4fa"
    accent_hover: str = "#74a7f8"
    success: str = "#a6e3a1"
    danger: str = "#f38ba8"
    warning: str = "#f9e2af"
    purple: str = "#cba6f7"


PALETTE = GuiPalette()


def load_customtkinter():
    """Return CustomTkinter if the optional GUI extra is installed."""

    try:
        import customtkinter as ctk
    except ImportError:
        return None
    return ctk


def configure_customtkinter(ctk) -> None:
    """Configure the optional root toolkit consistently with our palette."""

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")


def configure_ttk(style, palette: GuiPalette = PALETTE) -> None:
    """Apply the shared palette to the native ttk controls."""

    style.theme_use("clam")
    style.configure(".", background=palette.background, foreground=palette.text,
                    font=("Segoe UI", 10))
    style.configure("TFrame", background=palette.background)
    style.configure("TLabel", background=palette.background, foreground=palette.text)
    style.configure("Muted.TLabel", background=palette.background,
                    foreground=palette.text_muted, font=("Segoe UI", 9))
    style.configure("Status.TLabel", background=palette.background,
                    foreground=palette.text_muted, font=("Segoe UI", 9))
    style.configure("Warning.TLabel", background=palette.background,
                    foreground=palette.warning, font=("Segoe UI", 9, "bold"))
    style.configure("Danger.TLabel", background=palette.background,
                    foreground=palette.danger, font=("Segoe UI", 9, "bold"))
    style.configure("Error.TLabel", background=palette.background,
                    foreground=palette.danger, font=("Segoe UI", 8))
    style.configure("Invalid.TEntry", fieldbackground="#4a2430",
                    foreground=palette.text, insertcolor=palette.text)
    style.configure("TEntry", fieldbackground=palette.surface_raised,
                    foreground=palette.text, insertcolor=palette.text)
    style.configure("TCheckbutton", background=palette.background,
                    foreground=palette.text)
    style.map("TCheckbutton", background=[("active", palette.background)])
    style.configure("TCombobox", fieldbackground=palette.surface_raised,
                    foreground=palette.text, selectbackground=palette.surface_raised,
                    selectforeground=palette.text)
    style.map("TCombobox", fieldbackground=[("readonly", palette.surface_raised)])
    style.configure("TSeparator", background=palette.surface_raised)
    style.configure("Title.TLabel", background=palette.background,
                    foreground=palette.purple, font=("Segoe UI", 15, "bold"))
    style.configure("Section.TLabel", background=palette.background,
                    foreground=palette.accent, font=("Segoe UI", 9, "bold"))
    style.configure("Card.TFrame", background=palette.surface_raised)
    style.configure("TNotebook", background=palette.surface, borderwidth=0)
    style.configure("TNotebook.Tab", background=palette.surface_raised,
                    foreground=palette.text_muted, padding=(16, 8),
                    font=("Segoe UI", 10))
    style.map("TNotebook.Tab", background=[("selected", palette.background)],
              foreground=[("selected", palette.text)])

    for name, background, foreground in [
        ("TButton", palette.surface_raised, palette.text),
        ("Primary.TButton", palette.accent, palette.background),
        ("Danger.TButton", palette.danger, palette.background),
        ("Success.TButton", palette.success, palette.background),
    ]:
        style.configure(name, background=background, foreground=foreground,
                        padding=(10, 7), relief="flat", font=("Segoe UI", 10))
        style.map(name, background=[("active", palette.accent_hover)])
