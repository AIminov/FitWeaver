import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    import garmin_fit.telegram_bot as telegram_bot
except Exception:
    telegram_bot = None


@unittest.skipIf(telegram_bot is None, "telegram_bot dependencies are unavailable")
class SessionTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        telegram_bot.USER_STATES.clear()
        self._bot_config_backup = dict(telegram_bot.BOT_CONFIG)
        telegram_bot.BOT_CONFIG.clear()

    async def asyncTearDown(self):
        telegram_bot.BOT_CONFIG.clear()
        telegram_bot.BOT_CONFIG.update(self._bot_config_backup)

    @staticmethod
    def _make_update(user_id, replies, text="a plan long enough to pass the length check"):
        async def _reply_text(message):
            replies.append(message)

        return SimpleNamespace(
            effective_user=SimpleNamespace(id=user_id),
            effective_chat=SimpleNamespace(id=700 + user_id),
            message=SimpleNamespace(text=text, reply_text=_reply_text),
        )

    # ── _session_timed_out ──────────────────────────────────────────────────
    def test_never_active_is_not_a_timeout(self):
        state = telegram_bot.UserState()
        self.assertFalse(telegram_bot._session_timed_out(state))

    def test_recently_active_is_not_a_timeout(self):
        state = telegram_bot.UserState(last_active=datetime.now())
        self.assertFalse(telegram_bot._session_timed_out(state))

    def test_stale_last_active_is_a_timeout(self):
        state = telegram_bot.UserState(
            last_active=datetime.now() - timedelta(seconds=telegram_bot.DEFAULT_SESSION_TIMEOUT_SEC + 1)
        )
        self.assertTrue(telegram_bot._session_timed_out(state))

    def test_session_timeout_sec_is_configurable(self):
        telegram_bot.BOT_CONFIG["session_timeout_sec"] = 60
        state = telegram_bot.UserState(last_active=datetime.now() - timedelta(seconds=61))
        self.assertTrue(telegram_bot._session_timed_out(state))

    # ── _enforce_session ─────────────────────────────────────────────────────
    async def test_enforce_session_resets_when_not_onboarded(self):
        user_id = 5001
        state = telegram_bot.get_state(user_id)
        state.onboarded = False
        replies = []
        update = self._make_update(user_id, replies)

        reset = await telegram_bot._enforce_session(update, user_id, state)

        self.assertTrue(reset)
        self.assertTrue(any("/start" in text for text in replies))
        # a fresh UserState was installed
        self.assertIsNot(telegram_bot.get_state(user_id), state)

    async def test_enforce_session_resets_when_timed_out(self):
        user_id = 5002
        state = telegram_bot.get_state(user_id)
        state.onboarded = True
        state.last_active = datetime.now() - timedelta(seconds=telegram_bot.DEFAULT_SESSION_TIMEOUT_SEC + 1)
        replies = []
        update = self._make_update(user_id, replies)

        reset = await telegram_bot._enforce_session(update, user_id, state)

        self.assertTrue(reset)
        self.assertTrue(any("/start" in text for text in replies))

    async def test_enforce_session_passes_through_when_healthy(self):
        user_id = 5003
        state = telegram_bot.get_state(user_id)
        state.onboarded = True
        state.last_active = datetime.now()
        replies = []
        update = self._make_update(user_id, replies)

        reset = await telegram_bot._enforce_session(update, user_id, state)

        self.assertFalse(reset)
        self.assertEqual(replies, [])
        self.assertIs(telegram_bot.get_state(user_id), state)  # not reset

    async def test_enforce_session_updates_last_active_on_success(self):
        user_id = 5004
        state = telegram_bot.get_state(user_id)
        state.onboarded = True
        state.last_active = datetime.now() - timedelta(seconds=5)
        old_last_active = state.last_active
        update = self._make_update(user_id, [])

        await telegram_bot._enforce_session(update, user_id, state)

        self.assertGreater(state.last_active, old_last_active)

    # ── handle_text_message end-to-end ──────────────────────────────────────
    async def test_second_phone_without_start_gets_reset_not_processed(self):
        """Regression for TODO #6: a user who never chose a language via
        /start (state.onboarded stays False) must not have their plan text
        silently processed."""
        user_id = 5005
        state = telegram_bot.get_state(user_id)
        self.assertFalse(state.onboarded)  # default for a brand-new state
        replies = []
        update = self._make_update(user_id, replies)
        context = SimpleNamespace(bot=SimpleNamespace())

        with patch("garmin_fit.telegram_bot.ensure_user_allowed", new=AsyncMock(return_value=True)):
            await telegram_bot.handle_text_message(update, context)

        self.assertTrue(any("/start" in text for text in replies))
        self.assertEqual(telegram_bot.get_state(user_id).status, "idle")

    async def test_handle_lang_choice_marks_onboarded(self):
        user_id = 5006
        state = telegram_bot.get_state(user_id)
        self.assertFalse(state.onboarded)

        edited = []

        async def _edit_message_text(text):
            edited.append(text)

        sent = []

        async def _send_message(chat_id, text, reply_markup=None):
            sent.append(text)

        query = SimpleNamespace(
            data="lang:ru",
            from_user=SimpleNamespace(id=user_id),
            message=SimpleNamespace(chat_id=800 + user_id),
            answer=AsyncMock(),
            edit_message_text=_edit_message_text,
        )
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(bot=SimpleNamespace(send_message=_send_message))

        await telegram_bot.handle_lang_choice(update, context)

        self.assertTrue(telegram_bot.get_state(user_id).onboarded)
        self.assertIsNotNone(telegram_bot.get_state(user_id).last_active)


if __name__ == "__main__":
    unittest.main()
