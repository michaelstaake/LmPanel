from app.core.anpu_arch_map import (
    converter_family_for_architecture,
    flm_template_for_converter_family,
    is_anpu_compatible_architecture,
)


def test_converter_family_for_llama_variants() -> None:
    assert converter_family_for_architecture("llama") == "llama"
    assert converter_family_for_architecture("llama3") == "llama"
    assert converter_family_for_architecture("qwen3") == "qwen3"


def test_is_anpu_compatible_architecture() -> None:
    assert is_anpu_compatible_architecture("llama3")
    assert not is_anpu_compatible_architecture("falcon")


def test_flm_template_for_converter_family() -> None:
    assert flm_template_for_converter_family("llama") == "llama3.2:3b"
    assert flm_template_for_converter_family("unknown") == "llama3.2:3b"
