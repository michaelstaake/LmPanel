export type KnowledgeBaseCategoryRecord = {
  id: number;
  user_id: number;
  name: string;
  is_default: boolean;
  created_at: string | null;
};

export type KnowledgeBaseDocumentRecord = {
  id: number;
  user_id: number;
  category_id: number | null;
  title: string;
  content: string;
  created_at: string | null;
  updated_at: string | null;
};

export type WebSearchProviderRecord = {
  id: number;
  provider_type: string;
  display_name: string;
  description: string;
  enabled: boolean;
  api_key_set: boolean;
  result_count: number;
};

export type ActiveProviderRecord = {
  provider_type: string | null;
};

export type FetchProgressRecord = {
  job_id: string;
  status: "downloading" | "processing" | "completed" | "error";
  downloaded: number;
  total: number | null;
  percent: number;
  file_name: string | null;
  model: Record<string, unknown> | null;
  error: string | null;
};

export type UserRecord = {
  id: number;
  username: string;
  email: string;
  is_admin: boolean;
  is_active: boolean;
  password?: string;
  package_id?: number | null;
  package_name?: string | null;
};

export type UserTokenUsageRecord = {
  user_id: number;
  username: string;
  last_60_minutes: TokenUsageMetricRecord & { web_searches: number };
  last_24_hours: TokenUsageMetricRecord & { web_searches: number };
  last_7_days: TokenUsageMetricRecord & { web_searches: number };
  last_30_days: TokenUsageMetricRecord & { web_searches: number };
  forever: TokenUsageMetricRecord & { web_searches: number };
  estimated_cost: number;
};

export type ApiKeyRecord = {
  id: number;
  user_id: number;
  user_username: string;
  name: string;
  created_at: string | null;
  last_used_at: string | null;
};

export type ModelDirectoryFile = {
  name: string;
  size: number;
};

export type ModelRuntimeState = "disabled" | "running" | "recovering" | "error";

export type ModelRecord = {
  id: number;
  priority: number;
  file_name: string;
  model_dir_name: string;
  file_path: string;
  file_size: number | null;
  directory_files: ModelDirectoryFile[];
  directory_size: number;
  alias: string;
  description: string;
  system_prompt: string;
  chat_template: string;
  max_context_length: number | null;
  context_length: number;
  gpu_layers: number;
  threads: number;
  temperature: number;
  top_p: number;
  min_p: number;
  top_k: number;
  presence_penalty: number;
  repetition_penalty: number;
  tool_calling_enabled: boolean;
  discourage_thinking: boolean;
  default_thinking_enabled: boolean;
  thinking_capability: string;
  vision_enabled: boolean;
  web_search_enabled: boolean;
  rag_enabled: boolean;
  flash_attention_enabled: boolean;
  memory_mapping_enabled: boolean;
  mmproj_file_name: string | null;
  shard_count: number | null;
  shards_complete: boolean;
  missing_shards: string[];
  assignment_mode: string;
  pinned_device_id: number | null;
  pinned_pool_id: number | null;
  activated: boolean;
  runtime_state?: ModelRuntimeState;
  runtime_error?: string | null;
};

export type DeviceRecord = {
  id: number;
  hardware_id: string;
  stable_hardware_id: string | null;
  stable_hardware_id_source: string | null;
  display_suffix: string;
  name: string;
  default_name: string;
  vendor: string;
  device_type: string;
  memory_mb: number;
  enabled: boolean;
  priority: number;
  max_threads: number;
  max_slots: number;
  in_pool: boolean;
};

export type GpuPoolRecord = {
  id: number;
  name: string;
  vendor: string;
  split_mode: string;
  max_slots: number;
  pool_order: number;
  enabled: boolean;
  devices: DeviceRecord[];
};

export type StatusModelRecord = {
  model_id: number;
  alias: string;
  file_name: string;
  memory_used_mb: number;
  display_memory_used_mb: number;
  pid: number | null;
};

export type DeviceStatusRecord = {
  id: number;
  hardware_id: string;
  stable_hardware_id: string | null;
  stable_hardware_id_source: string | null;
  display_suffix: string;
  name: string;
  vendor: string;
  device_type: string;
  enabled: boolean;
  priority: number;
  max_slots: number;
  max_threads: number;
  memory_total_mb: number;
  memory_used_mb: number;
  gpu_usage_percent: number | null;
  gpu_usage_source: string;
  usage_percent: number | null;
  usage_source: string;
  memory_source: string;
  models: StatusModelRecord[];
};

export type TokenUsageMetricRecord = {
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
};

export type TopTokenUserRecord = {
  username: string;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
} | null;

export type TokenUsageSummaryRecord = {
  since_startup: TokenUsageMetricRecord;
  last_1_hour: TokenUsageMetricRecord;
  last_24_hours: TokenUsageMetricRecord;
  last_7_days: TokenUsageMetricRecord;
  last_30_days: TokenUsageMetricRecord;
  forever: TokenUsageMetricRecord;
  top_user_last_24_hours: TopTokenUserRecord;
  top_user_forever: TopTokenUserRecord;
};

export type AccountUsagePeriodRecord = {
  id: string;
  label: string;
  limit_tokens: number;
  used_tokens: number;
  percent: number;
  resets_in_seconds: number | null;
};

export type AccountUsageStatusRecord = {
  enabled: boolean;
  is_admin: boolean;
  at_limit: boolean;
  periods: AccountUsagePeriodRecord[];
};

export type AccountToolUsageStatusRecord = {
  enabled: boolean;
  is_admin: boolean;
  at_limit: boolean;
  periods: AccountUsagePeriodRecord[];
};

export type StatusResponse = {
  status: string;
  refreshed_at: string;
  system_cpu_usage_percent: number | null;
  system_disk_free_bytes: number;
  input_tokens_processed: number;
  output_tokens_processed: number;
  tokens_processed: number;
  token_usage: TokenUsageSummaryRecord;
  account_usage: AccountUsageStatusRecord | null;
  account_tool_usage: AccountToolUsageStatusRecord | null;
  devices: DeviceStatusRecord[];
  runtime_errors: {
    vendor: string;
    base_url: string;
    detail: string;
  }[];
  package_name?: string | null;
};

export type ScanResponse = {
  status: string;
  discovered: number;
  added: number;
};

export type UploadResponse = {
  status: string;
  task_id: string;
};

export type AssetUploadResponse = {
  status: string;
  uploaded: string[];
  model: ModelRecord;
};

export type AssetDeleteResponse = {
  status: string;
  deleted: string;
  model: ModelRecord;
};

export type ModelUpdateResponse = {
  status: string;
  model: ModelRecord;
};

export type ModelActivationResponse = {
  status: string;
  model_id: number;
  device_id?: number;
  pool_id?: number;
  elapsed_seconds?: number;
};

export type DeviceUpdateResponse = {
  status: string;
  device: DeviceRecord;
};

export type UserUpdateResponse = {
  status: string;
  user: UserRecord;
};

export type PackageRecord = {
  id: number;
  name: string;
  is_admin_package: boolean;
  is_default_package: boolean;
  usage_limit_tokens_60_minutes: number;
  usage_limit_tokens_24_hours: number;
  usage_limit_tokens_7_days: number;
  usage_limit_tokens_30_days: number;
  usage_limit_tools_60_minutes: number;
  usage_limit_tools_24_hours: number;
  usage_limit_tools_7_days: number;
  usage_limit_tools_30_days: number;
};

export type AppSettingsRecord = {
  users_can_register: boolean;
  sitename: string;
  favicon_path: string | null;
  logo_path: string | null;
  input_price_per_1m: number;
  output_price_per_1m: number;
  public_url: string;
  cloudflare_turnstile_enabled: boolean;
  cloudflare_turnstile_site_key: string | null;
  cloudflare_turnstile_secret_key_set: boolean;
  two_factor_enabled: boolean;
  usage_limit_tokens_60_minutes: number;
  usage_limit_tokens_24_hours: number;
  usage_limit_tokens_7_days: number;
  usage_limit_tokens_30_days: number;
  usage_limit_tools_60_minutes: number;
  usage_limit_tools_24_hours: number;
  usage_limit_tools_7_days: number;
  usage_limit_tools_30_days: number;
  update_check_mode: "development" | "release" | "disabled";
  brute_force_enabled: boolean;
  brute_force_max_failures: number;
  brute_force_window_minutes: number;
  brute_force_block_minutes: number;
  notifications_enabled: boolean;
  notification_server_errors_enabled: boolean;
  notification_ip_blocked_enabled: boolean;
  notification_user_login_enabled: boolean;
  notification_user_registers_enabled: boolean;
  notification_usage_limit_reached_enabled: boolean;
  mail_email_address: string | null;
  mail_email_username: string | null;
  mail_email_password_set: boolean;
  mail_email_server: string | null;
  mail_email_port: number;
  mail_email_security: string;
  mail_email_from_name: string | null;
  request_timeout_seconds: number;
};

export type SslCertificateStatus = {
  subject: string | null;
  issuer: string;
  not_after: string;
  days_remaining: number;
  is_self_signed: boolean;
  is_lets_encrypt: boolean;
  san_names: string[];
  domain_matches: boolean;
};

export type SslStatusRecord = {
  public_url: string;
  letsencrypt_available: boolean;
  cloudflare_api_token_set: boolean;
  letsencrypt_email_set: boolean;
  certificate: SslCertificateStatus | null;
};

export type SslSettingsUpdateRequest = {
  letsencrypt_email?: string;
  cloudflare_api_token?: string;
};

export type SslTaskResponse = {
  status: string;
  task_id: string;
};

export type ApiKeyCreateResponse = {
  status: string;
  api_key: ApiKeyRecord;
  plain_text_key: string;
};

export type ActivityLogRecord = {
  id: number;
  created_at: string | null;
  event_type: string;
  user_id: number | null;
  username: string | null;
  ip_address: string | null;
  details: string | null;
};

export type LogsResponse = {
  total: number;
  page: number;
  page_size: number;
  items: ActivityLogRecord[];
};

export type DockerContainersResponse = {
  containers: string[];
};

export type DockerLogsResponse = {
  container: string;
  lines: string[];
};