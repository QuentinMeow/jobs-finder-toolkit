"""Shared DOCX -> PDF conversion (LibreOffice, with a docx2pdf fallback).

Used by both .agents/skills/resume-writer/scripts/render.py (resume) and
.agents/skills/resume-writer/scripts/cover_letter.py so the conversion path is
defined in exactly one place.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# LibreOffice locations to try, in order: the JOBHUNT_SOFFICE env override,
# the common macOS install locations, then PATH lookups (Linux/CI).
LO_PATHS = [p for p in (os.environ.get("JOBHUNT_SOFFICE"),) if p] + [
    str(Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice"),
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "soffice",
    "libreoffice",
]


def docx_to_pdf(docx_path: Path, output_dir: Path, stem: str) -> Path | None:
    """Convert docx_path to <output_dir>/<stem>.pdf. Return the PDF path or None.

    Tries LibreOffice headless first, then docx2pdf. LibreOffice names its
    output after the input file stem, so we rename to the desired stem when
    they differ.
    """
    docx_path, output_dir = Path(docx_path), Path(output_dir)
    pdf_path = output_dir / f"{stem}.pdf"

    # Isolate the LibreOffice user profile per process so multiple headless
    # conversions can run concurrently without contending on the single shared
    # profile lock (which otherwise makes parallel renders fail or hang).
    profile_dir = Path(tempfile.gettempdir()) / f"lo_profile_{os.getpid()}"
    user_install = f"-env:UserInstallation=file://{profile_dir}"

    for lo in LO_PATHS:
        if shutil.which(lo) or Path(lo).exists():
            try:
                result = subprocess.run(
                    [lo, user_install, "--headless", "--convert-to", "pdf",
                     "--outdir", str(output_dir), str(docx_path)],
                    capture_output=True, text=True, timeout=120,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue
            produced = output_dir / f"{docx_path.stem}.pdf"
            if result.returncode == 0 and produced.exists():
                if produced != pdf_path:
                    produced.replace(pdf_path)
                return pdf_path

    try:
        from docx2pdf import convert
        convert(str(docx_path), str(pdf_path))
        if pdf_path.exists():
            return pdf_path
    except ImportError:
        pass
    except Exception as e:
        print(f"  docx2pdf failed: {e}", file=sys.stderr)

    return None
