import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile

from telegram.error import TimedOut

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

    async def test_cancel_sets_flag_for_active_generation(self):
        user_id = 1002
        state = telegram_bot.get_state(user_id)
        state.status = "generating"

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
        self.assertEqual(state.status, "generating")
        self.assertTrue(any("LLM request" in text for text in replies))

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

    async def test_delivery_garmin_old_button_requires_existing_zip(self):
        user_id = 2502
        state = telegram_bot.get_state(user_id)
        state.status = "awaiting_delivery_choice"
        state.pending_zip_path = None
        state.garmin_client = object()

        edits = []
        query = SimpleNamespace(
            from_user=SimpleNamespace(id=user_id),
            data="delivery:garmin",
            message=SimpleNamespace(chat_id=9001),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(side_effect=lambda text: edits.append(text)),
        )
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(bot=SimpleNamespace(send_document=AsyncMock(), send_message=AsyncMock()))

        with patch("garmin_fit.telegram_bot.user_is_allowed", return_value=True), patch(
            "garmin_fit.telegram_bot._garmin_upload_and_report", new=AsyncMock()
        ) as upload_mock:
            await telegram_bot.handle_delivery_choice(update, context)

        upload_mock.assert_not_awaited()
        self.assertEqual(state.status, "idle")
        self.assertTrue(any("ZIP file not found" in text for text in edits))

    async def test_process_plan_stops_after_generation_when_cancel_was_requested(self):
        user_id = 2602
        state = telegram_bot.get_state(user_id)
        replies = []
        update = self._make_update(user_id, replies, text="10.03\nEasy 6 km")
        context = self._make_context()

        class _FakeLlm:
            def check_connection(self):
                return True

        def _fake_build_plan_draft(_llm, _plan_text):
            state.cancel_requested = True
            return SimpleNamespace(
                yaml_text="workouts: []",
                data={"workouts": []},
                validation_errors=[],
                ambiguities=[],
                warnings=[],
                repairs=[],
            )

        with patch("garmin_fit.telegram_bot._build_llm_client", return_value=_FakeLlm()), patch(
            "garmin_fit.telegram_bot.build_plan_draft", side_effect=_fake_build_plan_draft
        ):
            await telegram_bot._process_plan(update, context, "10.03\nEasy 6 km")

        self.assertEqual(state.status, "idle")
        self.assertFalse(state.cancel_requested)
        self.assertTrue(any("reset" in text.lower() for text in replies))
        self.assertFalse(any("YAML ready" in text for text in replies))

    async def test_garmin_connect_continues_when_status_reply_times_out(self):
        user_id = 2702
        state = telegram_bot.get_state(user_id)
        state.status = "awaiting_garmin_password"
        state.return_status_after_garmin_auth = "awaiting_delivery_choice"
        client = object()

        class _FakeManager:
            def __init__(self, email, password, token_dir, return_on_mfa):
                self.email = email
                self.password = password
                self.token_dir = token_dir
                self.return_on_mfa = return_on_mfa

            def connect(self):
                return client

        reply = AsyncMock(side_effect=[TimedOut("telegram timeout"), None])
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=user_id),
            message=SimpleNamespace(reply_text=reply),
        )
        context = SimpleNamespace()

        with patch("garmin_fit.garmin_auth_manager.GarminAuthManager", _FakeManager):
            await telegram_bot._do_garmin_connect(
                update,
                context,
                user_id,
                state,
                "runner@example.com",
                "secret",
            )

        self.assertIs(state.garmin_client, client)
        self.assertEqual(state.status, "awaiting_delivery_choice")
        self.assertEqual(reply.await_count, 2)

    async def test_garmin_connect_preserves_built_plan_and_delivery_state(self):
        user_id = 2752
        state = telegram_bot.get_state(user_id)
        state.status = "awaiting_delivery_choice"
        state.yaml_text = "workouts:\n- filename: W01\n"
        state.yaml_path = Path("Plan/plan_u2752.yaml")
        state.fit_files = [Path("Output_fit/W01.fit")]
        state.pending_zip_path = Path("bundle.zip")
        client = object()

        class _FakeManager:
            def __init__(self, email, password, token_dir, return_on_mfa):
                pass

            def connect(self):
                return client

        reply = AsyncMock()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=user_id),
            message=SimpleNamespace(reply_text=reply),
        )
        context = SimpleNamespace()

        telegram_bot._begin_garmin_auth(state)
        state.status = "awaiting_garmin_password"
        with patch("garmin_fit.garmin_auth_manager.GarminAuthManager", _FakeManager):
            await telegram_bot._do_garmin_connect(
                update,
                context,
                user_id,
                state,
                "runner@example.com",
                "secret",
            )

        self.assertIs(state.garmin_client, client)
        self.assertEqual(state.status, "awaiting_delivery_choice")
        self.assertIsNotNone(state.yaml_text)
        self.assertEqual(state.yaml_path, Path("Plan/plan_u2752.yaml"))
        self.assertEqual(state.fit_files, [Path("Output_fit/W01.fit")])
        self.assertEqual(state.pending_zip_path, Path("bundle.zip"))

    async def test_delivery_garmin_not_connected_preserves_zip_and_state(self):
        user_id = 2762
        state = telegram_bot.get_state(user_id)
        state.status = "awaiting_delivery_choice"
        state.pending_zip_path = Path("bundle.zip")

        edits = []
        query = SimpleNamespace(
            from_user=SimpleNamespace(id=user_id),
            data="delivery:garmin",
            message=SimpleNamespace(chat_id=9002),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(side_effect=lambda text: edits.append(text)),
        )
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(
            bot=SimpleNamespace(send_document=AsyncMock(), send_message=AsyncMock()),
            application=SimpleNamespace(),
        )

        with patch("garmin_fit.telegram_bot.user_is_allowed", return_value=True), patch.object(
            Path,
            "exists",
            return_value=True,
        ), patch.object(Path, "unlink") as unlink_mock:
            await telegram_bot.handle_delivery_choice(update, context)

        unlink_mock.assert_not_called()
        self.assertEqual(state.status, "awaiting_delivery_choice")
        self.assertEqual(state.pending_zip_path, Path("bundle.zip"))
        self.assertTrue(any("Garmin Connect" in text for text in edits))

    async def test_send_to_garmin_success_keeps_delivery_state_and_zip(self):
        user_id = 2772
        state = telegram_bot.get_state(user_id)
        state.status = "awaiting_delivery_choice"
        state.garmin_client = object()
        state.fit_files = [Path("Output_fit/W01.fit")]
        state.pending_zip_path = Path("bundle.zip")

        replies = []
        update = self._make_update(user_id, replies)
        context = SimpleNamespace(args=[], application=SimpleNamespace())

        with patch("garmin_fit.telegram_bot.ensure_user_allowed", new=AsyncMock(return_value=True)), patch(
            "garmin_fit.telegram_bot._garmin_upload_and_report",
            new=AsyncMock(return_value=True),
        ) as upload_mock, patch.object(Path, "unlink") as unlink_mock, patch.object(
            Path, "exists", return_value=True
        ):
            await telegram_bot.send_to_garmin(update, context)

        upload_mock.assert_awaited_once()
        unlink_mock.assert_not_called()
        self.assertEqual(state.status, "awaiting_delivery_choice")
        self.assertEqual(state.pending_zip_path, Path("bundle.zip"))

    async def test_garmin_upload_uses_yaml_text_when_archived_plan_path_is_gone(self):
        user_id = 2782
        state = telegram_bot.get_state(user_id)
        state.garmin_client = object()
        state.yaml_path = Path("Plan/moved_to_archive.yaml")
        state.yaml_text = (
            "workouts:\n"
            "- filename: W18_05-01_Fri_Easy_10km\n"
            "  name: W18_05-01_Fri_Easy_10km\n"
            "  desc: Easy run\n"
            "  type_code: easy\n"
            "  distance_km: 10.0\n"
            "  estimated_duration_min: 68\n"
            "  steps:\n"
            "  - type: dist_hr\n"
            "    km: 10.0\n"
            "    hr_low: 120\n"
            "    hr_high: 140\n"
            "    intensity: active\n"
        )
        sent = []

        class _Bot:
            async def send_message(self, chat_id, text):
                sent.append((chat_id, text))

        class _Result:
            uploaded = 1
            results = []

            def summary(self):
                return "uploaded 1"

        class _Exporter:
            def __init__(self, client):
                self.client = client

            def upload_plan(self, plan, schedule, dry_run, year):
                self.plan = plan
                return _Result()

        application = SimpleNamespace(bot=_Bot())

        with patch.object(Path, "exists", return_value=False), patch(
            "garmin_fit.garmin_calendar_export.GarminCalendarExporter", _Exporter
        ):
            uploaded = await telegram_bot._garmin_upload_and_report(
                application,
                chat_id=777,
                user_id=user_id,
            )

        self.assertTrue(uploaded)
        self.assertTrue(any("uploaded 1" in text for _, text in sent))
        self.assertTrue(any("/disconnect_garmin" in text for _, text in sent))

    async def test_build_during_delivery_choice_reshows_delivery_keyboard(self):
        user_id = 2792
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "bundle.zip"
            zip_path.write_bytes(b"zip")

            state = telegram_bot.get_state(user_id)
            state.status = "awaiting_delivery_choice"
            state.yaml_text = "workouts:\n- filename: W01\n"
            state.pending_zip_path = zip_path
            replies = []
            reply_markups = []

            async def _reply_text(text, reply_markup=None):
                replies.append(text)
                reply_markups.append(reply_markup)

            update = SimpleNamespace(
                effective_user=SimpleNamespace(id=user_id),
                effective_chat=SimpleNamespace(id=700 + user_id),
                message=SimpleNamespace(text="/build", reply_text=_reply_text),
            )
            context = self._make_context()

            with patch("garmin_fit.telegram_bot.ensure_user_allowed", new=AsyncMock(return_value=True)):
                await telegram_bot.build(update, context)

            self.assertEqual(state.status, "awaiting_delivery_choice")
            self.assertTrue(replies)
            self.assertIsNotNone(reply_markups[-1])

    async def test_pasted_yaml_skips_llm_and_loads_ready_plan(self):
        user_id = 2802
        yaml_text = (
            "workouts:\n"
            "- filename: W18_05-01_Fri_Easy_10km\n"
            "  name: W18_05-01_Fri_Easy_10km\n"
            "  desc: Easy run\n"
            "  type_code: easy\n"
            "  distance_km: 10.0\n"
            "  estimated_duration_min: 68\n"
            "  steps:\n"
            "  - type: dist_hr\n"
            "    km: 10.0\n"
            "    hr_low: 120\n"
            "    hr_high: 140\n"
            "    intensity: warmup\n"
        )
        replies = []
        update = self._make_update(user_id, replies, text=yaml_text)
        context = self._make_context()

        with patch("garmin_fit.telegram_bot.ensure_user_allowed", new=AsyncMock(return_value=True)), patch(
            "garmin_fit.telegram_bot._process_plan", new=AsyncMock()
        ) as process_mock:
            await telegram_bot.handle_text_message(update, context)

        state = telegram_bot.get_state(user_id)
        process_mock.assert_not_awaited()
        self.assertEqual(state.status, "awaiting_confirm")
        self.assertIsNotNone(state.yaml_text)
        self.assertIn("intensity: active", state.yaml_text)
        self.assertTrue(any("YAML plan detected" in text for text in replies))

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
