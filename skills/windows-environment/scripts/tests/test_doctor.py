from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import doctor  # noqa: E402


class RuntimeTests(unittest.TestCase):
    def test_detects_wsl_from_kernel_release(self):
        self.assertEqual(
            doctor.classify_runtime(
                system_name="Linux", release="microsoft-standard-WSL2", environ={}
            ),
            "wsl",
        )

    def test_distinguishes_native_windows_and_macos(self):
        self.assertEqual(
            doctor.classify_runtime(system_name="Windows", release="", environ={}),
            "windows-native",
        )
        self.assertEqual(
            doctor.classify_runtime(system_name="Darwin", release="", environ={}),
            "macos",
        )

    def test_windows_mount_detection_is_drive_scoped(self):
        self.assertTrue(doctor.is_windows_mount(Path("/mnt/c/work/repo")))
        self.assertFalse(doctor.is_windows_mount(Path("/home/user/repo")))
        self.assertFalse(doctor.is_windows_mount(Path("/mnt/wsl/repo")))


class InspectionTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        (root / ".git").mkdir()
        python = root / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text("", encoding="utf-8")
        python.chmod(0o755)
        return root

    @staticmethod
    def _which(name: str) -> str | None:
        paths = {
            "git": "/usr/bin/git",
            "gh": "/usr/bin/gh",
            "bwrap": "/usr/bin/bwrap",
            "soffice": "/usr/bin/soffice",
        }
        return paths.get(name)

    def test_linux_storage_and_temp_are_ready(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            checks = doctor.inspect_environment(
                self._repo(Path(td)),
                runtime="wsl",
                release="microsoft-standard-WSL2",
                temp_dir=Path("/tmp"),
                which=self._which,
            )
        self.assertFalse([check for check in checks if check.status == "FAIL"], checks)

    def test_windows_temp_is_a_blocking_finding(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            checks = doctor.inspect_environment(
                self._repo(Path(td)),
                runtime="wsl",
                release="microsoft-standard-WSL2",
                temp_dir=Path("/mnt/c/Temp"),
                which=self._which,
            )
        finding = next(check for check in checks if check.label == "temporary directory")
        self.assertEqual(finding.status, "FAIL")
        self.assertIn("TMPDIR=/tmp", finding.fix or "")

    def test_missing_bwrap_warns_but_does_not_block_toolkit(self):
        def without_bwrap(name: str) -> str | None:
            return None if name == "bwrap" else self._which(name)

        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            checks = doctor.inspect_environment(
                self._repo(Path(td)),
                runtime="wsl",
                release="microsoft-standard-WSL2",
                temp_dir=Path("/tmp"),
                which=without_bwrap,
            )
        finding = next(check for check in checks if check.label == "bwrap")
        self.assertEqual(finding.status, "WARN")


if __name__ == "__main__":
    unittest.main()
