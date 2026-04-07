from __future__ import annotations

import sys

from proxy import main as proxy_main


def test_cli_devices_dispatches_to_devices_handler(monkeypatch) -> None:
    calls: list[str] = []

    def fake_devices() -> None:
        calls.append("devices")

    monkeypatch.setattr(proxy_main, "_devices", fake_devices)
    monkeypatch.setattr(sys, "argv", ["proxy", "devices"])

    proxy_main.cli()

    assert calls == ["devices"]


def test_devices_prints_device_table(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        proxy_main,
        "list_input_devices",
        lambda: [(1, "USB Mic", 48000), (3, "Webcam Mic", 16000)],
    )

    proxy_main._devices()
    output = capsys.readouterr().out

    assert "INDEX" in output
    assert "RATE" in output
    assert "USB Mic" in output
    assert "48000" in output


def test_devices_handles_empty_list(monkeypatch, capsys) -> None:
    monkeypatch.setattr(proxy_main, "list_input_devices", lambda: [])

    proxy_main._devices()
    output = capsys.readouterr().out

    assert "No audio input devices found." in output


def test_devices_handles_sounddevice_import_error(monkeypatch, capsys) -> None:
    def _raise() -> list[tuple[int, str, int]]:
        raise RuntimeError("sounddevice is required")

    monkeypatch.setattr(proxy_main, "list_input_devices", _raise)

    proxy_main._devices()
    output = capsys.readouterr().out

    assert "Unable to list input devices" in output
