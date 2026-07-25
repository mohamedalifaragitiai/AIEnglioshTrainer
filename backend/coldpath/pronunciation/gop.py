"""Real, audio-based Goodness-of-Pronunciation via the wav2vec2 phoneme model.

Runs the resident wav2vec2 CTC phoneme model over the learner's audio and derives a
goodness score from the per-frame posterior confidence (mean of the max phoneme
probability across non-blank frames). This is a genuine acoustic measure — the LLM
never sees audio. Full phoneme-level forced-alignment GOP is a later refinement;
this posterior-confidence formulation is the v1 real pipeline.

All heavy imports are deferred so the module loads without torch present.
"""

from __future__ import annotations

import wave

from backend.coldpath.evaluators.base import clamp_score
from backend.core.logging import get_logger
from backend.serving.adapters import Wav2Vec2GOPModel

log = get_logger("gop")


def _read_wav_mono16k(path: str):
    import numpy as np

    with wave.open(path, "rb") as wf:
        sr = wf.getframerate()
        n = wf.getnframes()
        raw = wf.readframes(n)
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return audio, sr


class GOPScorer:
    def __init__(self, model: Wav2Vec2GOPModel):
        self._model = model

    def available(self) -> bool:
        return self._model.available() and self._model.model is not None

    def score(self, audio_path: str) -> tuple[float, dict]:
        """Return (0-100 pronunciation score, details). Raises on load/read error."""
        import torch

        if self._model.model is None or self._model.processor is None:
            raise RuntimeError("GOP model not loaded")

        audio, sr = _read_wav_mono16k(audio_path)
        if sr != 16000:
            raise ValueError(f"expected 16kHz audio, got {sr}")

        proc = self._model.processor
        inputs = proc(audio, sampling_rate=16000, return_tensors="pt")
        device = next(self._model.model.parameters()).device
        with torch.no_grad():
            logits = self._model.model(inputs.input_values.to(device)).logits
        probs = torch.softmax(logits, dim=-1)[0]           # [frames, vocab]
        max_prob, pred = probs.max(dim=-1)                  # per-frame goodness
        blank_id = getattr(self._model.model.config, "pad_token_id", 0)
        keep = pred != blank_id
        goodness = float(max_prob[keep].mean()) if keep.any() else float(max_prob.mean())

        score = clamp_score(goodness * 100.0)
        return score, {
            "method": "wav2vec2_gop",
            "goodness": round(goodness, 4),
            "frames": int(probs.shape[0]),
            "voiced_frames": int(keep.sum()),
        }
