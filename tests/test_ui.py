import tempfile
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resolve_timer.database import TimerDatabase
from resolve_timer.models import Course, RawMarker
from resolve_timer.service import SelectedRunInput, TimerService
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
    def __init__(
        self,
        markers=None,
        *,
        filename="GX010123.MP4",
        clip_id="clip-1",
        timeline_runs=None,
    ):
        self.markers = markers or (
            RawMarker("Start", 0),
            RawMarker("S1", 100),
            RawMarker("Finish", 300),
        )
        self.filename = filename
        self.clip_id = clip_id

        timeline_runs = list(timeline_runs or [])
        if not timeline_runs:
            timeline_runs = [
                {
                    "filename": self.filename,
                    "source_fps": 100.0,
                    "markers": self.markers,
                    "clip_id": self.clip_id,
                }
            ]
        self.timeline_items = [
            FakeTimelineItem(f"timeline-{index}", run.get("start"))
            for index, run in enumerate(timeline_runs)
        ]
        self.timeline_runs = {
            item: self._run(
                filename=run.get("filename", f"Timeline{index}.MP4"),
                source_fps=run.get("source_fps", 100.0),
                markers=run.get(
                    "markers",
                    (
                        RawMarker("Start", 0),
                        RawMarker("S1", 100),
                        RawMarker("Finish", 300),
                    ),
                ),
                clip_id=run.get("clip_id", f"timeline-clip-{index}"),
            )
            for index, (item, run) in enumerate(zip(self.timeline_items, timeline_runs))
        }
        self.current_item = self.timeline_items[0]

    def selected_media_pool_run(self):
        return self._run(
            filename=self.filename,
            source_fps=100.0,
            markers=self.markers,
            clip_id=self.clip_id,
        )

    def matching_current_timeline_video_item(self, selected):
        return SimpleNamespace(selected=selected)

    def current_timeline_video_item(self):
        return self.current_item

    def timeline_item_media_pool_run(self, timeline_item):
        return self.timeline_runs[timeline_item]

    def timeline_video_items(self):
        return tuple(self.timeline_items)

    @staticmethod
    def _run(*, filename, source_fps, markers, clip_id):
        return SimpleNamespace(
            filename=filename,
            source_fps=source_fps,
            source_markers=markers,
            marker_source="source_clip",
            clip_id=clip_id,
        )


class FakeTimelineItem:
    def __init__(self, name, start=None):
        self.name = name
        self.start = start

    def GetStart(self):
        return self.start


class TimelineOnlyAdapter(FakeControllerAdapter):
    def selected_media_pool_run(self):
        raise TypeError("no Media Pool selection")


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

    def test_controller_adds_updates_and_deletes_courses(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([], []).save(db_path)
            controller = ResolveTimerController(db_path, FakeControllerAdapter())
            initial = controller.initialize()

            added = controller.add_course("course", "Course", 2)
            rows_after_add = controller.course_rows()
            updated = controller.update_course("course", name="Renamed", sector_count=3)
            rows_after_update = controller.course_rows()
            deleted = controller.delete_course("course")
            loaded = TimerDatabase.load(db_path)

        self.assertEqual(initial.status, "No courses configured")
        self.assertEqual(added.status, "Added course course")
        self.assertIsNone(added.error)
        self.assertEqual(rows_after_add[0].course_id, "course")
        self.assertEqual(rows_after_add[0].run_count, 0)
        self.assertEqual(updated.status, "Updated course course")
        self.assertEqual(rows_after_update[0].name, "Renamed")
        self.assertEqual(rows_after_update[0].sector_count, 3)
        self.assertEqual(deleted.status, "Deleted course course")
        self.assertIsNone(deleted.selected_course_id)
        self.assertEqual(loaded.courses, [])

    def test_controller_blocks_referenced_course_mutations(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)
            controller = ResolveTimerController(db_path, FakeControllerAdapter())
            controller.initialize()
            controller.commit_new_run()

            sector_change = controller.update_course("course", sector_count=3)
            delete = controller.delete_course("course")
            rows = controller.course_rows()

        self.assertEqual(sector_change.status, "Course update failed")
        self.assertIn("cannot change sector_count", sector_change.error)
        self.assertEqual(delete.status, "Course delete failed")
        self.assertIn("cannot delete course course", delete.error)
        self.assertEqual(rows[0].run_count, 1)

    def test_courses_handler_opens_course_management_window(self):
        window = ResolveTimerWindow.__new__(ResolveTimerWindow)
        manager = Mock()
        window._course_window = None
        window.ui = object()
        window.dispatcher = object()
        window.controller = Mock()

        with patch("resolve_timer.ui.ResolveCourseManagementWindow", return_value=manager) as cls:
            window._on_courses({})

        cls.assert_called_once_with(
            window.ui,
            window.dispatcher,
            window.controller,
            window._on_courses_closed,
        )
        manager.show.assert_called_once_with()

    def test_controller_updates_current_overlay_from_timeline_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)
            timeline_markers = (
                RawMarker("Start", 0),
                RawMarker("S1", 50),
                RawMarker("Finish", 250),
            )
            adapter = FakeControllerAdapter(
                filename="Selected.MP4",
                clip_id="selected-clip",
                timeline_runs=[
                    {
                        "filename": "Timeline.MP4",
                        "source_fps": 50.0,
                        "markers": timeline_markers,
                        "clip_id": "timeline-clip",
                    }
                ],
            )
            updater = FakeOverlayUpdater()
            controller = ResolveTimerController(
                db_path,
                adapter,
                overlay_updater=updater,
            )
            controller.initialize()
            controller.comparison_mode = "optimal"
            original = db_path.read_text(encoding="utf-8")

            state = controller.update_overlay()
            current = db_path.read_text(encoding="utf-8")

        self.assertEqual(
            state.status,
            "Created live overlay for Timeline.MP4: Resolve Timer - course",
        )
        self.assertIsNone(state.error)
        self.assertEqual(current, original)
        self.assertEqual(len(updater.calls), 1)
        timeline_item, payload = updater.calls[0]
        self.assertIs(timeline_item, adapter.current_item)
        self.assertEqual(payload.marker_frames, {"Start": 0, "S1": 50, "Finish": 250})
        self.assertEqual(payload.source_fps, 50.0)
        self.assertEqual(payload.comparison_mode, "optimal")

    def test_controller_updates_all_timeline_overlays_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)
            adapter = FakeControllerAdapter(
                timeline_runs=[
                    {
                        "filename": "First.MP4",
                        "markers": (
                            RawMarker("Start", 0),
                            RawMarker("S1", 100),
                            RawMarker("Finish", 300),
                        ),
                        "clip_id": "first",
                    },
                    {
                        "filename": "Second.MP4",
                        "source_fps": 50.0,
                        "markers": (
                            RawMarker("Start", 10),
                            RawMarker("S1", 60),
                            RawMarker("Finish", 160),
                        ),
                        "clip_id": "second",
                    },
                ]
            )
            updater = FakeOverlayUpdater()
            controller = ResolveTimerController(
                db_path,
                adapter,
                overlay_updater=updater,
            )
            controller.initialize()

            state = controller.update_all_overlays()

        self.assertEqual(state.status, "Updated live overlays for 2 timeline clip(s)")
        self.assertIsNone(state.error)
        self.assertEqual([call[0] for call in updater.calls], adapter.timeline_items)
        self.assertEqual(updater.calls[0][1].marker_frames["Finish"], 300)
        self.assertEqual(updater.calls[1][1].marker_frames["Finish"], 160)
        self.assertEqual(updater.calls[1][1].source_fps, 50.0)

    def test_controller_update_all_overlays_uses_chronological_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            course = Course("course", "Course", 2)
            baseline_markers = (
                RawMarker("Start", 0),
                RawMarker("S1", 100),
                RawMarker("Finish", 320),
            )
            first_markers = (
                RawMarker("Start", 0),
                RawMarker("S1", 100),
                RawMarker("Finish", 300),
            )
            second_markers = (
                RawMarker("Start", 0),
                RawMarker("S1", 95),
                RawMarker("Finish", 290),
            )
            third_markers = (
                RawMarker("Start", 0),
                RawMarker("S1", 90),
                RawMarker("Finish", 280),
            )
            service = TimerService(TimerDatabase([course], []))
            for run_id, filename, markers, clip_id in (
                ("baseline", "Baseline.MP4", baseline_markers, "baseline"),
                ("first", "First.MP4", first_markers, "first"),
                ("second", "Second.MP4", second_markers, "second"),
                ("third", "Third.MP4", third_markers, "third"),
            ):
                service.commit_new_run(
                    SelectedRunInput(
                        course_id="course",
                        filename=filename,
                        source_fps=100.0,
                        markers=markers,
                        clip_id=clip_id,
                    ),
                    run_id=run_id,
                )
            service.save(db_path)
            adapter = FakeControllerAdapter(
                timeline_runs=[
                    {
                        "filename": "Third.MP4",
                        "markers": third_markers,
                        "clip_id": "third",
                        "start": 30,
                    },
                    {
                        "filename": "First.MP4",
                        "markers": first_markers,
                        "clip_id": "first",
                        "start": 10,
                    },
                    {
                        "filename": "Second.MP4",
                        "markers": second_markers,
                        "clip_id": "second",
                        "start": 20,
                    },
                ]
            )
            updater = FakeOverlayUpdater()
            controller = ResolveTimerController(
                db_path,
                adapter,
                overlay_updater=updater,
            )
            controller.initialize()

            state = controller.update_all_overlays()

        self.assertEqual(state.status, "Updated live overlays for 3 timeline clip(s)")
        self.assertIsNone(state.error)
        self.assertEqual(
            [payload.best_lap_seconds for _item, payload in updater.calls],
            [3.2, 3.0, 2.9],
        )
        self.assertEqual(
            [payload.marker_frames["Finish"] for _item, payload in updater.calls],
            [300, 290, 280],
        )

    def test_controller_update_all_reports_skipped_timeline_clips(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)
            adapter = FakeControllerAdapter(
                timeline_runs=[
                    {
                        "filename": "Good.MP4",
                        "markers": (
                            RawMarker("Start", 0),
                            RawMarker("S1", 100),
                            RawMarker("Finish", 300),
                        ),
                    },
                    {
                        "filename": "Bad.MP4",
                        "markers": (RawMarker("Start", 0), RawMarker("Finish", 300)),
                    },
                ]
            )
            updater = FakeOverlayUpdater()
            controller = ResolveTimerController(
                db_path,
                adapter,
                overlay_updater=updater,
            )
            controller.initialize()

            state = controller.update_all_overlays()

        self.assertEqual(state.status, "Updated live overlays for 1 timeline clip(s); skipped 1")
        self.assertIn("Bad.MP4", state.error)
        self.assertIn("missing marker S1", state.error)
        self.assertEqual(len(updater.calls), 1)

    def test_controller_commits_timeline_runs_in_timeline_start_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            service = TimerService(TimerDatabase([Course("course", "Course", 2)], []))
            service.commit_new_run(
                SelectedRunInput(
                    course_id="course",
                    filename="Baseline.MP4",
                    source_fps=100.0,
                    markers=(
                        RawMarker("Start", 0),
                        RawMarker("S1", 100),
                        RawMarker("Finish", 320),
                    ),
                    clip_id="baseline",
                ),
                run_id="baseline",
            )
            service.save(db_path)
            adapter = FakeControllerAdapter(
                timeline_runs=[
                    {
                        "filename": "Third.MP4",
                        "markers": (
                            RawMarker("Start", 0),
                            RawMarker("S1", 90),
                            RawMarker("Finish", 280),
                        ),
                        "clip_id": "third",
                        "start": 30,
                    },
                    {
                        "filename": "First.MP4",
                        "markers": (
                            RawMarker("Start", 0),
                            RawMarker("S1", 100),
                            RawMarker("Finish", 300),
                        ),
                        "clip_id": "first",
                        "start": 10,
                    },
                    {
                        "filename": "Second.MP4",
                        "markers": (
                            RawMarker("Start", 0),
                            RawMarker("S1", 95),
                            RawMarker("Finish", 290),
                        ),
                        "clip_id": "second",
                        "start": 20,
                    },
                ]
            )
            controller = ResolveTimerController(db_path, adapter)
            controller.initialize()

            state = controller.commit_update_timeline_runs()
            loaded = TimerDatabase.load(db_path)

        self.assertEqual(
            state.status,
            "Timeline runs: committed 3, updated 0, unchanged 0, skipped 0, failed 0",
        )
        self.assertIsNone(state.error)
        self.assertEqual(
            [run.filename for run in loaded.runs],
            ["Baseline.MP4", "First.MP4", "Second.MP4", "Third.MP4"],
        )
        self.assertFalse(any(run.ignored for run in loaded.runs[1:]))

    def test_controller_timeline_batch_reports_skipped_invalid_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)
            adapter = FakeControllerAdapter(
                timeline_runs=[
                    {
                        "filename": "Good.MP4",
                        "markers": (
                            RawMarker("Start", 0),
                            RawMarker("S1", 100),
                            RawMarker("Finish", 300),
                        ),
                    },
                    {
                        "filename": "Bad.MP4",
                        "markers": (RawMarker("Start", 0), RawMarker("Finish", 300)),
                    },
                ]
            )
            controller = ResolveTimerController(db_path, adapter)
            controller.initialize()

            state = controller.commit_update_timeline_runs()

        self.assertEqual(
            state.status,
            "Timeline runs: committed 1, updated 0, unchanged 0, skipped 1, failed 0",
        )
        self.assertIn("Bad.MP4", state.error)
        self.assertIn("missing marker S1", state.error)

    def test_current_overlay_does_not_require_media_pool_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)
            updater = FakeOverlayUpdater()
            controller = ResolveTimerController(
                db_path,
                TimelineOnlyAdapter(),
                overlay_updater=updater,
            )

            initial = controller.initialize()
            state = controller.update_overlay()

        self.assertEqual(initial.status, "Refresh failed")
        self.assertTrue(initial.can_update_overlay)
        self.assertEqual(
            state.status,
            "Created live overlay for GX010123.MP4: Resolve Timer - course",
        )
        self.assertIsNone(state.error)
        self.assertEqual(len(updater.calls), 1)

    def test_summary_export_does_not_require_media_pool_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            output_path = Path(tmp) / "summary.png"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)
            controller = ResolveTimerController(db_path, TimelineOnlyAdapter())

            initial = controller.initialize()
            state = controller.export_course_summary_card(output_path)
            output_exists = output_path.exists()

        self.assertEqual(initial.status, "Refresh failed")
        self.assertTrue(initial.can_export_summary)
        self.assertEqual(state.status, f"Exported course summary PNG: {output_path}")
        self.assertIsNone(state.error)
        self.assertTrue(output_exists)

    def test_overlay_all_handler_calls_controller(self):
        window = ResolveTimerWindow.__new__(ResolveTimerWindow)
        state = SimpleNamespace(status="updated")
        window.controller = Mock()
        window.controller.update_all_overlays.return_value = state
        window.render = Mock()

        window._on_overlay_all({})

        window.controller.update_all_overlays.assert_called_once_with()
        window.render.assert_called_once_with(state)

    def test_timeline_runs_handler_calls_controller(self):
        window = ResolveTimerWindow.__new__(ResolveTimerWindow)
        state = SimpleNamespace(status="timeline")
        window.controller = Mock()
        window.controller.commit_update_timeline_runs.return_value = state
        window.render = Mock()

        window._on_timeline_runs({})

        window.controller.commit_update_timeline_runs.assert_called_once_with()
        window.render.assert_called_once_with(state)

    def test_summary_export_handler_calls_controller(self):
        window = ResolveTimerWindow.__new__(ResolveTimerWindow)
        state = SimpleNamespace(status="exported")
        window.controller = Mock()
        window.controller.export_course_summary_card.return_value = state
        window.render = Mock()

        window._on_summary_export({})

        window.controller.export_course_summary_card.assert_called_once_with()
        window.render.assert_called_once_with(state)


if __name__ == "__main__":
    unittest.main()
