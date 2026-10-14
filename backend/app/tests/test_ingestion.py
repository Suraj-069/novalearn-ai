"""Extraction, provenance and the indexing lifecycle."""
import shutil
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.models.knowledge import ContentChunk
from app.services.ingestion.chunking import MAX_WINDOW_SECONDS, TARGET_CHARS, chunk_units
from app.services.ingestion.extract import RawUnit
from app.services.providers.base import ProviderError
from app.tests import samples
from app.tests.conftest import THERMO_PDF, upload
from app.tests.fakes import FakeSTT, segs


def chunks_of(db, doc_id):
    return list(db.scalars(select(ContentChunk).where(ContentChunk.document_id == uuid.UUID(str(doc_id))).order_by(ContentChunk.chunk_index)))


def status(client, headers, doc_id):
    return client.get(f"/api/documents/{doc_id}", headers=headers).json()


def test_pdf_chunks_keep_exact_page_numbers(client, alice, course, db):
    d = upload(client, alice, course["id"], "t.pdf", samples.make_text_pdf(THERMO_PDF))
    cs = chunks_of(db, d["id"])
    assert {c.page_number for c in cs} == {1, 2, 3}
    for c in cs:  # each chunk's text really comes from the page it claims
        assert ("entropy" in c.text.lower()) == (c.page_number == 2)
        assert ("carnot" in c.text.lower()) == (c.page_number == 3)
        assert c.slide_number is None and c.start_seconds is None and c.end_seconds is None  # not applicable => NULL
        assert c.source_type == "pdf" and c.embedding is not None and c.is_generated_description is False


def test_pdf_embedded_figure_is_indexed_with_page_and_description(client, alice, course, db, monkeypatch):
    from app.services.ingestion import extract
    from app.tests.fakes import FakeLLM

    monkeypatch.setattr(extract, "get_settings", lambda: SimpleNamespace(vision_enabled=True))
    monkeypatch.setattr(extract, "ocr_available", lambda: False)
    vision = FakeLLM()
    vision.describe_image = lambda image_png, prompt: "A line diagram compares two engine efficiencies."  # noqa: E731
    monkeypatch.setattr("app.services.ingestion.pipeline.get_llm", lambda: vision)

    d = upload(client, alice, course["id"], "figure.pdf", samples.make_pdf_with_figure())
    info = status(client, alice, d["id"])
    figures = [c for c in chunks_of(db, d["id"]) if c.figure_ref]
    assert info["job"]["status"] == "indexed", info["job"]
    assert len(figures) == 1
    assert (figures[0].figure_ref, figures[0].page_number, figures[0].is_generated_description) == ("page1-img1", 1, True)
    assert "AI description of figure" in figures[0].text


def test_pdf_figure_warns_when_vision_is_unavailable(client, alice, course, monkeypatch):
    from app.services.ingestion import extract

    monkeypatch.setattr(extract, "get_settings", lambda: SimpleNamespace(vision_enabled=True))
    monkeypatch.setattr(extract, "ocr_available", lambda: False)
    monkeypatch.setattr("app.services.ingestion.pipeline.get_llm", lambda: None)
    d = upload(client, alice, course["id"], "figure.pdf", samples.make_pdf_with_figure())
    info = status(client, alice, d["id"])
    assert info["job"]["status"] == "indexed", info["job"]
    warnings = info["file_meta"]["index"]["warnings"]
    assert any("figure(s) have no model description" in warning for warning in warnings)


def test_pptx_skips_decorative_pictures_but_indexes_substantial_figures(tmp_path, monkeypatch):
    from PIL import Image

    from app.services.ingestion import extract

    image_buf = __import__("io").BytesIO()
    Image.new("RGB", (640, 480), "white").save(image_buf, "PNG")
    deck = samples.make_pptx(["A figure slide"], pictures={1: [(samples.make_png(), 0.4), (image_buf.getvalue(), 4.0)]})
    path = tmp_path / "figures.pptx"
    path.write_bytes(deck)
    monkeypatch.setattr(extract, "get_settings", lambda: SimpleNamespace(vision_enabled=True))
    monkeypatch.setattr(extract, "ocr_available", lambda: False)
    vision = type("Vision", (), {"describe_image": lambda self, _data, _prompt: "A diagram of a rising line."})()

    out = extract.extract_pptx(path, vision)
    figure_units = [u for u in out.units if u.figure_ref]
    assert len(figure_units) == 1
    assert figure_units[0].figure_ref == "slide1-img2" and figure_units[0].generated


def test_figure_threshold_skips_tiny_and_full_page_assets():
    from app.services.ingestion.extract import significant_figure

    assert significant_figure(0.08, (640, 480))
    assert not significant_figure(0.004, (64, 48))
    assert not significant_figure(0.99, (2000, 1200))


def test_pptx_chunks_keep_slide_numbers_notes_and_tables(client, alice, course, db):
    deck = samples.make_pptx(["Intro", "Entropy", "Carnot"], notes={2: "Remember the second law"}, table_on=3)
    d = upload(client, alice, course["id"], "deck.pptx", deck)
    cs = chunks_of(db, d["id"])
    by_slide = {c.slide_number: c.text for c in cs}
    assert set(by_slide) == {1, 2, 3}
    assert "Remember the second law" in by_slide[2]
    assert "Carnot | Maximum" in by_slide[3]  # table row text extracted
    assert all(c.page_number is None for c in cs)


def test_vtt_timestamps_preserved_exactly(client, alice, course, db):
    d = upload(client, alice, course["id"], "l.vtt", samples.VTT)
    (c,) = chunks_of(db, d["id"])
    assert (c.start_seconds, c.end_seconds) == (1.0, 8.5)  # first cue start .. last cue end
    assert "Heat flows from hot to cold" in c.text and "Entropy never decreases" in c.text
    assert c.page_number is None and c.slide_number is None


def test_long_transcript_splits_into_time_windows(client, alice, course, db):
    cues = "".join(f"{i*10 // 60:02d}:{i*10 % 60:02d}.000 --> {(i*10+9) // 60:02d}:{(i*10+9) % 60:02d}.000\n"
                   f"Sentence number {i} about heat engines.\n\n" for i in range(20))
    d = upload(client, alice, course["id"], "long.vtt", ("WEBVTT\n\n" + cues).encode())
    cs = chunks_of(db, d["id"])
    assert len(cs) >= 3
    assert cs[0].start_seconds == 0.0 and cs[-1].end_seconds == 199.0
    assert all(c.end_seconds - c.start_seconds <= MAX_WINDOW_SECONDS + 10 for c in cs)
    assert all(a.end_seconds <= b.start_seconds for a, b in zip(cs, cs[1:]))  # in order, no overlap


def test_plain_text_transcript_has_null_times_and_a_warning(client, alice, course, db):
    d = upload(client, alice, course["id"], "notes.txt", b"Heat flows from hot to cold.\n\nEntropy increases.")
    cs = chunks_of(db, d["id"])
    assert cs and all(c.start_seconds is None and c.end_seconds is None for c in cs)
    assert any("no timestamps" in w for w in status(client, alice, d["id"])["file_meta"]["index"]["warnings"])


from app.core.binaries import find_system_binary


@pytest.mark.skipif(find_system_binary("ffmpeg") is None, reason="FFmpeg not installed")
def test_video_transcript_timestamps_via_stt_provider(client, alice, course, db, monkeypatch, tmp_path):
    fake = FakeSTT(segs((0.0, 2.0, "Welcome to thermodynamics."), (2.0, 5.5, "Today we study entropy.")))
    monkeypatch.setattr("app.services.ingestion.pipeline.get_stt", lambda: fake)
    d = upload(client, alice, course["id"], "lec.mp4", samples.make_mp4(tmp_path, seconds=3))
    info = status(client, alice, d["id"])
    assert info["job"]["status"] == "indexed", info["job"]
    (c,) = chunks_of(db, d["id"])
    assert (c.start_seconds, c.end_seconds) == (0.0, 5.5) and c.source_type == "video"
    assert any("fake-stt" in w and "errors" in w for w in info["file_meta"]["index"]["warnings"])  # flagged as automatic


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract not installed")
def test_scanned_pdf_is_read_with_ocr_and_flagged(client, alice, course, db):
    d = upload(client, alice, course["id"], "scan.pdf", samples.make_scanned_pdf("Entropy always increases"))
    info = status(client, alice, d["id"])
    assert info["job"]["status"] == "indexed", info["job"]
    (c, *_) = chunks_of(db, d["id"])
    assert c.page_number == 1 and "entropy" in c.text.lower()
    assert any("OCR" in w for w in info["file_meta"]["index"]["warnings"])


def test_scanned_pdf_without_tesseract_fails_with_a_fix(client, alice, course, monkeypatch):
    monkeypatch.setattr("app.services.ingestion.extract.ocr_available", lambda: False)
    d = upload(client, alice, course["id"], "scan.pdf", samples.make_scanned_pdf("Entropy always increases"))
    job = status(client, alice, d["id"])["job"]
    assert job["status"] == "failed" and "Tesseract" in job["error"]


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract not installed")
def test_image_ocr_keeps_figure_reference(client, alice, course, db):
    d = upload(client, alice, course["id"], "carnot.png", samples.make_png("Carnot cycle efficiency"))
    (c,) = chunks_of(db, d["id"])
    assert "carnot" in c.text.lower() and c.figure_ref == "carnot.png" and c.is_generated_description is False


def test_retry_reindexes_without_duplicate_chunks(client, alice, course, db):
    d = upload(client, alice, course["id"], "t.pdf", samples.make_text_pdf(THERMO_PDF))
    n = len(chunks_of(db, d["id"]))
    assert client.post(f"/api/documents/{d['id']}/retry", headers=alice).status_code == 200
    db.expire_all()
    assert len(chunks_of(db, d["id"])) == n
    assert status(client, alice, d["id"])["job"]["attempts"] == 1


def test_replace_swaps_chunks_and_delete_removes_them(client, alice, course, db):
    d = upload(client, alice, course["id"], "a.pdf", samples.make_text_pdf(["Original statement about entropy and heat."]))
    client.post(f"/api/documents/{d['id']}/replace", headers=alice,
                files={"file": ("b.pdf", samples.make_text_pdf(["Replacement statement about the Carnot engine."]), "application/pdf")})
    db.expire_all()
    texts = " ".join(c.text for c in chunks_of(db, d["id"]))
    assert "Replacement" in texts and "Original" not in texts
    client.delete(f"/api/documents/{d['id']}", headers=alice)
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(ContentChunk)) == 0


def test_embedding_failure_fails_job_and_stores_nothing(client, alice, course, db, monkeypatch):
    class Boom:
        name, semantic = "boom", True
        def embed(self, texts):
            raise ProviderError("Embedding service returned HTTP 500.")
    monkeypatch.setattr("app.services.ingestion.pipeline.get_embedding_provider", lambda: Boom())
    d = upload(client, alice, course["id"], "t.pdf", samples.make_text_pdf(THERMO_PDF))
    job = status(client, alice, d["id"])["job"]
    assert job["status"] == "failed" and "HTTP 500" in job["error"] and job["stage"] == "embedding"
    assert chunks_of(db, d["id"]) == []  # all-or-nothing


# ---------- chunking unit tests ----------
def test_chunks_never_cross_page_boundaries():
    units = [RawUnit("Alpha sentence. " * 80, page=1), RawUnit("Beta sentence. " * 80, page=2)]
    cs = chunk_units(units)
    assert {c.page for c in cs} == {1, 2}
    assert all(("Alpha" in c.text) != ("Beta" in c.text) for c in cs)
    assert all(len(c.text) <= TARGET_CHARS * 1.6 for c in cs)


def test_adjacent_chunks_overlap_for_context():
    text = " ".join(f"Sentence number {i} explains something distinct about topic {i}." for i in range(60))
    cs = chunk_units([RawUnit(text, page=1)])
    assert len(cs) > 1
    assert cs[0].text.split()[-2:] == cs[1].text.split()[:len(cs[0].text.split()[-2:])] or any(w in cs[1].text for w in cs[0].text.split()[-4:])


def test_generated_flag_is_carried_through():
    (c,) = chunk_units([RawUnit("AI description of figure: a graph.", slide=2, figure_ref="slide2-img1", generated=True)])
    assert c.generated is True and c.slide == 2 and c.figure_ref == "slide2-img1"
