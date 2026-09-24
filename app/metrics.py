from __future__ import annotations

import math
from collections import defaultdict, deque
from threading import Lock
from typing import Any

from contracts.events import HOPS


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 2)


class HopLatencyMetrics:
    """Bounded in-memory latency distribution derived from TraceStamp events."""

    def __init__(self, max_samples: int = 5_000) -> None:
        self._samples: dict[tuple[str, str, str], deque[float]] = defaultdict(
            lambda: deque(maxlen=max_samples)
        )
        self._lock = Lock()

    def observe(self, stage_id: str, traces: list[dict[str, Any]]) -> None:
        by_hop: dict[str, int] = {}
        for trace in traces:
            hop = str(trace.get("hop", ""))
            value = trace.get("t_wall_ms")
            if hop in HOPS and isinstance(value, int):
                by_hop[hop] = value

        present = [(hop, by_hop[hop]) for hop in HOPS if hop in by_hop]
        with self._lock:
            for index, (from_hop, from_ms) in enumerate(present):
                for to_hop, to_ms in present[index + 1 :]:
                    delta = to_ms - from_ms
                    if delta >= 0:
                        self._samples[(stage_id, from_hop, to_hop)].append(float(delta))

    def stage_snapshot(self, stage_id: str) -> list[dict[str, Any]]:
        with self._lock:
            items = [
                (from_hop, to_hop, list(values))
                for (sample_stage, from_hop, to_hop), values in self._samples.items()
                if sample_stage == stage_id and values
            ]
        return [
            {
                "from_hop": from_hop,
                "to_hop": to_hop,
                "p50_ms": _percentile(values, 0.50),
                "p95_ms": _percentile(values, 0.95),
                "n": len(values),
            }
            for from_hop, to_hop, values in sorted(
                items, key=lambda item: (HOPS.index(item[0]), HOPS.index(item[1]))
            )
        ]

    def prometheus(self) -> list[str]:
        lines = [
            "# HELP nerdearla_hop_latency_ms Latency between pipeline trace hops.",
            "# TYPE nerdearla_hop_latency_ms summary",
        ]
        with self._lock:
            keys = sorted(
                self._samples,
                key=lambda item: (item[0], HOPS.index(item[1]), HOPS.index(item[2])),
            )
            samples = [(key, list(self._samples[key])) for key in keys]
        for (stage_id, from_hop, to_hop), values in samples:
            if not values:
                continue
            labels = (
                f'stage_id="{stage_id}",from_hop="{from_hop}",to_hop="{to_hop}"'
            )
            lines.append(
                f'nerdearla_hop_latency_ms{{{labels},quantile="0.5"}} '
                f"{_percentile(values, 0.50)}"
            )
            lines.append(
                f'nerdearla_hop_latency_ms{{{labels},quantile="0.95"}} '
                f"{_percentile(values, 0.95)}"
            )
            lines.append(f"nerdearla_hop_latency_ms_count{{{labels}}} {len(values)}")
        return lines


PIPELINE_METRICS = HopLatencyMetrics()

