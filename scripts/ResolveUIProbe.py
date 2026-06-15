"""Validate Resolve UI Manager and dispatcher availability."""

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "resolve_ui_probe.json"

fusion = globals().get("fusion")
bmd = globals().get("bmd")
ui = getattr(fusion, "UIManager", None) if fusion is not None else None
dispatcher_factory = getattr(bmd, "UIDispatcher", None) if bmd is not None else None

report = {
    "fusion_injected": fusion is not None,
    "bmd_injected": bmd is not None,
    "ui_manager_available": ui is not None,
    "ui_dispatcher_callable": callable(dispatcher_factory),
    "window_opened": False,
    "button_clicked": False,
}

if ui is not None and callable(dispatcher_factory):
    dispatcher = dispatcher_factory(ui)
    window = dispatcher.AddWindow(
        {
            "ID": "ResolveTimerUIProbe",
            "WindowTitle": "Resolve Timer UI Probe",
            "Geometry": [300, 300, 420, 140],
        },
        ui.VGroup(
            [
                ui.Label({"Text": "Resolve UI Manager is available."}),
                ui.Button({"ID": "CloseButton", "Text": "Close Probe"}),
            ]
        ),
    )

    def close_probe(_event):
        report["button_clicked"] = True
        dispatcher.ExitLoop()

    window.On.ResolveTimerUIProbe.Close = close_probe
    window.On.CloseButton.Clicked = close_probe
    report["window_opened"] = True
    window.Show()
    dispatcher.RunLoop()
    window.Hide()

OUTPUT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
print(f"Wrote {OUTPUT_PATH}")
