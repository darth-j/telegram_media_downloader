import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("telethon")

from bot_downloader import (  # noqa: E402
    _download_telegram_links,
    _format_size,
    _parse_command,
    _resolve_link_entity,
    _target_path,
    _telegram_message_links,
    _TelegramProgressReporter,
)


def test_target_path_sanitizes_name_and_avoids_overwrite(tmp_path: Path):
    message = SimpleNamespace(
        id=42, file=SimpleNamespace(name="../../video.mp4", ext=".mp4")
    )

    first = _target_path(str(tmp_path), 123, message)
    assert first == tmp_path / "bot" / "123" / "video.mp4"
    first.touch()

    second = _target_path(str(tmp_path), 123, message)
    assert second == tmp_path / "bot" / "123" / "video_42.mp4"


@pytest.mark.parametrize(
    ("text", "expected"),
    [(None, ""), ("", ""), ("/HELP", "/help"), ("/help@dwmy_bot x", "/help")],
)
def test_parse_command(text, expected):
    assert _parse_command(text) == expected


def test_extracts_public_private_and_topic_telegram_links():
    text = (
        "https://t.me/public_channel/42, "
        "https://t.me/s/another_channel/88?single "
        "https://t.me/c/1234567890/7/99"
    )

    assert _telegram_message_links(text) == [
        ("public_channel", 42),
        ("another_channel", 88),
        (-1001234567890, 99),
    ]


def test_ignores_non_message_and_invite_links_and_removes_duplicates():
    text = (
        "https://example.com/file.mp4 https://t.me/+invite "
        "t.me/channel/5 https://t.me/channel/5"
    )

    assert _telegram_message_links(text) == [("channel", 5)]


def test_downloads_media_from_telegram_link(monkeypatch, tmp_path):
    linked_message = SimpleNamespace(id=42, media=object())
    client = SimpleNamespace(
        get_entity=AsyncMock(return_value="entity"),
        get_messages=AsyncMock(return_value=linked_message),
    )
    event = SimpleNamespace(sender_id=123, respond=AsyncMock())
    download = AsyncMock(return_value=True)
    monkeypatch.setattr("bot_downloader._download_message", download)

    async def download_link():
        return await _download_telegram_links(
            client, event, "https://t.me/channel/42", str(tmp_path)
        )

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    assert loop.run_until_complete(download_link()) is True
    client.get_entity.assert_awaited_once_with("channel")
    client.get_messages.assert_awaited_once_with("entity", ids=42)
    download.assert_awaited_once_with(client, event, linked_message, str(tmp_path))


def test_resolves_private_channel_from_user_dialogs(monkeypatch):
    entity = object()

    class Client:
        get_entity = AsyncMock(side_effect=ValueError("not cached"))

        async def iter_dialogs(self):
            yield SimpleNamespace(entity=entity)

    monkeypatch.setattr("bot_downloader.telethon_utils.get_peer_id", lambda _: -100123)

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    resolved = loop.run_until_complete(_resolve_link_entity(Client(), -100123))
    assert resolved is entity


@pytest.mark.parametrize(
    ("size", "expected"),
    [(0, "0.0 B"), (1024, "1.0 KB"), (5 * 1024 * 1024, "5.0 MB")],
)
def test_format_size(size, expected):
    assert _format_size(size) == expected


def test_progress_reporter_throttles_and_reports_completion(monkeypatch):
    edits = []

    class StatusMessage:
        async def edit(self, text):
            edits.append(text)

    times = iter([10.0, 11.0, 14.0])
    monkeypatch.setattr("bot_downloader.monotonic", lambda: next(times))
    reporter = _TelegramProgressReporter(StatusMessage(), "video.mp4", interval=3.0)

    async def report_progress():
        await reporter(10, 100)
        await reporter(20, 100)
        await reporter(100, 100)

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(report_progress())

    assert len(edits) == 2
    assert "10.0%" in edits[0]
    assert "100.0%" in edits[1]
