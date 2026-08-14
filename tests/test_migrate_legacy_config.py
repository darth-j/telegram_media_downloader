import os
from pathlib import Path

import yaml

from migrate_legacy_config import migrate


def test_migrate_legacy_config_preserves_credentials_and_progress(
    tmp_path: Path, monkeypatch
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "api_id: 123\napi_hash: secret\nchat:\n  - chat_id: -1001\n    last_read_message_id: 42\n",
        encoding="utf-8",
    )

    backup_dir = tmp_path / "backups"
    monkeypatch.setenv("CONFIG_BACKUP_DIR", os.fspath(backup_dir))
    assert migrate(os.fspath(config_path)) is True

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert config["api_id"] == 123
    assert config["api_hash"] == "secret"
    assert config["chats"] == [{"chat_id": -1001, "last_read_message_id": 42}]
    assert config["download_directory"] == "/app/downloads"
    assert list(backup_dir.glob("config.yaml.bak.*"))


def test_current_config_is_not_rewritten(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "api_id: 123\napi_hash: secret\nchats: []\ndownload_directory: /data\n",
        encoding="utf-8",
    )

    assert migrate(os.fspath(config_path)) is False
    assert not list(tmp_path.glob("config.yaml.bak.*"))
