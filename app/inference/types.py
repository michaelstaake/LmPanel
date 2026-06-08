from pydantic import BaseModel, ConfigDict


class ActivateModelRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: int
    alias: str
    file_path: str
    model_dir_name: str | None = None
    mmproj_path: str | None = None
    context_length: int
    threads: int
    gpu_layers: int
    flash_attention_enabled: bool = False
    memory_mapping_enabled: bool = True
    vendor: str
    hardware_id: str
    hardware_ids: list[str] = []
    vram_ratios: list[int] = []
    split_mode: str = "layer"
    stable_hardware_id: str | None = None
    stable_hardware_ids: list[str] = []
    discourage_thinking: bool = False
    anpu_architecture: str | None = None
    anpu_flm_tag: str | None = None
