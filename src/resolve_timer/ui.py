from __future__ import annotations

from pathlib import Path

from .resolve_adapter import ResolveAdapter, ResolveAdapterError
from .runtime_support import append_exception_log, write_startup_diagnostics
from .service import RunPreview, TimerService
from .timing import format_delta, format_duration
from .ui_controller import ResolveTimerController, ResolveTimerViewState


def default_database_path() -> Path:
    return Path.cwd() / "timer_db.yaml"


def preview_selected_clip(
    *,
    database_path: str | Path,
    course_id: str,
    adapter: ResolveAdapter | None = None,
) -> RunPreview:
    service = TimerService.load(database_path)
    resolve_adapter = adapter or ResolveAdapter()
    selected = resolve_adapter.selected_run_input(course_id)
    return service.preview(selected)


def format_preview_summary(preview: RunPreview, comparison_mode: str = "best_lap") -> str:
    lines = [f"Course: {preview.course.name}"]
    for row in preview.comparison_rows(comparison_mode):
        if row.delta_seconds is None:
            lines.append(f"{row.label}: {format_duration(row.duration_seconds)}")
        else:
            lines.append(
                f"{row.label}: {format_duration(row.duration_seconds)} ({format_delta(row.delta_seconds)})"
            )
    if preview.stats.best_lap:
        lines.append(
            f"Best: {_format_summary_stat(preview.stats.best_lap.timing.lap_seconds, preview.best_lap_delta)}"
        )
    if preview.stats.optimal_seconds is not None:
        lines.append(
            f"Optimal: {_format_summary_stat(preview.stats.optimal_seconds, preview.optimal_lap_delta)}"
        )
    if preview.matching_run:
        state = "changed" if preview.has_marker_changes else "matched"
        lines.append(f"History: {state} {preview.matching_run.id}")
    else:
        lines.append("History: no committed run")
    return "\n".join(lines)


def _format_summary_stat(seconds: float, delta_seconds: float | None) -> str:
    value = format_duration(seconds)
    if delta_seconds is not None:
        value = f"{value} ({format_delta(delta_seconds)})"
    return value


def run_interactive_tool(
    database_path: str | Path | None = None,
    *,
    resolve: object | None = None,
    fusion: object | None = None,
    bmd: object | None = None,
    preferences_path: str | Path | None = None,
    log_path: str | Path | None = None,
    diagnostics_path: str | Path | None = None,
) -> None:
    """Launch the Resolve Timer UI."""
    db_path = Path(database_path) if database_path else default_database_path()
    preferences = (
        Path(preferences_path)
        if preferences_path is not None
        else db_path.with_name("resolve_timer_preferences.json")
    )
    log = Path(log_path) if log_path is not None else db_path.with_name("resolve_timer.log")
    diagnostics = (
        Path(diagnostics_path)
        if diagnostics_path is not None
        else db_path.with_name("resolve_timer_startup.json")
    )
    try:
        write_startup_diagnostics(
            diagnostics,
            database_path=db_path,
            preferences_path=preferences,
            log_path=log,
            resolve=resolve,
            fusion=fusion,
            bmd=bmd,
        )
    except Exception as exc:
        append_exception_log(log, "write startup diagnostics", exc)

    try:
        adapter = ResolveAdapter(resolve)
        if fusion is None:
            raise ResolveAdapterError("Resolve did not inject the fusion scripting object")
        if bmd is None:
            raise ResolveAdapterError("Resolve did not inject the bmd scripting object")

        ui = getattr(fusion, "UIManager", None)
        dispatcher_factory = getattr(bmd, "UIDispatcher", None)
        if ui is None or not callable(dispatcher_factory):
            raise ResolveAdapterError("Resolve UI Manager or UIDispatcher is unavailable")

        controller = ResolveTimerController(
            db_path,
            adapter,
            preferences_path=preferences,
            log_path=log,
        )
        window = ResolveTimerWindow(ui, dispatcher_factory(ui), controller)
        window.run()
    except Exception as exc:
        append_exception_log(log, "interactive tool", exc)
        raise


class ResolveTimerWindow:
    def __init__(self, ui: object, dispatcher: object, controller: ResolveTimerController):
        self.ui = ui
        self.dispatcher = dispatcher
        self.controller = controller
        self._rendering = False
        self._course_ids: list[str] = []
        self._mode_combo_initialized = False
        self._state: ResolveTimerViewState | None = None
        self._pending_update_run_id: str | None = None
        self._pending_delete_run_id: str | None = None
        self._manage_window: ResolveRunManagementWindow | None = None
        self._course_window: ResolveCourseManagementWindow | None = None
        self.window = self._build_window()
        self.items = self.window.GetItems()
        self._configure_timing_table()
        self._bind_events()

    def run(self) -> None:
        self.render(self.controller.initialize())
        self.window.Show()
        self.dispatcher.RunLoop()
        self.window.Hide()

    def _build_window(self):
        ui = self.ui
        section_label_style = (
            "QLabel { border: 1px solid #777; padding: 6px; "
            "border-radius: 4px; background-color: #2c2c2c; }"
        )

        def section_label(text: str):
            return ui.Label(
                {
                    "Text": text,
                    "Font": {"Bold": True},
                    "MinimumSize": [220, 34],
                    "StyleSheet": section_label_style,
                    "Weight": 0,
                }
            )

        return self.dispatcher.AddWindow(
            {
                "ID": "ResolveTimerWindow",
                "WindowTitle": "Resolve Timer",
                "Geometry": [180, 100, 860, 680],
            },
            ui.VGroup(
                {"Spacing": 8, "Weight": 1},
                [
                    ui.HGroup(
                        {"Weight": 0, "Spacing": 6},
                        [
                            ui.Label(
                                {
                                    "Text": "Course",
                                    "FixedSize": [55, 28],
                                    "Alignment": {"AlignVCenter": True},
                                    "Weight": 0,
                                }
                            ),
                            ui.ComboBox(
                                {
                                    "ID": "CourseCombo",
                                    "FixedSize": [240, 28],
                                    "Weight": 0,
                                }
                            ),
                            ui.Button(
                                {
                                    "ID": "CoursesButton",
                                    "Text": "Courses",
                                    "FixedSize": [82, 28],
                                    "Weight": 0,
                                }
                            ),
                            ui.Label(
                                {
                                    "Text": "Compare",
                                    "FixedSize": [65, 28],
                                    "Alignment": {"AlignVCenter": True},
                                    "Weight": 0,
                                }
                            ),
                            ui.ComboBox(
                                {
                                    "ID": "ModeCombo",
                                    "FixedSize": [120, 28],
                                    "Weight": 0,
                                }
                            ),
                            ui.HGap(0, 1),
                        ],
                    ),
                    ui.VGroup(
                        {"Weight": 0, "Spacing": 4},
                        [
                            section_label("Media Pool Preview"),
                            ui.Label(
                                {
                                    "Text": (
                                        "Selected Media Pool clip controls preview "
                                        "and database actions."
                                    ),
                                    "WordWrap": True,
                                    "Weight": 0,
                                }
                            ),
                            ui.Label(
                                {
                                    "ID": "ClipLabel",
                                    "Text": "No valid selection",
                                    "Font": {"Bold": True},
                                    "Weight": 0,
                                }
                            ),
                            ui.Label({"ID": "ClipDetailLabel", "Text": "", "Weight": 0}),
                            ui.Label({"ID": "MarkerLabel", "Text": "", "Weight": 0}),
                            ui.HGroup(
                                {"Weight": 0, "Spacing": 6},
                                [
                                    ui.Button(
                                        {
                                            "ID": "RefreshButton",
                                            "Text": "Refresh Preview",
                                            "Weight": 0,
                                        }
                                    ),
                                    ui.HGap(0, 1),
                                ],
                            ),
                        ],
                    ),
                    ui.VGroup(
                        {"Weight": 1, "Spacing": 3},
                        [
                            section_label("Preview Timing"),
                            ui.Tree(
                                {
                                    "ID": "TimingTree",
                                    "Weight": 1,
                                    "ColumnCount": 4,
                                    "HeaderHidden": False,
                                    "RootIsDecorated": False,
                                    "ItemsExpandable": False,
                                    "SortingEnabled": False,
                                    "AlternatingRowColors": True,
                                    "SelectionMode": "NoSelection",
                                    "UniformRowHeights": True,
                                    "HorizontalScrollMode": "ScrollPerPixel",
                                    "VerticalScrollMode": "ScrollPerPixel",
                                }
                            ),
                        ],
                    ),
                    ui.VGroup(
                        {"Weight": 0, "Spacing": 4},
                        [
                            section_label("Media Pool History"),
                            ui.Label({"ID": "HistoryLabel", "Text": "-"}),
                            ui.Label({"ID": "StatsLabel", "Text": ""}),
                            ui.HGroup(
                                {"Weight": 0, "Spacing": 6},
                                [
                                    ui.Button(
                                        {
                                            "ID": "SummaryExportButton",
                                            "Text": "Export Course Summary PNG",
                                            "Weight": 0,
                                        }
                                    ),
                                    ui.HGap(0, 1),
                                ],
                            ),
                        ],
                    ),
                    ui.HGroup(
                        {"Weight": 0, "Spacing": 6},
                        [
                            ui.Button({"ID": "CommitButton", "Text": "Commit New Run"}),
                            ui.Button({"ID": "UpdateButton", "Text": "Update Existing"}),
                            ui.Button({"ID": "IgnoreButton", "Text": "Ignore Run"}),
                            ui.Button({"ID": "DeleteButton", "Text": "Delete Run"}),
                            ui.Button({"ID": "ManageButton", "Text": "Manage Runs"}),
                            ui.Button(
                                {
                                    "ID": "CancelUpdateButton",
                                    "Text": "Cancel",
                                    "Visible": False,
                                }
                            ),
                            ui.Button(
                                {
                                    "ID": "ConfirmUpdateButton",
                                    "Text": "Confirm Update",
                                    "Visible": False,
                                }
                            ),
                            ui.Button(
                                {
                                    "ID": "CancelDeleteButton",
                                    "Text": "Cancel",
                                    "Visible": False,
                                }
                            ),
                            ui.Button(
                                {
                                    "ID": "ConfirmDeleteButton",
                                    "Text": "Confirm Delete",
                                    "Visible": False,
                                }
                            ),
                        ],
                    ),
                    ui.VGroup(
                        {"Weight": 0, "Spacing": 4},
                        [
                            section_label("Timeline Overlay"),
                            ui.Label(
                                {
                                    "Text": (
                                        "Reads markers from timeline clip source media. "
                                        "The preview table above is not used."
                                    ),
                                    "WordWrap": True,
                                    "Weight": 0,
                                }
                            ),
                            ui.HGroup(
                                {"Weight": 0, "Spacing": 6},
                                [
                                    ui.Button(
                                        {
                                            "ID": "OverlayButton",
                                            "Text": "Update Clip Under Playhead",
                                        }
                                    ),
                                    ui.Button(
                                        {
                                            "ID": "OverlayAllButton",
                                            "Text": "Update All Timeline Clips",
                                        }
                                    ),
                                    ui.Button(
                                        {
                                            "ID": "TimelineRunsButton",
                                            "Text": "Commit/Update Timeline Runs",
                                        }
                                    ),
                                    ui.HGap(0, 1),
                                ],
                            ),
                        ],
                    ),
                    ui.Group(
                        {"Title": "Activity", "Weight": 0},
                        [
                            ui.VGroup(
                                {"Spacing": 3, "Weight": 0},
                                [
                                    ui.Label(
                                        {
                                            "ID": "StatusLabel",
                                            "Text": "Starting...",
                                            "WordWrap": True,
                                            "Font": {"Bold": True},
                                            "Weight": 0,
                                        }
                                    ),
                                    ui.TextEdit(
                                        {
                                            "ID": "ErrorText",
                                            "ReadOnly": True,
                                            "Visible": False,
                                            "MinimumSize": [0, 48],
                                            "MaximumSize": [16777215, 70],
                                            "Weight": 0,
                                        }
                                    ),
                                    ui.Label(
                                        {
                                            "ID": "DatabaseLabel",
                                            "Text": "",
                                            "WordWrap": True,
                                            "Weight": 0,
                                        }
                                    ),
                                ],
                            )
                        ],
                    ),
                ],
            ),
        )

    def _bind_events(self) -> None:
        self.window.On.ResolveTimerWindow.Close = self._on_close
        self.window.On.RefreshButton.Clicked = self._on_refresh
        self.window.On.CommitButton.Clicked = self._on_commit
        self.window.On.UpdateButton.Clicked = self._on_update
        self.window.On.IgnoreButton.Clicked = self._on_ignore
        self.window.On.DeleteButton.Clicked = self._on_delete
        self.window.On.CancelUpdateButton.Clicked = self._on_cancel_update
        self.window.On.ConfirmUpdateButton.Clicked = self._on_confirm_update
        self.window.On.CancelDeleteButton.Clicked = self._on_cancel_delete
        self.window.On.ConfirmDeleteButton.Clicked = self._on_confirm_delete
        self.window.On.ManageButton.Clicked = self._on_manage
        self.window.On.CoursesButton.Clicked = self._on_courses
        self.window.On.SummaryExportButton.Clicked = self._on_summary_export
        self.window.On.OverlayButton.Clicked = self._on_overlay
        self.window.On.OverlayAllButton.Clicked = self._on_overlay_all
        self.window.On.TimelineRunsButton.Clicked = self._on_timeline_runs
        self.window.On.CourseCombo.CurrentIndexChanged = self._on_course_changed
        self.window.On.ModeCombo.CurrentIndexChanged = self._on_mode_changed

    def _configure_timing_table(self) -> None:
        tree = self.items["TimingTree"]
        tree.SetHeaderLabels(["Row", "Current", "Reference", "Delta"])
        tree.ColumnWidth[0] = 100
        tree.ColumnWidth[1] = 170
        tree.ColumnWidth[2] = 190
        tree.ColumnWidth[3] = 140

    def render(self, state: ResolveTimerViewState) -> None:
        self._state = state
        self._rendering = True
        try:
            self._render_combos(state)
            self.items["ClipLabel"].Text = state.filename
            self.items["ClipDetailLabel"].Text = (
                f"FPS: {state.source_fps}    Scope: {state.source_range}"
            )
            self.items["MarkerLabel"].Text = (
                f"Markers: {state.marker_count}    Source: {state.marker_source}"
            )
            self._render_timing_table(state)
            self.items["HistoryLabel"].Text = state.history_status
            self.items["StatsLabel"].Text = (
                f"Best lap: {state.best_lap}    Optimal: {state.optimal_lap}"
            )
            error_text = self.items["ErrorText"]
            error_text.Visible = state.error is not None
            error_text.PlainText = "" if state.error is None else f"Error: {state.error}"
            self.items["DatabaseLabel"].Text = f"Database: {state.database_path}"
            self.items["StatusLabel"].Text = state.status
            self.items["CommitButton"].Enabled = state.can_commit
            self.items["UpdateButton"].Enabled = state.can_update
            self.items["IgnoreButton"].Enabled = state.can_toggle_ignored
            self.items["IgnoreButton"].Text = (
                "Unignore Run"
                if state.history_status.startswith("Matched ignored run")
                else "Ignore Run"
            )
            self.items["DeleteButton"].Enabled = state.can_delete
            self.items["ManageButton"].Enabled = bool(state.selected_course_id)
            self.items["CoursesButton"].Enabled = True
            self.items["SummaryExportButton"].Enabled = state.can_export_summary
            self.items["OverlayButton"].Enabled = state.can_update_overlay
            self.items["OverlayAllButton"].Enabled = state.can_update_overlay
            self.items["TimelineRunsButton"].Enabled = state.can_update_overlay
            if not state.can_update:
                self._hide_update_confirmation()
            if not state.can_delete:
                self._hide_delete_confirmation()
        finally:
            self._rendering = False
            self.window.RecalcLayout()

    def _render_timing_table(self, state: ResolveTimerViewState) -> None:
        tree = self.items["TimingTree"]
        tree.Clear()

        mono_font = {
            "Family": "Consolas",
            "PixelSize": 13,
            "MonoSpaced": True,
        }
        right_alignment = {"AlignRight": True, "AlignVCenter": True}
        for row in state.timing_rows:
            item = tree.NewItem()
            values = (row.label, row.duration, row.reference, row.delta)
            for column, value in enumerate(values):
                item.Text[column] = value
                item.Font[column] = mono_font
                if column > 0:
                    item.TextAlignment[column] = right_alignment
            tree.AddTopLevelItem(item)

    def _render_combos(self, state: ResolveTimerViewState) -> None:
        course_combo = self.items["CourseCombo"]
        if self._course_ids != [course_id for course_id, _ in state.courses]:
            course_combo.Clear()
            self._course_ids = []
            for course_id, name in state.courses:
                course_combo.AddItem(name)
                self._course_ids.append(course_id)
        if state.selected_course_id in self._course_ids:
            course_index = self._course_ids.index(state.selected_course_id)
            if int(course_combo.CurrentIndex) != course_index:
                course_combo.CurrentIndex = course_index

        mode_combo = self.items["ModeCombo"]
        if not self._mode_combo_initialized:
            mode_combo.AddItem("Best Lap")
            mode_combo.AddItem("Optimal")
            self._mode_combo_initialized = True
        mode_index = 0 if state.comparison_mode == "best_lap" else 1
        if int(mode_combo.CurrentIndex) != mode_index:
            mode_combo.CurrentIndex = mode_index

    def _on_close(self, _event) -> None:
        self.dispatcher.ExitLoop()

    def _on_refresh(self, _event) -> None:
        self.render(self.controller.refresh_selection())

    def _on_commit(self, _event) -> None:
        self.render(self.controller.commit_new_run())

    def _on_update(self, _event) -> None:
        state = self._state
        if state is None or not state.matching_run_id:
            return
        self._pending_update_run_id = state.matching_run_id
        self.items["StatusLabel"].Text = (
            f"Confirm replacing marker data for {state.matching_run_id}."
        )
        self.items["UpdateButton"].Enabled = False
        self.items["UpdateButton"].Visible = False
        self.items["CancelUpdateButton"].Visible = True
        self.items["ConfirmUpdateButton"].Visible = True
        self.window.RecalcLayout()

    def _on_ignore(self, _event) -> None:
        state = self._state
        if state is None or not state.matching_run_id:
            return
        ignored = not state.history_status.startswith("Matched ignored run")
        self.render(self.controller.set_run_ignored(state.matching_run_id, ignored))

    def _on_delete(self, _event) -> None:
        state = self._state
        if state is None or not state.matching_run_id:
            return
        self._pending_delete_run_id = state.matching_run_id
        self.items["StatusLabel"].Text = f"Confirm deleting {state.matching_run_id}."
        self.items["DeleteButton"].Visible = False
        self.items["CancelDeleteButton"].Visible = True
        self.items["ConfirmDeleteButton"].Visible = True
        self.window.RecalcLayout()

    def _on_cancel_delete(self, _event) -> None:
        self._hide_delete_confirmation()

    def _on_confirm_delete(self, _event) -> None:
        run_id = self._pending_delete_run_id
        self._hide_delete_confirmation()
        if run_id:
            self.render(self.controller.delete_run(run_id))

    def _on_manage(self, _event) -> None:
        if self._manage_window is not None:
            self._manage_window.show()
            return
        self._manage_window = ResolveRunManagementWindow(
            self.ui,
            self.dispatcher,
            self.controller,
            self._on_manage_closed,
        )
        self._manage_window.show()

    def _on_manage_closed(self, state: ResolveTimerViewState) -> None:
        self._manage_window = None
        self.render(state)

    def _on_courses(self, _event) -> None:
        if self._course_window is not None:
            self._course_window.show()
            return
        self._course_window = ResolveCourseManagementWindow(
            self.ui,
            self.dispatcher,
            self.controller,
            self._on_courses_closed,
        )
        self._course_window.show()

    def _on_courses_closed(self, state: ResolveTimerViewState) -> None:
        self._course_window = None
        self.render(state)

    def _on_overlay(self, _event) -> None:
        self.render(self.controller.update_overlay())

    def _on_overlay_all(self, _event) -> None:
        self.render(self.controller.update_all_overlays())

    def _on_timeline_runs(self, _event) -> None:
        self.render(self.controller.commit_update_timeline_runs())

    def _on_summary_export(self, _event) -> None:
        self.render(self.controller.export_course_summary_card())

    def _on_cancel_update(self, _event) -> None:
        self._hide_update_confirmation()

    def _on_confirm_update(self, _event) -> None:
        run_id = self._pending_update_run_id
        self._hide_update_confirmation()
        if run_id:
            self.render(self.controller.update_existing_run(run_id))

    def _hide_update_confirmation(self) -> None:
        self._pending_update_run_id = None
        self.items["CancelUpdateButton"].Visible = False
        self.items["ConfirmUpdateButton"].Visible = False
        self.items["UpdateButton"].Visible = True
        if self._state is not None:
            self.items["UpdateButton"].Enabled = self._state.can_update
            self.items["StatusLabel"].Text = self._state.status
        self.window.RecalcLayout()

    def _hide_delete_confirmation(self) -> None:
        self._pending_delete_run_id = None
        self.items["CancelDeleteButton"].Visible = False
        self.items["ConfirmDeleteButton"].Visible = False
        self.items["DeleteButton"].Visible = True
        if self._state is not None:
            self.items["DeleteButton"].Enabled = self._state.can_delete
            self.items["StatusLabel"].Text = self._state.status
        self.window.RecalcLayout()

    def _on_course_changed(self, event) -> None:
        if self._rendering or not self._course_ids:
            return
        index = int(self.items["CourseCombo"].CurrentIndex)
        if 0 <= index < len(self._course_ids):
            course_id = self._course_ids[index]
            if self._state is None or course_id != self._state.selected_course_id:
                self.render(self.controller.select_course(course_id))

    def _on_mode_changed(self, event) -> None:
        if self._rendering:
            return
        index = int(self.items["ModeCombo"].CurrentIndex)
        mode = "best_lap" if index == 0 else "optimal"
        if self._state is None or mode != self._state.comparison_mode:
            self.render(self.controller.set_comparison_mode(mode))


class ResolveCourseManagementWindow:
    def __init__(self, ui, dispatcher, controller, on_close):
        self.ui = ui
        self.dispatcher = dispatcher
        self.controller = controller
        self.on_close = on_close
        self.selected_course_id: str | None = None
        self.pending_delete_course_id: str | None = None
        self.rows = ()
        self.window = self._build_window()
        self.items = self.window.GetItems()
        self._configure_table()
        self._bind_events()

    def _build_window(self):
        return self.dispatcher.AddWindow(
            {
                "ID": "ResolveTimerCoursesWindow",
                "WindowTitle": "Resolve Timer - Manage Courses",
                "Geometry": [260, 160, 760, 500],
            },
            self.ui.VGroup(
                {"Spacing": 8},
                [
                    self.ui.Tree(
                        {
                            "ID": "CoursesTree",
                            "Weight": 1,
                            "ColumnCount": 4,
                            "HeaderHidden": False,
                            "RootIsDecorated": False,
                            "ItemsExpandable": False,
                            "SortingEnabled": False,
                            "SelectionMode": "SingleSelection",
                        }
                    ),
                    self.ui.HGroup(
                        {"Weight": 0, "Spacing": 6},
                        [
                            self.ui.Label(
                                {
                                    "Text": "ID",
                                    "FixedSize": [50, 26],
                                    "Alignment": {"AlignVCenter": True},
                                }
                            ),
                            self.ui.LineEdit(
                                {
                                    "ID": "CourseIdEdit",
                                    "PlaceholderText": "course_id",
                                    "MinimumSize": [170, 26],
                                }
                            ),
                            self.ui.Label(
                                {
                                    "Text": "Name",
                                    "FixedSize": [50, 26],
                                    "Alignment": {"AlignVCenter": True},
                                }
                            ),
                            self.ui.LineEdit(
                                {
                                    "ID": "CourseNameEdit",
                                    "PlaceholderText": "Course name",
                                    "MinimumSize": [220, 26],
                                }
                            ),
                        ],
                    ),
                    self.ui.HGroup(
                        {"Weight": 0, "Spacing": 6},
                        [
                            self.ui.Label(
                                {
                                    "Text": "Sectors",
                                    "FixedSize": [50, 26],
                                    "Alignment": {"AlignVCenter": True},
                                }
                            ),
                            self.ui.LineEdit(
                                {
                                    "ID": "CourseSectorsEdit",
                                    "PlaceholderText": "4",
                                    "FixedSize": [80, 26],
                                }
                            ),
                            self.ui.HGap(0, 1),
                        ],
                    ),
                    self.ui.Label(
                        {
                            "ID": "CoursesStatusLabel",
                            "Text": "Select a course, or enter a new one.",
                            "WordWrap": True,
                        }
                    ),
                    self.ui.HGroup(
                        {"Weight": 0, "Spacing": 6},
                        [
                            self.ui.Button({"ID": "CourseAddButton", "Text": "Add"}),
                            self.ui.Button(
                                {
                                    "ID": "CourseUpdateButton",
                                    "Text": "Update",
                                    "Enabled": False,
                                }
                            ),
                            self.ui.Button(
                                {
                                    "ID": "CourseDeleteButton",
                                    "Text": "Delete",
                                    "Enabled": False,
                                }
                            ),
                            self.ui.Button(
                                {
                                    "ID": "CourseCancelDeleteButton",
                                    "Text": "Cancel",
                                    "Visible": False,
                                }
                            ),
                            self.ui.Button(
                                {
                                    "ID": "CourseConfirmDeleteButton",
                                    "Text": "Confirm Delete",
                                    "Visible": False,
                                }
                            ),
                            self.ui.Button({"ID": "CourseClearButton", "Text": "Clear"}),
                            self.ui.Button({"ID": "CourseCloseButton", "Text": "Close"}),
                        ],
                    ),
                ],
            ),
        )

    def _configure_table(self) -> None:
        tree = self.items["CoursesTree"]
        tree.SetHeaderLabels(["Course ID", "Name", "Sectors", "Runs"])
        for index, width in enumerate((190, 280, 80, 70)):
            tree.ColumnWidth[index] = width

    def _bind_events(self) -> None:
        self.window.On.ResolveTimerCoursesWindow.Close = self._close
        self.window.On.CourseCloseButton.Clicked = self._close
        self.window.On.CoursesTree.ItemClicked = self._on_item_clicked
        self.window.On.CourseAddButton.Clicked = self._on_add
        self.window.On.CourseUpdateButton.Clicked = self._on_update
        self.window.On.CourseDeleteButton.Clicked = self._on_delete
        self.window.On.CourseCancelDeleteButton.Clicked = self._cancel_delete
        self.window.On.CourseConfirmDeleteButton.Clicked = self._confirm_delete
        self.window.On.CourseClearButton.Clicked = self._clear_selection

    def show(self) -> None:
        self._refresh_rows()
        self.window.Show()

    def _refresh_rows(self, status: str | None = None) -> None:
        try:
            self.rows = self.controller.course_rows()
        except Exception as exc:
            self.rows = ()
            status = f"Unable to load courses: {exc}"
        self.selected_course_id = None
        self.pending_delete_course_id = None
        tree = self.items["CoursesTree"]
        tree.Clear()
        for row in self.rows:
            item = tree.NewItem()
            values = (
                row.course_id,
                row.name,
                str(row.sector_count),
                str(row.run_count),
            )
            for column, value in enumerate(values):
                item.Text[column] = value
            tree.AddTopLevelItem(item)
        self.items["CoursesStatusLabel"].Text = status or (
            f"{len(self.rows)} course(s)."
        )
        self._hide_delete_confirmation()
        self._clear_fields()
        self._render_selection()

    def _on_item_clicked(self, event) -> None:
        item = event.get("item") or event.get("Item")
        if item is None:
            item = getattr(self.items["CoursesTree"], "CurrentItem", None)
        self._select_course_id(None if item is None else str(item.Text[0]))

    def _select_course_id(self, course_id: str | None, *, announce: bool = True) -> None:
        self.selected_course_id = course_id
        row = self._selected_row()
        if row is None:
            self._clear_fields()
        else:
            _set_widget_text(self.items["CourseIdEdit"], row.course_id)
            _set_widget_text(self.items["CourseNameEdit"], row.name)
            _set_widget_text(self.items["CourseSectorsEdit"], str(row.sector_count))
        self._hide_delete_confirmation()
        self._render_selection()
        if announce and row is not None and row.run_count > 0:
            self.items["CoursesStatusLabel"].Text = (
                f"{row.course_id} has {row.run_count} run(s); delete and sector changes are blocked."
            )

    def _clear_selection(self, _event=None) -> None:
        self.selected_course_id = None
        self.pending_delete_course_id = None
        self._hide_delete_confirmation()
        self._clear_fields()
        self._render_selection()
        self.items["CoursesStatusLabel"].Text = "Enter a new course."

    def _clear_fields(self) -> None:
        _set_widget_text(self.items["CourseIdEdit"], "")
        _set_widget_text(self.items["CourseNameEdit"], "")
        _set_widget_text(self.items["CourseSectorsEdit"], "")

    def _render_selection(self) -> None:
        row = self._selected_row()
        has_selection = row is not None
        self.items["CourseIdEdit"].Enabled = not has_selection
        self.items["CourseUpdateButton"].Enabled = has_selection
        self.items["CourseDeleteButton"].Enabled = bool(
            has_selection and row is not None and row.run_count == 0
        )
        self.window.RecalcLayout()

    def _selected_row(self):
        return next(
            (row for row in self.rows if row.course_id == self.selected_course_id),
            None,
        )

    def _on_add(self, _event) -> None:
        course_id = _widget_text(self.items["CourseIdEdit"]).strip()
        name = _widget_text(self.items["CourseNameEdit"]).strip()
        sector_count = self._sector_count_from_field()
        if sector_count is None:
            return
        state = self.controller.add_course(course_id, name, sector_count)
        self._refresh_rows(_state_status(state))
        if any(row.course_id == course_id for row in self.rows):
            self._select_course_id(course_id, announce=False)

    def _on_update(self, _event) -> None:
        row = self._selected_row()
        if row is None:
            return
        name = _widget_text(self.items["CourseNameEdit"]).strip()
        sector_count = self._sector_count_from_field()
        if sector_count is None:
            return
        state = self.controller.update_course(
            row.course_id,
            name=name,
            sector_count=sector_count,
        )
        self._refresh_rows(_state_status(state))
        if any(item.course_id == row.course_id for item in self.rows):
            self._select_course_id(row.course_id, announce=False)

    def _sector_count_from_field(self) -> int | None:
        raw = _widget_text(self.items["CourseSectorsEdit"]).strip()
        try:
            return int(raw)
        except ValueError:
            self.items["CoursesStatusLabel"].Text = "Sectors must be a whole number."
            return None

    def _on_delete(self, _event) -> None:
        row = self._selected_row()
        if row is None:
            return
        if row.run_count > 0:
            self.items["CoursesStatusLabel"].Text = (
                f"Cannot delete {row.course_id}; {row.run_count} run(s) exist."
            )
            return
        self.pending_delete_course_id = row.course_id
        self.items["CoursesStatusLabel"].Text = f"Confirm deleting {row.course_id}."
        self.items["CourseDeleteButton"].Visible = False
        self.items["CourseCancelDeleteButton"].Visible = True
        self.items["CourseConfirmDeleteButton"].Visible = True
        self.window.RecalcLayout()

    def _cancel_delete(self, _event) -> None:
        self._hide_delete_confirmation()

    def _confirm_delete(self, _event) -> None:
        course_id = self.pending_delete_course_id
        self._hide_delete_confirmation()
        if course_id:
            state = self.controller.delete_course(course_id)
            self._refresh_rows(_state_status(state))

    def _hide_delete_confirmation(self) -> None:
        self.pending_delete_course_id = None
        self.items["CourseCancelDeleteButton"].Visible = False
        self.items["CourseConfirmDeleteButton"].Visible = False
        self.items["CourseDeleteButton"].Visible = True
        self.window.RecalcLayout()

    def _close(self, _event) -> None:
        self.window.Hide()
        self.on_close(self.controller.refresh_selection())


def _widget_text(widget) -> str:
    text = getattr(widget, "Text", None)
    if text is not None:
        return str(text)
    plain_text = getattr(widget, "PlainText", None)
    if plain_text is not None:
        return str(plain_text)
    return ""


def _set_widget_text(widget, value: str) -> None:
    if hasattr(widget, "Text"):
        widget.Text = value
    elif hasattr(widget, "PlainText"):
        widget.PlainText = value


def _state_status(state: ResolveTimerViewState) -> str:
    if state.error is None:
        return state.status
    return f"{state.status}: {state.error}"


class ResolveRunManagementWindow:
    def __init__(self, ui, dispatcher, controller, on_close):
        self.ui = ui
        self.dispatcher = dispatcher
        self.controller = controller
        self.on_close = on_close
        self.selected_run_id: str | None = None
        self.rows = ()
        self.window = self._build_window()
        self.items = self.window.GetItems()
        self._configure_table()
        self._bind_events()

    def _build_window(self):
        return self.dispatcher.AddWindow(
            {
                "ID": "ResolveTimerRunsWindow",
                "WindowTitle": "Resolve Timer - Manage Runs",
                "Geometry": [240, 150, 850, 480],
            },
            self.ui.VGroup(
                {"Spacing": 8},
                [
                    self.ui.Tree(
                        {
                            "ID": "RunsTree",
                            "Weight": 1,
                            "ColumnCount": 7,
                            "HeaderHidden": False,
                            "RootIsDecorated": False,
                            "ItemsExpandable": False,
                            "SortingEnabled": False,
                            "SelectionMode": "SingleSelection",
                        }
                    ),
                    self.ui.Label(
                        {
                            "ID": "RunsStatusLabel",
                            "Text": "Select a run.",
                            "WordWrap": True,
                        }
                    ),
                    self.ui.HGroup(
                        {"Weight": 0},
                        [
                            self.ui.Button(
                                {"ID": "RunsIgnoreButton", "Text": "Ignore", "Enabled": False}
                            ),
                            self.ui.Button(
                                {"ID": "RunsDeleteButton", "Text": "Delete", "Enabled": False}
                            ),
                            self.ui.Button(
                                {
                                    "ID": "RunsCancelDeleteButton",
                                    "Text": "Cancel",
                                    "Visible": False,
                                }
                            ),
                            self.ui.Button(
                                {
                                    "ID": "RunsConfirmDeleteButton",
                                    "Text": "Confirm Delete",
                                    "Visible": False,
                                }
                            ),
                            self.ui.Button({"ID": "RunsCloseButton", "Text": "Close"}),
                        ],
                    ),
                ],
            ),
        )

    def _configure_table(self) -> None:
        tree = self.items["RunsTree"]
        tree.SetHeaderLabels(
            ["Run ID", "Date", "Filename", "Lap", "Committed", "Ignored", "Clip ID"]
        )
        widths = [190, 90, 180, 100, 80, 70, 70]
        for index, width in enumerate(widths):
            tree.ColumnWidth[index] = width

    def _bind_events(self) -> None:
        self.window.On.ResolveTimerRunsWindow.Close = self._close
        self.window.On.RunsCloseButton.Clicked = self._close
        self.window.On.RunsTree.ItemClicked = self._on_item_clicked
        self.window.On.RunsIgnoreButton.Clicked = self._on_ignore
        self.window.On.RunsDeleteButton.Clicked = self._on_delete
        self.window.On.RunsCancelDeleteButton.Clicked = self._cancel_delete
        self.window.On.RunsConfirmDeleteButton.Clicked = self._confirm_delete

    def show(self) -> None:
        self._refresh_rows()
        self.window.Show()

    def _refresh_rows(self, status: str | None = None) -> None:
        try:
            self.rows = self.controller.course_runs()
        except Exception as exc:
            self.rows = ()
            status = f"Unable to load runs: {exc}"
        self.selected_run_id = None
        tree = self.items["RunsTree"]
        tree.Clear()
        for row in self.rows:
            item = tree.NewItem()
            values = (
                row.run_id,
                row.date,
                row.filename,
                row.lap,
                "Yes" if row.committed else "No",
                "Yes" if row.ignored else "No",
                "Yes" if row.has_clip_id else "No",
            )
            for column, value in enumerate(values):
                item.Text[column] = value
            tree.AddTopLevelItem(item)
        self.items["RunsStatusLabel"].Text = status or (
            f"{len(self.rows)} run(s) for the selected course."
        )
        self._render_selection()

    def _on_item_clicked(self, event) -> None:
        item = event.get("item") or event.get("Item")
        if item is None:
            item = getattr(self.items["RunsTree"], "CurrentItem", None)
        self.selected_run_id = None if item is None else str(item.Text[0])
        self._render_selection()

    def _render_selection(self) -> None:
        row = self._selected_row()
        enabled = row is not None
        self.items["RunsIgnoreButton"].Enabled = enabled
        self.items["RunsDeleteButton"].Enabled = enabled
        self.items["RunsIgnoreButton"].Text = (
            "Unignore" if row is not None and row.ignored else "Ignore"
        )

    def _selected_row(self):
        return next(
            (row for row in self.rows if row.run_id == self.selected_run_id),
            None,
        )

    def _on_ignore(self, _event) -> None:
        row = self._selected_row()
        if row is None:
            return
        state = self.controller.set_run_ignored(row.run_id, not row.ignored)
        status = state.status if state.error is None else f"{state.status}: {state.error}"
        self._refresh_rows(status)

    def _on_delete(self, _event) -> None:
        if self.selected_run_id is None:
            return
        self.items["RunsStatusLabel"].Text = (
            f"Confirm deleting {self.selected_run_id}."
        )
        self.items["RunsDeleteButton"].Visible = False
        self.items["RunsCancelDeleteButton"].Visible = True
        self.items["RunsConfirmDeleteButton"].Visible = True
        self.window.RecalcLayout()

    def _cancel_delete(self, _event) -> None:
        self._hide_delete_confirmation()

    def _confirm_delete(self, _event) -> None:
        run_id = self.selected_run_id
        self._hide_delete_confirmation()
        if run_id:
            state = self.controller.delete_run(run_id)
            status = state.status if state.error is None else f"{state.status}: {state.error}"
            self._refresh_rows(status)

    def _hide_delete_confirmation(self) -> None:
        self.items["RunsCancelDeleteButton"].Visible = False
        self.items["RunsConfirmDeleteButton"].Visible = False
        self.items["RunsDeleteButton"].Visible = True
        self.window.RecalcLayout()

    def _close(self, _event) -> None:
        self.window.Hide()
        self.on_close(self.controller.refresh_selection())
