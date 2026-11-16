from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Supabase / database ---
    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    db_service_role: str = ""  # optional: SET ROLE for worker/system queries (e.g. service_role) when DATABASE_URL is not `postgres`
    supabase_url: str = "http://127.0.0.1:54321"
    supabase_public_url: str = ""  # browser-reachable Supabase URL; defaults to supabase_url
    supabase_service_role_key: str = ""
    supabase_anon_key: str = (
        ""  # optional: `apikey` header for Storage; defaults to the service-role key
    )
    supabase_jwt_secret: str = ""  # HS256 projects; leave empty to verify via JWKS
    web_origin: str = "http://localhost:3000"

    # --- Uploads ---
    max_video_bytes: int = 2 * 1024**3
    signed_url_ttl_sec: int = 3600
    videos_bucket: str = "drone-videos"
    frames_bucket: str = "video-frames"
    reference_bucket: str = "reference-images"
    reference_max_side: int = 1024
    max_reference_upload_bytes: int = 10 * 1024**2

    # --- Worker / frame extraction ---
    poll_interval_sec: float = 5.0
    frame_sample_interval_sec: float = 8.0
    max_frames: int = 24
    max_candidate_frames: int = 120
    frame_max_side: int = 1280
    thumb_max_side: int = 320
    blur_threshold: float = 60.0
    dup_hash_distance: int = 4
    max_video_duration_sec: int = 3600
    max_prev_frames: int = 3
    compare_max_pairs: int = 4  # comparable frame pairs sent when comparing against an earlier day
    compare_max_hash_distance: int = (
        22  # dHash Hamming distance (of 64) still treated as a similar view
    )

    # --- AI (Qwen3-VL via OpenAI-compatible endpoint). Nothing is assumed: all must be configured. ---
    qwen_vl_base_url: str = ""
    qwen_vl_api_key: str = ""
    qwen_vl_model: str = ""
    qwen_vl_timeout_sec: float = 180.0
    qwen_vl_json_mode: bool = True
    prompt_version: str = "v4"

    @property
    def public_supabase_url(self) -> str:
        return (self.supabase_public_url or self.supabase_url).rstrip("/")

    @property
    def ai_configured(self) -> bool:
        return bool(self.qwen_vl_base_url and self.qwen_vl_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()
