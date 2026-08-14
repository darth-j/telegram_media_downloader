"""Telegram bot service for downloading media sent by authorised users."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from time import monotonic
from typing import Optional, Set
from urllib.parse import urlparse

from telethon import TelegramClient, events
from telethon import utils as telethon_utils

import db
from config_manager import load_config
from media_downloader import get_media_type

logger = logging.getLogger("bot_downloader")
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_bot_client: Optional[TelegramClient] = None
_link_client: Optional[TelegramClient] = None
_allowed_user_ids: Set[int] = set()
_TELEGRAM_LINK_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/[^\s<>()]+",
    re.IGNORECASE,
)


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


def _telegram_message_links(raw_text: Optional[str]):
    """Extract Telegram message targets as ``(entity, message_id)`` tuples."""
    targets = []
    seen = set()
    for match in _TELEGRAM_LINK_PATTERN.finditer(raw_text or ""):
        raw_url = match.group(0).rstrip(".,;:!?，。；：！？）]}")
        parsed = urlparse(
            raw_url
            if raw_url.lower().startswith(("http://", "https://"))
            else f"https://{raw_url}"
        )
        parts = [part for part in parsed.path.split("/") if part]
        if parts and parts[0].lower() == "s":
            parts = parts[1:]
        if len(parts) < 2 or not parts[-1].isdigit():
            continue
        if parts[0].lower() == "c":
            if len(parts) < 3 or not parts[1].isdigit():
                continue
            entity = int(f"-100{parts[1]}")
        elif parts[0].startswith(("+", "joinchat")):
            continue
        else:
            entity = parts[0]
        target = (entity, int(parts[-1]))
        if target not in seen:
            seen.add(target)
            targets.append(target)
    return targets


async def _resolve_allowed_users(client: TelegramClient, configured_users) -> Set[int]:
    resolved: Set[int] = set()
    for value in configured_users or []:
        try:
            resolved.add(int(value))
        except (TypeError, ValueError):
            entity = await client.get_entity(value)
            resolved.add(int(entity.id))
    return resolved


async def _download_message(
    client: TelegramClient, event, message, download_root: str
) -> bool:
    """Download one media message, report progress, and record Web history."""
    if not message or not message.media:
        return False
    destination = _target_path(download_root, int(event.sender_id), message)
    status_message = await event.respond(f"开始下载：{destination.name}\n进度：0.0%")
    progress = _TelegramProgressReporter(status_message, destination.name)
    try:
        saved_path = await client.download_media(
            message,
            file=str(destination),
            progress_callback=progress,
        )
        size = os.path.getsize(saved_path) if saved_path else 0
        absolute_path = os.path.abspath(saved_path) if saved_path else str(destination)
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
        return True
    except Exception as error:  # pylint: disable=broad-except
        logger.exception("Bot media download failed for message %s", message.id)
        await status_message.edit(f"下载失败：{type(error).__name__}")
        return False


async def _download_telegram_links(
    client: TelegramClient, event, raw_text: Optional[str], download_root: str
) -> bool:
    """Resolve Telegram post links and download their media."""
    targets = _telegram_message_links(raw_text)
    if not targets:
        return False
    downloaded = False
    for entity_ref, message_id in targets:
        try:
            entity = await _resolve_link_entity(client, entity_ref)
            linked_message = await client.get_messages(entity, ids=message_id)
            if not linked_message or not linked_message.media:
                await event.respond("Telegram 链接中的消息不含媒体。")
                continue
            downloaded = (
                await _download_message(client, event, linked_message, download_root)
                or downloaded
            )
        except Exception as error:  # pylint: disable=broad-except
            logger.warning(
                "Unable to resolve Telegram message link: %s", type(error).__name__
            )
            await event.respond(
                "无法访问该 Telegram 链接。公开频道链接可直接下载；"
                "私有频道需要先将 Bot 加入并授予访问权限。"
            )
    return downloaded


async def _resolve_link_entity(client: TelegramClient, entity_ref):
    """Resolve a public username or locate a private channel in user dialogs."""
    try:
        return await client.get_entity(entity_ref)
    except ValueError:
        if not isinstance(entity_ref, int):
            raise
        async for dialog in client.iter_dialogs():
            if telethon_utils.get_peer_id(dialog.entity) == entity_ref:
                return dialog.entity
        raise


async def _start_link_client(config: dict) -> Optional[TelegramClient]:
    """Connect the optional authorised user session used for Telegram links."""
    session_path = os.environ.get(
        "TELEGRAM_LINK_SESSION",
        os.path.join(THIS_DIR, "sessions", "media_downloader_link_telethon"),
    )
    client = TelegramClient(
        session_path,
        api_id=config["api_id"],
        api_hash=config["api_hash"],
        proxy=_proxy_from_config(config),
    )
    await client.connect()
    if await client.is_user_authorized():
        logger.info("Telegram user session for message links is ready.")
        return client
    await client.disconnect()
    logger.warning(
        "Telegram user session for message links is not authorised; "
        "only links accessible to the Bot can be resolved."
    )
    return None


async def start_bot() -> None:
    """Start the optional bot listener inside the NiceGUI event loop."""
    global _bot_client, _link_client, _allowed_user_ids
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
                "直接发送、转发媒体文件，或发送 Telegram 消息链接给我，"
                "我会自动下载。\n"
                "/status - 查看运行状态\n"
                "/help - 查看帮助"
            )
            return
        if command == "/status":
            link_status = "已启用" if _link_client else "仅限 Bot 可访问频道"
            await event.respond(
                "Bot 在线，媒体自动下载已启用。\n" f"Telegram 链接下载：{link_status}。"
            )
            return
        if message.media:
            await _download_message(_bot_client, event, message, download_root)
            return
        await _download_telegram_links(
            _link_client or _bot_client, event, message.raw_text, download_root
        )

    await _bot_client.start(bot_token=bot_token)
    _link_client = await _start_link_client(config)
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
    global _bot_client, _link_client
    if _link_client and _link_client.is_connected():
        await _link_client.disconnect()
    _link_client = None
    if _bot_client and _bot_client.is_connected():
        await _bot_client.disconnect()
    _bot_client = None
