from __future__ import annotations

from pathlib import Path

from scripts.smoke_validator import (
    default_plumbing_url,
    default_redis_url,
    default_transcriber_url,
    default_ws_url,
    write_resilience_report,
)


def test_url_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://custom:6379/1")
    monkeypatch.setenv("WS_URL", "ws://custom:80/ws/stages/1/es")
    monkeypatch.setenv("PLUMBING_URL", "http://custom-plumbing:8080")
    monkeypatch.setenv("TRANSCRIBER_URL", "http://custom-transcriber:8090")

    assert default_redis_url() == "redis://custom:6379/1"
    assert default_ws_url() == "ws://custom:80/ws/stages/1/es"
    assert default_plumbing_url() == "http://custom-plumbing:8080"
    assert default_transcriber_url() == "http://custom-transcriber:8090"


def test_write_resilience_report(tmp_path: Path) -> None:
    report_file = tmp_path / "smoke-resilience-report.md"
    write_resilience_report(
        report_path=report_file,
        recovery_time_seconds=2.45,
        total_published=200,
        total_received=200,
        total_duplicates=0,
        total_overflows=0,
        memory_peak_mb=128.5,
        status_pass=True,
    )

    assert report_file.is_file()
    content = report_file.read_text(encoding="utf-8")
    assert "Tiempo de recuperación de Redis" in content
    assert "2.45 s" in content
    assert "Mensajes publicados" in content
    assert "200" in content
    assert "Duplicados detectados" in content
    assert "Queue Overflows" in content
    assert "Pico de Memoria" in content
    assert "PASS" in content
