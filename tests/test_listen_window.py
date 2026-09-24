import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from function.listen_window import CHINA_TIME, current_window_end, main, parse_listen_windows


class ListenWindowTests(unittest.TestCase):
    def test_multiline_weekly_windows_use_china_time(self):
        windows = parse_listen_windows(
            "MON=08:00-10:00,14:00-16:00\nTUE=09:30-11:30"
        )
        monday_utc = datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc)
        end = current_window_end(windows, monday_utc)

        self.assertEqual(datetime(2026, 9, 28, 10, 0, tzinfo=CHINA_TIME), end)
        self.assertIsNone(current_window_end(
            windows, datetime(2026, 9, 28, 3, 0, tzinfo=timezone.utc)
        ))

    def test_semicolon_entries_and_exact_end_boundary(self):
        windows = parse_listen_windows("MON=08:00-10:00;TUE=09:30-11:30")

        self.assertIsNone(current_window_end(
            windows, datetime(2026, 9, 28, 10, 0, tzinfo=CHINA_TIME)
        ))
        self.assertEqual(datetime(2026, 9, 29, 11, 30, tzinfo=CHINA_TIME),
                         current_window_end(
                             windows, datetime(2026, 9, 29, 9, 30, tzinfo=CHINA_TIME)
                         ))

    def test_invalid_or_overlapping_windows_are_rejected(self):
        for value in (
            "MON=8:00-10:00",
            "MON=10:00-08:00",
            "MON=08:00-10:00,09:00-11:00",
            "MON=24:00-25:00",
            "MON=08:00-14:00",
            "FUNDAY=08:00-10:00",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_listen_windows(value)

    def test_empty_configuration_is_inactive(self):
        self.assertIsNone(current_window_end(parse_listen_windows("")))

    def test_github_gate_writes_only_active_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = os.path.join(directory, "github_output")
            with mock.patch.dict(os.environ, {
                "LISTEN_WINDOWS": "MON=08:00-10:00",
                "GITHUB_OUTPUT": output_path,
            }), mock.patch("function.listen_window.current_window_end", return_value=object()):
                main()
            with open(output_path, encoding="utf-8") as output:
                self.assertEqual("active=true\n", output.read())

    def test_github_gate_without_secret_is_inactive(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = os.path.join(directory, "github_output")
            with mock.patch.dict(os.environ, {
                "LISTEN_WINDOWS": "",
                "GITHUB_OUTPUT": output_path,
            }):
                main()
            with open(output_path, encoding="utf-8") as output:
                self.assertEqual("active=false\n", output.read())


if __name__ == "__main__":
    unittest.main()
