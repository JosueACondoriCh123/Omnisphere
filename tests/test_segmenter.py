from app.segmenter import SegmentWindow, UtteranceSegmenter


def make_segmenter(*, max_seconds: float = 10) -> UtteranceSegmenter:
    return UtteranceSegmenter(
        sample_rate=1_000,
        sample_bytes=2,
        frame_samples=100,
        pre_roll_ms=200,
        partial_seconds=1.5,
        max_seconds=max_seconds,
    )


def push_frame(
    segmenter: UtteranceSegmenter,
    sample: int,
    *,
    started: bool = False,
    ended: bool = False,
) -> list[SegmentWindow]:
    return segmenter.push(
        b"\x01\x00" * 100,
        stream_end_sample=sample,
        speech_started=started,
        speech_ended=ended,
    )


def test_silence_is_not_buffered_as_a_segment() -> None:
    segmenter = make_segmenter()
    assert all(not push_frame(segmenter, sample) for sample in range(100, 1_100, 100))
    assert segmenter.flush(1_000) == []


def test_continuous_speech_emits_overlapping_drafts_then_commit() -> None:
    segmenter = make_segmenter()
    emitted: list[SegmentWindow] = []
    for sample in range(100, 500, 100):
        emitted.extend(push_frame(segmenter, sample))
    emitted.extend(push_frame(segmenter, 500, started=True))
    for sample in range(600, 3_500, 100):
        emitted.extend(push_frame(segmenter, sample))
    emitted.extend(push_frame(segmenter, 3_500, ended=True))

    assert [item.reason for item in emitted] == ["partial", "partial", "silence"]
    assert [item.t0_ms for item in emitted] == [300, 300, 300]
    assert [item.t1_ms for item in emitted] == [1800, 3300, 3500]
    assert [item.is_clause_end for item in emitted] == [False, False, True]
    assert len(emitted[0].audio) < len(emitted[1].audio) < len(emitted[2].audio)


def test_stream_interruption_flushes_only_an_uncommitted_draft() -> None:
    segmenter = make_segmenter()
    push_frame(segmenter, 100)
    push_frame(segmenter, 200, started=True)
    flushed = segmenter.flush(900)
    assert len(flushed) == 1
    assert flushed[0].reason == "stream_interrupted"
    assert flushed[0].is_clause_end is False


def test_max_duration_force_cut_is_not_a_clause_end() -> None:
    segmenter = make_segmenter(max_seconds=2)
    push_frame(segmenter, 100)
    push_frame(segmenter, 200, started=True)
    emitted = []
    for sample in range(300, 2_200, 100):
        emitted.extend(push_frame(segmenter, sample))
    assert emitted[-1].reason == "max_duration"
    assert emitted[-1].is_clause_end is False
