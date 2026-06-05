import threading

_tokens_processed = 0
_input_tokens_processed = 0
_output_tokens_processed = 0
_tokens_lock = threading.Lock()


def _coalesce_token_count(value: int | None) -> int | None:
    if value is None or value <= 0:
        return None

    return value


def add_processed_tokens(
    total_tokens: int | None,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    normalized_input_tokens = _coalesce_token_count(input_tokens)
    normalized_output_tokens = _coalesce_token_count(output_tokens)
    normalized_total_tokens = _coalesce_token_count(total_tokens)

    if normalized_total_tokens is None:
        normalized_total_tokens = (normalized_input_tokens or 0) + (normalized_output_tokens or 0)

    if normalized_total_tokens is None and normalized_input_tokens is None and normalized_output_tokens is None:
        return

    global _tokens_processed, _input_tokens_processed, _output_tokens_processed
    with _tokens_lock:
        if normalized_input_tokens is not None:
            _input_tokens_processed += normalized_input_tokens
        if normalized_output_tokens is not None:
            _output_tokens_processed += normalized_output_tokens
        if normalized_total_tokens is not None:
            _tokens_processed += normalized_total_tokens


def get_processed_tokens() -> int:
    with _tokens_lock:
        return _tokens_processed


def get_input_tokens_processed() -> int:
    with _tokens_lock:
        return _input_tokens_processed


def get_output_tokens_processed() -> int:
    with _tokens_lock:
        return _output_tokens_processed