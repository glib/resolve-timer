"""Interactive Resolve UI layout lab for testing safer section styles.

This script is intentionally separate from the production Resolve Timer window.
It does not read or write timer data. Use it to find which UIManager layout
patterns Resolve sizes reliably before moving a pattern into the main tool.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "resolve_ui_layout_probe.json"

CHECKBOX_IDS = (
    "DirectSectionsOk",
    "StyledTitleOk",
    "SeparatorRowsOk",
    "IndentedCardsOk",
)


def main() -> None:
    fusion = globals().get("fusion")
    bmd = globals().get("bmd")
    ui = getattr(fusion, "UIManager", None) if fusion is not None else None
    dispatcher_factory = getattr(bmd, "UIDispatcher", None) if bmd is not None else None

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "fusion_injected": fusion is not None,
        "bmd_injected": bmd is not None,
        "ui_manager_available": ui is not None,
        "ui_dispatcher_callable": callable(dispatcher_factory),
        "window_opened": False,
        "closed_by_button": False,
        "usable_layouts": {},
        "notes": "",
    }

    if ui is None or not callable(dispatcher_factory):
        _write_report(report)
        print(f"Wrote {OUTPUT_PATH}")
        return

    dispatcher = dispatcher_factory(ui)
    window = dispatcher.AddWindow(
        {
            "ID": "ResolveTimerUILayoutProbe",
            "WindowTitle": "Resolve Timer UI Layout Lab",
            "Geometry": [220, 120, 980, 760],
        },
        ui.VGroup(
            {"Spacing": 8, "Weight": 1},
            [
                _title(ui, "Resolve Timer UI Layout Lab", pixel_size=16),
                ui.Label(
                    {
                        "Text": (
                            "Group boxes rendered garbled in this Resolve runtime, so "
                            "this pass tests no-Group alternatives only."
                        ),
                        "WordWrap": True,
                        "Weight": 0,
                    }
                ),
                _title(ui, "A. Direct Sections"),
                _direct_sections(ui),
                _title(ui, "B. Styled Title Labels"),
                _styled_titles(ui),
                _title(ui, "C. Separator Rows"),
                _separator_rows(ui),
                _title(ui, "D. Indented Cards"),
                _indented_cards(ui),
                ui.TextEdit(
                    {
                        "ID": "ProbeNotes",
                        "PlaceholderText": "Optional notes: what collapsed, clipped, or looked good?",
                        "MinimumSize": [0, 56],
                        "MaximumSize": [16777215, 80],
                        "Weight": 0,
                    }
                ),
                ui.HGroup(
                    {"Spacing": 6, "Weight": 0},
                    [
                        ui.Button({"ID": "CloseButton", "Text": "Write Report and Close"}),
                        ui.HGap(0, 1),
                    ],
                ),
            ],
        ),
    )
    items = window.GetItems()
    _populate_tree(items["DirectSectionsTree"])

    def close_probe(_event):
        report["closed_by_button"] = True
        _collect_report(report, items)
        _write_report(report)
        dispatcher.ExitLoop()

    def close_window(_event):
        _collect_report(report, items)
        _write_report(report)
        dispatcher.ExitLoop()

    window.On.ResolveTimerUILayoutProbe.Close = close_window
    window.On.CloseButton.Clicked = close_probe
    report["window_opened"] = True
    window.Show()
    dispatcher.RunLoop()
    window.Hide()
    print(f"Wrote {OUTPUT_PATH}")


def _title(ui, text: str, *, pixel_size: int | None = None):
    font = {"Bold": True}
    if pixel_size is not None:
        font["PixelSize"] = pixel_size
    return ui.Label({"Text": text, "Font": font, "Weight": 0})


def _direct_sections(ui):
    return ui.VGroup(
        {"Spacing": 5, "Weight": 1},
        [
            ui.Label(
                {
                    "Text": "Baseline: direct VGroup/HGroup nesting with a real table.",
                    "WordWrap": True,
                    "Weight": 0,
                }
            ),
            ui.Tree(
                {
                    "ID": "DirectSectionsTree",
                    "Weight": 1,
                    "MinimumSize": [0, 150],
                    "ColumnCount": 4,
                    "HeaderHidden": False,
                    "RootIsDecorated": False,
                    "ItemsExpandable": False,
                    "AlternatingRowColors": True,
                    "UniformRowHeights": True,
                }
            ),
            ui.HGroup(
                {"Spacing": 6, "Weight": 0},
                [
                    ui.Button({"Text": "Refresh Preview"}),
                    ui.Button({"Text": "Commit New Run"}),
                    ui.Button({"Text": "Manage"}),
                    ui.HGap(0, 1),
                ],
            ),
            ui.CheckBox(
                {
                    "ID": "DirectSectionsOk",
                    "Text": "A is usable: table expands and buttons are visible",
                    "Weight": 0,
                }
            ),
        ],
    )


def _styled_titles(ui):
    title_style = (
        "QLabel { border: 1px solid #777; padding: 6px; "
        "border-radius: 4px; background-color: #2c2c2c; }"
    )
    return ui.VGroup(
        {"Spacing": 5, "Weight": 0},
        [
            ui.Label(
                {
                    "Text": "Tests whether StyleSheet works well enough for title bars.",
                    "WordWrap": True,
                    "Weight": 0,
                }
            ),
            ui.HGroup(
                {"Spacing": 8, "Weight": 0},
                [
                    ui.Label(
                        {
                            "Text": "Media Pool Preview",
                            "Font": {"Bold": True},
                            "MinimumSize": [220, 34],
                            "StyleSheet": title_style,
                        }
                    ),
                    ui.Label(
                        {
                            "Text": "Timeline Overlay",
                            "Font": {"Bold": True},
                            "MinimumSize": [220, 34],
                            "StyleSheet": title_style,
                        }
                    ),
                    ui.HGap(0, 1),
                ],
            ),
            ui.CheckBox(
                {
                    "ID": "StyledTitleOk",
                    "Text": "B is usable: styled labels render cleanly",
                    "Weight": 0,
                }
            ),
        ],
    )


def _separator_rows(ui):
    separator_font = {"Family": "Consolas", "MonoSpaced": True}
    return ui.VGroup(
        {"Spacing": 5, "Weight": 0},
        [
            ui.Label(
                {
                    "Text": "Uses plain labels as dividers. Least fancy, likely most stable.",
                    "WordWrap": True,
                    "Weight": 0,
                }
            ),
            ui.Label(
                {
                    "Text": "-----------------------------  Media Pool Preview  -----------------------------",
                    "Font": separator_font,
                    "Weight": 0,
                }
            ),
            ui.HGroup(
                {"Spacing": 6, "Weight": 0},
                [
                    ui.Button({"Text": "Refresh Preview"}),
                    ui.Button({"Text": "Commit"}),
                    ui.Button({"Text": "Manage"}),
                    ui.HGap(0, 1),
                ],
            ),
            ui.Label(
                {
                    "Text": "-----------------------------  Timeline Overlay  -----------------------------",
                    "Font": separator_font,
                    "Weight": 0,
                }
            ),
            ui.HGroup(
                {"Spacing": 6, "Weight": 0},
                [
                    ui.Button({"Text": "Update Under Playhead"}),
                    ui.Button({"Text": "Update All Timeline Clips"}),
                    ui.HGap(0, 1),
                ],
            ),
            ui.CheckBox(
                {
                    "ID": "SeparatorRowsOk",
                    "Text": "C is usable: separators give enough visual structure",
                    "Weight": 0,
                }
            ),
        ],
    )


def _indented_cards(ui):
    return ui.VGroup(
        {"Spacing": 5, "Weight": 0},
        [
            ui.Label(
                {
                    "Text": "Uses indentation and compact rows instead of borders.",
                    "WordWrap": True,
                    "Weight": 0,
                }
            ),
            _indented_row(
                ui,
                "Media Pool Preview",
                "Selected clip -> timing preview -> database actions",
                ("Refresh Preview", "Commit", "Manage"),
            ),
            _indented_row(
                ui,
                "Timeline Overlay",
                "Timeline clip source media -> overlay actions",
                ("Update Under Playhead", "Update All"),
            ),
            ui.CheckBox(
                {
                    "ID": "IndentedCardsOk",
                    "Text": "D is usable: indentation gives enough separation",
                    "Weight": 0,
                }
            ),
        ],
    )


def _indented_row(ui, heading: str, detail: str, buttons: tuple[str, ...]):
    return ui.HGroup(
        {"Spacing": 6, "Weight": 0},
        [
            ui.HGap(18, 0),
            ui.VGroup(
                {"Spacing": 4, "Weight": 1},
                [
                    ui.Label({"Text": heading, "Font": {"Bold": True}, "Weight": 0}),
                    ui.Label({"Text": detail, "Weight": 0}),
                    ui.HGroup(
                        {"Spacing": 6, "Weight": 0},
                        [
                            *[ui.Button({"Text": label}) for label in buttons],
                            ui.HGap(0, 1),
                        ],
                    ),
                ],
            ),
        ],
    )


def _populate_tree(tree) -> None:
    tree.SetHeaderLabels(["Row", "Current", "Reference", "Delta"])
    for index, width in enumerate((70, 100, 100, 80)):
        tree.ColumnWidth[index] = width
    for values in (
        ("S1", "0:20.020", "0:21.255", "-1.235"),
        ("S2", "0:17.784", "0:19.319", "-1.535"),
        ("S3", "0:08.642", "0:08.775", "-0.133"),
        ("LAP", "0:59.326", "1:02.062", "-2.736"),
    ):
        item = tree.NewItem()
        for column, value in enumerate(values):
            item.Text[column] = value
        tree.AddTopLevelItem(item)


def _collect_report(report: dict, items: dict) -> None:
    report["usable_layouts"] = {
        checkbox_id: bool(getattr(items[checkbox_id], "Checked", False))
        for checkbox_id in CHECKBOX_IDS
        if checkbox_id in items
    }
    notes = items.get("ProbeNotes")
    if notes is not None:
        report["notes"] = str(
            getattr(notes, "PlainText", None) or getattr(notes, "Text", "") or ""
        )


def _write_report(report: dict) -> None:
    OUTPUT_PATH.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
