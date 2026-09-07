import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "linux_installer", Path(__file__).resolve().parents[1] / "scripts/install_resolve_linux.py"
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class LinuxInstallerTests(unittest.TestCase):
    def test_launcher_handles_spaces_quotes_and_injected_globals_without_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "timer's checkout"
            (project / "scripts").mkdir(parents=True)
            result = project / "result.txt"
            (project / "scripts/ResolveTimer.py").write_text(
                "from pathlib import Path\n"
                "assert __name__ == '__main__'\n"
                "assert resolve == 'resolve' and fusion == 'fusion' and bmd == 'bmd'\n"
                f"Path({str(result)!r}).write_text(__file__)\n"
            )
            exec(installer.launcher_text(project),
                 dict(resolve="resolve", fusion="fusion", bmd="bmd"))
            self.assertEqual(result.read_text(), str(project / "scripts/ResolveTimer.py"))

    def test_repeat_install_preserves_database_and_updates_managed_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "examples").mkdir()
            (project / "examples/timer_db.yaml").write_text("starter")
            launcher = project / "Utility/Resolve Timer/ResolveTimer.py"
            installer.install_launcher(project, launcher)
            self.assertEqual((project / "timer_db.yaml").read_text(), "starter")
            (project / "timer_db.yaml").write_text("user data")
            launcher.write_text(installer.SIGNATURE + "\n# old launcher")
            installer.install_launcher(project, launcher)
            self.assertEqual((project / "timer_db.yaml").read_text(), "user data")
            self.assertEqual(launcher.read_text(), installer.launcher_text(project))

    def test_unmanaged_launcher_and_symlink_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher = root / "ResolveTimer.py"
            launcher.write_text("user script")
            with self.assertRaisesRegex(RuntimeError, "not managed"):
                installer.install_launcher(root, launcher)
            self.assertEqual(launcher.read_text(), "user script")
            link = root / "linked"
            link.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                installer.check_destination(link / "new.py")

    def test_missing_resolve_stops_before_installation(self):
        with patch("sys.argv", ["installer"]), patch.object(Path, "is_file", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "Resolve was not found"):
                installer.main()


if __name__ == "__main__":
    unittest.main()
