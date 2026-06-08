import json
from pathlib import Path

from app.core.anpu_conversion import AnpuManifest, manifest_is_current, manifest_path


def test_manifest_is_current_matches_gguf_mtime(tmp_path: Path) -> None:
    model_dir = tmp_path / "demo"
    model_dir.mkdir()
    gguf = model_dir / "model.gguf"
    gguf.write_bytes(b"gguf")
    mtime = gguf.stat().st_mtime

    cache_dir = model_dir / ".anpu"
    cache_dir.mkdir()
    manifest_path(model_dir).write_text(
        json.dumps(
            AnpuManifest(
                flm_tag="lmpanel:1",
                converter_family="llama",
                template_tag="llama3.2:3b",
                template_folder_name="Llama",
                gguf_mtime=mtime,
                converted_at="2026-01-01T00:00:00+00:00",
                files=["model.q4nx"],
            ).to_dict()
        ),
        encoding="utf-8",
    )

    assert manifest_is_current(model_dir, gguf)

    gguf.write_bytes(b"gguf-updated")
    assert not manifest_is_current(model_dir, gguf)
