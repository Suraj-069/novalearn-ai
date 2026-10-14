"""Content extraction with provenance. Each RawUnit knows exactly where its text came from.

Location fields that don't apply stay None. Nothing here is inferred or invented:
OCR text and model-written figure descriptions are flagged so the UI can label them.
"""
import io
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from app.core.config import get_settings
from app.services.ingestion.ocr import ocr_available, ocr_image
from app.services.providers.base import ProviderError, ProviderUnavailable, TranscriptSegment

log = logging.getLogger("novalearn.extract")


@dataclass
class RawUnit:
    text: str
    page: int | None = None
    slide: int | None = None
    start: float | None = None
    end: float | None = None
    figure_ref: str | None = None
    generated: bool = False      # True only for model-written descriptions (never for OCR/extracted text)
    timed: bool = False          # True for transcript cues (merged by time window)


@dataclass
class Extraction:
    units: list[RawUnit] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ExtractionError(Exception):
    """User-presentable extraction failure."""


MIN_PAGE_TEXT = 20
MIN_FIGURE_WIDTH_PX = 96
MIN_FIGURE_HEIGHT_PX = 72
MIN_FIGURE_AREA_RATIO = 0.02
MAX_FIGURE_AREA_RATIO = 0.85


def significant_figure(area_ratio: float, pixel_size: tuple[int, int]) -> bool:
    """Skip tiny/decorative assets and full-page scan backgrounds."""
    width, height = pixel_size
    return (MIN_FIGURE_AREA_RATIO <= area_ratio <= MAX_FIGURE_AREA_RATIO
            and width >= MIN_FIGURE_WIDTH_PX and height >= MIN_FIGURE_HEIGHT_PX
            and width * height >= 10_000)


def pdf_figure_objects(page):
    """Yield (1-based object index, image object) for substantial placed PDF figures."""
    import pypdfium2 as pdfium

    page_width, page_height = page.get_size()
    if page_width <= 0 or page_height <= 0:
        return
    objects = page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE])
    for index, image_obj in enumerate(objects, start=1):
        try:
            left, bottom, right, top = image_obj.get_bounds()
            area_ratio = max(0.0, right - left) * max(0.0, top - bottom) / (page_width * page_height)
            if significant_figure(area_ratio, image_obj.get_px_size()):
                yield index, image_obj
        except Exception:
            # Malformed or unsupported image objects should not fail text extraction.
            continue


def pptx_picture_is_figure(picture, slide_width: int, slide_height: int) -> bool:
    try:
        pixel_size = picture.image.size
        ratio = picture.width * picture.height / max(1, slide_width * slide_height)
        return significant_figure(ratio, pixel_size)
    except Exception:
        return False


def _image_object_to_pil(image_obj) -> Image.Image:
    bitmap = image_obj.get_bitmap(render=True, scale_to_original=True)
    try:
        return bitmap.to_pil().copy()
    finally:
        bitmap.close()


# ---------------- PDF ----------------
def extract_pdf(path: Path, llm=None) -> Extraction:
    from pypdf import PdfReader
    import pypdfium2 as pdfium

    out = Extraction()
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        reader.decrypt("")
    pdfium_doc = pdfium.PdfDocument(str(path))
    ocr_pages = 0
    skipped_ocr: list[int] = []
    figure_count = 0
    undescribed = 0
    vision_enabled = get_settings().vision_enabled
    try:
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = (page.extract_text() or "").strip()
            except Exception:
                text = ""
            if len(text) < MIN_PAGE_TEXT:
                if ocr_available():
                    ocr_text = ocr_image(pdfium_doc[i - 1].render(scale=2.5).to_pil()).strip()
                    if len(ocr_text) > len(text):  # keep the real text layer unless OCR actually found more
                        text = ocr_text
                        ocr_pages += 1
                elif not text:
                    skipped_ocr.append(i)
            if text:
                out.units.append(RawUnit(text=text, page=i))
            pdf_page = pdfium_doc[i - 1]
            for image_index, image_obj in pdf_figure_objects(pdf_page):
                figure_count += 1
                figure_ref = f"page{i}-img{image_index}"
                image = _image_object_to_pil(image_obj)
                if ocr_available():
                    figure_text = ocr_image(image).strip()
                    if len(figure_text) >= MIN_PAGE_TEXT:
                        out.units.append(RawUnit(text=f"Text in figure: {figure_text}", page=i, figure_ref=figure_ref))
                if vision_enabled and llm is not None:
                    description = describe_figure(llm, image)
                    if description:
                        out.units.append(RawUnit(text=description, page=i, figure_ref=figure_ref, generated=True))
                    else:
                        undescribed += 1
                else:
                    undescribed += 1
    finally:
        pdfium_doc.close()
    if ocr_pages:
        out.warnings.append(f"{ocr_pages} page(s) were read with OCR and may contain recognition errors.")
    if skipped_ocr:
        out.warnings.append(
            f"{len(skipped_ocr)} page(s) had no text layer and were skipped because Tesseract (OCR) isn't installed."
        )
    if figure_count and not ocr_available():
        out.warnings.append(f"{figure_count} figure(s) were not OCR'd because Tesseract (OCR) isn't installed.")
    if undescribed:
        reason = "VISION_ENABLED is false" if not vision_enabled else "no vision-capable LLM is configured or description failed"
        out.warnings.append(f"{undescribed} figure(s) have no model description because {reason}.")
    return out


# ---------------- PPTX ----------------
def _shape_text(shape) -> list[str]:
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    parts: list[str] = []
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        for s in shape.shapes:
            parts += _shape_text(s)
    elif getattr(shape, "has_table", False) and shape.has_table:
        for row in shape.table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    elif getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
        parts.append(shape.text_frame.text.strip())
    return parts


def _iter_pictures(shapes):
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for s in shapes:
        if s.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _iter_pictures(s.shapes)
        elif s.shape_type == MSO_SHAPE_TYPE.PICTURE:
            yield s


def extract_pptx(path: Path, llm=None) -> Extraction:
    from pptx import Presentation

    out = Extraction()
    prs = Presentation(str(path))
    ocr_ok = ocr_available()
    skipped_figs = 0
    figure_count = 0
    undescribed = 0
    vision_enabled = get_settings().vision_enabled
    slide_width, slide_height = prs.slide_width, prs.slide_height
    for n, slide in enumerate(prs.slides, start=1):
        body: list[str] = []
        for shape in slide.shapes:
            body += _shape_text(shape)
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            body.append("Speaker notes: " + slide.notes_slide.notes_text_frame.text.strip())
        if body:
            out.units.append(RawUnit(text="\n".join(body), slide=n))
        for k, pic in enumerate(_iter_pictures(slide.shapes), start=1):
            ref = f"slide{n}-img{k}"
            if not pptx_picture_is_figure(pic, slide_width, slide_height):
                continue
            figure_count += 1
            try:
                img = Image.open(io.BytesIO(pic.image.blob))
                img.load()
            except Exception:
                continue
            if ocr_ok:
                text = ocr_image(img).strip()
                if len(text) >= MIN_PAGE_TEXT:
                    out.units.append(RawUnit(text=f"Text in figure: {text}", slide=n, figure_ref=ref))
            else:
                skipped_figs += 1
            if vision_enabled and llm is not None:
                desc = describe_figure(llm, img)
                if desc:
                    out.units.append(RawUnit(text=desc, slide=n, figure_ref=ref, generated=True))
                else:
                    undescribed += 1
            else:
                undescribed += 1
    if skipped_figs:
        out.warnings.append(f"{skipped_figs} figure(s) were not read because Tesseract (OCR) isn't installed.")
    if undescribed:
        reason = "VISION_ENABLED is false" if not vision_enabled else "no vision-capable LLM is configured or description failed"
        out.warnings.append(f"{undescribed} figure(s) have no model description because {reason}.")
    return out


def describe_figure(llm, img: Image.Image) -> str | None:
    """Model-written figure description, clearly flagged as generated downstream. Failures are non-fatal."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    try:
        text = llm.describe_image(
            buf.getvalue(),
            "Describe this educational figure factually: what it shows, labels, axes, relationships. "
            "Do not speculate beyond what is visible. If it contains no educational content, reply NONE.",
        ).strip()
    except ProviderError as e:
        log.warning("Vision description failed: %s", e)
        return None
    return None if not text or text.upper().startswith("NONE") else f"AI description of figure: {text}"


# ---------------- Images ----------------
def extract_image(path: Path, llm=None, label: str | None = None) -> Extraction:
    label = label or path.name
    out = Extraction()
    img = Image.open(path)
    img.load()
    text = ocr_image(img).strip()
    if text:
        out.units.append(RawUnit(text=text, figure_ref=label))
    vision_enabled = get_settings().vision_enabled
    if vision_enabled and llm is not None:
        desc = describe_figure(llm, img)
        if desc:
            out.units.append(RawUnit(text=desc, figure_ref=label, generated=True))
        else:
            out.warnings.append("The image has no model description because vision description failed.")
    elif vision_enabled:
        out.warnings.append("The image has no model description because no vision-capable LLM is configured.")
    else:
        out.warnings.append("The image has no model description because VISION_ENABLED is false.")
    return out


# ---------------- Transcripts ----------------
_CUE = re.compile(r"(?:(\d{1,2}):)?(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(?:(\d{1,2}):)?(\d{2}):(\d{2})[.,](\d{3})")


def _secs(h, m, s, ms) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_cues(text: str) -> list[TranscriptSegment]:
    """Parse WebVTT/SRT into timestamped segments, preserving the original times."""
    cues: list[TranscriptSegment] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [l for l in block.strip().split("\n") if l.strip()]
        for idx, line in enumerate(lines):
            m = _CUE.search(line)
            if m:
                g = m.groups()
                body = " ".join(re.sub(r"<[^>]+>", "", l).strip() for l in lines[idx + 1:]).strip()
                if body:
                    cues.append(TranscriptSegment(_secs(*g[0:4]), _secs(*g[4:8]), body))
                break
    return cues


def extract_transcript(path: Path) -> Extraction:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    cues = parse_cues(text)
    out = Extraction()
    if cues:
        out.units = [RawUnit(text=c.text, start=c.start, end=c.end, timed=True) for c in cues]
    else:
        out.warnings.append("This transcript has no timestamps, so citations can't link to a video time.")
        for para in re.split(r"\n\s*\n", text):
            if para.strip():
                out.units.append(RawUnit(text=" ".join(para.split())))
    return out


# ---------------- Video ----------------
def extract_audio_wav(video: Path, dest: Path) -> None:
    from app.core.binaries import find_system_binary
    ffmpeg = find_system_binary("ffmpeg")
    if ffmpeg is None:
        raise ProviderUnavailable("FFmpeg isn't installed, so audio can't be extracted from this video (see README).")
    proc = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(dest)],
        capture_output=True, text=True, timeout=3600,
    )
    if proc.returncode != 0:
        raise ExtractionError("FFmpeg couldn't extract audio from this video.")


def extract_video(path: Path, stt) -> Extraction:
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "audio.wav"
        extract_audio_wav(path, wav)
        segments = stt.transcribe(str(wav))
    out = Extraction()
    out.units = [RawUnit(text=s.text, start=s.start, end=s.end, timed=True) for s in segments]
    if not out.units:
        out.warnings.append("No speech was detected in this video.")
    out.warnings.append(f"Transcribed automatically by {stt.name}; it may contain errors.")
    return out
