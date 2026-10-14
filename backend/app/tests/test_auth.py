from sqlalchemy import select

from app.models.user import User


def test_register_login_me(client):
    r = client.post("/api/auth/register", json={"name": "Ada", "email": "Ada@Example.com", "password": "correct-horse-1"})
    assert r.status_code == 201
    assert r.json()["user"]["email"] == "ada@example.com"  # normalised
    r = client.post("/api/auth/login", json={"email": "ada@example.com", "password": "correct-horse-1"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["name"] == "Ada"


def test_password_is_hashed_never_plaintext(client, db):
    client.post("/api/auth/register", json={"name": "Ada", "email": "ada@example.com", "password": "correct-horse-1"})
    user = db.scalar(select(User))
    assert user.password_hash != "correct-horse-1"
    assert user.password_hash.startswith("$2")  # bcrypt


def test_duplicate_email_rejected(client):
    body = {"name": "A", "email": "a@example.com", "password": "correct-horse-1"}
    assert client.post("/api/auth/register", json=body).status_code == 201
    assert client.post("/api/auth/register", json=body).status_code == 409


def test_wrong_password_and_unknown_user_same_error(client):
    client.post("/api/auth/register", json={"name": "A", "email": "a@example.com", "password": "correct-horse-1"})
    bad_pw = client.post("/api/auth/login", json={"email": "a@example.com", "password": "nope-nope-nope"})
    no_user = client.post("/api/auth/login", json={"email": "z@example.com", "password": "nope-nope-nope"})
    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json() == no_user.json()


def test_weak_and_overlong_passwords_rejected(client):
    base = {"name": "A", "email": "a@example.com"}
    assert client.post("/api/auth/register", json={**base, "password": "short"}).status_code == 422
    assert client.post("/api/auth/register", json={**base, "password": "x" * 73}).status_code == 422


def test_protected_endpoints_require_token(client):
    for path in ("/api/auth/me", "/api/courses", "/api/dashboard"):
        assert client.get(path).status_code == 401
    assert client.get("/api/courses", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_rate_limit_on_auth(client):
    codes = [client.post("/api/auth/login", json={"email": "a@example.com", "password": "x"}).status_code for _ in range(25)]
    assert 429 in codes


def test_profile_update_and_account_deletion(client, alice, db):
    r = client.patch("/api/users/me", json={"learning_goals": ["Pass finals", " "], "explanation_style": "simple", "onboarded": True}, headers=alice)
    assert r.status_code == 200
    assert r.json()["learning_goals"] == ["Pass finals"] and r.json()["onboarded"] is True
    assert client.patch("/api/users/me", json={"explanation_style": "poetic"}, headers=alice).status_code == 422
    assert client.delete("/api/users/me", headers=alice).status_code == 204
    assert db.scalar(select(User)) is None
