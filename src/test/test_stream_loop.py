"""Smoke tests for StreamLoop v2 (S3)."""


def test_stream_loop_importable():
    from src.runtime.stream.loop import StreamLoop
    from src.runtime.stream.demux import StreamDemux

    assert StreamLoop.__name__ == "StreamLoop"
    assert StreamDemux.__name__ == "StreamDemux"
