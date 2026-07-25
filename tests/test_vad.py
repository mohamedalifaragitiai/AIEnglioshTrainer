"""Tests for the energy VAD and the turn segmenter."""

from __future__ import annotations

from array import array

from backend.hotpath.vad import EnergyVAD, Segmenter

SR = 16000
FRAME_MS = 20
FRAME_SAMPLES = SR * FRAME_MS // 1000  # 320
FRAME_BYTES = FRAME_SAMPLES * 2


def _loud(amplitude: int = 8000) -> bytes:
    return array("h", [amplitude] * FRAME_SAMPLES).tobytes()


def _silent() -> bytes:
    return b"\x00\x00" * FRAME_SAMPLES


def _vad(threshold: float = 0.02) -> EnergyVAD:
    return EnergyVAD(SR, FRAME_MS, threshold)


def test_energy_vad_distinguishes_speech_from_silence():
    vad = _vad()
    assert vad.is_speech(_loud()) is True
    assert vad.is_speech(_silent()) is False


def test_energy_vad_frame_bytes():
    assert _vad().frame_bytes == FRAME_BYTES


def _segmenter() -> Segmenter:
    return Segmenter(
        _vad(),
        frame_ms=FRAME_MS,
        silence_hangover_ms=100,  # 5 frames
        min_speech_ms=60,          # 3 frames
    )


def test_segmenter_finalizes_after_silence_hangover():
    seg = _segmenter()
    out = None
    # 10 speech frames (>= min), then silence until hangover trips.
    for _ in range(10):
        assert seg.push(_loud()) is None
    for _ in range(5):
        out = seg.push(_silent())
        if out is not None:
            break
    assert out is not None
    # Utterance = 10 speech + trailing silence frames, each FRAME_BYTES.
    assert len(out) >= 10 * FRAME_BYTES
    assert len(out) % FRAME_BYTES == 0


def test_segmenter_ignores_too_short_blip():
    seg = _segmenter()
    seg.push(_loud())  # only 1 speech frame (< min 3)
    for _ in range(10):
        assert seg.push(_silent()) is None  # never finalizes a sub-min blip


def test_segmenter_flush_forces_finalize():
    seg = _segmenter()
    for _ in range(5):
        seg.push(_loud())
    out = seg.flush()
    assert out is not None and len(out) == 5 * FRAME_BYTES


def test_segmenter_resets_between_utterances():
    seg = _segmenter()
    for _ in range(10):
        seg.push(_loud())
    first = None
    for _ in range(5):
        first = seg.push(_silent()) or first
    assert first is not None
    # A fresh utterance should segment independently.
    for _ in range(10):
        seg.push(_loud())
    second = None
    for _ in range(5):
        second = seg.push(_silent()) or second
    assert second is not None
