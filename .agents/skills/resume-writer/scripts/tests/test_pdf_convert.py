"""Unit tests for pdf_convert: the silent-skip detect+retry flake fix (Item 2)
and the parallel multi-conversion helper (Item 3).

All LibreOffice invocations are mocked — no real soffice runs — by patching
``pdf_convert._find_soffice`` (pretend a binary exists) and
``pdf_convert._run_soffice`` (simulate what that binary does to the output dir).
"""

from __future__ import annotations

import collections
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import pdf_convert  # noqa: E402

FAKE_SOFFICE = "/fake/soffice"
BIG_PDF = b"%PDF-1.4\n" + b"x" * 4000  # comfortably > MIN_PDF_BYTES
TINY_PDF = b"%PDF"                      # < MIN_PDF_BYTES (no-op stub)


class FakeSoffice:
    """Stand-in for ``_run_soffice``, keyed by input-DOCX stem.

    ``by_stem`` maps a docx stem to a list of per-attempt behaviors, each one of:
      'valid'      -> exit 0 and write a real (> MIN_PDF_BYTES) PDF
      'skip'       -> exit 0 but write NOTHING (the silent-skip flake)
      'tiny'       -> exit 0 but write a < MIN_PDF_BYTES stub PDF
      'launchfail' -> could not launch / timed out (returns None)
      'error'      -> non-zero exit, no PDF
    The last behavior repeats if there are more attempts than entries.
    """

    def __init__(self, by_stem: dict[str, list[str]]):
        self.by_stem = {k: list(v) for k, v in by_stem.items()}
        self.calls: collections.Counter = collections.Counter()
        self._lock = threading.Lock()

    def __call__(self, lo, docx_path, output_dir, profile_dir):
        stem = Path(docx_path).stem
        with self._lock:
            self.calls[stem] += 1
            seq = self.by_stem[stem]
            behavior = seq[min(self.calls[stem] - 1, len(seq) - 1)]
        produced = Path(output_dir) / f"{stem}.pdf"
        if behavior == "valid":
            produced.write_bytes(BIG_PDF)
            return types.SimpleNamespace(returncode=0, stderr="")
        if behavior == "tiny":
            produced.write_bytes(TINY_PDF)
            return types.SimpleNamespace(returncode=0, stderr="")
        if behavior == "skip":
            return types.SimpleNamespace(returncode=0, stderr="")
        if behavior == "error":
            return types.SimpleNamespace(returncode=1, stderr="boom")
        if behavior == "launchfail":
            return None
        raise AssertionError(f"unknown behavior {behavior!r}")


class PdfConvertTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(_rmtree, self.tmp)
        (self.tmp / "source").mkdir()
        self.docx = self.tmp / "source" / "Resume.docx"
        self.docx.write_bytes(b"PK\x03\x04 fake docx")
        # Neutralize the retry backoff so tests are instant.
        p = mock.patch.object(pdf_convert.time, "sleep", lambda *_: None)
        p.start()
        self.addCleanup(p.stop)
        p2 = mock.patch.object(pdf_convert, "_find_soffice", lambda: FAKE_SOFFICE)
        p2.start()
        self.addCleanup(p2.stop)

    def _patch_soffice(self, fake: FakeSoffice):
        p = mock.patch.object(pdf_convert, "_run_soffice", fake)
        p.start()
        self.addCleanup(p.stop)
        return fake


def _rmtree(path: Path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


class SingleConversionTests(PdfConvertTestBase):
    def test_success_first_try(self):
        fake = self._patch_soffice(FakeSoffice({"Resume": ["valid"]}))
        out = pdf_convert.docx_to_pdf(self.docx, self.tmp, "Resume")
        self.assertEqual(out, self.tmp / "Resume.pdf")
        self.assertTrue(out.exists())
        self.assertEqual(fake.calls["Resume"], 1)  # no retry needed

    def test_success_renames_to_requested_stem(self):
        # LibreOffice writes <docx-stem>.pdf; docx_to_pdf renames to <stem>.pdf.
        self._patch_soffice(FakeSoffice({"Resume": ["valid"]}))
        out = pdf_convert.docx_to_pdf(self.docx, self.tmp, "Jordan_Rivers_Resume")
        self.assertEqual(out, self.tmp / "Jordan_Rivers_Resume.pdf")
        self.assertTrue(out.exists())
        self.assertFalse((self.tmp / "Resume.pdf").exists())

    def test_skip_then_retry_success(self):
        # First invocation silently no-ops (exit 0, no PDF); retry succeeds.
        fake = self._patch_soffice(FakeSoffice({"Resume": ["skip", "valid"]}))
        out = pdf_convert.docx_to_pdf(self.docx, self.tmp, "Resume")
        self.assertEqual(out, self.tmp / "Resume.pdf")
        self.assertTrue(out.exists())
        self.assertEqual(fake.calls["Resume"], 2)  # exactly one retry

    def test_tiny_pdf_is_treated_as_skip_then_retry(self):
        # A sub-1KB stub PDF counts as invalid (a no-op), so it retries.
        fake = self._patch_soffice(FakeSoffice({"Resume": ["tiny", "valid"]}))
        out = pdf_convert.docx_to_pdf(self.docx, self.tmp, "Resume")
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, pdf_convert.MIN_PDF_BYTES)
        self.assertEqual(fake.calls["Resume"], 2)

    def test_hard_fail_raises_after_single_retry(self):
        fake = self._patch_soffice(FakeSoffice({"Resume": ["skip", "skip"]}))
        with self.assertRaises(pdf_convert.PdfConversionError) as ctx:
            pdf_convert.docx_to_pdf(self.docx, self.tmp, "Resume")
        self.assertEqual(fake.calls["Resume"], 2)  # first try + one retry, no more
        msg = str(ctx.exception)
        self.assertIn("without producing a valid PDF", msg)
        self.assertIn("--convert-to pdf", msg)  # actionable manual command
        self.assertFalse((self.tmp / "Resume.pdf").exists())

    def test_tiny_pdf_hard_fail_never_returns_stub(self):
        self._patch_soffice(FakeSoffice({"Resume": ["tiny", "tiny"]}))
        with self.assertRaises(pdf_convert.PdfConversionError):
            pdf_convert.docx_to_pdf(self.docx, self.tmp, "Resume")

    def test_launch_failure_then_success(self):
        fake = self._patch_soffice(FakeSoffice({"Resume": ["launchfail", "valid"]}))
        out = pdf_convert.docx_to_pdf(self.docx, self.tmp, "Resume")
        self.assertTrue(out.exists())
        self.assertEqual(fake.calls["Resume"], 2)

    def test_lock_state_cleared_before_retry(self):
        # A stray per-document lock file must be removed before the retry.
        lock = pdf_convert._docx_lock_path(self.docx)
        lock.write_text("stale")
        cleared = {"seen": None}
        real_run = FakeSoffice({"Resume": ["skip", "valid"]})

        def watching_run(lo, docx_path, output_dir, profile_dir):
            # Record whether the lock survived into the 2nd (retry) call.
            if real_run.calls["Resume"] == 1:  # about to run the retry
                cleared["seen"] = lock.exists()
            return real_run(lo, docx_path, output_dir, profile_dir)

        self._patch_soffice(watching_run)
        out = pdf_convert.docx_to_pdf(self.docx, self.tmp, "Resume")
        self.assertTrue(out.exists())
        self.assertFalse(cleared["seen"])  # lock gone before the retry ran

    def test_no_converter_available_returns_none(self):
        # No LibreOffice and no docx2pdf -> legitimate None (install a converter),
        # NOT a raised flake.
        with mock.patch.object(pdf_convert, "_find_soffice", lambda: None), \
                mock.patch.dict(sys.modules, {"docx2pdf": None}):
            out = pdf_convert.docx_to_pdf(self.docx, self.tmp, "Resume")
        self.assertIsNone(out)


class ManyConversionTests(PdfConvertTestBase):
    def _cover(self, name: str) -> Path:
        p = self.tmp / "source" / f"{name}.docx"
        p.write_bytes(b"PK\x03\x04 fake docx")
        return p

    def test_empty_jobs(self):
        self.assertEqual(pdf_convert.docx_to_pdf_many([]), [])

    def test_parallel_all_succeed_order_preserved(self):
        cover = self._cover("Cover_A")
        self._patch_soffice(FakeSoffice({"Resume": ["valid"], "Cover_A": ["valid"]}))
        jobs = [(self.docx, self.tmp, "Resume"), (cover, self.tmp, "Cover_A")]
        results = pdf_convert.docx_to_pdf_many(jobs)
        self.assertEqual(results, [self.tmp / "Resume.pdf", self.tmp / "Cover_A.pdf"])
        self.assertTrue(all(p.exists() for p in results))

    def test_parallel_one_hard_fail_propagates(self):
        cover = self._cover("Cover_A")
        # Resume converts fine; the cover letter silently skips both attempts.
        self._patch_soffice(FakeSoffice(
            {"Resume": ["valid"], "Cover_A": ["skip", "skip"]}))
        jobs = [(self.docx, self.tmp, "Resume"), (cover, self.tmp, "Cover_A")]
        with self.assertRaises(pdf_convert.PdfConversionError):
            pdf_convert.docx_to_pdf_many(jobs)

    def test_parallel_retries_each_job_independently(self):
        cover = self._cover("Cover_A")
        fake = self._patch_soffice(FakeSoffice(
            {"Resume": ["skip", "valid"], "Cover_A": ["valid"]}))
        jobs = [(self.docx, self.tmp, "Resume"), (cover, self.tmp, "Cover_A")]
        results = pdf_convert.docx_to_pdf_many(jobs)
        self.assertTrue(all(p and p.exists() for p in results))
        self.assertEqual(fake.calls["Resume"], 2)
        self.assertEqual(fake.calls["Cover_A"], 1)


if __name__ == "__main__":
    unittest.main()
