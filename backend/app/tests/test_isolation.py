"""Course-level data isolation: another user must get 404 for everything."""
from app.tests.samples import make_text_pdf


def _upload(client, headers, course_id):
    return client.post(
        f"/api/courses/{course_id}/documents", headers=headers,
        files={"file": ("notes.pdf", make_text_pdf(["Heat and work"]), "application/pdf")},
    )


def test_other_user_cannot_touch_course_or_documents(client, alice, bob, course):
    cid = course["id"]
    up = _upload(client, alice, cid)
    assert up.status_code == 201
    doc = up.json()

    assert client.get("/api/courses", headers=bob).json() == []
    assert client.get(f"/api/courses/{cid}", headers=bob).status_code == 404
    assert client.patch(f"/api/courses/{cid}", json={"title": "pwned"}, headers=bob).status_code == 404
    assert client.get(f"/api/courses/{cid}/documents", headers=bob).status_code == 404
    assert _upload(client, bob, cid).status_code == 404
    assert client.get(f"/api/documents/{doc['id']}", headers=bob).status_code == 404
    assert client.get(f"/api/documents/{doc['id']}/file", headers=bob).status_code == 404
    assert client.post(f"/api/documents/{doc['id']}/retry", headers=bob).status_code == 404
    assert client.delete(f"/api/documents/{doc['id']}", headers=bob).status_code == 404
    assert client.get(f"/api/jobs/{doc['job']['id']}", headers=bob).status_code == 404
    assert client.delete(f"/api/courses/{cid}", headers=bob).status_code == 404

    # Owner still has everything, unchanged
    assert client.get(f"/api/courses/{cid}", headers=alice).json()["title"] == "Thermodynamics"
    assert client.get(f"/api/documents/{doc['id']}/file", headers=alice).status_code == 200


def test_unauthenticated_file_access_blocked(client, alice, course):
    doc = _upload(client, alice, course["id"]).json()
    assert client.get(f"/api/documents/{doc['id']}/file").status_code == 401


def test_dashboard_only_shows_own_data(client, alice, bob, course):
    _upload(client, alice, course["id"])
    d = client.get("/api/dashboard", headers=bob).json()
    assert d["course_count"] == 0 and d["document_count"] == 0 and d["recent_activity"] == []
