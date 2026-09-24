from app.capture_node import build_capture_command
from app.room_worker import build_ffmpeg_command


def test_room_worker_audio_contract() -> None:
    command = build_ffmpeg_command("rtsp://mediamtx:8554/live/stage-1")
    joined = " ".join(command)
    assert "highpass=f=80" in joined
    assert "loudnorm=I=-16:TP=-1.5:LRA=11:linear=true" in joined
    assert "pcm_s16le" in command
    assert command[command.index("-ar") + 1] == "16000"
    assert command[command.index("-ac") + 1] == "1"
    assert command[-2:] == ["s16le", "pipe:1"]


def test_capture_node_publishes_expected_rtmp_shape() -> None:
    command = build_capture_command(
        "alsa", "hw:0", "rtmp://mediamtx:1935/live/stage-2"
    )
    assert command[-1] == "rtmp://mediamtx:1935/live/stage-2"
    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-f", 5) + 1] in {"alsa", "flv"}


def test_demo_capture_uses_synthetic_source() -> None:
    command = build_capture_command(
        "alsa", "ignored", "rtmp://mediamtx:1935/live/stage-1", demo=True
    )
    assert "lavfi" in command
    assert "anoisesrc=color=pink:amplitude=0.04:sample_rate=48000" in command

