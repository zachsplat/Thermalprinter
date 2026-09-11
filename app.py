#!/usr/bin/env python3
"""Web app to convert eBay shipping label PDFs to 4x6 thermal label prints."""

import os, io, base64, subprocess, tempfile, uuid, time, logging
from pathlib import Path

from flask import Flask, request, send_file, render_template, jsonify

import fitz
from PIL import Image, ImageOps
import numpy as np

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB upload limit

UPLOAD_DIR = Path(tempfile.gettempdir()) / "label-printer-uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

PRINTER_NAME = "Y42BT_TSPL"
PAGE_SIZE = "w288h432"  # 4x6 inches
MAX_FILE_AGE_SECONDS = 3600  # Clean up files older than 1 hour

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _cleanup_old_files():
    """Remove uploaded/processed files older than MAX_FILE_AGE_SECONDS."""
    now = time.time()
    for f in UPLOAD_DIR.iterdir():
        if f.is_file() and (now - f.stat().st_mtime) > MAX_FILE_AGE_SECONDS:
            try:
                f.unlink()
            except OSError:
                pass


def _cleanup_dict():
    """Remove entries from processed_files whose files no longer exist."""
    stale = [k for k, v in processed_files.items() if not os.path.exists(v)]
    for k in stale:
        del processed_files[k]


def _get_printer_status() -> dict:
    """Check if the CUPS printer is available and idle."""
    try:
        result = subprocess.run(
            ["lpstat", "-p", PRINTER_NAME],
            capture_output=True, text=True, timeout=5,
        )
        output = result.stdout.strip()
        if "idle" in output or "ready" in output:
            return {"online": True, "status": "ready"}
        if "printing" in output:
            return {"online": True, "status": "printing"}
        if "disabled" in output or result.returncode != 0:
            return {"online": False, "status": "offline"}
        return {"online": True, "status": "unknown"}
    except Exception:
        return {"online": False, "status": "unreachable"}


def process_pdf(input_path: str) -> str:
    """Crop, rotate, and scale a shipping label PDF to 4x6 inches.
    Auto-detects the label region on any page size.
    Always rotates landscape content 90° CCW so it prints correctly
    on a portrait 4x6 thermal label.
    Returns path to the processed PDF."""
    src = fitz.open(input_path)

    if src.page_count == 0:
        src.close()
        raise ValueError("PDF has no pages")

    out_path = str(UPLOAD_DIR / f"{uuid.uuid4().hex}_4x6.pdf")
    dst = fitz.open()

    for page in src:
        # Render full page at 300 DPI
        pix = page.get_pixmap(dpi=300)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Auto-detect label region using numpy (finds actual dark pixels,
        # unlike invert().getbbox() which picks up white page backgrounds)
        arr = np.array(img.convert("L"))
        dark = arr < 200  # pixels darker than 200/255 = content
        rows = np.where(np.any(dark, axis=1))[0]
        cols = np.where(np.any(dark, axis=0))[0]

        if len(rows) > 0 and len(cols) > 0:
            pad = 30
            content_crop = (
                max(int(cols[0]) - pad, 0),
                max(int(rows[0]) - pad, 0),
                min(int(cols[-1]) + pad, img.width),
                min(int(rows[-1]) + pad, img.height),
            )
            img_cropped = img.crop(content_crop)
        else:
            img_cropped = img

        # If wider than tall, rotate 90° CCW for portrait 4x6 label
        if img_cropped.width > img_cropped.height:
            img_rot = img_cropped.rotate(90, expand=True)
        else:
            img_rot = img_cropped

        # Auto-trim white margins from rotated image using numpy
        arr_rot = np.array(img_rot.convert("L"))
        dark_rot = arr_rot < 200
        rows_rot = np.where(np.any(dark_rot, axis=1))[0]
        cols_rot = np.where(np.any(dark_rot, axis=0))[0]
        if len(rows_rot) > 0 and len(cols_rot) > 0:
            trim_pad = 10
            content_crop = (
                max(int(cols_rot[0]) - trim_pad, 0),
                max(int(rows_rot[0]) - trim_pad, 0),
                min(int(cols_rot[-1]) + trim_pad, img_rot.width),
                min(int(rows_rot[-1]) + trim_pad, img_rot.height),
            )
            img_trimmed = img_rot.crop(content_crop)
        else:
            img_trimmed = img_rot

        # Create 4x6 inch PDF page
        label_w_pts = 4 * 72   # 288
        label_h_pts = 6 * 72   # 432
        new_page = dst.new_page(width=label_w_pts, height=label_h_pts)

        # Scale image to fit inside 4x6 (contain, no distortion)
        img_w, img_h = img_trimmed.size
        dpi = 300
        label_px_w = int(label_w_pts * dpi / 72)   # 1200
        label_px_h = int(label_h_pts * dpi / 72)   # 1800
        scale = min(label_px_w / img_w, label_px_h / img_h)
        scaled_w = int(img_w * scale)
        scaled_h = int(img_h * scale)
        img_scaled = img_trimmed.resize((scaled_w, scaled_h), Image.LANCZOS)

        # Center on page
        x_pts = (label_w_pts - scaled_w * 72 / dpi) / 2
        y_pts = (label_h_pts - scaled_h * 72 / dpi) / 2
        rect = fitz.Rect(x_pts, y_pts,
                         x_pts + scaled_w * 72 / dpi,
                         y_pts + scaled_h * 72 / dpi)

        buf = io.BytesIO()
        img_scaled.save(buf, format="PNG")
        new_page.insert_image(rect, stream=buf.getvalue())

    dst.save(out_path)
    dst.close()
    src.close()
    return out_path


def print_pdf(pdf_path: str) -> str:
    """Send PDF to the thermal printer via CUPS."""
    result = subprocess.run(
        ["lp", "-d", PRINTER_NAME, "-o", f"PageSize={PAGE_SIZE}", pdf_path],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return f"Error: {result.stderr.strip()}"
    return result.stdout.strip()


def pdf_to_preview_base64(pdf_path: str) -> str:
    """Render first page of PDF as base64 PNG for preview."""
    doc = fitz.open(pdf_path)
    page = doc[0]
    pix = page.get_pixmap(dpi=150)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()
    doc.close()
    return b64


# Store processed files for download/print
processed_files: dict[str, str] = {}


@app.route("/")
def index():
    _cleanup_old_files()
    _cleanup_dict()
    printer = _get_printer_status()
    return render_template("index.html",
        preview=None, printed=False, error=None,
        printer_name=PRINTER_NAME, printer_info="",
        printer_status=printer,
    )


@app.route("/upload", methods=["POST"])
def upload():
    _cleanup_old_files()
    _cleanup_dict()
    printer = _get_printer_status()

    if "file" not in request.files:
        return render_template("index.html", preview=None, printed=False,
            error="No file uploaded",
            printer_name=PRINTER_NAME, printer_info="",
            printer_status=printer,
        )

    f = request.files["file"]
    if not f.filename or not f.filename.lower().endswith(".pdf"):
        return render_template("index.html", preview=None, printed=False,
            error="Please upload a PDF file",
            printer_name=PRINTER_NAME, printer_info="",
            printer_status=printer,
        )

    upload_path = str(UPLOAD_DIR / f"{uuid.uuid4().hex}_upload.pdf")
    f.save(upload_path)

    try:
        processed_path = process_pdf(upload_path)
    except ValueError as e:
        return render_template("index.html", preview=None, printed=False,
            error=str(e),
            printer_name=PRINTER_NAME, printer_info="",
            printer_status=printer,
        )
    except Exception as e:
        log.error("Processing error for %s: %s", upload_path, e)
        return render_template("index.html", preview=None, printed=False,
            error="Could not process PDF. Make sure it's a valid, unencrypted file.",
            printer_name=PRINTER_NAME, printer_info="",
            printer_status=printer,
        )
    finally:
        if os.path.exists(upload_path):
            os.unlink(upload_path)

    file_id = uuid.uuid4().hex[:8]
    processed_files[file_id] = processed_path

    preview = pdf_to_preview_base64(processed_path)
    return render_template("index.html", preview=preview, printed=False, error=None,
        printer_name=PRINTER_NAME, printer_info="", file_id=file_id,
        printer_status=printer,
    )


@app.route("/download/<file_id>")
def download(file_id):
    path = processed_files.get(file_id)
    if not path or not os.path.exists(path):
        return "File not found", 404
    return send_file(path, as_attachment=True, download_name="label_4x6.pdf")


@app.route("/print/<file_id>", methods=["POST"])
def print_label(file_id):
    printer = _get_printer_status()
    path = processed_files.get(file_id)
    if not path or not os.path.exists(path):
        return render_template("index.html", preview=None, printed=False,
            error="File not found",
            printer_name=PRINTER_NAME, printer_info="",
            printer_status=printer,
        )

    if not printer["online"]:
        return render_template("index.html", preview=pdf_to_preview_base64(path),
            printed=False, error=f"Printer is {printer['status']}. Check connection and try again.",
            printer_name=PRINTER_NAME, printer_info="", file_id=file_id,
            printer_status=printer,
        )

    result = print_pdf(path)
    preview = pdf_to_preview_base64(path)

    if result.startswith("Error"):
        return render_template("index.html", preview=preview, printed=False,
            error=result,
            printer_name=PRINTER_NAME, printer_info="", file_id=file_id,
            printer_status=printer,
        )

    return render_template("index.html", preview=preview, printed=True, error=None,
        printer_name=PRINTER_NAME, printer_info=result, file_id=file_id,
        printer_status=printer,
    )


@app.route("/api/status")
def api_status():
    """JSON endpoint for printer status."""
    return jsonify(_get_printer_status())


@app.errorhandler(413)
def request_entity_too_large(error):
    printer = _get_printer_status()
    return render_template("index.html", preview=None, printed=False,
        error="File too large. Maximum upload size is 20 MB.",
        printer_name=PRINTER_NAME, printer_info="",
        printer_status=printer,
    ), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
