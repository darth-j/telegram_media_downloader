from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("telethon")

from bot_downloader import _parse_command, _target_path  # noqa: E402


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
