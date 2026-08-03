"""Pure LibreOffice discovery and macOS sandbox preflight helpers.

The executable path and the permission to launch it are separate facts:
``JOBHUNT_SOFFICE`` can select a binary, but it cannot grant the macOS
LaunchServices access LibreOffice needs even for ``--headless`` conversion.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


_LAUNCHSERVICES_NAME = b"com.apple.coreservices.launchservicesd"
_SANDBOX_FILTER_GLOBAL_NAME = 2


class LaunchServicesAccess(Enum):
    """Whether this process may look up macOS LaunchServices."""

    ALLOWED = "allowed"
    DENIED = "denied"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not-applicable"


@dataclass(frozen=True)
class LibreOfficeEnvironment:
    """The selected executable and whether it is usable in this process."""

    executable: str | None
    launchservices: LaunchServicesAccess

    @property
    def usable(self) -> bool:
        return (
            self.executable is not None
            and self.launchservices is not LaunchServicesAccess.DENIED
        )


def soffice_candidates() -> tuple[str, ...]:
    """Return LibreOffice candidates in priority order, resolved at call time."""
    candidates = [
        os.environ.get("JOBHUNT_SOFFICE"),
        str(Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice"),
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "soffice",
        "libreoffice",
    ]
    # Preserve order while avoiding duplicate probes (an override may match a
    # standard location or PATH command).
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))


def find_soffice() -> str | None:
    """Return the first installed/on-PATH LibreOffice executable, else ``None``."""
    for candidate in soffice_candidates():
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        if Path(candidate).exists():
            return candidate
    return None


def launchservices_access() -> LaunchServicesAccess:
    """Probe the current process's macOS LaunchServices mach-lookup access.

    ``sandbox_check`` returns 0 when allowed, a positive value when denied, and
    a negative value when the query is unknown. If the direct API is absent or
    inconclusive, only Darwin with the exact Codex seatbelt marker is classified
    conservatively as denied. Other platforms are never restricted by this
    macOS-specific check.
    """
    if sys.platform != "darwin":
        return LaunchServicesAccess.NOT_APPLICABLE

    result: int | None = None
    try:
        sandbox_check = ctypes.CDLL(None).sandbox_check
        sandbox_check.restype = ctypes.c_int
        # sandbox_check is variadic. Declaring its three fixed arguments keeps
        # pointer-sized values ABI-correct (especially on arm64); the filter
        # value remains an explicitly typed variadic c_char_p below.
        sandbox_check.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
        )
        result = sandbox_check(
            os.getpid(),
            b"mach-lookup",
            _SANDBOX_FILTER_GLOBAL_NAME,
            ctypes.c_char_p(_LAUNCHSERVICES_NAME),
        )
    # This is a best-effort availability probe. Any API lookup/call failure is
    # "unknown" and may use the exact Codex seatbelt fallback below.
    except Exception:
        pass

    if result == 0:
        return LaunchServicesAccess.ALLOWED
    if result is not None and result > 0:
        return LaunchServicesAccess.DENIED
    if os.environ.get("CODEX_SANDBOX") == "seatbelt":
        return LaunchServicesAccess.DENIED
    return LaunchServicesAccess.UNKNOWN


def libreoffice_environment() -> LibreOfficeEnvironment:
    """Inspect binary availability and launch usability without starting it."""
    return LibreOfficeEnvironment(find_soffice(), launchservices_access())


def launchservices_denied_diagnostic(executable: str | None = None) -> str:
    """Canonical actionable diagnostic for a known LaunchServices denial."""
    selected = f" ({executable})" if executable else ""
    return (
        f"LibreOffice{selected} cannot start because this macOS sandbox denies "
        "the LaunchServices mach lookup it needs during application initialization. "
        "No LibreOffice process was started. PDF conversion and one-page PDF checks "
        "did not run: this is FAIL, not SKIP or PASS. Run the PDF-producing command "
        "outside the Codex app sandbox, or through a separately validated route that "
        "can access LaunchServices. JOBHUNT_SOFFICE only selects a LibreOffice binary; "
        "it does not grant LaunchServices access or escape the sandbox."
    )
