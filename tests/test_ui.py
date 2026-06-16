import tempfile
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resolve_timer.database import TimerDatabase
from resolve_timer.models import Course, RawMarker
from resolve_timer.service import SelectedRunInput
from resolve_timer.ui import ResolveTimerWindow, format_preview_summary, preview_selected_clip
from resolve_timer.ui_controller import ResolveTimerController


class FakeAdapter:
    def selected_run_input(self, course_id):
        return SelectedRunInput(
            course_id=course_id,
            filename="GX010123.MP4",
            source_fps=100.0,
            markers=(
                RawMarker("Start", 0),
                RawMarker("S1", 100),
                RawMarker("Finish", 300),
            ),
            clip_id="clip-1",
        )


class FakeControllerAdapter:
    def __init__(self, markers=None):
        self.markers = markers or (
            RawMarker("Start", 0),
            RawMarker("S1", 100),
            RawMarker("Finish", 300),
        )

    def selected_media_pool_run(self):
        return SimpleNamespace(
            filename="GX010123.MP4",
            source_fps=100.0,
            source_markers=self.markers,
            marker_source="source_clip",
            clip_id="clip-1",
        )

    def matching_current_timeline_video_item(self, selected):
        return SimpleNamespace(selected=selected)


class BrokenControllerAdapter:
    def selected_media_pool_run(self):
        raise TypeError("unexpected adapter result")


class FakeOverlayUpdater:
    def __init__(self):
        self.calls = []

    def update_or_create(self, timeline_item, payload):
        self.calls.append((timeline_item, payload))
        return SimpleNamespace(
            created=True,
            comp_name="Resolve Timer - course",
        )


class UiTests(unittest.TestCase):
    def test_preview_selected_clip_uses_adapter_and_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)

            preview = preview_selected_clip(
                database_path=db_path,
                course_id="course",
                adapter=FakeAdapter(),
            )

        self.assertEqual(preview.course.id, "course")
        self.assertEqual(preview.timing.lap_seconds, 3.0)

    def test_format_preview_summary_includes_history_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)
            preview = preview_selected_clip(
                database_path=db_path,
                course_id="course",
                adapter=FakeAdapter(),
            )

        summary = format_preview_summary(preview)

        self.assertIn("Course: Course", summary)
        self.assertIn("S1: 0:01.000", summary)
        self.assertIn("LAP: 0:03.000", summary)
        self.assertIn("History: no committed run", summary)

    def test_controller_initializes_read_only_preview_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)

            state = ResolveTimerController(db_path, FakeControllerAdapter()).initialize()

        self.assertIsNone(state.error)
        self.assertEqual(state.selected_course_id, "course")
        self.assertEqual(state.filename, "GX010123.MP4")
        self.assertEqual(state.marker_source, "Media Pool source clip")
        self.assertEqual(state.marker_count, 3)
        self.assertEqual(state.source_range, "Full source clip")
        self.assertEqual([row.label for row in state.timing_rows], ["S1", "S2", "LAP"])
        self.assertTrue(state.can_commit)
        self.assertFalse(state.can_update)
        self.assertTrue(state.can_update_overlay)

    def test_controller_switches_comparison_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)
            controller = ResolveTimerController(db_path, FakeControllerAdapter())
            controller.initialize()

            state = controller.set_comparison_mode("optimal")

        self.assertEqual(state.comparison_mode, "optimal")
        self.assertIsNone(state.error)

    def test_controller_restores_course_and_comparison_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "timer_db.yaml"
            preferences_path = root / "preferences.json"
            TimerDatabase(
                [
                    Course("course-a", "Course A", 2),
                    Course("course-b", "Course B", 2),
                ],
                [],
            ).save(db_path)
            first = ResolveTimerController(
                db_path,
                FakeControllerAdapter(),
                preferences_path=preferences_path,
            )
            first.initialize()
            first.select_course("course-b")
            first.set_comparison_mode("optimal")

            restored = ResolveTimerController(
                db_path,
                FakeControllerAdapter(),
                preferences_path=preferences_path,
            ).initialize()

        self.assertEqual(restored.selected_course_id, "course-b")
        self.assertEqual(restored.comparison_mode, "optimal")

    def test_controller_recovers_from_invalid_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "timer_db.yaml"
            preferences_path = root / "preferences.json"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)
            preferences_path.write_text("{invalid", encoding="utf-8")

            state = ResolveTimerController(
                db_path,
                FakeControllerAdapter(),
                preferences_path=preferences_path,
            ).initialize()

        self.assertEqual(state.selected_course_id, "course")
        self.assertIn("preferences reset", state.status)
        self.assertIn("could not read preferences", state.error)

    def test_controller_logs_unexpected_refresh_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "timer_db.yaml"
            log_path = root / "resolve_timer.log"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)

            state = ResolveTimerController(
                db_path,
                BrokenControllerAdapter(),
                log_path=log_path,
            ).initialize()
            log_text = log_path.read_text(encoding="utf-8")

        self.assertEqual(state.status, "Refresh failed")
        self.assertIn("refresh selection: TypeError", log_text)
        self.assertIn("unexpected adapter result", log_text)

    def test_mode_handler_ignores_stale_queued_event(self):
        window = ResolveTimerWindow.__new__(ResolveTimerWindow)
        window._rendering = False
        window._state = SimpleNamespace(comparison_mode="optimal")
        window.items = {"ModeCombo": SimpleNamespace(CurrentIndex=1)}
        window.controller = Mock()
        window.render = Mock()

        window._on_mode_changed({"Index": 0})

        window.controller.set_comparison_mode.assert_not_called()
        window.render.assert_not_called()

    def test_mode_handler_uses_actual_combo_index_for_user_change(self):
        window = ResolveTimerWindow.__new__(ResolveTimerWindow)
        window._rendering = False
        window._state = SimpleNamespace(comparison_mode="best_lap")
        window.items = {"ModeCombo": SimpleNamespace(CurrentIndex=1)}
        changed_state = SimpleNamespace(comparison_mode="optimal")
        window.controller = Mock()
        window.controller.set_comparison_mode.return_value = changed_state
        window.render = Mock()

        window._on_mode_changed({"Index": 0})

        window.controller.set_comparison_mode.assert_called_once_with("optimal")
        window.render.assert_called_once_with(changed_state)

    def test_controller_returns_marker_validation_error_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)
            adapter = FakeControllerAdapter(
                markers=(RawMarker("Start", 0), RawMarker("Finish", 300))
            )

            state = ResolveTimerController(db_path, adapter).initialize()

        self.assertEqual(state.status, "Refresh failed")
        self.assertIn("selected Media Pool clip GX010123.MP4", state.error)
        self.assertIn("missing marker S1", state.error)
        self.assertFalse(state.can_commit)

    def test_controller_commits_new_run_and_reloads_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)
            controller = ResolveTimerController(db_path, FakeControllerAdapter())
            controller.initialize()

            state = controller.commit_new_run()
            loaded = TimerDatabase.load(db_path)

        self.assertIsNone(state.error)
        self.assertTrue(state.status.startswith("Committed run_"))
        self.assertEqual(len(loaded.runs), 1)
        self.assertEqual(loaded.runs[0].filename, "GX010123.MP4")
        self.assertEqual(
            loaded.runs[0].marker_frames,
            {"Start": 0, "S1": 100, "Finish": 300},
        )
        self.assertFalse(state.can_commit)
        self.assertFalse(state.can_update)

    def test_controller_updates_existing_run_after_marker_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)
            adapter = FakeControllerAdapter()
            controller = ResolveTimerController(db_path, adapter)
            controller.initialize()
            committed = controller.commit_new_run()
            run_id = committed.matching_run_id
            adapter.markers = (
                RawMarker("Start", 0),
                RawMarker("S1", 120),
                RawMarker("Finish", 320),
            )
            changed = controller.refresh_selection()

            state = controller.update_existing_run(run_id)
            loaded = TimerDatabase.load(db_path)

        self.assertTrue(changed.can_update)
        self.assertEqual(state.status, f"Updated {run_id}")
        self.assertIsNone(state.error)
        self.assertEqual(len(loaded.runs), 1)
        self.assertEqual(
            loaded.runs[0].marker_frames,
            {"Start": 0, "S1": 120, "Finish": 320},
        )
        self.assertFalse(state.can_update)

    def test_controller_failed_commit_preserves_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)
            original = db_path.read_text(encoding="utf-8")
            controller = ResolveTimerController(db_path, FakeControllerAdapter())
            controller.initialize()

            with patch(
                "resolve_timer.ui_controller.TimerService.save",
                side_effect=OSError("disk unavailable"),
            ):
                state = controller.commit_new_run()

            current = db_path.read_text(encoding="utf-8")

        self.assertEqual(state.status, "Commit failed")
        self.assertIn("disk unavailable", state.error)
        self.assertEqual(current, original)

    def test_controller_ignores_and_unignores_matching_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)
            controller = ResolveTimerController(db_path, FakeControllerAdapter())
            controller.initialize()
            committed = controller.commit_new_run()
            run_id = committed.matching_run_id

            ignored = controller.set_run_ignored(run_id, True)
            ignored_run = TimerDatabase.load(db_path).runs[0]
            restored = controller.set_run_ignored(run_id, False)
            restored_run = TimerDatabase.load(db_path).runs[0]

        self.assertEqual(ignored.status, f"Ignored {run_id}")
        self.assertTrue(ignored_run.ignored)
        self.assertEqual(ignored.best_lap, "--:--.---")
        self.assertEqual(restored.status, f"Unignored {run_id}")
        self.assertFalse(restored_run.ignored)
        self.assertEqual(restored.best_lap, "0:03.000")

    def test_controller_deletes_matching_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)
            controller = ResolveTimerController(db_path, FakeControllerAdapter())
            controller.initialize()
            committed = controller.commit_new_run()
            run_id = committed.matching_run_id

            state = controller.delete_run(run_id)
            loaded = TimerDatabase.load(db_path)

        self.assertEqual(state.status, f"Deleted {run_id}")
        self.assertEqual(loaded.runs, [])
        self.assertTrue(state.can_commit)
        self.assertIsNone(state.matching_run_id)

    def test_controller_lists_selected_course_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)
            controller = ResolveTimerController(db_path, FakeControllerAdapter())
            controller.initialize()
            controller.commit_new_run()

            rows = controller.course_runs()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].filename, "GX010123.MP4")
        self.assertEqual(rows[0].lap, "0:03.000")
        self.assertTrue(rows[0].committed)
        self.assertFalse(rows[0].ignored)
        self.assertTrue(rows[0].has_clip_id)

    def test_controller_updates_static_overlay_for_matching_timeline_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)
            updater = FakeOverlayUpdater()
            controller = ResolveTimerController(
                db_path,
                FakeControllerAdapter(),
                overlay_updater=updater,
            )
            controller.initialize()
            controller.set_comparison_mode("optimal")

            state = controller.update_overlay()

        self.assertEqual(
            state.status,
            "Created live overlay Resolve Timer - course",
        )
        self.assertIsNone(state.error)
        self.assertEqual(len(updater.calls), 1)
        _timeline_item, payload = updater.calls[0]
        self.assertEqual(payload.comparison_mode, "optimal")


if __name__ == "__main__":
    unittest.main()
