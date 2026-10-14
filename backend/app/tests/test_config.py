import pytest

from app.core.config import REPO_ROOT, Settings


def test_relative_storage_dir_resolves_against_repo_root_not_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    s = Settings(jwt_secret="x" * 40, storage_dir="./storage")
    assert s.upload_root == (REPO_ROOT / "storage" / "uploads").resolve()


def test_placeholder_jwt_secret_rejected():
    with pytest.raises(ValueError):
        Settings(jwt_secret="change-me")


def test_missing_jwt_secret_fails_fast_with_clear_message(monkeypatch):
    from app.core import config
    monkeypatch.setattr(config, "Settings", lambda: Settings(jwt_secret=""))
    config.get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            config.get_settings()
    finally:
        config.get_settings.cache_clear()
