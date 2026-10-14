"""Structural inspection of uploaded files (Stage 2).

This records *facts* about a file (page count, slide count, duration, whether a
text layer exists). It does NOT extract content, run OCR, transcribe, chunk or
embed — that is Stage 3. Anything we cannot determine is left as None.
"""
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class InspectionError(Exception):
    """Raised with a user-presentable message when a file is unusable."""


@dataclass
class Inspection:
    page_count: int | None = None
    slide_count: int | None = None
    duration_seconds: float | None = None
    has_text_layer: bool | None = None
    meta: dict = field(default_factory=dict)


TEXT_SAMPLE_PAGES = 25
MIN_CHARS_FOR_TEXT_PAGE = 20


def inspect_pdf(path: Path) -> Inspection:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                ok = reader.decrypt("")
            except Exception:
                ok = 0
            if not ok:
                raise InspectionError("This PDF is password-protected. Remove the password and upload it again.")
        n = len(reader.pages)
    except PdfReadError as e:
        raise InspectionError(f"This PDF is corrupted or unreadable ({e}).") from e
    if n == 0:
        raise InspectionError("This PDF has no pages.")

    # Sample pages evenly so large textbooks stay fast.
    step = max(1, n // TEXT_SAMPLE_PAGES)
    sampled = list(range(0, n, step))[:TEXT_SAMPLE_PAGES]
    with_text = 0
    images = 0
    for i in sampled:
        page = reader.pages[i]
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if len(text.strip()) >= MIN_CHARS_FOR_TEXT_PAGE:
            with_text += 1
        try:
            images += len(page.images)
        except Exception:
            pass
    ratio = with_text / len(sampled)
    return Inspection(
        page_count=n,
        has_text_layer=ratio >= 0.5,
        meta={
            "pages_sampled": len(sampled),
            "sampled_pages_with_text": with_text,
            "sampled_images": images,
            "likely_scanned": ratio < 0.5,
            "needs_ocr": ratio < 0.5,
        },
    )


def inspect_pptx(path: Path) -> Inspection:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    try:
        prs = Presentation(str(path))
    except Exception as e:
        raise InspectionError(f"This PowerPoint file couldn't be opened ({e}).") from e
    slides = list(prs.slides)
    if not slides:
        raise InspectionError("This presentation has no slides.")
    pictures = 0
    slides_with_text = 0
    notes = 0
    for s in slides:
        has_text = False
        for shape in s.shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                pictures += 1
            if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
                has_text = True
        slides_with_text += has_text
        if s.has_notes_slide and s.notes_slide.notes_text_frame.text.strip():
            notes += 1
    return Inspection(
        slide_count=len(slides),
        has_text_layer=slides_with_text > 0,
        meta={"pictures": pictures, "slides_with_text": slides_with_text, "slides_with_notes": notes},
    )


def inspect_image(path: Path) -> Inspection:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = 100_000_000
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            w, h = im.size
            fmt = im.format
    except Exception as e:
        raise InspectionError(f"This image couldn't be decoded ({e}).") from e
    return Inspection(meta={"width": w, "height": h, "format": fmt, "needs_ocr": True})


from app.core.binaries import find_system_binary


def inspect_video(path: Path) -> Inspection:
    ffprobe = find_system_binary("ffprobe")
    if ffprobe is None:
        return Inspection(meta={
            "warning": "ffprobe was not found, so duration and audio track could not be checked. "
                       "Install FFmpeg (see README) before processing videos in Stage 3.",
            "ffprobe_available": False,
        })
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise InspectionError("FFmpeg could not read this video. It may be corrupted or use an unsupported codec.")
    info = json.loads(proc.stdout or "{}")
    streams = info.get("streams", [])
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise InspectionError("No video stream was found in this file.")
    if not has_audio:
        raise InspectionError("This video has no audio track, so there is nothing to transcribe.")
    try:
        duration = float(info.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    return Inspection(
        duration_seconds=duration,
        meta={
            "ffprobe_available": True,
            "width": video.get("width"),
            "height": video.get("height"),
            "video_codec": video.get("codec_name"),
            "has_audio": True,
        },
    )


_TS = re.compile(r"(\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}\s*-->\s*(\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}")


def inspect_transcript(path: Path) -> Inspection:
    text = path.read_text(encoding="utf-8", errors="replace")
    cues = len(_TS.findall(text))
    if not text.strip():
        raise InspectionError("This transcript is empty.")
    return Inspection(
        has_text_layer=True,
        meta={
            "timed_cues": cues,
            "has_timestamps": cues > 0,
            "characters": len(text),
            "warning": None if cues else "No timestamps found. Citations to this transcript cannot link to a video time.",
        },
    )


INSPECTORS = {
    "pdf": inspect_pdf,
    "pptx": inspect_pptx,
    "image": inspect_image,
    "video": inspect_video,
    "transcript": inspect_transcript,
}


def inspect_file(source_type: str, path: Path) -> Inspection:
    fn = INSPECTORS.get(source_type)
    if fn is None:
        raise InspectionError(f"No inspector for source type '{source_type}'.")
    return fn(path)
