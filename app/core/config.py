from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


RUNTIME_VENDOR_KEYS = {"cpu", "vulkan", "default"}


def _default_llama_server_path() -> str:
    return "/opt/llama.cpp/build/bin/llama-server"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "LmPanel"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8444
    app_external_port: int = 0
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

    default_context_length: int = 32768
    default_threads: int = 8
    default_gpu_layers: int = 99
    default_temperature: float = 0.7
    default_top_p: float = 0.95
    default_min_p: float = 0.05
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

    # Background watchdog: periodically re-syncs returning GPUs and auto-restarts
    # crashed models so a server reboot is never required for recovery.
    device_watchdog_enabled: bool = True
    device_watchdog_interval_seconds: int = 30
    # Max consecutive failed (re)activation attempts before the watchdog backs off
    # a model until its next genuine state change.
    model_recovery_max_attempts: int = 5
    # Serialize model activations and require host RAM headroom before each load.
    # Vulkan staging buffers can use multiple GB of system RAM per concurrent load.
    model_activation_min_free_ram_mb: int = 4096
    model_activation_ram_headroom_ratio: float = 1.25
    model_activation_gpu_offload_headroom_ratio: float = 0.20
    model_activation_gpu_no_mmap_headroom_ratio: float = 0.50
    # Max model (re)activation attempts per watchdog tick (1 avoids retry storms).
    watchdog_max_activations_per_tick: int = 1
    # When true, models marked activated in the database are loaded during app startup.
    auto_load_activated_models_on_startup: bool = False
    # On startup, wait up to this long for the inference runtime to report a GPU
    # before reconciling devices, so we don't reconcile against a not-yet-ready GPU.
    gpu_ready_timeout_seconds: int = 120
    # Once the runtime is reachable but reports no GPU, wait this long before
    # accepting a CPU-only result (covers slow amdgpu/driver init).
    gpu_ready_grace_seconds: int = 20

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
