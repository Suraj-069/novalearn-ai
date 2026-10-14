"""OCR via Tesseract (system binary) with graceful unavailability."""
import shutil

from PIL import Image

from app.core.binaries import find_system_binary
from app.core.config import get_settings
from app.services.providers.base import ProviderUnavailable

MIN_OCR_CONFIDENCE = 40  # drop words Tesseract itself is unsure about


def ocr_available() -> bool:
    return find_system_binary("tesseract") is not None


def ocr_image(img: Image.Image) -> str:
    if not ocr_available():
        raise ProviderUnavailable(
            "OCR needs Tesseract, which isn't installed. Install it (see README) and retry, "
            "or upload a text-based PDF."
        )
    import pytesseract

    tess = find_system_binary("tesseract")
    if tess is not None:
        pytesseract.pytesseract.tesseract_cmd = str(tess)

    img = img.convert("RGB")
    data = pytesseract.image_to_data(img, lang=get_settings().ocr_language, output_type=pytesseract.Output.DICT)
    lines: dict[tuple[int, int, int], list[str]] = {}
    for i, word in enumerate(data["text"]):
        word = word.strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if word and conf >= MIN_OCR_CONFIDENCE:
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(word)
    return "\n".join(" ".join(ws) for ws in lines.values())
