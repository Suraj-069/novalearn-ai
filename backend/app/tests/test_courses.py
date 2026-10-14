def test_course_crud(client, alice):
    r = client.post("/api/courses", json={"title": "  Linear Algebra  ", "description": "Spring"}, headers=alice)
    assert r.status_code == 201 and r.json()["title"] == "Linear Algebra"
    cid = r.json()["id"]
    assert client.post("/api/courses", json={"title": "   "}, headers=alice).status_code == 422
    r = client.patch(f"/api/courses/{cid}", json={"title": "Linear Algebra II"}, headers=alice)
    assert r.json()["title"] == "Linear Algebra II"
    assert len(client.get("/api/courses", headers=alice).json()) == 1
    assert client.delete(f"/api/courses/{cid}", headers=alice).status_code == 204
    assert client.get(f"/api/courses/{cid}", headers=alice).status_code == 404


def test_invalid_uuid_is_422_not_500(client, alice):
    assert client.get("/api/courses/not-a-uuid", headers=alice).status_code == 422
