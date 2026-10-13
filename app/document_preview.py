"""Bounded, flattened reviewer previews. This deters export; it is not DRM.

PDFium is not thread-safe: decode in a short-lived resource-limited process.
Official APIs: https://pypdfium2.readthedocs.io/en/stable/python_api.html
https://pillow.readthedocs.io/en/stable/reference/Image.html
No original file, embedded metadata, PDF script, or raw fallback is returned.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import textwrap

MAX_INPUT = 3 * 1024 * 1024
MAX_OUTPUT = 3 * 1024 * 1024
MAX_PAGES = 12
MAX_PIXELS = 16_000_000
MAX_EDGE = 1600
TIMEOUT = 10
_SLOT = threading.BoundedSemaphore(1)  # per application worker, no unbounded queue


class PreviewError(Exception):
    def __init__(self, message="This document could not be previewed. Ask for a replacement.", status=422, code="document_preview_invalid"):
        super().__init__(message)
        self.status, self.code = status, code


def page_number(value):
    if type(value) is int and 1 <= value <= MAX_PAGES:
        return value
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]?", value) and int(value) <= MAX_PAGES:
        return int(value)
    raise PreviewError("Choose a valid document page.", 400, "document_preview_page_invalid")


def inspection_complete(rows, actor_id, application, documents):
    """Only successful current-version preview receipts count, including all PDF pages."""
    relevant = [r for r in rows if r.get("actor_id") == actor_id
                and r.get("application_id") == application["id"]
                and r.get("application_version") == application["version"]
                and r.get("mode") == "watermarked_preview"]
    for doc in documents:
        receipts = [r for r in relevant if r.get("document_id") == doc["id"]]
        counts = {r.get("page_count") for r in receipts if type(r.get("page_count")) is int}
        if len(counts) != 1:
            return False
        count = counts.pop()
        if not 1 <= count <= MAX_PAGES or {r.get("page") for r in receipts} != set(range(1, count + 1)):
            return False
    return True


def render_preview(content, content_type, page, reviewer_id, at):
    page = page_number(page)
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_INPUT:
        raise PreviewError()
    if content_type not in ("image/png", "image/jpeg", "application/pdf"):
        raise PreviewError()
    reviewer = re.sub(r"[^A-Za-z0-9_.-]", "_", str(reviewer_id))[:64]
    tag = hashlib.sha256(str(reviewer_id).encode()).hexdigest()[:8]
    watermark = f"SeatPal PRIVATE REVIEW | {reviewer} ({tag}) | {at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
    request = json.dumps({"content": base64.b64encode(content).decode(), "content_type": content_type,
                          "page": page, "watermark": watermark}).encode()
    if not _SLOT.acquire(blocking=False):
        raise PreviewError("A document preview is busy. Try again shortly.", 429, "document_preview_busy")
    try:
        # Output is capped both by the child's file-size limit and this bounded read.
        # Anonymous temporary storage is closed on every exit; originals use stdin only.
        with tempfile.TemporaryFile() as output:
            proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--render"],
                                    stdin=subprocess.PIPE, stdout=output, stderr=subprocess.DEVNULL,
                                    cwd="/", env={"PATH": os.defpath, "LANG": "C.UTF-8"}, close_fds=True)
            try:
                proc.communicate(request, timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                raise PreviewError("Document preview timed out. Try a smaller document.", 504, "document_preview_timeout") from None
            output.seek(0)
            encoded = output.read(MAX_OUTPUT + 1)
            if proc.returncode != 0 or len(encoded) > MAX_OUTPUT:
                raise PreviewError()
            try:
                result = json.loads(encoded)
            except (ValueError, UnicodeError):
                raise PreviewError() from None
            if result.get("error") == "page":
                raise PreviewError("That page does not exist.", 400, "document_preview_page_invalid")
            if (set(result) != {"image_data_url", "page", "page_count", "watermark"}
                    or result["page"] != page or type(result["page_count"]) is not int
                    or not page <= result["page_count"] <= MAX_PAGES
                    or result["watermark"] != watermark
                    or not isinstance(result["image_data_url"], str)
                    or not result["image_data_url"].startswith("data:image/jpeg;base64,")):
                raise PreviewError()
            return result
    except OSError:
        raise PreviewError("Document preview is unavailable. Try again later.", 503, "document_preview_unavailable") from None
    finally:
        _SLOT.release()


def _render(request):
    import warnings
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    raw = base64.b64decode(request["content"], validate=True)
    if not 0 < len(raw) <= MAX_INPUT:
        raise ValueError("input")
    page = page_number(request["page"])
    if request["content_type"] == "application/pdf":
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(raw) as document:
            count = len(document)
            if not 1 <= count <= MAX_PAGES:
                raise ValueError("pages")
            if page > count:
                return {"error": "page"}
            pdfpage = document[page - 1]
            try:
                width, height = pdfpage.get_size()
                if not all(math.isfinite(v) and 0 < v <= 14400 for v in (width, height)):
                    raise ValueError("dimensions")
                # Do not initialize JavaScript/XFA or execute document actions/forms.
                bitmap = pdfpage.render(scale=min(2, MAX_EDGE / max(width, height)), may_draw_forms=False)
                try:
                    picture = bitmap.to_pil().convert("RGB")
                finally:
                    bitmap.close()
            finally:
                pdfpage.close()
    else:
        count = 1
        if page != 1:
            return {"error": "page"}
        with Image.open(io.BytesIO(raw), formats=["PNG", "JPEG"]) as original:
            if original.width * original.height > MAX_PIXELS or getattr(original, "n_frames", 1) != 1:
                raise ValueError("dimensions")
            picture = ImageOps.exif_transpose(original).convert("RGBA")
            picture.thumbnail((MAX_EDGE, MAX_EDGE))
            white = Image.new("RGB", picture.size, "white")
            white.paste(picture, mask=picture.getchannel("A"))
            picture = white
    # Fresh RGB canvas drops EXIF, comments, ICC profiles and every source metadata field.
    picture.thumbnail((MAX_EDGE, MAX_EDGE))
    canvas = Image.new("RGB", (max(640, picture.width), max(320, picture.height)), "white")
    canvas.paste(picture, ((canvas.width - picture.width) // 2, (canvas.height - picture.height) // 2))
    overlay = Image.new("RGBA", canvas.size)
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default(size=17)
    lines = [line for part in request["watermark"].split(" | ") for line in textwrap.wrap(part, width=32)]
    for y in range(12, canvas.height, 170):
        for x in range(12, canvas.width, 680):
            for n, line in enumerate(lines):
                draw.text((x, y + n * 23), line, font=font, fill=(115, 25, 25, 125), stroke_width=1, stroke_fill=(255, 255, 255, 80))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    buffer = io.BytesIO()
    canvas.save(buffer, format="JPEG", quality=82, optimize=False)
    return {"image_data_url": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode(),
            "page": page, "page_count": count, "watermark": request["watermark"]}


def _worker():
    # Linux/macOS only: absence/failure of resource limits fails closed.
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (6, 6))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT, MAX_OUTPUT))
    request = sys.stdin.buffer.read(4 * MAX_INPUT // 3 + 4097)
    if len(request) > 4 * MAX_INPUT // 3 + 4096:
        raise ValueError("input")
    result = json.dumps(_render(json.loads(request))).encode()
    if len(result) > MAX_OUTPUT:
        raise ValueError("output")
    sys.stdout.buffer.write(result)


if __name__ == "__main__":
    try:
        _worker()
    except Exception:
        sys.exit(1)  # Never print document contents, metadata, paths or parser diagnostics.
