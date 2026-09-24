from app.metrics import HopLatencyMetrics


def test_hop_metrics_report_p50_p95_and_count() -> None:
    metrics = HopLatencyMetrics()
    for total in (100, 200, 300, 400, 500):
        metrics.observe(
            "1",
            [
                {"hop": "ingest", "t_wall_ms": 1_000},
                {"hop": "vad", "t_wall_ms": 1_020},
                {"hop": "fanout", "t_wall_ms": 1_000 + total},
            ],
        )

    item = next(
        row
        for row in metrics.stage_snapshot("1")
        if row["from_hop"] == "ingest" and row["to_hop"] == "fanout"
    )
    assert item == {
        "from_hop": "ingest",
        "to_hop": "fanout",
        "p50_ms": 300.0,
        "p95_ms": 500.0,
        "n": 5,
    }
    output = "\n".join(metrics.prometheus())
    assert 'quantile="0.95"' in output
    assert "nerdearla_hop_latency_ms_count" in output
