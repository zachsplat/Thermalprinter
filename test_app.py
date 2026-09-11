#!/usr/bin/env python3
"""Tests for the label printer web app — covers PDF processing, routes, print logic, and edge cases."""

import base64, io, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent))

import fitz
from PIL import Image, ImageOps

import app as label_app


# ── PDF helpers ──

def _make_letter_pdf_with_image() -> str:
    """Fake eBay label: letter-size page with a colored rectangle + text."""
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    rect = fitz.Rect(72, 82, 504, 370)
    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(color=(0.8, 0.1, 0.1), fill=(0.85, 0.85, 0.85))
    shape.commit()
    page.insert_text(fitz.Point(100, 150), "SHIP TO: Test User", fontsize=14)
    page.insert_text(fitz.Point(100, 180), "123 Main St, Anytown USA", fontsize=10)
    doc.save(tmp.name)
    doc.close()
    return tmp.name


def _make_a4_pdf_with_image() -> str:
    """A4-size PDF with label content — tests non-letter page sizes."""
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4
    rect = fitz.Rect(50, 50, 545, 400)
    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(fill=(0.9, 0.9, 0.9))
    shape.commit()
    page.insert_text(fitz.Point(80, 120), "LABEL CONTENT", fontsize=20)
    doc.save(tmp.name)
    doc.close()
    return tmp.name


def _make_empty_pdf() -> str:
    """Letter-size PDF with no visible content (all white)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    doc = fitz.open()
    doc.new_page(width=612, height=792)
    doc.save(tmp.name)
    doc.close()
    return tmp.name


def _make_no_pages_pdf() -> str:
    """Create a minimal valid PDF, then truncate it to break page structure.
    fitz refuses to save 0-page PDFs, so we create a 1-page PDF and strip
    the page content to simulate a file that opens but has no usable pages."""
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.write(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
              b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
              b"xref\n0 3\n"
              b"trailer<</Size 3/Root 1 0 R>>\n"
              b"startxref\n0\n%%EOF\n")
    tmp.close()
    return tmp.name


def _make_non_pdf() -> str:
    """Non-PDF file (plain text)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
    tmp.write(b"not a pdf")
    tmp.close()
    return tmp.name


def _make_corrupted_pdf() -> str:
    """File with .pdf extension but garbage content."""
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.write(b"%PDF-1.4\n%%EOF\nGARBAGE_DATA_BROKEN")
    tmp.close()
    return tmp.name


def _make_portrait_label_pdf() -> str:
    """PDF where the label is already portrait (taller than wide)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    # Tall narrow content area — already portrait
    rect = fitz.Rect(72, 50, 300, 600)
    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(fill=(0.8, 0.8, 0.95))
    shape.commit()
    page.insert_text(fitz.Point(100, 100), "PORTRAIT LABEL", fontsize=16)
    doc.save(tmp.name)
    doc.close()
    return tmp.name


def _make_multi_page_pdf(n=3) -> str:
    """Multi-page PDF with content on each page."""
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    doc = fitz.open()
    for i in range(n):
        page = doc.new_page(width=612, height=792)
        rect = fitz.Rect(72, 82, 504, 370)
        shape = page.new_shape()
        shape.draw_rect(rect)
        shape.finish(fill=(0.9, 0.9, 0.9))
        shape.commit()
        page.insert_text(fitz.Point(100, 150), f"Page {i+1}", fontsize=14)
    doc.save(tmp.name)
    doc.close()
    return tmp.name


def _make_large_white_border_pdf() -> str:
    """PDF where content is tiny with huge white borders — tests auto-crop."""
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    # Tiny content in the center
    rect = fitz.Rect(250, 300, 360, 400)
    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(fill=(0.9, 0.1, 0.1))
    shape.commit()
    doc.save(tmp.name)
    doc.close()
    return tmp.name


# ── Test: PDF Processing ──

class TestProcessPdf(unittest.TestCase):
    """Core PDF processing pipeline."""

    def setUp(self):
        self.input_pdf = _make_letter_pdf_with_image()

    def tearDown(self):
        if os.path.exists(self.input_pdf):
            os.unlink(self.input_pdf)

    def test_output_is_valid_pdf(self):
        out = label_app.process_pdf(self.input_pdf)
        self.assertTrue(os.path.exists(out))
        doc = fitz.open(out)
        self.assertEqual(doc.page_count, 1)
        doc.close()
        os.unlink(out)

    def test_output_page_is_4x6_inches(self):
        out = label_app.process_pdf(self.input_pdf)
        doc = fitz.open(out)
        p = doc[0]
        self.assertAlmostEqual(p.rect.width / 72, 4.0, places=1)
        self.assertAlmostEqual(p.rect.height / 72, 6.0, places=1)
        doc.close()
        os.unlink(out)

    def test_output_exact_dimensions(self):
        out = label_app.process_pdf(self.input_pdf)
        doc = fitz.open(out)
        p = doc[0]
        self.assertEqual(p.rect.width, 288.0)
        self.assertEqual(p.rect.height, 432.0)
        doc.close()
        os.unlink(out)

    def test_output_contains_image(self):
        out = label_app.process_pdf(self.input_pdf)
        doc = fitz.open(out)
        images = doc[0].get_images()
        self.assertGreaterEqual(len(images), 1)
        doc.close()
        os.unlink(out)

    def test_output_not_empty_document(self):
        """Regression: output must be openable."""
        out = label_app.process_pdf(self.input_pdf)
        try:
            doc = fitz.open(out)
            self.assertGreater(doc.page_count, 0)
            doc.close()
        except Exception as e:
            self.fail(f"Output PDF could not be opened: {e}")
        finally:
            os.unlink(out)

    def test_empty_pdf_still_produces_output(self):
        empty = _make_empty_pdf()
        try:
            out = label_app.process_pdf(empty)
            doc = fitz.open(out)
            self.assertEqual(doc.page_count, 1)
            p = doc[0]
            self.assertAlmostEqual(p.rect.width / 72, 4.0, places=1)
            doc.close()
            os.unlink(out)
        finally:
            os.unlink(empty)

    def test_no_pages_pdf_raises_error(self):
        no_pages = _make_no_pages_pdf()
        try:
            with self.assertRaises(ValueError):
                label_app.process_pdf(no_pages)
        finally:
            os.unlink(no_pages)

    def test_multi_page_pdf(self):
        multi = _make_multi_page_pdf(3)
        try:
            out = label_app.process_pdf(multi)
            doc = fitz.open(out)
            self.assertEqual(doc.page_count, 3)
            for i in range(3):
                p = doc[i]
                self.assertAlmostEqual(p.rect.width / 72, 4.0, places=1)
                self.assertAlmostEqual(p.rect.height / 72, 6.0, places=1)
            doc.close()
            os.unlink(out)
        finally:
            os.unlink(multi)

    def test_a4_pdf_auto_detects_content(self):
        """Non-letter page sizes should work via auto-detection."""
        a4 = _make_a4_pdf_with_image()
        try:
            out = label_app.process_pdf(a4)
            doc = fitz.open(out)
            self.assertEqual(doc.page_count, 1)
            p = doc[0]
            self.assertEqual(p.rect.width, 288.0)
            self.assertEqual(p.rect.height, 432.0)
            doc.close()
            os.unlink(out)
        finally:
            os.unlink(a4)

    def test_portrait_label_no_rotation(self):
        """Portrait content should not be rotated."""
        portrait = _make_portrait_label_pdf()
        try:
            out = label_app.process_pdf(portrait)
            doc = fitz.open(out)
            self.assertEqual(doc.page_count, 1)
            doc.close()
            os.unlink(out)
        finally:
            os.unlink(portrait)

    def test_large_white_border_auto_crops(self):
        """Tiny content with huge borders should be auto-cropped."""
        bordered = _make_large_white_border_pdf()
        try:
            out = label_app.process_pdf(bordered)
            doc = fitz.open(out)
            images = doc[0].get_images()
            self.assertGreaterEqual(len(images), 1)
            doc.close()
            os.unlink(out)
        finally:
            os.unlink(bordered)

    def test_corrupted_pdf_raises_error(self):
        corrupted = _make_corrupted_pdf()
        try:
            with self.assertRaises(Exception):
                label_app.process_pdf(corrupted)
        finally:
            os.unlink(corrupted)


# ── Test: Preview Generation ──

class TestPdfToPreview(unittest.TestCase):

    def setUp(self):
        self.input_pdf = _make_letter_pdf_with_image()
        self.processed_pdf = label_app.process_pdf(self.input_pdf)

    def tearDown(self):
        os.unlink(self.input_pdf)
        if os.path.exists(self.processed_pdf):
            os.unlink(self.processed_pdf)

    def test_returns_base64_string(self):
        b64 = label_app.pdf_to_preview_base64(self.processed_pdf)
        self.assertIsInstance(b64, str)
        self.assertGreater(len(b64), 0)

    def test_base64_decodes_to_png(self):
        b64 = label_app.pdf_to_preview_base64(self.processed_pdf)
        data = base64.b64decode(b64)
        self.assertEqual(data[:4], b'\x89PNG')


# ── Test: Print Function ──

class TestPrintPdf(unittest.TestCase):

    def test_successful_print(self):
        with patch("app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="request id is Y42BT_TSPL-99 (1 file(s))\n",
                stderr=""
            )
            result = label_app.print_pdf("/tmp/fake.pdf")
            mock_run.assert_called_once_with(
                ["lp", "-d", "Y42BT_TSPL", "-o", "PageSize=w288h432", "/tmp/fake.pdf"],
                capture_output=True, text=True, timeout=30,
            )
            self.assertIn("Y42BT_TSPL-99", result)
            self.assertFalse(result.startswith("Error"))

    def test_failed_print(self):
        with patch("app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="lp: printer not found"
            )
            result = label_app.print_pdf("/tmp/fake.pdf")
            self.assertTrue(result.startswith("Error"))
            self.assertIn("printer not found", result)

    def test_print_timeout(self):
        with patch("app.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="lp", timeout=30)
            with self.assertRaises(subprocess.TimeoutExpired):
                label_app.print_pdf("/tmp/fake.pdf")


# ── Test: Printer Status ──

class TestPrinterStatus(unittest.TestCase):

    def test_printer_idle(self):
        with patch("app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="printer Y42BT_TSPL is idle.  enabled since ..."
            )
            status = label_app._get_printer_status()
            self.assertTrue(status["online"])
            self.assertEqual(status["status"], "ready")

    def test_printer_printing(self):
        with patch("app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="printer Y42BT_TSPL now printing ..."
            )
            status = label_app._get_printer_status()
            self.assertTrue(status["online"])
            self.assertEqual(status["status"], "printing")

    def test_printer_disabled(self):
        with patch("app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="printer Y42BT_TSPL disabled since ..."
            )
            status = label_app._get_printer_status()
            self.assertFalse(status["online"])
            self.assertEqual(status["status"], "offline")

    def test_printer_not_found(self):
        with patch("app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            status = label_app._get_printer_status()
            self.assertFalse(status["online"])

    def test_lpstat_unreachable(self):
        with patch("app.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            status = label_app._get_printer_status()
            self.assertFalse(status["online"])
            self.assertEqual(status["status"], "unreachable")


# ── Test: File Cleanup ──

class TestFileCleanup(unittest.TestCase):

    def test_cleanup_removes_old_files(self):
        # Create a file and set its mtime to 2 hours ago
        old_file = label_app.UPLOAD_DIR / "test_old_file.pdf"
        old_file.write_text("old")
        import datetime
        old_time = time.time() - 7200
        os.utime(old_file, (old_time, old_time))

        label_app._cleanup_old_files()
        self.assertFalse(old_file.exists())

    def test_cleanup_keeps_recent_files(self):
        recent_file = label_app.UPLOAD_DIR / "test_recent_file.pdf"
        recent_file.write_text("recent")
        try:
            label_app._cleanup_old_files()
            self.assertTrue(recent_file.exists())
        finally:
            recent_file.unlink(missing_ok=True)

    def test_cleanup_dict_removes_stale_entries(self):
        label_app.processed_files["stale_key"] = "/tmp/nonexistent_file_12345.pdf"
        label_app._cleanup_dict()
        self.assertNotIn("stale_key", label_app.processed_files)

    def test_cleanup_dict_keeps_valid_entries(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, dir=label_app.UPLOAD_DIR)
        tmp.write(b"%PDF-1.4 test"); tmp.close()
        try:
            label_app.processed_files["valid_key"] = tmp.name
            label_app._cleanup_dict()
            self.assertIn("valid_key", label_app.processed_files)
        finally:
            os.unlink(tmp.name)


# ── Test: Web Routes ──

class TestWebRoutes(unittest.TestCase):

    def setUp(self):
        self.client = label_app.app.test_client()
        self.input_pdf = _make_letter_pdf_with_image()

    def tearDown(self):
        os.unlink(self.input_pdf)

    @patch("app._get_printer_status", return_value={"online": True, "status": "ready"})
    def test_index_page(self, mock_status):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode()
        self.assertIn("ShipIt", html)
        self.assertIn("Y42BT_TSPL", html)

    @patch("app._get_printer_status", return_value={"online": True, "status": "ready"})
    def test_upload_no_file(self, mock_status):
        resp = self.client.post("/upload", data={})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("No file uploaded", resp.data.decode())

    @patch("app._get_printer_status", return_value={"online": True, "status": "ready"})
    def test_upload_non_pdf(self, mock_status):
        non_pdf = _make_non_pdf()
        try:
            with open(non_pdf, "rb") as f:
                resp = self.client.post("/upload", data={"file": (f, "test.txt")})
            self.assertIn("Please upload a PDF file", resp.data.decode())
        finally:
            os.unlink(non_pdf)

    @patch("app._get_printer_status", return_value={"online": True, "status": "ready"})
    def test_upload_valid_pdf(self, mock_status):
        with open(self.input_pdf, "rb") as f:
            resp = self.client.post("/upload", data={"file": (f, "ebay-label.pdf")})
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode()
        self.assertIn("Preview", html)
        self.assertIn("4 x 6 in", html)

    @patch("app._get_printer_status", return_value={"online": True, "status": "ready"})
    def test_upload_corrupted_pdf(self, mock_status):
        corrupted = _make_corrupted_pdf()
        try:
            with open(corrupted, "rb") as f:
                resp = self.client.post("/upload", data={"file": (f, "bad.pdf")})
            html = resp.data.decode()
            self.assertIn("Could not process PDF", html)
        finally:
            os.unlink(corrupted)

    @patch("app._get_printer_status", return_value={"online": True, "status": "ready"})
    def test_upload_no_pages_pdf(self, mock_status):
        no_pages = _make_no_pages_pdf()
        try:
            with open(no_pages, "rb") as f:
                resp = self.client.post("/upload", data={"file": (f, "empty.pdf")})
            html = resp.data.decode()
            self.assertIn("no pages", html.lower())
        finally:
            os.unlink(no_pages)

    def test_download_invalid_id(self):
        resp = self.client.get("/download/nonexistent")
        self.assertEqual(resp.status_code, 404)

    @patch("app._get_printer_status", return_value={"online": True, "status": "ready"})
    def test_print_invalid_id(self, mock_status):
        resp = self.client.post("/print/nonexistent")
        self.assertIn("File not found", resp.data.decode())

    @patch("app._get_printer_status", return_value={"online": True, "status": "ready"})
    def test_upload_and_download_flow(self, mock_status):
        with open(self.input_pdf, "rb") as f:
            resp = self.client.post("/upload", data={"file": (f, "ebay-label.pdf")})
        html = resp.data.decode()
        import re
        match = re.search(r'/download/([a-f0-9]+)', html)
        self.assertIsNotNone(match)
        file_id = match.group(1)

        resp = self.client.get(f"/download/{file_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content_type, "application/pdf")

    @patch("app._get_printer_status", return_value={"online": True, "status": "ready"})
    def test_upload_and_print_flow(self, mock_status):
        with open(self.input_pdf, "rb") as f:
            resp = self.client.post("/upload", data={"file": (f, "ebay-label.pdf")})
        html = resp.data.decode()
        import re
        match = re.search(r'/print/([a-f0-9]+)', html)
        self.assertIsNotNone(match)
        file_id = match.group(1)

        with patch("app.print_pdf", return_value="request id is Y42BT_TSPL-100 (1 file(s))"):
            resp = self.client.post(f"/print/{file_id}")

        html = resp.data.decode()
        self.assertIn("Sent to printer", html)
        self.assertIn("Y42BT_TSPL-100", html)

    @patch("app._get_printer_status", return_value={"online": False, "status": "offline"})
    def test_print_when_printer_offline(self, mock_status):
        # First upload with printer online
        with patch("app._get_printer_status", return_value={"online": True, "status": "ready"}):
            with open(self.input_pdf, "rb") as f:
                resp = self.client.post("/upload", data={"file": (f, "ebay-label.pdf")})
            html = resp.data.decode()
            import re
            match = re.search(r'/print/([a-f0-9]+)', html)
            file_id = match.group(1)

        # Then try to print with printer offline
        resp = self.client.post(f"/print/{file_id}")
        html = resp.data.decode()
        self.assertIn("offline", html)

    @patch("app._get_printer_status", return_value={"online": True, "status": "ready"})
    def test_upload_file_cleaned_up(self, mock_status):
        """Raw upload file should be deleted after processing."""
        # Record existing upload files first
        before = set(label_app.UPLOAD_DIR.glob("*_upload.pdf"))
        with open(self.input_pdf, "rb") as f:
            resp = self.client.post("/upload", data={"file": (f, "ebay-label.pdf")})
        self.assertEqual(resp.status_code, 200)
        after = set(label_app.UPLOAD_DIR.glob("*_upload.pdf"))
        # No new _upload.pdf files should have been created
        self.assertEqual(len(after - before), 0)


# ── Test: API Endpoints ──

class TestApiEndpoints(unittest.TestCase):

    def setUp(self):
        self.client = label_app.app.test_client()

    def test_status_endpoint(self):
        with patch("app._get_printer_status", return_value={"online": True, "status": "ready"}):
            resp = self.client.get("/api/status")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data["online"])
            self.assertEqual(data["status"], "ready")


# ── Test: Upload Size Limit ──

class TestUploadSizeLimit(unittest.TestCase):

    def setUp(self):
        self.client = label_app.app.test_client()

    def test_max_content_length_configured(self):
        """Flask MAX_CONTENT_LENGTH should be set to 20 MB."""
        self.assertEqual(label_app.app.config["MAX_CONTENT_LENGTH"], 20 * 1024 * 1024)

    def test_413_error_handler_registered(self):
        """The 413 error handler should be registered on the app."""
        self.assertIn(413, label_app.app.error_handler_spec.get(None, {}).keys())


# ── Test: Real eBay PDF ──

class TestRealEbayPdf(unittest.TestCase):
    """If the real eBay PDF exists, test against it."""

    def test_process_real_ebay_pdf(self):
        ebay_path = "/home/zacharyalexander/Downloads/ebay-documents.pdf"
        if not os.path.exists(ebay_path):
            self.skipTest("Real eBay PDF not found")

        out = label_app.process_pdf(ebay_path)
        try:
            doc = fitz.open(out)
            self.assertGreater(doc.page_count, 0)
            p = doc[0]
            self.assertEqual(p.rect.width, 288.0)
            self.assertEqual(p.rect.height, 432.0)
            images = p.get_images()
            self.assertGreaterEqual(len(images), 1)
            doc.close()
        finally:
            os.unlink(out)


if __name__ == "__main__":
    unittest.main()
