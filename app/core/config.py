from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


RUNTIME_VENDOR_KEYS = {"cpu", "nvidia", "vulkan", "rocm", "anpu", "default"}


def _default_llama_server_path() -> str:
    return "/opt/llama.cpp/build/bin/llama-server"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "LmPanel"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8444
    app_log_level: str = "INFO"

    database_url: str = "sqlite:///./data/lmpanel.db"

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440
    openai_api_auth_required: bool = True
    openai_models_auth_required: bool = False

    models_dir: str = "./models"
    data_dir: str = "./data"
    logs_dir: str = "./logs"

    llama_server_path: str = _default_llama_server_path()
    llama_host: str = "127.0.0.1"
    llama_base_port: int = 9100
    llama_health_timeout_seconds: int = 5
    llama_startup_timeout_seconds: int = 120
    llama_request_timeout_seconds: int = 300
    # When true, llama-server may reduce GPU layers / context to fit VRAM (--fit on).
    llama_fit_to_vram: bool = False
    # RDNA4 (gfx1200/gfx1201): helps HIP find the GPU when ROCm mis-detects the arch.
    rocm_hsa_override_gfx_version: str = "12.0.1"
    # ROCm multi-GPU pools can produce unstable output when slot cache state is reused.
    # Keep this at 1 unless you have validated multi-slot stability on your stack.
    rocm_pool_parallel: int = 1
    # Disable prompt cache in ROCm pools by default to avoid kv-cache restore corruption.
    rocm_pool_cache_ram_mb: int = 0
    # Some ROCm multi-GPU combinations produce unstable output with flash attention.
    rocm_pool_flash_attn_enabled: bool = False
    # Tensor split on ROCm pools is experimental; keep disabled unless validated.
    rocm_pool_allow_tensor_split: bool = False

    default_context_length: int = 32768
    default_threads: int = 8
    default_gpu_layers: int = 99
    default_temperature: float = 0.7
    default_top_p: float = 0.95
    default_top_k: int = 40
    default_presence_penalty: float = 0.0
    default_repetition_penalty: float = 1.0

    queue_max_size: int = 1000
    queue_poll_interval_ms: int = 100

    frontend_origin: str = "https://localhost:8443"
    ssl_certfile: str = "./certs/server.crt"
    ssl_keyfile: str = "./certs/server.key"
    letsencrypt_email: str = ""
    letsencrypt_use_staging: bool = False
    letsencrypt_config_dir: str = ""
    cloudflare_api_token: str = ""
    docker_frontend_container: str = "lmpanel-frontend"
    docker_backend_container: str = "lmpanel-backend"
    supported_devices: str = ""
    inference_service_url: str = "http://localhost:8100"
    inference_runtime_urls: str = ""
    inference_service_timeout_seconds: int = 300
    max_upload_size_mb: int = 102400

    anpu_backend: str = "flm"
    flm_bin: str = "/usr/bin/flm"
    flm_model_path: str = "/app/models/flm"
    flm_template_models: str = "/opt/flm-templates"
    flm_converter_root: str = "/opt/FLM_Q4NX_Converter"
    anpu_conversion_timeout_seconds: int = 3600
    anpu_default_template_family: str = "llama3.2:3b"

    def supported_device_list(self) -> list[str]:
        return [item.strip().lower() for item in self.supported_devices.split(",") if item.strip()]

    def inference_runtime_url_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for entry in self.inference_runtime_urls.split(","):
            item = entry.strip()
            if not item or "=" not in item:
                continue
            vendor, url = item.split("=", 1)
            key = vendor.strip().lower()
            value = url.strip().rstrip("/")
            if key in RUNTIME_VENDOR_KEYS and value:
                mapping[key] = value

        if mapping:
            return mapping

        return {"default": self.inference_service_url.rstrip("/")}

    def inference_runtime_url_for_vendor(self, vendor: str) -> str | None:
        mapping = self.inference_runtime_url_map()
        return mapping.get(vendor.strip().lower()) or mapping.get("default")

    def resolved_letsencrypt_config_dir(self) -> str:
        if self.letsencrypt_config_dir.strip():
            return self.letsencrypt_config_dir.strip()
        return str(Path(self.data_dir) / "letsencrypt")


@lru_cache
def get_settings() -> Settings:
    return Settings()
