import unittest
from types import SimpleNamespace
import tempfile
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile
from pathlib import Path

try:
    import Scripts.telegram_bot as telegram_bot
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

        with patch("Scripts.telegram_bot.ensure_user_allowed", new=AsyncMock(return_value=True)):
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

        with patch("Scripts.telegram_bot.run_pipeline") as run_pipeline_mock, patch(
            "Scripts.telegram_bot.archive_current_plan"
        ) as archive_mock:
            await telegram_bot._execute_build_job(application, job)
            run_pipeline_mock.assert_not_called()
            archive_mock.assert_not_called()

        self.assertEqual(state.status, "idle")
        self.assertFalse(state.cancel_requested)
        self.assertTrue(any("Build cancelled." in text for _, text in sent_messages))

    async def test_create_plan_zip_exports_templates_when_workspace_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            yaml_path = root / "plan.yaml"
            fit_path = root / "W01_TEST.fit"
            zip_path = root / "bundle.zip"
            report_path = root / "plan.build_report.json"
            templates_dir = root / "templates"
            templates_dir.mkdir()
            yaml_path.write_text("workouts: []", encoding="utf-8")
            fit_path.write_bytes(b"fit")
            report_path.write_text("{}", encoding="utf-8")

            def _fake_generate_all_templates(source_yaml, *, output_dir=None, cleanup_output=False):
                output = Path(output_dir)
                output.mkdir(parents=True, exist_ok=True)
                (output / "W01_TEST.py").write_text("# template", encoding="utf-8")
                return 1, 1

            with patch.object(telegram_bot, "TEMPLATES_DIR", templates_dir), patch(
                "Scripts.telegram_bot.generate_all_templates",
                side_effect=_fake_generate_all_templates,
            ):
                telegram_bot._create_plan_zip(zip_path, yaml_path, [fit_path], [report_path])

            with ZipFile(zip_path) as archive:
                names = set(archive.namelist())

            self.assertIn("plan/plan.yaml", names)
            self.assertIn("artifacts/plan.build_report.json", names)
            self.assertIn("templates/W01_TEST.py", names)
            self.assertIn("fit/W01_TEST.fit", names)


if __name__ == "__main__":
    unittest.main()
