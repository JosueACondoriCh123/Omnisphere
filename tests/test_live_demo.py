from scripts.validate_live_demo import overlaps, websocket_url


def test_live_validator_uses_the_nginx_websocket_partition() -> None:
    assert websocket_url("http://localhost:8088", "1", "es") == (
        "ws://localhost:8088/ws/stages/1/es"
    )
    assert websocket_url("https://captions.example", "main", "en") == (
        "wss://captions.example/ws/stages/main/en"
    )


def test_live_validator_requires_real_timestamp_overlap() -> None:
    draft = {"t0_ms": 1000, "t1_ms": 2500}
    assert overlaps(draft, {"t0_ms": 1000, "t1_ms": 3100})
    assert not overlaps(draft, {"t0_ms": 2500, "t1_ms": 3100})
