"""Authorised source opening: media tokens, PDF page images, slide views, video ranges."""
import shutil
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import get_settings
from app.tests import samples
from app.tests.conftest import upload


def token(client, headers, doc_id):
    return client.get(f"/api/documents/{doc_id}/media-token", headers=headers).json()["token"]


def test_media_token_opens_the_original_file(client, alice, thermo):
    d = thermo["pdf"]["id"]
    r = client.get(f"/api/media/documents/{d}", params={"t": token(client, alice, d)})
    assert r.status_code == 200 and r.content.startswith(b"%PDF-")


def test_media_requires_a_valid_scoped_unexpired_token(client, alice, thermo):
    pdf, pptx = thermo["pdf"]["id"], thermo["pptx"]["id"]
    good = token(client, alice, pdf)
    assert client.get(f"/api/media/documents/{pdf}").status_code == 422                       # no token
    assert client.get(f"/api/media/documents/{pdf}", params={"t": "garbage"}).status_code == 401
    assert client.get(f"/api/media/documents/{pptx}", params={"t": good}).status_code == 401  # token is scoped to one document
    s = get_settings()
    me = client.get("/api/auth/me", headers=alice).json()["id"]
    expired = jwt.encode({"sub": me, "doc": pdf, "typ": "media", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}, s.jwt_secret, algorithm="HS256")
    assert client.get(f"/api/media/documents/{pdf}", params={"t": expired}).status_code == 401
    access = jwt.encode({"sub": me, "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, s.jwt_secret, algorithm="HS256")
    assert client.get(f"/api/media/documents/{pdf}", params={"t": access}).status_code == 401  # a login token isn't a media token


def test_other_users_cannot_mint_or_use_media_tokens(client, alice, bob, thermo):
    d = thermo["pdf"]["id"]
    assert client.get(f"/api/documents/{d}/media-token", headers=bob).status_code == 404
    assert client.get(f"/api/documents/{thermo['pptx']['id']}/slides/1", headers=bob).status_code == 404
    leaked = token(client, alice, d)  # even a leaked token dies when the document is deleted
    client.delete(f"/api/documents/{d}", headers=alice)
    assert client.get(f"/api/media/documents/{d}", params={"t": leaked}).status_code == 404


def test_pdf_page_renders_to_png(client, alice, thermo):
    d = thermo["pdf"]["id"]
    t = token(client, alice, d)
    r = client.get(f"/api/media/documents/{d}/pages/2.png", params={"t": t})
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG") and r.headers["cache-control"].startswith("private")
    assert client.get(f"/api/media/documents/{d}/pages/99.png", params={"t": t}).status_code == 404
    assert client.get(f"/api/media/documents/{d}/pages/0.png", params={"t": t}).status_code == 404
    pp = thermo["pptx"]["id"]
    assert client.get(f"/api/media/documents/{pp}/pages/1.png", params={"t": token(client, alice, pp)}).status_code == 404


def test_pdf_figure_thumbnail_is_scoped_and_resolves_the_indexed_figure(client, alice, bob, course):
    doc = upload(client, alice, course["id"], "diagram.pdf", samples.make_pdf_with_figure())
    doc_id = doc["id"]
    media_token = token(client, alice, doc_id)
    response = client.get(f"/api/media/documents/{doc_id}/figures/page1-img1", params={"t": media_token})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content.startswith(b"\x89PNG")
    assert client.get(f"/api/media/documents/{doc_id}/figures/page1-img99", params={"t": media_token}).status_code == 404
    assert client.get(f"/api/media/documents/{doc_id}/figures/page1-img1").status_code == 422
    assert client.get(f"/api/documents/{doc_id}/media-token", headers=bob).status_code == 404


def test_slide_view_returns_the_slides_own_content(client, alice, thermo):
    pp = thermo["pptx"]["id"]
    s = client.get(f"/api/documents/{pp}/slides/1", headers=alice).json()
    assert s["slide"] == 1 and s["of"] == 2 and s["title"] == "Heat engines"
    assert "Body for Heat engines" in s["text"] and s["notes"] == "Engines convert heat into work."
    assert client.get(f"/api/documents/{pp}/slides/3", headers=alice).status_code == 404
    assert client.get(f"/api/documents/{thermo['pdf']['id']}/slides/1", headers=alice).status_code == 404


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")
def test_video_supports_range_requests_for_seeking(client, alice, course, tmp_path):
    d = upload(client, alice, course["id"], "lec.mp4", samples.make_mp4(tmp_path, seconds=2))
    r = client.get(f"/api/media/documents/{d['id']}", params={"t": token(client, alice, d["id"])}, headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100
