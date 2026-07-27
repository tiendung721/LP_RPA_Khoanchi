from __future__ import annotations

from pathlib import Path

import pytest

import app.services.browser_launcher as browser_module
from app.services.browser_launcher import (
    BrowserExecutable,
    BrowserLauncher,
    InvalidBrowserUrlError,
)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "ftp://example.com/gpt",
        "chatgpt.com/g/g-example",
        "https://",
        "https://user:secret@example.com/gpt",
        "https://example.com/a path",
    ],
)
def test_validate_url_rejects_invalid_values(url: str) -> None:
    with pytest.raises(InvalidBrowserUrlError):
        BrowserLauncher.validate_url(url)


def test_validate_url_accepts_http_and_https() -> None:
    assert (
        BrowserLauncher.validate_url(" https://chatgpt.com/g/g-example ")
        == "https://chatgpt.com/g/g-example"
    )
    assert BrowserLauncher.validate_url("http://localhost:8080/gpt") == (
        "http://localhost:8080/gpt"
    )


def test_missing_configured_browser_falls_back_without_opening_real_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened_urls: list[str] = []

    class FakeDesktopServices:
        @staticmethod
        def openUrl(url: object) -> bool:
            opened_urls.append(url.toString())  # type: ignore[attr-defined]
            return True

    monkeypatch.setattr(browser_module, "QDesktopServices", FakeDesktopServices)
    monkeypatch.setattr(
        BrowserLauncher,
        "autodetect_executable",
        classmethod(lambda cls, preference="auto": None),
    )

    result = BrowserLauncher().launch(
        "https://chatgpt.com/g/g-example",
        preference="chrome",
        executable_path="Z:/khong-ton-tai/chrome.exe",
    )

    assert result.success is True
    assert result.used_default_browser is True
    assert result.fallback_used is True
    assert result.warning
    assert opened_urls == ["https://chatgpt.com/g/g-example"]


def test_chromium_launch_uses_separate_profile_and_detached_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "chrome.exe"
    executable.write_bytes(b"fake executable")
    profile = tmp_path / "BrowserProfile"
    calls: list[tuple[str, list[str]]] = []

    class FakeProcess:
        @staticmethod
        def startDetached(program: str, arguments: list[str]) -> tuple[bool, int]:
            calls.append((program, arguments))
            return True, 12345

    monkeypatch.setattr(browser_module, "QProcess", FakeProcess)
    monkeypatch.setattr(
        BrowserLauncher,
        "autodetect_executable",
        classmethod(
            lambda cls, preference="auto": BrowserExecutable(
                "Google Chrome", executable
            )
        ),
    )

    result = BrowserLauncher().launch(
        "https://chatgpt.com/g/g-example",
        preference="auto",
        profile_dir=profile,
    )

    assert result.success is True
    assert result.used_default_browser is False
    assert result.pid == 12345
    assert profile.is_dir()
    assert calls == [
        (
            str(executable.resolve()),
            [
                f"--user-data-dir={profile.resolve()}",
                "--profile-directory=Default",
                "https://chatgpt.com/g/g-example",
            ],
        )
    ]
