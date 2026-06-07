"""Stream multipart model uploads directly to their final paths."""

from __future__ import annotations

import errno
import os
import shutil
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from anyio.to_thread import run_sync
from fastapi import Request
from starlette.formparsers import MultiPartException, _user_safe_decode

try:
    import python_multipart as multipart
    from python_multipart.multipart import parse_options_header
except ModuleNotFoundError:  # pragma: no cover
    import multipart  # type: ignore[no-redef]
    from multipart.multipart import parse_options_header  # type: ignore[no-redef]

UPLOAD_CHUNK_BYTES = 1024 * 1024


@dataclass
class _MultipartPart:
    content_disposition: bytes | None = None
    field_name: str = ""
    filename: str = ""
    item_headers: list[tuple[bytes, bytes]] = field(default_factory=list)


@dataclass
class StreamedModelFile:
    field_name: str
    filename: str
    destination: Path
    written: int


@dataclass
class ModelMultipartUploadResult:
    files: list[StreamedModelFile]


class ModelMultipartUploadParser:
    """Parse multipart uploads while writing file parts directly to disk."""

    def __init__(
        self,
        headers,
        stream: AsyncGenerator[bytes, None],
        *,
        model_dir: Path,
        max_bytes: int,
        on_progress,
    ) -> None:
        self.headers = headers
        self.stream = stream
        self.model_dir = model_dir
        self.max_bytes = max_bytes
        self.on_progress = on_progress
        self._charset = ""
        self._current_part = _MultipartPart()
        self._current_partial_header_name: bytes = b""
        self._current_partial_header_value: bytes = b""
        self._current_output: BinaryIO | None = None
        self._current_destination: Path | None = None
        self._current_written = 0
        self._total_written = 0
        self._files: list[StreamedModelFile] = []
        self._pending_writes: list[bytes] = []

    def on_part_begin(self) -> None:
        self._close_current_output()
        self._current_part = _MultipartPart()

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self._current_output is None:
            raise MultiPartException("Received file data before file headers were finished")
        self._pending_writes.append(data[start:end])

    def on_part_end(self) -> None:
        self._flush_pending_writes_sync()
        self._close_current_output()

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._current_partial_header_name += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._current_partial_header_value += data[start:end]

    def on_header_end(self) -> None:
        field = self._current_partial_header_name.lower()
        if field == b"content-disposition":
            self._current_part.content_disposition = self._current_partial_header_value
        self._current_part.item_headers.append((field, self._current_partial_header_value))
        self._current_partial_header_name = b""
        self._current_partial_header_value = b""

    def on_headers_finished(self) -> None:
        disposition, options = parse_options_header(self._current_part.content_disposition)
        try:
            self._current_part.field_name = _user_safe_decode(options[b"name"], self._charset)
        except KeyError as exc:
            raise MultiPartException('The Content-Disposition header field "name" must be provided.') from exc
        if b"filename" not in options:
            raise MultiPartException("Only file uploads are supported for model import")
        if self._current_part.field_name not in {"file", "files"}:
            raise MultiPartException("Unexpected upload field name")
        self._current_part.filename = _user_safe_decode(options[b"filename"], self._charset)
        destination = self.model_dir / Path(self._current_part.filename).name
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self._current_destination = destination
        self._current_output = destination.open("wb")
        self._current_written = 0

    def on_end(self) -> None:
        self._close_current_output()

    def _close_current_output(self) -> None:
        if self._current_output is None:
            return
        self._current_output.close()
        if self._current_destination is not None and self._current_written > 0:
            self._files.append(
                StreamedModelFile(
                    field_name=self._current_part.field_name,
                    filename=Path(self._current_part.filename).name,
                    destination=self._current_destination,
                    written=self._current_written,
                )
            )
        elif self._current_destination is not None and self._current_destination.exists():
            self._current_destination.unlink(missing_ok=True)
        self._current_output = None
        self._current_destination = None
        self._current_written = 0

    def _flush_pending_writes_sync(self) -> None:
        if self._current_output is None or not self._pending_writes:
            self._pending_writes.clear()
            return
        for message_bytes in self._pending_writes:
            self._current_output.write(message_bytes)
            self._current_written += len(message_bytes)
            self._total_written += len(message_bytes)
            if self._total_written > self.max_bytes:
                raise MultiPartException("Uploaded file exceeds the configured size limit")
            self.on_progress(self._total_written)
        self._pending_writes.clear()

    async def _flush_pending_writes(self) -> None:
        if self._current_output is None or not self._pending_writes:
            self._pending_writes.clear()
            return
        for message_bytes in self._pending_writes:
            await run_sync(self._current_output.write, message_bytes)
            self._current_written += len(message_bytes)
            self._total_written += len(message_bytes)
            if self._total_written > self.max_bytes:
                raise MultiPartException("Uploaded file exceeds the configured size limit")
            self.on_progress(self._total_written)
        self._pending_writes.clear()

    async def parse(self) -> ModelMultipartUploadResult:
        _, params = parse_options_header(self.headers["Content-Type"])
        charset = params.get(b"charset", "utf-8")
        if isinstance(charset, bytes):
            charset = charset.decode("latin-1")
        self._charset = charset
        try:
            boundary = params[b"boundary"]
        except KeyError as exc:
            raise MultiPartException("Missing boundary in multipart.") from exc

        callbacks = {
            "on_part_begin": self.on_part_begin,
            "on_part_data": self.on_part_data,
            "on_part_end": self.on_part_end,
            "on_header_field": self.on_header_field,
            "on_header_value": self.on_header_value,
            "on_header_end": self.on_header_end,
            "on_headers_finished": self.on_headers_finished,
            "on_end": self.on_end,
        }
        parser = multipart.MultipartParser(boundary, callbacks)
        try:
            async for chunk in self.stream:
                if chunk:
                    parser.write(chunk)
                    await self._flush_pending_writes()
                else:
                    parser.finalize()
            parser.finalize()
            await self._flush_pending_writes()
            self.on_end()
        except Exception:
            self._close_current_output()
            for streamed in self._files:
                streamed.destination.unlink(missing_ok=True)
            raise

        if not self._files:
            raise MultiPartException("No files were provided")
        return ModelMultipartUploadResult(files=self._files)


async def stream_model_upload(request: Request, *, model_dir: Path, max_bytes: int, on_progress) -> ModelMultipartUploadResult:
    content_type = request.headers.get("content-type")
    if content_type is None or "multipart/form-data" not in content_type:
        raise MultiPartException("Expected multipart form data")
    parser = ModelMultipartUploadParser(
        request.headers,
        request.stream(),
        model_dir=model_dir,
        max_bytes=max_bytes,
        on_progress=on_progress,
    )
    return await parser.parse()


def detach_spooled_temp_file(spool) -> str | None:
    if not getattr(spool, "_rolled", False):
        return None
    temp_path = getattr(spool, "name", None)
    if not temp_path:
        return None
    if spool._file is not None:
        spool._file.close()
        spool._file = None
    spool._rolled = False
    return temp_path


def move_or_copy_spooled_file(temp_path: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(temp_path, destination)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        with open(temp_path, "rb") as source, destination.open("wb") as target:
            shutil.copyfileobj(source, target, UPLOAD_CHUNK_BYTES)
        os.unlink(temp_path)
