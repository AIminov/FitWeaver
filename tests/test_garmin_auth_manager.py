import time
import unittest
from unittest.mock import patch

from garmin_fit.garmin_auth_manager import prompt_mfa_with_timeout


class PromptMfaWithTimeoutTests(unittest.TestCase):
    def test_returns_value_when_input_is_fast(self):
        with patch("builtins.input", return_value="123456"):
            self.assertEqual(prompt_mfa_with_timeout(timeout_sec=5), "123456")

    def test_raises_timeout_error_when_input_never_arrives(self):
        def _slow_input(_prompt):
            time.sleep(2)
            return "too-late"

        with patch("builtins.input", side_effect=_slow_input):
            with self.assertRaises(TimeoutError):
                prompt_mfa_with_timeout(timeout_sec=0.2)

    def test_empty_input_on_eof_does_not_hang_or_raise(self):
        with patch("builtins.input", side_effect=EOFError):
            self.assertEqual(prompt_mfa_with_timeout(timeout_sec=5), "")


if __name__ == "__main__":
    unittest.main()
