"""Upload validation, inspection facts, retry/replace/delete."""
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.course import Document
from app.tests import samples


def up(client, headers, cid, name, data, ctype="application/octet-stream"):
    return client.post(f"/api/courses/{cid}/documents", headers=headers, files={"file": (name, data, ctype)})


def stored(doc) -> Path:
    return get_settings().upload_root / doc["id"]  # not used directly; see helper below


def test_pdf_page_count_and_text_layer(client, alice, course):
    r = up(client, alice, course["id"], "lecture1.pdf", samples.make_text_pdf(["First law of thermodynamics", "Second law"] ))
    assert r.status_code == 201
    doc = client.get(f"/api/documents/{r.json()['id']}", headers=alice).json()
    assert doc["source_type"] == "pdf"
    assert doc["job"]["status"] == "indexed"
    assert doc["page_count"] == 2 and doc["slide_count"] is None
    assert doc["has_text_layer"] is True
    assert doc["file_meta"]["needs_ocr"] is False


def test_scanned_pdf_flagged_for_ocr(client, alice, course):
    r = up(client, alice, course["id"], "scan.pdf", samples.make_scanned_pdf())
    doc = client.get(f"/api/documents/{r.json()['id']}", headers=alice).json()
    assert doc["has_text_layer"] is False
    assert doc["file_meta"]["likely_scanned"] is True and doc["file_meta"]["needs_ocr"] is True
    # Tesseract is installed in the test environment, so the scan is actually read (see test_stage3 for the text)
    assert doc["job"]["status"] == ("indexed" if shutil.which("tesseract") else "failed")


def test_pptx_slide_count(client, alice, course):
    r = up(client, alice, course["id"], "deck.pptx", samples.make_pptx(["Intro", "Entropy", "Cycles"]))
    doc = client.get(f"/api/documents/{r.json()['id']}", headers=alice).json()
    assert doc["source_type"] == "pptx" and doc["slide_count"] == 3 and doc["page_count"] is None
    assert doc["job"]["status"] == "indexed"


def test_image_dimensions(client, alice, course):
    r = up(client, alice, course["id"], "diagram.png", samples.make_png())
    doc = client.get(f"/api/documents/{r.json()['id']}", headers=alice).json()
    assert doc["source_type"] == "image"
    assert (doc["file_meta"]["width"], doc["file_meta"]["height"]) == (64, 48)
    # a plain blue square has no text: honest failure instead of an empty "indexed" document
    assert doc["job"]["status"] == "failed"
    # Tesseract is an optional system dependency. Without it, the upload still
    # fails honestly with the install hint; with it, blank OCR fails as unreadable.
    assert "No readable text" in doc["job"]["error"] or "Tesseract" in doc["job"]["error"]


def test_transcript_timestamps_detected(client, alice, course):
    r = up(client, alice, course["id"], "lec.vtt", samples.VTT)
    doc = client.get(f"/api/documents/{r.json()['id']}", headers=alice).json()
    assert doc["source_type"] == "transcript"
    assert doc["file_meta"]["timed_cues"] == 2 and doc["file_meta"]["has_timestamps"] is True
    assert doc["job"]["status"] == "indexed"


def test_plain_text_transcript_warns_no_timestamps(client, alice, course):
    r = up(client, alice, course["id"], "notes.txt", b"Just some words with no timing.")
    doc = client.get(f"/api/documents/{r.json()['id']}", headers=alice).json()
    assert doc["file_meta"]["has_timestamps"] is False and doc["file_meta"]["warning"]


from app.core.binaries import find_system_binary


@pytest.mark.skipif(find_system_binary("ffmpeg") is None, reason="FFmpeg not installed")
def test_video_duration_and_audio(client, alice, course, tmp_path):
    r = up(client, alice, course["id"], "lecture.mp4", samples.make_mp4(tmp_path, seconds=2))
    assert r.status_code == 201
    doc = client.get(f"/api/documents/{r.json()['id']}", headers=alice).json()
    # facts are recorded even though no speech-to-text provider is configured...
    assert 1.5 < doc["duration_seconds"] < 3.0
    assert doc["file_meta"]["has_audio"] is True
    # ...and the job fails honestly with a way forward, rather than pretending to be transcribed
    assert doc["job"]["status"] == "failed"
    assert "Speech-to-text is not configured" in doc["job"]["error"] and "transcript" in doc["job"]["error"]


@pytest.mark.skipif(find_system_binary("ffmpeg") is None, reason="FFmpeg not installed")
def test_video_without_audio_fails_with_reason(client, alice, course, tmp_path):
    r = up(client, alice, course["id"], "silent.mp4", samples.make_mp4(tmp_path, audio=False))
    doc = client.get(f"/api/documents/{r.json()['id']}", headers=alice).json()
    assert doc["job"]["status"] == "failed" and "no audio" in doc["job"]["error"].lower()


# ---------- validation ----------

def test_wrong_extension_rejected(client, alice, course):
    r = up(client, alice, course["id"], "malware.exe", b"MZ\x90\x00")
    assert r.status_code == 415 and "aren't supported" in r.json()["detail"]


def test_legacy_ppt_gives_helpful_message(client, alice, course):
    r = up(client, alice, course["id"], "old.ppt", b"\xd0\xcf\x11\xe0")
    assert r.status_code == 415 and ".pptx" in r.json()["detail"]


def test_content_must_match_extension(client, alice, course):
    assert up(client, alice, course["id"], "fake.pdf", b"this is not a pdf").status_code == 415
    assert up(client, alice, course["id"], "fake.png", samples.make_text_pdf(["x"])).status_code == 415
    assert up(client, alice, course["id"], "fake.pptx", b"PK\x03\x04junk").status_code == 415
    assert up(client, alice, course["id"], "bin.txt", b"abc\x00def").status_code == 415


def test_empty_file_rejected(client, alice, course):
    assert up(client, alice, course["id"], "empty.pdf", b"").status_code == 400


def test_size_limit_enforced(client, alice, course, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_document_mb", 0)  # any non-empty file is too big
    r = up(client, alice, course["id"], "a.pdf", samples.make_text_pdf(["x"]))
    assert r.status_code == 413
    assert list((get_settings().upload_root / course["id"]).glob("*")) == []  # partial file cleaned up


def test_filename_sanitised_and_not_used_on_disk(client, alice, course, db):
    r = up(client, alice, course["id"], "../../etc/passwd.pdf", samples.make_text_pdf(["x"]))
    assert r.status_code == 201
    assert r.json()["original_filename"] == "passwd.pdf"
    doc = db.scalar(select(Document))
    p = (get_settings().upload_root / doc.stored_path).resolve()
    assert p.is_relative_to(get_settings().upload_root.resolve())
    assert p.name == f"{doc.id}.pdf"


# ---------- lifecycle ----------

def test_corrupt_pdf_fails_then_retry_reruns(client, alice, course):
    r = up(client, alice, course["id"], "broken.pdf", b"%PDF-1.4\nthis is garbage\n%%EOF")
    assert r.status_code == 201
    doc = client.get(f"/api/documents/{r.json()['id']}", headers=alice).json()
    assert doc["job"]["status"] == "failed" and doc["job"]["error"]
    retried = client.post(f"/api/documents/{doc['id']}/retry", headers=alice).json()
    assert retried["job"]["id"] != doc["job"]["id"]  # a new job row was created
    assert retried["job"]["status"] == "queued"      # response is returned before the background run
    again = client.get(f"/api/documents/{doc['id']}", headers=alice).json()
    assert again["job"]["id"] == retried["job"]["id"]
    assert again["job"]["status"] == "failed" and again["job"]["attempts"] == 1  # it really re-ran
    assert len(client.get(f"/api/courses/{course['id']}/documents", headers=alice).json()) == 1


def test_replace_swaps_file_and_reprocesses(client, alice, course):
    d = up(client, alice, course["id"], "v1.pdf", samples.make_text_pdf(["one"])).json()
    r = client.post(f"/api/documents/{d['id']}/replace", headers=alice,
                    files={"file": ("v2.pdf", samples.make_text_pdf(["a", "b", "c"]), "application/pdf")})
    assert r.status_code == 200
    doc = client.get(f"/api/documents/{d['id']}", headers=alice).json()
    assert doc["original_filename"] == "v2.pdf" and doc["page_count"] == 3
    files = list((get_settings().upload_root / course["id"]).glob("*.pdf"))
    assert len(files) == 1  # old file removed


def test_delete_document_and_course_remove_files(client, alice, course):
    d = up(client, alice, course["id"], "a.pdf", samples.make_text_pdf(["x"])).json()
    folder = get_settings().upload_root / course["id"]
    assert len(list(folder.glob("*.pdf"))) == 1
    assert client.delete(f"/api/documents/{d['id']}", headers=alice).status_code == 204
    assert list(folder.glob("*.pdf")) == []
    up(client, alice, course["id"], "b.pdf", samples.make_text_pdf(["y"]))
    assert client.delete(f"/api/courses/{course['id']}", headers=alice).status_code == 204
    assert not folder.exists()


def test_course_summary_counts(client, alice, course):
    up(client, alice, course["id"], "a.pdf", samples.make_text_pdf(["x"]))
    up(client, alice, course["id"], "d.pptx", samples.make_pptx(["s"]))
    c = client.get(f"/api/courses/{course['id']}", headers=alice).json()
    assert c["document_count"] == 2
    assert c["source_counts"] == {"pdf": 1, "pptx": 1}
    assert c["status_counts"] == {"indexed": 2}
    assert c["topic_count"] >= 1


def test_sanitize_filename_strips_paths_and_control_chars():
    from app.services.ingestion.validation import sanitize_filename
    assert sanitize_filename("../../etc/pass\x00wd.pdf") == "passwd.pdf"
    assert sanitize_filename("C:\\Users\\me\\notes.pdf") == "notes.pdf"
    assert sanitize_filename("...") == "upload"
    assert sanitize_filename(None) == "upload"
    assert len(sanitize_filename("a" * 500 + ".pdf")) <= 200
