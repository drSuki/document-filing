"""Text extraction: direct text first, OCR only for pages with no usable text."""

import hashlib
import io
from pathlib import Path
from typing import NamedTuple

import pymupdf

MIN_CHARS_PER_PAGE = 25


class Extraction(NamedTuple):
    text: str
    method: str        # 'text' or 'ocr'
    page_count: int


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ocr_page(page, tesseract_cmd: str = "") -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    pixmap = page.get_pixmap(dpi=300)
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    return pytesseract.image_to_string(image, lang="eng")


def extract_text(path: Path, tesseract_cmd: str = "") -> Extraction:
    pages = []
    used_ocr = False
    with pymupdf.open(path) as pdf:
        for page in pdf:
            text = page.get_text("text") or ""
            if len(text.strip()) < MIN_CHARS_PER_PAGE:
                ocr_text = _ocr_page(page, tesseract_cmd)
                if len(ocr_text.strip()) > len(text.strip()):
                    text = ocr_text
                    used_ocr = True
            pages.append(text)
        count = pdf.page_count
    return Extraction("\n".join(pages), "ocr" if used_ocr else "text", count)
