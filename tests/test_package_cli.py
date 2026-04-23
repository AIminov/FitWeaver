import unittest


class PackageCliTests(unittest.TestCase):
    def test_package_imports_from_src(self):
        import garmin_fit

        self.assertEqual(garmin_fit.__version__, "0.1.0")

    def test_primary_cli_parser_exposes_supported_subcommands(self):
        from garmin_fit.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["run", "--validate-mode", "strict"])
        self.assertEqual(args.command, "run")
        self.assertEqual(args.validate_mode, "strict")

        args = parser.parse_args(["doctor", "--llm"])
        self.assertEqual(args.command, "doctor")
        self.assertTrue(args.llm)

        args = parser.parse_args(
            [
                "garmin-calendar-delete",
                "--year",
                "2026",
                "--from-date",
                "2026-06-01",
                "--to-date",
                "2026-06-30",
                "--dry-run",
            ]
        )
        self.assertEqual(args.command, "garmin-calendar-delete")
        self.assertEqual(args.year, 2026)
        self.assertEqual(args.from_date, "2026-06-01")
        self.assertEqual(args.to_date, "2026-06-30")
        self.assertTrue(args.dry_run)

    def test_legacy_cli_parser_exposes_legacy_subcommands(self):
        from garmin_fit.legacy_cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["compare", "--validate-mode", "soft"])
        self.assertEqual(args.command, "compare")
        self.assertEqual(args.validate_mode, "soft")

    def test_validate_cli_parser_accepts_plan(self):
        from garmin_fit.validate_cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["--plan", "Plan/plan.yaml"])
        self.assertEqual(args.plan, "Plan/plan.yaml")
