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


def test_tangyoha_data_yaml_chat_is_merged(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "api_id: 123\napi_hash: secret\nproxy:\n  scheme: socks5\n  hostname: proxy\n  port: 1080\n",
        encoding="utf-8",
    )
    (tmp_path / "data.yaml").write_text(
        "chat:\n  - chat_id: -1009\n    ids_to_retry: [7, 8]\nids_to_retry: []\n",
        encoding="utf-8",
    )
    backup_dir = tmp_path / "backups"
    monkeypatch.setenv("CONFIG_BACKUP_DIR", os.fspath(backup_dir))

    assert migrate(os.fspath(config_path)) is True

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert config["chats"] == [{"chat_id": -1009, "ids_to_retry": [7, 8]}]
    assert config["proxy"] == {
        "scheme": "socks5",
        "hostname": "proxy",
        "port": 1080,
    }
    assert list(backup_dir.glob("config.yaml.bak.*"))
