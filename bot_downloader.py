"""Telegram bot service for downloading media sent by authorised users."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from time import monotonic
from typing import Optional, Set

from telethon import TelegramClient, events

import db
from config_manager import load_config
from media_downloader import get_media_type

logger = logging.getLogger("bot_downloader")
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_bot_client: Optional[TelegramClient] = None
_allowed_user_ids: Set[int] = set()


def _format_size(size: int) -> str:
    """Format a byte count for concise Telegram progress messages."""
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


class _TelegramProgressReporter:
    """Throttle progress edits to avoid Telegram flood limits."""

    def __init__(self, status_message, file_name: str, interval: float = 3.0):
        self.status_message = status_message
        self.file_name = file_name
        self.interval = interval
        self.last_update = 0.0

    async def __call__(self, current: int, total: int) -> None:
        now = monotonic()
        completed = total > 0 and current >= total
        if not completed and now - self.last_update < self.interval:
            return
        self.last_update = now
        percent = min(100.0, current * 100 / total) if total > 0 else 0.0
        total_text = _format_size(total) if total > 0 else "未知"
        try:
            await self.status_message.edit(
                f"正在下载：{self.file_name}\n"
                f"进度：{percent:.1f}%（{_format_size(current)} / {total_text}）"
            )
        except Exception as error:  # pylint: disable=broad-except
            logger.debug("Unable to update Bot download progress: %s", error)


def _proxy_from_config(config: dict):
    proxy = config.get("proxy")
    if not proxy:
        return None
    return {
        "proxy_type": proxy["scheme"],
        "addr": proxy["hostname"],
        "port": proxy["port"],
        "username": proxy.get("username"),
        "password": proxy.get("password"),
    }


def _target_path(root: str, sender_id: int, message) -> Path:
    """Return a safe, non-overwriting destination for a Telegram message."""
    sender_dir = Path(root) / "bot" / str(sender_id)
    sender_dir.mkdir(parents=True, exist_ok=True)
    telegram_file = getattr(message, "file", None)
    original_name = getattr(telegram_file, "name", None)
    extension = getattr(telegram_file, "ext", None) or ""
    safe_name = Path(original_name or f"media_{message.id}{extension}").name
    safe_name = safe_name.replace("\x00", "") or f"media_{message.id}{extension}"
    destination = sender_dir / safe_name
    if destination.exists():
        destination = destination.with_name(
            f"{destination.stem}_{message.id}{destination.suffix}"
        )
    return destination


def _is_allowed(sender_id: Optional[int]) -> bool:
    return sender_id is not None and sender_id in _allowed_user_ids


def _parse_command(raw_text: Optional[str]) -> str:
    parts = (raw_text or "").strip().split(maxsplit=1)
    return parts[0].split("@", 1)[0].lower() if parts else ""


async def _resolve_allowed_users(client: TelegramClient, configured_users) -> Set[int]:
    resolved: Set[int] = set()
    for value in configured_users or []:
        try:
            resolved.add(int(value))
        except (TypeError, ValueError):
            entity = await client.get_entity(value)
            resolved.add(int(entity.id))
    return resolved


async def start_bot() -> None:
    """Start the optional bot listener inside the NiceGUI event loop."""
    global _bot_client, _allowed_user_ids
    config = load_config()
    bot_token = config.get("bot_token")
    if not bot_token:
        logger.info("bot_token is not configured; bot listener is disabled.")
        return

    session_path = os.environ.get(
        "TELEGRAM_BOT_SESSION",
        os.path.join(THIS_DIR, "sessions", "media_downloader_bot_telethon"),
    )
    os.makedirs(os.path.dirname(os.path.abspath(session_path)), exist_ok=True)
    _bot_client = TelegramClient(
        session_path,
        api_id=config["api_id"],
        api_hash=config["api_hash"],
        proxy=_proxy_from_config(config),
    )
    download_root = config.get("download_directory") or os.path.join(
        THIS_DIR, "downloads"
    )

    @_bot_client.on(events.NewMessage(incoming=True))
    async def handle_message(event):
        authorised = _is_allowed(event.sender_id)
        logger.info(
            "Bot received message %s (authorised=%s, media=%s).",
            event.message.id,
            authorised,
            bool(event.message.media),
        )
        if not authorised:
            return
        message = event.message
        command = _parse_command(message.raw_text)
        if command in {"/start", "/help"}:
            await event.respond(
                "Telegram Media Downloader 已运行。\n\n"
                "直接发送或转发媒体文件给我，我会自动下载。\n"
                "/status - 查看运行状态\n"
                "/help - 查看帮助"
            )
            return
        if command == "/status":
            await event.respond("Bot 在线，媒体自动下载已启用。")
            return
        if not message.media:
            return

        destination = _target_path(download_root, int(event.sender_id), message)
        status_message = await event.respond(
            f"开始下载：{destination.name}\n进度：0.0%"
        )
        progress = _TelegramProgressReporter(status_message, destination.name)
        try:
            saved_path = await _bot_client.download_media(
                message,
                file=str(destination),
                progress_callback=progress,
            )
            size = os.path.getsize(saved_path) if saved_path else 0
            absolute_path = (
                os.path.abspath(saved_path) if saved_path else str(destination)
            )
            media_type = get_media_type(message) or "document"
            db.record_download(
                "Bot inbox",
                message.id,
                destination.name,
                size,
                absolute_path,
                media_type,
            )
            await status_message.edit(
                f"下载完成：{destination.name}\n"
                f"进度：100.0%（{_format_size(size)}）\n"
                "已写入 Web 下载历史。"
            )
        except Exception as error:  # pylint: disable=broad-except
            logger.exception("Bot media download failed for message %s", message.id)
            await status_message.edit(f"下载失败：{type(error).__name__}")

    await _bot_client.start(bot_token=bot_token)
    _allowed_user_ids = await _resolve_allowed_users(
        _bot_client, config.get("allowed_user_ids")
    )
    if not _allowed_user_ids:
        await _bot_client.disconnect()
        _bot_client = None
        raise RuntimeError("bot_token is configured but allowed_user_ids is empty")

    me = await _bot_client.get_me()
    logger.info(
        "Telegram bot @%s started for %d authorised user(s).",
        me.username,
        len(_allowed_user_ids),
    )


async def stop_bot() -> None:
    """Disconnect the optional bot client during application shutdown."""
    global _bot_client
    if _bot_client and _bot_client.is_connected():
        await _bot_client.disconnect()
    _bot_client = None
