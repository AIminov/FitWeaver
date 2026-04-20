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

    @staticmethod
    def _make_update(user_id, replies, text="plan text"):
        async def _reply_text(message):
            replies.append(message)

        return SimpleNamespace(
            effective_user=SimpleNamespace(id=user_id),
            effective_chat=SimpleNamespace(id=700 + user_id),
            message=SimpleNamespace(text=text, reply_text=_reply_text),
        )

    @staticmethod
    def _make_context():
        bot = SimpleNamespace(
            send_chat_action=AsyncMock(),
        )
        return SimpleNamespace(bot=bot)

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
        # Message is localised — accept any reset/cancel confirmation text
        self.assertTrue(any(
            any(keyword in text for keyword in ("reset", "cancel", "сброс", "отмен"))
            for _, text in sent_messages
        ))

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

    async def test_create_plan_zip_preserves_exact_original_plan_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fit_path = root / "W01_TEST.fit"
            zip_path = root / "bundle.zip"
            fit_path.write_bytes(b"fit")
            plan_text = "Week 1\nEasy 8 km"

            telegram_bot._create_plan_zip(zip_path, plan_text, [fit_path], now=datetime(2026, 4, 6))

            with ZipFile(zip_path) as archive:
                extracted = archive.read("2026/04/decade-1/input_plan.txt").decode("utf-8")

            self.assertEqual(extracted, plan_text)

    async def test_new_plan_resets_clarification_state(self):
        user_id = 3003
        state = telegram_bot.get_state(user_id)
        state.clarification_attempted = True
        state.pending_clarification = "• old ambiguity"
        state.pending_ambiguities = ["old ambiguity"]
        state.pending_sbu_yaml_data = {"workouts": []}

        replies = []
        update = self._make_update(user_id, replies, text="Long enough new plan text")
        context = self._make_context()

        with patch("garmin_fit.telegram_bot.ensure_user_allowed", new=AsyncMock(return_value=True)), patch(
            "garmin_fit.telegram_bot._process_plan", new=AsyncMock()
        ) as process_mock:
            await telegram_bot.handle_text_message(update, context)

        process_mock.assert_awaited_once()
        self.assertFalse(state.clarification_attempted)
        self.assertIsNone(state.pending_clarification)
        self.assertEqual(state.pending_ambiguities, [])
        self.assertIsNone(state.pending_sbu_yaml_data)
        self.assertEqual(state.original_plan_text, "Long enough new plan text")
        self.assertEqual(state.active_plan_text, "Long enough new plan text")

    async def test_standard_sbu_flows_to_clarification_when_ambiguities_exist(self):
        user_id = 4004
        state = telegram_bot.get_state(user_id)
        state.status = "awaiting_sbu_choice"
        state.yaml_text = "workouts:\n- name: W01"
        state.pending_sbu_yaml_data = {"workouts": [{"name": "W01", "steps": [{"type": "sbu_block"}]}]}
        state.pending_ambiguities = ["pace is ambiguous", "zone is ambiguous"]

        replies = []
        update = self._make_update(user_id, replies, text="standard")
        context = self._make_context()

        await telegram_bot._handle_sbu_choice(update, context, "standard")

        self.assertEqual(state.status, "awaiting_clarification")
        self.assertIn("pace is ambiguous", state.pending_clarification)
        self.assertIn("Ambiguities found:", replies[-1])

    async def test_custom_sbu_flows_to_clarification_when_ambiguities_exist(self):
        user_id = 5005
        state = telegram_bot.get_state(user_id)
        state.status = "awaiting_sbu_choice"
        state.pending_sbu_yaml_data = {"workouts": [{"name": "W01", "steps": [{"type": "sbu_block"}]}]}

        replies = []
        update = self._make_update(user_id, replies, text="custom drills")
        context = self._make_context()
        draft = SimpleNamespace(
            yaml_text="workouts:\n- name: W01",
            ambiguities=["unclear recovery pace"],
            warnings=[],
            repairs=[],
        )

        with patch("garmin_fit.telegram_bot._build_llm_client") as build_llm_mock, patch(
            "garmin_fit.telegram_bot.apply_custom_sbu_choice", return_value=draft
        ):
            await telegram_bot._handle_sbu_choice(update, context, "custom drills")

        build_llm_mock.assert_called_once()
        self.assertEqual(state.status, "awaiting_clarification")
        self.assertEqual(state.pending_ambiguities, ["unclear recovery pace"])
        self.assertIn("unclear recovery pace", state.pending_clarification)
        self.assertIn("Ambiguities found:", replies[-1])


if __name__ == "__main__":
    unittest.main()
