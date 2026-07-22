"""Shared DOCX -> PDF conversion (LibreOffice, with a docx2pdf fallback).

Used by both skills/resume-writer/scripts/render.py (resume) and
skills/resume-writer/scripts/cover_letter.py so the conversion path is
defined in exactly one place.

Two flake-hardening guarantees (a silent "PDF: skipped" used to hide both):
  * detect + retry: LibreOffice occasionally exits 0 without writing the PDF
    (a transient lock / first-run no-op). We verify a real PDF landed
    (exists AND > MIN_PDF_BYTES); if not, we clear stray lock state, back off,
    and retry ONCE. If a converter was available but still produced no valid
    PDF, we raise PdfConversionError instead of returning a silent None.
  * parallel-safe profiles: each conversion runs its own LibreOffice process
    against a UNIQUE, isolated user profile
    (``-env:UserInstallation=file://<distinct tmp dir>``). LibreOffice instances
    contend on a shared profile lock, so a distinct profile per call is what lets
    ``docx_to_pdf_many`` convert the resume and every cover letter concurrently.

``docx_to_pdf`` returns the PDF path on success, or ``None`` ONLY when no
converter is available at all (neither LibreOffice nor docx2pdf) — that is the
one legitimate "install a converter" case, not a flake.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# LibreOffice locations to try, in order: the JOBHUNT_SOFFICE env override,
# the common macOS install locations, then PATH lookups (Linux/CI).
LO_PATHS = [p for p in (os.environ.get("JOBHUNT_SOFFICE"),) if p] + [
    str(Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice"),
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "soffice",
    "libreoffice",
]

# A real one-page resume/cover PDF is comfortably larger than this; anything
# smaller (or absent) means LibreOffice silently no-op'd instead of converting.
MIN_PDF_BYTES = 1024
# Short pause before the single retry, to let a transient lock / first-run
# bootstrap settle.
RETRY_BACKOFF_S = float(os.environ.get("JOBHUNT_PDF_RETRY_BACKOFF_S", "1.5"))
_SOFFICE_TIMEOUT_S = 120


class PdfConversionError(RuntimeError):
    """A converter was available but failed to produce a valid PDF (the flake).

    Distinct from the ``docx_to_pdf`` -> ``None`` case, which means no converter
    is installed at all. Callers should treat this as a hard, non-zero failure
    rather than a skip.
    """


def _find_soffice() -> str | None:
    """First LibreOffice binary that actually exists / is on PATH, else None."""
    for lo in LO_PATHS:
        if shutil.which(lo) or Path(lo).exists():
            return lo
    return None


def _valid_pdf(path: Path) -> bool:
    """True if the PDF exists and is larger than a no-op stub."""
    try:
        return path.exists() and path.stat().st_size > MIN_PDF_BYTES
    except OSError:
        return False


def _docx_lock_path(docx_path: Path) -> Path:
    """LibreOffice's per-document lock file (``.~lock.<name>#``) beside the DOCX."""
    return docx_path.parent / f".~lock.{docx_path.name}#"


def _clear_lock_state(docx_path: Path, profile_dir: Path) -> None:
    """Best-effort removal of stray LibreOffice lock state before the retry.

    Only touches state WE own: the isolated per-call profile dir we created and
    the input DOCX's own lock file. Never a shared/global profile or another
    process's lock, so this is safe to call while sibling conversions run.
    """
    lock = _docx_lock_path(docx_path)
    try:
        if lock.exists():
            lock.unlink()
    except OSError:
        pass
    shutil.rmtree(profile_dir, ignore_errors=True)


def _new_profile_dir() -> Path:
    """A unique, isolated LibreOffice user-profile dir for one conversion.

    UUID-suffixed (not just PID) so concurrent conversions in the SAME process
    never share a profile and therefore never contend on its lock.
    """
    return Path(tempfile.gettempdir()) / f"lo_profile_{os.getpid()}_{uuid.uuid4().hex}"


def _run_soffice(lo: str, docx_path: Path, output_dir: Path,
                 profile_dir: Path) -> subprocess.CompletedProcess | None:
    """Run one headless LibreOffice conversion. Return the result, or None if the
    process could not be launched / timed out."""
    user_install = f"-env:UserInstallation=file://{profile_dir}"
    try:
        return subprocess.run(
            [lo, user_install, "--headless", "--convert-to", "pdf",
             "--outdir", str(output_dir), str(docx_path)],
            capture_output=True, text=True, timeout=_SOFFICE_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def docx_to_pdf(docx_path: Path, output_dir: Path, stem: str) -> Path | None:
    """Convert docx_path to <output_dir>/<stem>.pdf. Return the PDF path or None.

    Tries LibreOffice headless first (detect + single retry on the silent-skip
    flake), then docx2pdf. LibreOffice names its output after the input file
    stem, so we rename to the desired stem when they differ.

    Raises PdfConversionError if LibreOffice is available but fails to produce a
    valid PDF even after the retry (never a silent skip). Returns None only when
    no converter is available at all.
    """
    docx_path, output_dir = Path(docx_path), Path(output_dir)
    pdf_path = output_dir / f"{stem}.pdf"
    produced = output_dir / f"{docx_path.stem}.pdf"

    lo = _find_soffice()
    if lo is not None:
        attempts = 2  # first try + one retry
        result = None
        for attempt in range(attempts):
            profile_dir = _new_profile_dir()
            result = _run_soffice(lo, docx_path, output_dir, profile_dir)
            ok = (result is not None and result.returncode == 0
                  and _valid_pdf(produced))
            if ok:
                shutil.rmtree(profile_dir, ignore_errors=True)
                if produced != pdf_path:
                    produced.replace(pdf_path)
                return pdf_path
            # Failed: transient lock / first-run no-op / launch failure. Clear
            # any stray lock state we created and retry once after a short wait.
            _clear_lock_state(docx_path, profile_dir)
            if attempt + 1 < attempts:
                time.sleep(RETRY_BACKOFF_S)

        stderr = (result.stderr or "").strip() if result is not None else "<soffice did not run>"
        raise PdfConversionError(
            f"LibreOffice ({lo}) exited without producing a valid PDF for "
            f"{docx_path} after {attempts} attempts "
            f"(expected {produced} to exist and exceed {MIN_PDF_BYTES} bytes). "
            f"This is the known silent-skip / lock / first-run flake: the DOCX "
            f"rendered but the PDF did not. Last soffice stderr: {stderr!r}. "
            f"Retry the render, or convert manually:\n"
            f"  {lo} --headless --convert-to pdf --outdir {output_dir} {docx_path}")

    # No LibreOffice anywhere — try docx2pdf (Word), else report unavailable.
    try:
        from docx2pdf import convert
        convert(str(docx_path), str(pdf_path))
        if _valid_pdf(pdf_path):
            return pdf_path
    except ImportError:
        pass
    except Exception as e:
        print(f"  docx2pdf failed: {e}", file=sys.stderr)

    return None


def docx_to_pdf_many(jobs: list[tuple[Path, Path, str]],
                     max_workers: int | None = None) -> list[Path | None]:
    """Convert several DOCX -> PDF concurrently, one isolated LibreOffice per job.

    ``jobs`` is a list of ``(docx_path, output_dir, stem)`` tuples; the returned
    list holds each job's PDF path (or None) in the SAME order. Because every
    ``docx_to_pdf`` call uses its own UUID-isolated user profile, the underlying
    LibreOffice processes run in parallel without contending on a shared profile
    lock. subprocess.run releases the GIL while soffice runs, so the thread pool
    yields real wall-clock parallelism across separate soffice processes.

    Falls back to serial when there is a single job, or when no LibreOffice is
    available (the docx2pdf fallback is not necessarily process-safe to run
    concurrently). Propagates the first PdfConversionError raised by any job
    after all launched conversions have drained (no orphaned soffice processes).
    """
    if not jobs:
        return []
    if len(jobs) == 1 or _find_soffice() is None:
        return [docx_to_pdf(*job) for job in jobs]

    if max_workers is None:
        max_workers = len(jobs)

    results: list[Path | None] = [None] * len(jobs)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(docx_to_pdf, *job) for job in jobs]
        first_error: BaseException | None = None
        for i, fut in enumerate(futures):
            try:
                results[i] = fut.result()
            except BaseException as exc:  # drain the rest before re-raising
                if first_error is None:
                    first_error = exc
    if first_error is not None:
        raise first_error
    return results
