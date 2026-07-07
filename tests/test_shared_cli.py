import unittest
from pathlib import Path

from garmin_fit._shared_cli import display_path


class DisplayPathTests(unittest.TestCase):
    def test_returns_relative_path_when_under_root(self):
        root = Path("C:/repo")
        path = Path("C:/repo/Plan/plan.yaml")
        self.assertEqual(display_path(path, root), str(Path("Plan/plan.yaml")))

    def test_falls_back_to_absolute_path_when_outside_root(self):
        root = Path("C:/repo")
        path = Path("C:/elsewhere/plan.yaml")
        self.assertEqual(display_path(path, root), str(path))


if __name__ == "__main__":
    unittest.main()
