from app.core.config import Settings
from app.inference.backends.anpu_flm import AnpuFlmBackend
from app.inference.types import ActivateModelRequest


def test_anpu_flm_backend_build_launch_uses_flm_tag(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.inference.backends.anpu_flm.ensure_anpu_artifacts",
        lambda **kwargs: "lmpanel:7",
    )

    settings = Settings(
        llama_host="127.0.0.1",
        logs_dir=str(tmp_path),
        flm_bin="/usr/bin/flm",
        flm_model_path=str(tmp_path / "flm"),
    )
    payload = ActivateModelRequest(
        model_id=7,
        alias="test",
        file_path="/app/models/demo/model.gguf",
        model_dir_name="demo",
        context_length=8192,
        threads=8,
        gpu_layers=99,
        vendor="anpu",
        hardware_id="anpu:0",
        anpu_architecture="llama",
        anpu_flm_tag="lmpanel:7",
    )

    launch = AnpuFlmBackend().build_launch(payload, 9107, settings)

    assert launch.command[:4] == ["/usr/bin/flm", "serve", "lmpanel:7", "--ctx-len"]
    assert launch.command[-2:] == ["--port", "9107"]
    assert launch.health_url == "http://127.0.0.1:9107/v1/models"
    assert launch.log_prefix == "anpu"
    assert launch.post_launch_validate is False
