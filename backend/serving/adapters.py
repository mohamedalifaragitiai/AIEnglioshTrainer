"""Concrete managed models + the default registry factory.

Heavy ML libraries are imported **lazily inside ``_load``** so importing this module
(and booting the app with models disabled) never drags in torch/faster-whisper.
Availability is a cheap import-spec probe; missing weights surface as a load-time
failure with an actionable message. All GPU model loads pass ``local_files_only`` so
runtime never hits the network — weights must be pre-fetched by ``setup_models.py``.
"""

from __future__ import annotations

import importlib.util

from backend.core.logging import get_logger
from backend.core.resource_guard import ResourceGuard
from backend.serving.base import ManagedModel, ModelKind, ModelRegistry
from backend.serving.llm_client import VLLMClient
from config.settings import Settings

log = get_logger("adapters")


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


class VLLMManagedModel(ManagedModel):
    """Represents a vLLM-served LLM. 'Loading' = health-checking the external
    server; weights live in the separate vLLM process, not this one."""

    kind = ModelKind.LLM

    def __init__(self, name: str, client: VLLMClient, *, vram_gb: float, enabled: bool = True):
        super().__init__(name, device="cuda:vllm", vram_gb=vram_gb, enabled=enabled)
        self._client = client

    def available(self) -> bool:
        return bool(self._client.base_url)

    async def _load(self) -> None:
        healthy = await self._client.health()
        if not healthy:
            raise RuntimeError(
                f"vLLM server not reachable at {self._client.base_url} — start it "
                f"(WSL2/Linux) before enabling models. See setup_models.py."
            )


class WhisperSTTModel(ManagedModel):
    kind = ModelKind.STT

    def __init__(self, settings: Settings):
        super().__init__(
            f"faster-whisper:{settings.stt_model}",
            device=settings.stt_device,
            vram_gb=settings.stt_vram_gb,
            enabled=settings.enable_stt,
        )
        self._settings = settings
        self.model = None

    def available(self) -> bool:
        return _installed("faster_whisper")

    async def _load(self) -> None:
        from faster_whisper import WhisperModel
        from huggingface_hub import snapshot_download

        s = self._settings
        # Load from the exact repo setup_models.py fetched (a CTranslate2 build),
        # resolved to its local snapshot path — faster-whisper's size-name aliases
        # map to a different repo, so we bypass them. Offline: never fetch at runtime.
        local_path = snapshot_download(
            s.stt_repo, cache_dir=str(s.models_dir), local_files_only=True
        )
        compute_type = s.stt_compute_type if s.stt_device.startswith("cuda") else "int8"
        self.model = WhisperModel(
            local_path,
            device="cuda" if s.stt_device.startswith("cuda") else "cpu",
            compute_type=compute_type,
        )


class Wav2Vec2GOPModel(ManagedModel):
    kind = ModelKind.GOP

    def __init__(self, settings: Settings):
        super().__init__(
            f"wav2vec2-gop:{settings.gop_model}",
            device=settings.gop_device,
            vram_gb=settings.gop_vram_gb,
            enabled=settings.enable_gop,
        )
        self._settings = settings
        self.model = None
        self.processor = None

    def available(self) -> bool:
        return _installed("torch") and _installed("transformers")

    async def _load(self) -> None:
        import torch
        from transformers import AutoModelForCTC, Wav2Vec2FeatureExtractor

        s = self._settings
        # GOP uses only the acoustic posteriors (max-prob per frame), never phoneme
        # decoding — so load just the feature extractor, not the full processor. The
        # espeak phoneme *tokenizer* would otherwise require the espeak-ng system
        # binary at load time; the feature extractor needs no system deps.
        self.processor = Wav2Vec2FeatureExtractor.from_pretrained(
            s.gop_model, cache_dir=str(s.models_dir), local_files_only=True
        )
        model = AutoModelForCTC.from_pretrained(
            s.gop_model, cache_dir=str(s.models_dir), local_files_only=True
        )
        if s.gop_device.startswith("cuda") and torch.cuda.is_available():
            model = model.to("cuda")
        self.model = model.eval()


class KokoroTTSModel(ManagedModel):
    kind = ModelKind.TTS

    def __init__(self, settings: Settings):
        super().__init__(
            f"kokoro:{settings.tts_model}",
            device=settings.tts_device,
            vram_gb=settings.tts_vram_gb,
            enabled=settings.enable_tts,
        )
        self._settings = settings
        self.pipeline = None

    def available(self) -> bool:
        return _installed("kokoro")

    async def _load(self) -> None:
        from kokoro import KPipeline

        device = "cuda" if self._settings.tts_device.startswith("cuda") else "cpu"
        # American English by default; voice packs selected per-utterance later.
        self.pipeline = KPipeline(lang_code="a", device=device)
        # Warm up: the first synth compiles CUDA kernels + loads the voice pack, which
        # otherwise lands on the first live turn as a big first-audio spike. Run one
        # throwaway phrase now so the live path is hot.
        try:
            for _ in self.pipeline("Ready to help you practice.", voice="af_heart"):
                break
        except Exception as exc:  # noqa: BLE001 — warmup is best-effort
            log.warning("tts_warmup_failed", error=str(exc))


def build_default_registry(
    guard: ResourceGuard, settings: Settings
) -> tuple[ModelRegistry, VLLMClient]:
    """Wire the standard split-model set: vLLM hot 8B + cold 14B, Whisper turbo,
    wav2vec2 GOP, Kokoro TTS."""
    llm_client = VLLMClient(
        settings.vllm_base_url,
        hot_model=settings.vllm_hot_model,
        cold_model=settings.vllm_cold_model,
        guard=guard,
        timeout_s=settings.vllm_request_timeout_s,
    )
    registry = ModelRegistry(guard)
    # vLLM VRAM is the guard's reserved block; split the estimate across the two
    # entries for reporting only (they do not count toward the min-set sum).
    vllm_total_gb = settings.vllm_vram_fraction * 16.0
    if settings.vllm_hot_model == settings.vllm_cold_model:
        # One served model doing double duty for both paths: register it ONCE, with
        # the whole reservation. Registering it twice made /stats list the same model
        # in duplicate and over-report models_loaded.
        registry.register(
            VLLMManagedModel(
                f"vllm:{settings.vllm_hot_model}",
                llm_client,
                vram_gb=round(vllm_total_gb, 1),
            )
        )
    else:
        registry.register(
            VLLMManagedModel(
                f"vllm:{settings.vllm_hot_model}",
                llm_client,
                vram_gb=round(vllm_total_gb * 0.45, 1),
            )
        )
        registry.register(
            VLLMManagedModel(
                f"vllm:{settings.vllm_cold_model}",
                llm_client,
                vram_gb=round(vllm_total_gb * 0.55, 1),
            )
        )
    registry.register(WhisperSTTModel(settings))
    registry.register(Wav2Vec2GOPModel(settings))
    registry.register(KokoroTTSModel(settings))
    return registry, llm_client
