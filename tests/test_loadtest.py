from pathlib import Path

from scripts import loadtest


def test_room_levels_and_publish_path() -> None:
    assert loadtest.parse_room_levels("10,6,8,6") == [6, 8, 10]
    command = loadtest.build_publish_command(
        Path("voice.wav"), "load-6", "rtmp://server:1935/"
    )
    assert command[-1] == "rtmp://server:1935/live/stage-load-6"
    assert "-re" in command


def test_observation_and_report_expose_breakpoint() -> None:
    result = loadtest.LevelResult(rooms=6)
    loadtest.observe_metrics(
        result,
        {
            "items": [
                {
                    "stage_id": "load-1",
                    "stream_up": True,
                    "vad_backlog_ms": 42,
                    "redis_publish_ms": 3,
                    "hop_latencies": [
                        {
                            "from_hop": "ingest",
                            "to_hop": "fanout",
                            "p95_ms": 212,
                            "n": 4,
                        }
                    ],
                }
            ]
        },
    )
    loadtest.evaluate_result(
        result,
        max_cpu=90,
        max_vad_backlog_ms=1_000,
        max_redis_publish_ms=100,
    )
    report = loadtest.render_report([result])
    assert "212.0 ms" in report
    assert "Número de salas donde se rompe: 6" in report
