import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile

try:
    import garmin_fit.telegram_bot as telegram_bot
except Exception:
    telegram_bot = None


@unittest.skipIf(telegram_bot is None, "telegram_bot dependencies are unavailable")
class TelegramBotCancelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        telegram_bot.USER_STATES.clear()

    async def test_cancel_sets_flag_for_active_build(self):
        user_id = 1001
        state = telegram_bot.get_state(user_id)
        state.status = "building"

        replies = []

        async def _reply_text(text):
            replies.append(text)

        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=user_id),
            message=SimpleNamespace(reply_text=_reply_text),
        )

        with patch("garmin_fit.telegram_bot.ensure_user_allowed", new=AsyncMock(return_value=True)):
            await telegram_bot.cancel(update, None)

        self.assertTrue(state.cancel_requested)
        self.assertEqual(state.status, "building")
        self.assertTrue(any("Cancellation requested" in text for text in replies))

    async def test_execute_build_job_skips_when_cancel_requested(self):
        user_id = 2002
        state = telegram_bot.get_state(user_id)
        state.status = "queued"
        state.cancel_requested = True
        state.yaml_text = "workouts: []"

        sent_messages = []

        class _Bot:
            async def send_message(self, chat_id, text):
                sent_messages.append((chat_id, text))

        application = SimpleNamespace(bot=_Bot())
        job = telegram_bot.BuildJob(chat_id=77, user_id=user_id)

        with patch("garmin_fit.telegram_bot.run_pipeline") as run_pipeline_mock, patch(
            "garmin_fit.telegram_bot.archive_current_plan"
        ) as archive_mock:
            await telegram_bot._execute_build_job(application, job)
            run_pipeline_mock.assert_not_called()
            archive_mock.assert_not_called()

        self.assertEqual(state.status, "idle")
        self.assertFalse(state.cancel_requested)
        self.assertTrue(any("Build cancelled." in text for _, text in sent_messages))

    async def test_create_plan_zip_contains_only_input_and_fit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fit_path = root / "W01_TEST.fit"
            zip_path = root / "bundle.zip"
            fit_path.write_bytes(b"fit")
            plan_text = "Run 10km easy"
            now = datetime(2026, 4, 6)  # decade-1

            telegram_bot._create_plan_zip(zip_path, plan_text, [fit_path], now=now)

            with ZipFile(zip_path) as archive:
                names = set(archive.namelist())

            self.assertIn("2026/04/decade-1/input_plan.txt", names)
            self.assertIn("2026/04/decade-1/W01_TEST.fit", names)
            self.assertEqual(len(names), 2)  # nothing else in the archive


if __name__ == "__main__":
    unittest.main()

