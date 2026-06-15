import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resolve_timer.runtime_support import (
    PreferencesError,
    UserPreferences,
    append_exception_log,
    load_preferences,
    save_preferences,
    write_startup_diagnostics,
)


class FakeResolve:
    def GetVersionString(self):
        return "21.0.0.48"


class RuntimeSupportTests(unittest.TestCase):
    def test_preferences_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preferences.json"

            save_preferences(path, UserPreferences("course-b", "optimal"))
            loaded = load_preferences(path)

        self.assertEqual(loaded, UserPreferences("course-b", "optimal"))

    def test_invalid_preferences_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preferences.json"
            path.write_text('{"comparison_mode": "invalid"}', encoding="utf-8")

            with self.assertRaises(PreferencesError):
                load_preferences(path)

    def test_exception_log_contains_context_and_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resolve_timer.log"
            try:
                raise RuntimeError("unexpected failure")
            except RuntimeError as exc:
                append_exception_log(path, "test operation", exc)

            text = path.read_text(encoding="utf-8")

        self.assertIn("test operation: RuntimeError: unexpected failure", text)
        self.assertIn("Traceback (most recent call last)", text)

    def test_startup_diagnostics_records_runtime_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "startup.json"

            write_startup_diagnostics(
                path,
                database_path=root / "timer_db.yaml",
                preferences_path=root / "preferences.json",
                log_path=root / "resolve_timer.log",
                resolve=FakeResolve(),
                fusion=object(),
                bmd=object(),
            )
            report = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(report["resolve_version"], "21.0.0.48")
        self.assertTrue(report["resolve_injected"])
        self.assertTrue(report["fusion_injected"])
        self.assertTrue(report["bmd_injected"])
        self.assertEqual(report["python_executable"], sys.executable)


if __name__ == "__main__":
    unittest.main()
