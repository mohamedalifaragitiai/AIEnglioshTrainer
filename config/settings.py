"""Central configuration (pydantic-settings).

Every tunable — ports, resource ceilings, sample cadence, model/data paths —
lives here so the whole system shares one source of truth. Values may be
overridden via environment variables (prefix ``COACH_``) or a local ``.env``.

The 96% ceiling is the point of the project; it is configurable but defaults to
0.96 and should not be raised without understanding the freeze risk documented in
``references/resource-governance.md``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="COACH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App / serving -----------------------------------------------------
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_name: str = "english-coach"
    log_level: str = "INFO"
    log_json: bool = True  # structured JSON logs; set false for human-readable dev logs
    # Origins allowed to call the API (the Next.js dev server). JSON list or comma
    # string via COACH_CORS_ORIGINS.
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # --- Resource governance (the 96% ceiling) -----------------------------
    # Hard per-resource ceiling. Crossing it sustained risks a machine freeze.
    resource_ceiling: float = Field(default=0.96, ge=0.50, le=0.999)
    # Soft threshold: start shedding optional (cold-path) work well before the ceiling.
    resource_soft: float = Field(default=0.88, ge=0.10, le=0.999)
    # Background sampler cadence in seconds. Never busy-wait; this is an async sleep.
    sample_interval_s: float = Field(default=1.0, gt=0.0)
    # Rolling window length (# samples) so a single spike doesn't trip degradation.
    rolling_window: int = Field(default=3, ge=1, le=60)
    # Hysteresis margin: drop a degradation level only after usage falls this far
    # below the level's entry threshold, so the ladder doesn't flap.
    hysteresis_margin: float = Field(default=0.06, ge=0.0, le=0.5)

    # Degradation-ladder entry thresholds (peak usage ratio across resources).
    # L1 = pause cold jobs, L2 = trim LLM ctx/tokens, L3 = shrink STT/TTS,
    # L4 = reject new sessions. Kept as settings so they can be tuned per host.
    ladder_l1: float = Field(default=0.88, ge=0.0, le=1.0)
    ladder_l2: float = Field(default=0.92, ge=0.0, le=1.0)
    ladder_l3: float = Field(default=0.94, ge=0.0, le=1.0)
    ladder_l4: float = Field(default=0.96, ge=0.0, le=1.0)

    # --- VRAM budgeting for co-residency -----------------------------------
    # vLLM reserves this fraction of total VRAM statically at startup. The guard
    # treats it as a fixed pre-committed block (reserved-not-available), not free
    # VRAM it may hand out. Not loaded in Phase 0, but budgeted here from the start.
    vllm_vram_fraction: float = Field(default=0.68, ge=0.0, le=0.96)

    # --- Model serving (Phase 2) -------------------------------------------
    # Loading is OFF by default so the app boots without any weights present.
    # Turn on only after `setup_models.py` has fetched weights and (for the LLM)
    # a vLLM server is running. When on, startup refuses to proceed if the
    # minimum resident set won't fit under the 96% VRAM ceiling.
    load_models: bool = False

    # vLLM runs as a SEPARATE process (native Linux/WSL2 on Windows) exposing an
    # OpenAI-compatible API. The app never imports vLLM; it only talks HTTP.
    vllm_base_url: str = "http://127.0.0.1:8001"
    vllm_hot_model: str = "Qwen/Qwen3-8B"      # fast live dialogue
    vllm_cold_model: str = "Qwen/Qwen3-14B"    # cold-path assessment
    vllm_request_timeout_s: float = 60.0

    # Faster-Whisper STT (hot path). float16 on GPU, int8 on CPU fallback.
    enable_stt: bool = True
    stt_model: str = "large-v3-turbo"
    # HF repo actually downloaded + loaded (a CTranslate2 build of turbo).
    stt_repo: str = "deepdml/faster-whisper-large-v3-turbo-ct2"
    stt_device: str = "cuda"
    stt_compute_type: str = "float16"
    stt_vram_gb: float = 1.9  # measured 1.84GB on RTX 5080 (float16)

    # wav2vec2 GOP pronunciation (cold path). Real GOP algorithm lands in Phase 4;
    # Phase 2 loads/health-checks the model through the guard.
    enable_gop: bool = True
    gop_model: str = "facebook/wav2vec2-lv-60-espeak-cv-ft"  # phoneme CTC
    gop_device: str = "cuda"
    gop_vram_gb: float = 1.5  # measured 1.46GB on RTX 5080

    # Kokoro-82M TTS (hot path, own process/GPU).
    enable_tts: bool = True
    tts_model: str = "hexgrad/Kokoro-82M"
    tts_device: str = "cuda"
    tts_vram_gb: float = 0.3  # measured 0.23GB on RTX 5080

    # --- Hot path (Phase 3) ------------------------------------------------
    hotpath_sample_rate: int = 16000
    hotpath_system_prompt: str = (
        "You are a friendly, concise English speaking coach. Reply in one or two "
        "short, natural sentences to keep the conversation flowing, and gently model "
        "correct usage. Do not lecture."
    )
    hotpath_reply_max_tokens: int = 200
    first_audio_budget_ms: float = 300.0  # target time-to-first-audio

    # VAD: 'energy' is a dependency-free offline default so the hot path runs
    # without any model download; 'silero' is a higher-quality optional upgrade.
    vad_backend: str = "energy"
    vad_frame_ms: int = 20
    vad_energy_threshold: float = 0.02       # normalized RMS (int16 / 32768)
    # Trailing silence that ends a turn. Long enough that a natural mid-sentence
    # pause doesn't make the coach jump in before the learner finishes.
    vad_silence_hangover_ms: int = 900
    vad_min_speech_ms: int = 300             # ignore blips shorter than this

    # --- Paths -------------------------------------------------------------
    data_dir: Path = _REPO_ROOT / "data"
    models_dir: Path = _REPO_ROOT / "models"
    # SQLite file (WAL mode). Override with COACH_DB_PATH for tests/alt hosts.
    db_path: Path | None = None
    # Where learner-turn audio is written (for cold-path re-analysis). None = off.
    audio_dir: Path | None = None
    # Where generated report files are written. None = <data_dir>/reports.
    report_dir: Path | None = None

    # --- Gap analysis / plans (Phase 5) ------------------------------------
    # Per-dimension target score used to size gaps (85 ~ "fluent" band).
    gap_target_score: float = 85.0

    # --- Auth (Phase 8) ----------------------------------------------------
    # Bearer-token lifetime. 14 days suits a personal workstation: long enough not to
    # nag, short enough that a stale token in a browser eventually dies.
    auth_token_ttl_hours: int = 336
    auth_min_password_len: int = 8
    # Allow an existing profile that has no password (e.g. the seeded demo learner) to
    # be claimed by setting one, keeping its history. Turn off to require fresh
    # registration for every account.
    auth_allow_claim: bool = True
    # How long a freshly opened WebSocket may sit before sending its auth frame. A
    # socket that never authenticates otherwise holds a session slot forever.
    ws_auth_timeout_s: float = 10.0

    @property
    def resolved_report_dir(self) -> Path:
        return self.report_dir or (self.data_dir / "reports")

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, v: str) -> str:
        return v.upper()

    @property
    def ladder_thresholds(self) -> tuple[float, float, float, float]:
        """Entry thresholds for degradation levels 1..4, ascending."""
        return (self.ladder_l1, self.ladder_l2, self.ladder_l3, self.ladder_l4)

    @property
    def resolved_db_path(self) -> Path:
        """SQLite file path, defaulting to ``<data_dir>/coach.db``."""
        return self.db_path or (self.data_dir / "coach.db")


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so every module shares one config view."""
    return Settings()
