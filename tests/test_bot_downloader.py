import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("telethon")

from bot_downloader import (  # noqa: E402
    _format_size,
    _parse_command,
    _target_path,
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
    monkeypatch.setattr("bot_downloader.time.monotonic", lambda: next(times))
    reporter = _TelegramProgressReporter(StatusMessage(), "video.mp4", interval=3.0)

    async def report_progress():
        await reporter(10, 100)
        await reporter(20, 100)
        await reporter(100, 100)

    asyncio.run(report_progress())

    assert len(edits) == 2
    assert "10.0%" in edits[0]
    assert "100.0%" in edits[1]
