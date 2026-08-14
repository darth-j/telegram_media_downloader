"""Migrate the tangyoha Docker fork's config shape to the current upstream schema."""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime, timezone

import yaml


def _load_legacy_data(path: str) -> dict:
    """Load tangyoha's data.yaml without requiring it for new deployments."""
    data_path = os.path.join(os.path.dirname(path) or ".", "data.yaml")
    if not os.path.isfile(data_path):
        return {}
    with open(data_path, "r", encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def migrate(path: str = "config.yaml") -> bool:
    """Migrate legacy fields in-place and return whether the file changed."""
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream) or {}
    changed = False
    legacy_data = _load_legacy_data(path)
    legacy_chats = config.get("chat")
    if not isinstance(legacy_chats, list):
        legacy_chats = legacy_data.get("chat")
    if "chats" not in config and isinstance(legacy_chats, list):
        config.pop("chat", None)
        config["chats"] = legacy_chats
        changed = True
    if config.get("download_directory") in (None, ""):
        config["download_directory"] = "/app/downloads"
        changed = True
    if not changed:
        return False
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = os.environ.get("CONFIG_BACKUP_DIR", os.path.dirname(path) or ".")
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(backup_dir, f"{os.path.basename(path)}.bak.{stamp}")
    shutil.copy2(path, backup_path)
    with open(path, "w", encoding="utf-8") as stream:
        yaml.safe_dump(config, stream, sort_keys=False, allow_unicode=True)
    return True


if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    if migrate(config_path):
        print(f"已迁移旧配置并创建备份：{config_path}")
