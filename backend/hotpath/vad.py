"""Voice-activity detection and turn segmentation.

Default backend is a dependency-free **energy** VAD (RMS over PCM16 frames) so the
hot path segments speech offline without any model download. ``silero`` is an
optional higher-quality upgrade (lazy torch import). The :class:`Segmenter` turns a
stream of frames into finalized utterances: it starts collecting on speech and
ends the turn after a hangover of trailing silence.
"""

from __future__ import annotations

import math
from array import array
from typing import Protocol

from backend.core.logging import get_logger
from config.settings import Settings

log = get_logger("vad")


class VAD(Protocol):
    frame_bytes: int
    def is_speech(self, frame: bytes) -> bool: ...


def _rms_normalized(frame: bytes) -> float:
    """RMS of a PCM16 frame normalized to 0..1 (silence..full-scale)."""
    if not frame:
        return 0.0
    samples = array("h")
    # Drop a dangling odd byte defensively.
    samples.frombytes(frame[: len(frame) - (len(frame) % 2)])
    if not samples:
        return 0.0
    acc = sum(s * s for s in samples)
    return math.sqrt(acc / len(samples)) / 32768.0


class EnergyVAD:
    def __init__(self, sample_rate: int, frame_ms: int, threshold: float):
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.threshold = threshold
        self.frame_bytes = int(sample_rate * frame_ms / 1000) * 2  # int16

    def is_speech(self, frame: bytes) -> bool:
        return _rms_normalized(frame) >= self.threshold


class SileroVAD:
    """Optional Silero VAD (lazy torch). Falls back to raising if unavailable —
    callers should prefer EnergyVAD unless deps are known present."""

    def __init__(self, sample_rate: int, frame_ms: int, threshold: float = 0.5):
        import torch  # noqa: F401
        from silero_vad import load_silero_vad

        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.threshold = threshold
        self.frame_bytes = int(sample_rate * frame_ms / 1000) * 2
        self._model = load_silero_vad()

    def is_speech(self, frame: bytes) -> bool:
        import torch

        samples = array("h")
        samples.frombytes(frame[: len(frame) - (len(frame) % 2)])
        if not samples:
            return False
        t = torch.tensor(samples, dtype=torch.float32) / 32768.0
        return float(self._model(t, self.sample_rate).item()) >= self.threshold


def build_vad(settings: Settings) -> VAD:
    if settings.vad_backend == "silero":
        try:
            return SileroVAD(settings.hotpath_sample_rate, settings.vad_frame_ms)
        except Exception as exc:  # noqa: BLE001
            log.warning("silero_unavailable_fallback_energy", error=str(exc))
    return EnergyVAD(
        settings.hotpath_sample_rate, settings.vad_frame_ms, settings.vad_energy_threshold
    )


class Segmenter:
    """Collect frames into a finalized utterance using VAD + a silence hangover.

    ``push`` returns the utterance PCM once end-of-speech is detected (enough
    trailing silence after at least ``min_speech_ms`` of speech), else ``None``.
    """

    def __init__(
        self,
        vad: VAD,
        *,
        frame_ms: int,
        silence_hangover_ms: int,
        min_speech_ms: int,
    ):
        self.vad = vad
        self.frame_ms = frame_ms
        self.silence_hangover_frames = max(1, silence_hangover_ms // frame_ms)
        self.min_speech_frames = max(1, min_speech_ms // frame_ms)
        self._buf = bytearray()
        self._speech_frames = 0
        self._silence_run = 0
        self._in_speech = False

    def push(self, frame: bytes) -> bytes | None:
        speech = self.vad.is_speech(frame)
        if speech:
            self._in_speech = True
            self._speech_frames += 1
            self._silence_run = 0
            self._buf.extend(frame)
            return None

        # silence
        if self._in_speech:
            self._buf.extend(frame)  # keep a little trailing silence
            self._silence_run += 1
            if (
                self._silence_run >= self.silence_hangover_frames
                and self._speech_frames >= self.min_speech_frames
            ):
                return self._finalize()
        return None

    def reset(self) -> None:
        """Throw away whatever has accumulated without finalizing it.

        Used when a learner discards a take: the audio must not become an
        utterance, and the next recording must not inherit its trailing frames.
        """
        self._reset()

    def flush(self) -> bytes | None:
        """Force-finalize whatever speech has accumulated (e.g. client said stop)."""
        if self._in_speech and self._speech_frames >= self.min_speech_frames:
            return self._finalize()
        self._reset()
        return None

    def _finalize(self) -> bytes:
        pcm = bytes(self._buf)
        self._reset()
        return pcm

    def _reset(self) -> None:
        self._buf = bytearray()
        self._speech_frames = 0
        self._silence_run = 0
        self._in_speech = False
