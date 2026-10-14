"""Upload validation: extension allow-list + magic-byte sniffing + size caps.

We never trust the client-supplied content type or filename.
"""
import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fastapi import HTTPException, UploadFile

from app.core.config import get_settings

CHUNK = 1024 * 1024


class UploadRejected(HTTPException):
    def __init__(self, detail: str, status_code: int = 400):
        super().__init__(status_code=status_code, detail=detail)


@dataclass(frozen=True)
class FileKind:
    source_type: str
    mime: str
    is_video: bool = False


EXTENSIONS: dict[str, FileKind] = {
    ".pdf": FileKind("pdf", "application/pdf"),
    ".pptx": FileKind("pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ".png": FileKind("image", "image/png"),
    ".jpg": FileKind("image", "image/jpeg"),
    ".jpeg": FileKind("image", "image/jpeg"),
    ".webp": FileKind("image", "image/webp"),
    ".mp4": FileKind("video", "video/mp4", True),
    ".m4v": FileKind("video", "video/mp4", True),
    ".mov": FileKind("video", "video/quicktime", True),
    ".webm": FileKind("video", "video/webm", True),
    ".mkv": FileKind("video", "video/x-matroska", True),
    ".vtt": FileKind("transcript", "text/vtt"),
    ".srt": FileKind("transcript", "application/x-subrip"),
    ".txt": FileKind("transcript", "text/plain"),
}

LEGACY_HINTS = {
    ".ppt": "Legacy .ppt files can't be read reliably. Re-save the deck as .pptx and upload again.",
    ".doc": "Word documents aren't supported. Export to PDF and upload that.",
    ".docx": "Word documents aren't supported. Export to PDF and upload that.",
}

ALLOWED_LIST = ", ".join(sorted(EXTENSIONS))


def sanitize_filename(name: str | None) -> str:
    """Keep only a safe display name. The stored name on disk is a UUID, never this."""
    base = PurePosixPath((name or "upload").replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip().strip(".")
    return (base or "upload")[:200]


def extension_of(filename: str) -> str:
    return Path(filename).suffix.lower()


def kind_for(filename: str) -> tuple[str, FileKind]:
    ext = extension_of(filename)
    if ext in LEGACY_HINTS:
        raise UploadRejected(LEGACY_HINTS[ext], 415)
    kind = EXTENSIONS.get(ext)
    if kind is None:
        raise UploadRejected(f"'{ext or 'no extension'}' files aren't supported. Allowed: {ALLOWED_LIST}.", 415)
    return ext, kind


def size_limit_bytes(kind: FileKind) -> int:
    s = get_settings()
    return (s.max_video_mb if kind.is_video else s.max_document_mb) * 1024 * 1024


def _magic_ok(ext: str, path: Path) -> bool:
    with path.open("rb") as f:
        head = f.read(64)
    if ext == ".pdf":
        return head.startswith(b"%PDF-")
    if ext == ".pptx":
        if not head.startswith(b"PK\x03\x04"):
            return False
        try:
            with zipfile.ZipFile(path) as z:
                return "ppt/presentation.xml" in z.namelist()
        except zipfile.BadZipFile:
            return False
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ext in (".mp4", ".m4v", ".mov"):
        return head[4:8] == b"ftyp" or head[4:8] in (b"moov", b"mdat", b"free", b"wide")
    if ext in (".webm", ".mkv"):
        return head.startswith(b"\x1a\x45\xdf\xa3")
    if ext == ".vtt":
        return head.lstrip(b"\xef\xbb\xbf").startswith(b"WEBVTT")
    if ext in (".srt", ".txt"):
        sample = path.read_bytes()[:65536]
        if b"\x00" in sample:
            return False
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError:
            # a multi-byte char may be cut at the sample boundary; retry without the tail
            try:
                sample[:-4].decode("utf-8")
            except UnicodeDecodeError:
                return False
        return True
    return False


@dataclass
class SavedUpload:
    path: Path          # absolute path of the stored file
    rel_path: str       # path relative to upload root (what we store in the DB)
    size: int
    sha256: str
    display_name: str
    ext: str
    kind: FileKind


async def save_validated_upload(file: UploadFile, course_id: str, doc_id: str) -> SavedUpload:
    """Stream an upload to disk with a hard size cap, then verify its real content type."""
    display = sanitize_filename(file.filename)
    ext, kind = kind_for(display)
    limit = size_limit_bytes(kind)

    root = get_settings().upload_root
    dest_dir = root / course_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{doc_id}{ext}"
    tmp = dest_dir / f"{doc_id}.part"

    h = hashlib.sha256()
    size = 0
    try:
        with tmp.open("wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise UploadRejected(
                        f"File is larger than the {limit // (1024 * 1024)} MB limit for {kind.source_type} files.", 413
                    )
                h.update(chunk)
                out.write(chunk)
        if size == 0:
            raise UploadRejected("The file is empty.")
        if not _magic_ok(ext, tmp):
            raise UploadRejected(f"The file's contents don't look like a valid {ext} file.", 415)
        tmp.replace(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    return SavedUpload(dest, f"{course_id}/{dest.name}", size, h.hexdigest(), display, ext, kind)
