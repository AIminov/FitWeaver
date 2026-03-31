"""
Entry point for running the bot as a module.

Usage:
    python -m Scripts.telegram_bot
or
    python Scripts/telegram_bot.py
"""

from garmin_fit.bot import main

if __name__ == "__main__":
    raise SystemExit(main())
