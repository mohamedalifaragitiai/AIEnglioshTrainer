"""CPU proxy pronunciation score.

Fallback only, for when the wav2vec2 GOP model or the audio can't be loaded. Uses
STT token confidence as a coarse stand-in. The real, audio-based GOP in ``gop.py``
is preferred whenever the model is resident.
"""

from __future__ import annotations

from backend.coldpath.evaluators.base import clamp_score


def proxy_pronunciation(stt_confidence: float | None) -> tuple[float, dict]:
    if stt_confidence is None:
        return 60.0, {"method": "proxy", "reason": "no stt_confidence; neutral prior"}
    # Map a 0.5..1.0 confidence band onto ~40..100.
    score = clamp_score(40.0 + (stt_confidence - 0.5) * 120.0)
    return score, {"method": "proxy", "stt_confidence": stt_confidence}
