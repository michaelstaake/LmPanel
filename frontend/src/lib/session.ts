export const AUTH_TOKEN_KEY = "lmpanel.authToken";

export type BackgroundImageMode = "fill" | "stretch" | "repeat";

export type BootstrapStatus = {
  requires_setup: boolean;
  has_admin_user: boolean;
  has_enabled_device: boolean;
  has_active_model: boolean;
  users_can_register: boolean;
  sitename: string;
  background_color: string;
  background_image_path: string | null;
  background_image_mode: BackgroundImageMode;
  knowledge_base_enabled: boolean;
  cloudflare_turnstile_enabled: boolean;
  cloudflare_turnstile_site_key: string | null;
  public_url: string;
};

export type CurrentUser = {
  id: number;
  username: string;
  email: string;
  is_admin: boolean;
  is_active: boolean;
  terms_accepted: boolean;
};

export type LoginResponse = {
  access_token: string;
  token_type: string;
  terms_accepted: boolean;
  terms_enabled: boolean;
};

export function getStoredToken(): string {
  return window.localStorage.getItem(AUTH_TOKEN_KEY) ?? "";
}

export function storeToken(token: string) {
  window.localStorage.setItem(AUTH_TOKEN_KEY, token);
  window.dispatchEvent(new StorageEvent("storage", { key: AUTH_TOKEN_KEY, newValue: token }));
}

export function clearStoredToken() {
  window.localStorage.removeItem(AUTH_TOKEN_KEY);
  window.dispatchEvent(new StorageEvent("storage", { key: AUTH_TOKEN_KEY, newValue: null }));
}
