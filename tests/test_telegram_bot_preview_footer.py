import unittest

try:
    import garmin_fit.telegram_bot as telegram_bot
except Exception:
    telegram_bot = None


@unittest.skipIf(telegram_bot is None, "telegram_bot dependencies are unavailable")
class YamlPreviewFooterTests(unittest.TestCase):
    """TODO #7: the footer after a YAML preview must tell the user what to
    do in all three cases -- accept, fix, or cancel -- not just /build."""

    def _assert_footer_covers_all_cases(self, text: str):
        self.assertIn("/build", text)
        self.assertIn("/cancel", text)
        # some indication that resending text starts a new generation
        self.assertTrue(
            any(word in text.lower() for word in ("исправ", "corrected", "fix", "скоррект"))
        )

    def test_yaml_ready_footer_ru(self):
        self._assert_footer_covers_all_cases(telegram_bot.MSG["ru"]["yaml_ready_footer"])

    def test_yaml_ready_footer_en(self):
        self._assert_footer_covers_all_cases(telegram_bot.MSG["en"]["yaml_ready_footer"])

    def test_yaml_loaded_text_footer_ru(self):
        self._assert_footer_covers_all_cases(telegram_bot.MSG["ru"]["yaml_loaded_text_footer"])

    def test_yaml_loaded_text_footer_en(self):
        self._assert_footer_covers_all_cases(telegram_bot.MSG["en"]["yaml_loaded_text_footer"])


if __name__ == "__main__":
    unittest.main()
