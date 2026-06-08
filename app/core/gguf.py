import struct
from pathlib import Path
from typing import BinaryIO


GGUF_MAGIC = b"GGUF"

TYPE_UINT8 = 0
TYPE_INT8 = 1
TYPE_UINT16 = 2
TYPE_INT16 = 3
TYPE_UINT32 = 4
TYPE_INT32 = 5
TYPE_FLOAT32 = 6
TYPE_BOOL = 7
TYPE_STRING = 8
TYPE_ARRAY = 9
TYPE_UINT64 = 10
TYPE_INT64 = 11
TYPE_FLOAT64 = 12


def read_gguf_max_context_length(file_path: str) -> int | None:
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return None

    try:
        with path.open("rb") as handle:
            version = _read_header(handle)
            metadata_count = _read_metadata_count(handle, version)
            return _read_context_length_from_metadata(handle, metadata_count, version)
    except (OSError, UnicodeDecodeError, ValueError, struct.error):
        return None


def _read_header(handle: BinaryIO) -> int:
    magic = _read_exact(handle, 4)
    if magic != GGUF_MAGIC:
        raise ValueError("Invalid GGUF header")
    version = _unpack("<I", _read_exact(handle, 4))
    if version not in {1, 2, 3}:
        raise ValueError("Unsupported GGUF version")
    return version


def _read_metadata_count(handle: BinaryIO, version: int) -> int:
    if version == 1:
        _read_exact(handle, 4)
        return _unpack("<I", _read_exact(handle, 4))
    _read_exact(handle, 8)
    return _unpack("<Q", _read_exact(handle, 8))


def _read_context_length_from_metadata(handle: BinaryIO, metadata_count: int, version: int) -> int | None:
    architecture: str | None = None
    context_values: dict[str, int] = {}

    for _ in range(metadata_count):
        key = _read_string(handle, version)
        value_type = _unpack("<I", _read_exact(handle, 4))
        value = _read_value(handle, value_type, version)

        if key == "general.architecture" and isinstance(value, str):
            architecture = value
            continue

        if key.endswith(".context_length") and isinstance(value, int):
            context_values[key] = value

    if architecture:
        architecture_key = f"{architecture}.context_length"
        if architecture_key in context_values:
            return context_values[architecture_key]

    decoder_lengths = [
        value
        for key, value in context_values.items()
        if key.endswith("decoder.context_length")
    ]
    if decoder_lengths:
        return max(decoder_lengths)

    if context_values:
        return max(context_values.values())

    return None


def _read_value(handle: BinaryIO, value_type: int, version: int):
    if value_type == TYPE_UINT8:
        return _unpack("<B", _read_exact(handle, 1))
    if value_type == TYPE_INT8:
        return _unpack("<b", _read_exact(handle, 1))
    if value_type == TYPE_UINT16:
        return _unpack("<H", _read_exact(handle, 2))
    if value_type == TYPE_INT16:
        return _unpack("<h", _read_exact(handle, 2))
    if value_type == TYPE_UINT32:
        return _unpack("<I", _read_exact(handle, 4))
    if value_type == TYPE_INT32:
        return _unpack("<i", _read_exact(handle, 4))
    if value_type == TYPE_FLOAT32:
        return _unpack("<f", _read_exact(handle, 4))
    if value_type == TYPE_BOOL:
        return bool(_unpack("<B", _read_exact(handle, 1)))
    if value_type == TYPE_STRING:
        return _read_string(handle, version)
    if value_type == TYPE_ARRAY:
        element_type = _unpack("<I", _read_exact(handle, 4))
        length = _read_length(handle, version)
        return [_read_value(handle, element_type, version) for _ in range(length)]
    if value_type == TYPE_UINT64:
        return _unpack("<Q", _read_exact(handle, 8))
    if value_type == TYPE_INT64:
        return _unpack("<q", _read_exact(handle, 8))
    if value_type == TYPE_FLOAT64:
        return _unpack("<d", _read_exact(handle, 8))
    raise ValueError("Unsupported GGUF metadata value type")


def _read_string(handle: BinaryIO, version: int) -> str:
    length = _read_length(handle, version)
    return _read_exact(handle, length).decode("utf-8")


def _read_length(handle: BinaryIO, version: int) -> int:
    if version == 1:
        return _unpack("<I", _read_exact(handle, 4))
    return _unpack("<Q", _read_exact(handle, 8))


def _read_exact(handle: BinaryIO, size: int) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise ValueError("Unexpected end of GGUF file")
    return data


def _unpack(fmt: str, data: bytes):
    return struct.unpack(fmt, data)[0]