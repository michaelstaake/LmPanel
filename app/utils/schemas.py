import re
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

USERNAME_PATTERN = re.compile(r"^[a-z0-9]{4,16}$")
USERNAME_VALIDATION_MESSAGE = "Username must be 4-16 characters and contain only lowercase letters and numbers"


def validate_username(value: str) -> str:
    if not USERNAME_PATTERN.fullmatch(value):
        raise ValueError(USERNAME_VALIDATION_MESSAGE)
    return value


def validate_username_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return validate_username(value)


def normalize_public_url(value: str | None) -> str:
    if value is None:
        return ""

    normalized = value.strip()
    if not normalized:
        return ""

    if normalized.endswith("/"):
        raise ValueError("URL must not end with a trailing slash")

    parsed = urlparse(normalized)
    if parsed.scheme != "https":
        raise ValueError("URL must use https")
    if parsed.username or parsed.password:
        raise ValueError("URL must not include credentials")
    if parsed.port is not None:
        raise ValueError("URL must not include a port")
    if parsed.path not in ("", "/"):
        raise ValueError("URL must not include a path")
    if parsed.params or parsed.query or parsed.fragment:
        raise ValueError("URL must not include query parameters or fragments")
    if not parsed.hostname:
        raise ValueError("URL must include a hostname")

    return f"https://{parsed.hostname}"


def build_api_base_url(public_url: str, app_port: int) -> str:
    if not public_url:
        return ""

    parsed = urlparse(public_url)
    if parsed.port is not None:
        return public_url.rstrip("/")

    if not app_port or app_port == 443:
        return public_url

    hostname = parsed.hostname
    if not hostname:
        return public_url

    return f"https://{hostname}:{app_port}"


def normalize_message_content(content: Any) -> str:
    """Normalize OpenAI-style content to plain text for text-only backends.

    Supported inputs:
    - string content
    - list of content parts (only text parts are kept)
    """
    if content is None:
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts: list[str] = []
        for index, part in enumerate(content):
            if not isinstance(part, dict):
                raise ValueError(f"content part at index {index} must be an object")

            part_type = part.get("type")
            if not isinstance(part_type, str):
                raise ValueError(f"content part at index {index} is missing a valid type")

            if part_type != "text":
                # Non-text parts are currently ignored.
                continue

            text = part.get("text", "")
            if text is None:
                text = ""
            if not isinstance(text, str):
                raise ValueError(f"text content part at index {index} must have string text")
            text_parts.append(text)

        return "\n".join(text_parts)

    raise ValueError("content must be a string or an array of content parts")


def message_content_is_empty(content: Any) -> bool:
    if content is None:
        return True
    if isinstance(content, str):
        return content == ""
    if isinstance(content, list):
        if not content:
            return True
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")
            if part_type in {"text", "input_text"} and (part.get("text") or ""):
                return False
            if part_type == "image_url":
                image_url = part.get("image_url")
                if isinstance(image_url, dict) and image_url.get("url"):
                    return False
        return True
    return True


def normalize_message_for_inference(message: dict[str, Any]) -> dict[str, Any] | None:
    role = message.get("role")
    has_tool_calls = bool(message.get("tool_calls"))
    content_empty = message_content_is_empty(message.get("content"))

    if role == "assistant" and content_empty and not has_tool_calls:
        return None

    return {
        key: value
        for key, value in message.items()
        if value is not None and (key != "content" or not message_content_is_empty(value))
    }


def sanitize_inference_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        normalized = normalize_message_for_inference(message)
        if normalized is not None:
            sanitized.append(normalized)
    return sanitized


def validate_openai_message_content(content: Any) -> str | list[dict[str, Any]]:
    """Validate OpenAI-style content while preserving multimodal parts."""
    if content is None:
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        normalized_parts: list[dict[str, Any]] = []
        for index, part in enumerate(content):
            if not isinstance(part, dict):
                raise ValueError(f"content part at index {index} must be an object")

            part_type = part.get("type")
            if not isinstance(part_type, str):
                raise ValueError(f"content part at index {index} is missing a valid type")

            if part_type == "text":
                text = part.get("text", "")
                if text is None:
                    text = ""
                if not isinstance(text, str):
                    raise ValueError(f"text content part at index {index} must have string text")
                normalized_parts.append({**part, "text": text})
                continue

            if part_type == "image_url":
                image_url = part.get("image_url")
                if not isinstance(image_url, dict):
                    raise ValueError(f"image_url content part at index {index} must have an image_url object")
                url = image_url.get("url")
                if not isinstance(url, str) or not url:
                    raise ValueError(f"image_url content part at index {index} must include a non-empty string url")
                normalized_parts.append(part)
                continue

            if part_type == "input_text":
                text = part.get("text", "")
                if text is None:
                    text = ""
                if not isinstance(text, str):
                    raise ValueError(f"input_text content part at index {index} must have string text")
                normalized_parts.append({**part, "text": text})
                continue

            if part_type == "input_image":
                image_url = part.get("image_url") or part.get("image")
                if not isinstance(image_url, str) or not image_url:
                    raise ValueError(f"input_image content part at index {index} must include a non-empty image string")
                normalized_parts.append(part)
                continue

            raise ValueError(f"unsupported content part type at index {index}: {part_type}")

        return normalized_parts

    raise ValueError("content must be a string or an array of content parts")


def content_includes_vision(content: str | list[dict[str, Any]] | None) -> bool:
    if not isinstance(content, list):
        return False

    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") in {"image_url", "input_image"}:
            return True

    return False


class LoginRequest(BaseModel):
    username: str
    password: str
    turnstile_response: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    terms_accepted: bool = False
    terms_enabled: bool = False


class TermsStatusResponse(BaseModel):
    terms_enabled: bool
    terms_accepted: bool


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    is_admin: bool
    is_active: bool
    terms_accepted: bool = False
    package_id: int | None = None
    package_name: str | None = None


class ProfileUpdateRequest(BaseModel):
    email: str | None = Field(default=None, min_length=3, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=255)


class ApiKeyResponse(BaseModel):
    id: int
    user_id: int
    user_username: str
    name: str
    created_at: str | None = None
    last_used_at: str | None = None


class ApiKeyCreateResponse(BaseModel):
    status: str
    api_key: ApiKeyResponse
    plain_text_key: str


class BootstrapStatusResponse(BaseModel):
    requires_setup: bool
    has_admin_user: bool = False
    has_enabled_device: bool = False
    has_active_model: bool = False
    users_can_register: bool = False
    sitename: str = "LmPanel"
    favicon_path: str | None = None
    logo_path: str | None = None
    knowledge_base_enabled: bool = False
    cloudflare_turnstile_enabled: bool = False
    cloudflare_turnstile_site_key: str | None = None
    public_url: str = ""
    api_base_url: str = ""


class BootstrapAdminRequest(BaseModel):
    username: str = Field(min_length=4, max_length=16)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=255)

    @field_validator("username", mode="before")
    @classmethod
    def validate_username_field(cls, value: str) -> str:
        return validate_username(value)


class UserRegistrationRequest(BaseModel):
    username: str = Field(min_length=4, max_length=16)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=255)
    turnstile_response: str | None = None

    @field_validator("username", mode="before")
    @classmethod
    def validate_username_field(cls, value: str) -> str:
        return validate_username(value)


class AppSettingsResponse(BaseModel):
    users_can_register: bool = False
    sitename: str = "LmPanel"
    favicon_path: str | None = None
    logo_path: str | None = None
    knowledge_base_enabled: bool = False
    input_price_per_1m: float = 0.0
    output_price_per_1m: float = 0.0
    public_url: str = ""
    cloudflare_turnstile_enabled: bool = False
    cloudflare_turnstile_site_key: str | None = None
    cloudflare_turnstile_secret_key_set: bool = False
    two_factor_enabled: bool = False
    usage_limit_tokens_60_minutes: int = 0
    usage_limit_tokens_24_hours: int = 0
    usage_limit_tokens_7_days: int = 0
    usage_limit_tokens_30_days: int = 0
    usage_limit_tools_60_minutes: int = 0
    usage_limit_tools_24_hours: int = 0
    usage_limit_tools_7_days: int = 0
    usage_limit_tools_30_days: int = 0
    update_check_mode: Literal["development", "release", "disabled"] = "disabled"
    brute_force_enabled: bool = True
    brute_force_max_failures: int = 10
    brute_force_window_minutes: int = 15
    brute_force_block_minutes: int = 15
    notifications_enabled: bool = False
    notification_server_errors_enabled: bool = False
    notification_ip_blocked_enabled: bool = False
    notification_user_login_enabled: bool = False
    notification_user_registers_enabled: bool = False
    notification_usage_limit_reached_enabled: bool = False
    mail_email_address: str | None = None
    mail_email_username: str | None = None
    mail_email_password_set: bool = False
    mail_email_server: str | None = None
    mail_email_port: int = 587
    mail_email_security: str = "starttls"
    mail_email_from_name: str | None = None
    request_timeout_seconds: int = 300

    @field_validator("public_url", mode="before")
    @classmethod
    def validate_public_url(cls, value: str | None) -> str:
        return normalize_public_url(value)

class AppSettingsUpdateRequest(BaseModel):
    users_can_register: bool | None = None
    sitename: str | None = None
    knowledge_base_enabled: bool | None = None
    input_price_per_1m: float | None = None
    output_price_per_1m: float | None = None
    public_url: str | None = None
    cloudflare_turnstile_enabled: bool | None = None
    cloudflare_turnstile_site_key: str | None = None
    cloudflare_turnstile_secret_key: str | None = None
    two_factor_enabled: bool | None = None
    usage_limit_tokens_60_minutes: int | None = None
    usage_limit_tokens_24_hours: int | None = None
    usage_limit_tokens_7_days: int | None = None
    usage_limit_tokens_30_days: int | None = None
    usage_limit_tools_60_minutes: int | None = None
    usage_limit_tools_24_hours: int | None = None
    usage_limit_tools_7_days: int | None = None
    usage_limit_tools_30_days: int | None = None
    update_check_mode: Literal["development", "release", "disabled"] | None = None
    brute_force_enabled: bool | None = None
    brute_force_max_failures: int | None = None
    brute_force_window_minutes: int | None = None
    brute_force_block_minutes: int | None = None
    notifications_enabled: bool | None = None
    notification_server_errors_enabled: bool | None = None
    notification_ip_blocked_enabled: bool | None = None
    notification_user_login_enabled: bool | None = None
    notification_user_registers_enabled: bool | None = None
    notification_usage_limit_reached_enabled: bool | None = None
    mail_email_address: str | None = None
    mail_email_username: str | None = None
    mail_email_password: str | None = None
    mail_email_server: str | None = None
    mail_email_port: int | None = None
    mail_email_security: str | None = None
    mail_email_from_name: str | None = None
    request_timeout_seconds: int | None = None

    @field_validator("public_url", mode="before")
    @classmethod
    def validate_public_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_public_url(value)


class SslStatusResponse(BaseModel):
    public_url: str = ""
    letsencrypt_available: bool = False
    cloudflare_api_token_set: bool = False
    letsencrypt_email_set: bool = False
    certificate: dict | None = None


class SslSettingsUpdateRequest(BaseModel):
    letsencrypt_email: str | None = None
    cloudflare_api_token: str | None = None

    @field_validator("letsencrypt_email", mode="before")
    @classmethod
    def validate_letsencrypt_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return ""
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Invalid email address")
        return normalized

    @field_validator("cloudflare_api_token", mode="before")
    @classmethod
    def validate_cloudflare_api_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or ""


class WebSearchProviderResponse(BaseModel):
    id: int
    provider_type: str
    display_name: str
    description: str
    enabled: bool
    api_key_set: bool
    result_count: int


class WebSearchProviderUpdateRequest(BaseModel):
    enabled: bool | None = None
    api_key: str | None = None
    result_count: int | None = Field(default=None, ge=1, le=20)


class ActiveProviderResponse(BaseModel):
    provider_type: str | None


class ActiveProviderUpdateRequest(BaseModel):
    provider_type: str | None


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=4, max_length=16)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=255)
    is_admin: bool = False
    is_active: bool = True
    package_id: int | None = None

    @field_validator("username", mode="before")
    @classmethod
    def validate_username_field(cls, value: str) -> str:
        return validate_username(value)


class UserUpdateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=4, max_length=16)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=255)
    is_admin: bool | None = None
    is_active: bool | None = None
    package_id: int | None = None

    @field_validator("username", mode="before")
    @classmethod
    def validate_username_field(cls, value: str | None) -> str | None:
        return validate_username_optional(value)


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class DeviceUpdateRequest(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    priority: int | None = None
    max_threads: int | None = None
    max_slots: int | None = Field(default=None, ge=0)


class GpuPoolCreateRequest(BaseModel):
    name: str = Field(default="GPU Pool", min_length=1, max_length=120)
    vendor: str = Field(default="nvidia", min_length=1, max_length=32)
    device_ids: list[int] = Field(min_length=2)
    split_mode: str = Field(default="layer", min_length=1, max_length=16)
    max_slots: int = Field(default=0, ge=0)


class GpuPoolUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    vendor: str | None = Field(default=None, min_length=1, max_length=32)
    device_ids: list[int] = Field(min_length=2)
    split_mode: str | None = Field(default=None, min_length=1, max_length=16)
    max_slots: int | None = Field(default=None, ge=0)


class DeviceReorderItem(BaseModel):
    id: int
    priority: int


class DeviceReorderRequest(BaseModel):
    devices: list[DeviceReorderItem]


class PoolReorderItem(BaseModel):
    id: int
    pool_order: int


class PoolReorderRequest(BaseModel):
    pools: list[PoolReorderItem]


class ModelReorderItem(BaseModel):
    id: int
    priority: int


class ModelReorderRequest(BaseModel):
    models: list[ModelReorderItem]


class ModelUpdateRequest(BaseModel):
    alias: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    chat_template: str | None = None
    context_length: int | None = Field(default=None, ge=256)
    gpu_layers: int | None = None
    threads: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=0)
    presence_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    repetition_penalty: float | None = Field(default=None, ge=0.0)
    tool_calling_enabled: bool | None = None
    discourage_thinking: bool | None = None
    default_thinking_enabled: bool | None = None
    thinking_capability: str | None = None

    @field_validator("thinking_capability")
    @classmethod
    def _validate_thinking_capability(cls, value: str | None) -> str | None:
        if value is None:
            return value
        allowed = {"auto", "hybrid", "always", "none"}
        if value not in allowed:
            raise ValueError(f"thinking_capability must be one of: {', '.join(sorted(allowed))}")
        return value
    vision_enabled: bool | None = None
    web_search_enabled: bool | None = None
    rag_enabled: bool | None = None
    flash_attention_enabled: bool | None = None
    memory_mapping_enabled: bool | None = None
    assignment_mode: str | None = None
    pinned_device_id: int | None = None
    pinned_pool_id: int | None = None


class ChatMessageRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: str | list[dict[str, Any]] | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    function_call: dict[str, Any] | None = None

    @field_validator("content", mode="before")
    @classmethod
    def _normalize_content(cls, value: Any) -> str | list[dict[str, Any]]:
        return validate_openai_message_content(value)

    def includes_tooling(self) -> bool:
        return (
            self.role == "tool"
            or self.tool_call_id is not None
            or bool(self.tool_calls)
            or self.function_call is not None
        )

    def includes_vision(self) -> bool:
        return content_includes_vision(self.content)


class ChatCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class ChatRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ChatMessageAppendRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    role: str = Field(min_length=1, max_length=32)
    content: str | list[dict[str, Any]]
    model_name: str | None = Field(default=None, alias="modelName", min_length=1, max_length=120)
    stats: "ChatMessageStatsRequest | None" = None

    @field_validator("content", mode="before")
    @classmethod
    def _normalize_content(cls, value: Any) -> str:
        return normalize_message_content(value)

    @field_validator("content")
    @classmethod
    def _require_non_empty_content(cls, value: str) -> str:
        if len(value) < 1:
            raise ValueError("content must not be empty")
        return value


class ChatMessageStatsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    model: str = Field(min_length=1, max_length=120)
    elapsed_seconds: float = Field(alias="elapsedSeconds", ge=0)
    prompt_tokens: int | None = Field(default=None, alias="promptTokens", ge=0)
    completion_tokens: int | None = Field(default=None, alias="completionTokens", ge=0)
    total_tokens: int | None = Field(default=None, alias="totalTokens", ge=0)
    tokens_per_second: float | None = Field(default=None, alias="tokensPerSecond", ge=0)


class AttachmentExtractionResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    content_type: str | None = Field(default=None, alias="contentType")
    size: int = Field(ge=0)
    status: Literal["ok", "unsupported", "error"]
    content: str | None = None
    detail: str | None = None
    truncated: bool = False
    extractor: str | None = None


class AttachmentExtractionResponse(BaseModel):
    attachments: list[AttachmentExtractionResult]


class OpenAIChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessageRequest]
    stream: bool = False
    enable_thinking: bool | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = Field(default=None, ge=0)
    presence_penalty: float | None = None
    repetition_penalty: float | None = Field(default=None, ge=0.0)
    max_tokens: int | None = None
    use_web_search: bool | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None
    functions: list[dict[str, Any]] | None = None
    function_call: str | dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None

    def requests_tooling(self) -> bool:
        return (
            bool(self.tools)
            or self.tool_choice is not None
            or self.parallel_tool_calls is not None
            or bool(self.functions)
            or self.function_call is not None
            or any(message.includes_tooling() for message in self.messages)
        )

    def requests_vision(self) -> bool:
        return any(message.includes_vision() for message in self.messages)


class KnowledgeBaseCategoryResponse(BaseModel):
    id: int
    user_id: int
    name: str
    is_default: bool
    created_at: str | None = None


class KnowledgeBaseCategoryCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class KnowledgeBaseCategoryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)


class KnowledgeBaseDocumentCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    category_id: int


class KnowledgeBaseDocumentUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1)
    category_id: int | None = None


class KnowledgeBaseDocumentResponse(BaseModel):
    id: int
    user_id: int
    category_id: int | None = None
    title: str
    content: str
    created_at: str | None = None
    updated_at: str | None = None


class KnowledgeBaseRagContextResponse(BaseModel):
    context: str
    document_count: int


class PackageResponse(BaseModel):
    id: int
    name: str
    is_admin_package: bool
    is_default_package: bool
    usage_limit_tokens_60_minutes: int
    usage_limit_tokens_24_hours: int
    usage_limit_tokens_7_days: int
    usage_limit_tokens_30_days: int
    usage_limit_tools_60_minutes: int
    usage_limit_tools_24_hours: int
    usage_limit_tools_7_days: int
    usage_limit_tools_30_days: int


class PackageCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    is_admin_package: bool = False
    is_default_package: bool = False
    usage_limit_tokens_60_minutes: int = Field(default=0, ge=0)
    usage_limit_tokens_24_hours: int = Field(default=0, ge=0)
    usage_limit_tokens_7_days: int = Field(default=0, ge=0)
    usage_limit_tokens_30_days: int = Field(default=0, ge=0)
    usage_limit_tools_60_minutes: int = Field(default=0, ge=0)
    usage_limit_tools_24_hours: int = Field(default=0, ge=0)
    usage_limit_tools_7_days: int = Field(default=0, ge=0)
    usage_limit_tools_30_days: int = Field(default=0, ge=0)

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Package name is required")
        value = value.strip()
        if not re.match(r"^[a-zA-Z0-9]+$", value):
            raise ValueError("Package name can only contain letters and numbers")
        return value


class PackageUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_admin_package: bool | None = None
    is_default_package: bool | None = None
    usage_limit_tokens_60_minutes: int | None = Field(default=None, ge=0)
    usage_limit_tokens_24_hours: int | None = Field(default=None, ge=0)
    usage_limit_tokens_7_days: int | None = Field(default=None, ge=0)
    usage_limit_tokens_30_days: int | None = Field(default=None, ge=0)
    usage_limit_tools_60_minutes: int | None = Field(default=None, ge=0)
    usage_limit_tools_24_hours: int | None = Field(default=None, ge=0)
    usage_limit_tools_7_days: int | None = Field(default=None, ge=0)
    usage_limit_tools_30_days: int | None = Field(default=None, ge=0)

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not re.match(r"^[a-zA-Z0-9]+$", value):
            raise ValueError("Package name can only contain letters and numbers")
        return value
