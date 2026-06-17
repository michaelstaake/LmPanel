import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import { apiGet, apiPatch, apiPost } from "../lib/api";
import { BootstrapStatus, clearStoredToken, CurrentUser, getStoredToken, LoginResponse, storeToken, AUTH_TOKEN_KEY } from "../lib/session";

type TermsSettings = {
  terms_enabled: boolean;
  terms_content: string;
};

type AuthContextValue = {
  token: string;
  user: CurrentUser | null;
  requiresSetup: boolean;
  setupStatus: BootstrapStatus | null;
  bootstrapError: string | null;
  isBootstrapping: boolean;
  isAuthenticating: boolean;
  usersCanRegister: boolean;
  sitename: string;
  faviconPath: string | null;
  logoPath: string | null;
  knowledgeBaseEnabled: boolean;
  cloudflareTurnstileEnabled: boolean;
  cloudflareTurnstileSiteKey: string | null;
  termsSettings: TermsSettings;
  refreshAuthState: () => Promise<void>;
  refreshPublicSettings: () => Promise<void>;
  updateProfile: (payload: { email?: string; password?: string }) => Promise<CurrentUser>;
  login: (username: string, password: string, turnstileResponse?: string) => Promise<void>;
  register: (username: string, email: string, password: string, turnstileResponse?: string) => Promise<void>;
  bootstrapAdmin: (username: string, email: string, password: string) => Promise<void>;
  logout: () => void;
  acceptTerms: () => Promise<void>;
  declineTerms: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string>(() => getStoredToken());
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [requiresSetup, setRequiresSetup] = useState(false);
  const [setupStatus, setSetupStatus] = useState<BootstrapStatus | null>(null);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [isAuthenticating, setIsAuthenticating] = useState(false);
  const [usersCanRegister, setUsersCanRegister] = useState(false);
  const [sitename, setSitename] = useState("LmPanel");
  const [faviconPath, setFaviconPath] = useState<string | null>(null);
  const [logoPath, setLogoPath] = useState<string | null>(null);
  const [knowledgeBaseEnabled, setKnowledgeBaseEnabled] = useState(false);
  const [cloudflareTurnstileEnabled, setCloudflareTurnstileEnabled] = useState(false);
  const [cloudflareTurnstileSiteKey, setCloudflareTurnstileSiteKey] = useState<string | null>(null);
  const [termsSettings, setTermsSettings] = useState<TermsSettings>({
    terms_enabled: false,
    terms_content: "",
  });

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === AUTH_TOKEN_KEY) {
        setToken(event.newValue ?? "");
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  useEffect(() => {
    void refreshAuthState();
  }, [token]);

  async function refreshPublicSettings() {
    try {
      const bootstrap = await apiGet<BootstrapStatus>("/api/auth/bootstrap-status");
      setSetupStatus(bootstrap);
      setUsersCanRegister(bootstrap.users_can_register);
      setSitename(bootstrap.sitename || "LmPanel");
      setFaviconPath(bootstrap.favicon_path || null);
      setLogoPath(bootstrap.logo_path || null);
      setKnowledgeBaseEnabled(bootstrap.knowledge_base_enabled);
      setCloudflareTurnstileEnabled(bootstrap.cloudflare_turnstile_enabled);
      setCloudflareTurnstileSiteKey(bootstrap.cloudflare_turnstile_site_key || null);
    } catch {
      // silently ignore — UI will retain previous values
    }
  }

  async function refreshAuthState() {
    setIsBootstrapping(true);
    try {
      const bootstrap = await apiGet<BootstrapStatus>("/api/auth/bootstrap-status");
      setBootstrapError(null);
      setSetupStatus(bootstrap);
      setRequiresSetup(bootstrap.requires_setup);
      setUsersCanRegister(bootstrap.users_can_register);
      setSitename(bootstrap.sitename || "LmPanel");
      setFaviconPath(bootstrap.favicon_path || null);
      setLogoPath(bootstrap.logo_path || null);
      setKnowledgeBaseEnabled(bootstrap.knowledge_base_enabled);
      setCloudflareTurnstileEnabled(bootstrap.cloudflare_turnstile_enabled);
      setCloudflareTurnstileSiteKey(bootstrap.cloudflare_turnstile_site_key || null);

      if (!token) {
        setUser(null);
        return;
      }

      try {
        const currentUser = await apiGet<CurrentUser>("/api/auth/me", token);
        setUser(currentUser);
      } catch (error) {
        setUser(null);
        clearStoredToken();
        setToken("");
        throw error;
      }
    } catch (error) {
      setUser(null);
      setSetupStatus(null);
      setRequiresSetup(false);
      setUsersCanRegister(false);
      setSitename("LmPanel");
      setFaviconPath(null);
      setLogoPath(null);
      setKnowledgeBaseEnabled(false);
      setCloudflareTurnstileEnabled(false);
      setCloudflareTurnstileSiteKey(null);
      setBootstrapError(error instanceof Error ? error.message : "Unable to load installation state");
    } finally {
      setIsBootstrapping(false);
    }
  }

  async function login(username: string, password: string, turnstileResponse?: string) {
    setIsAuthenticating(true);
    try {
      const response = await apiPost<{ username: string; password: string; turnstile_response?: string }, LoginResponse>("/api/auth/login", { username, password, turnstile_response: turnstileResponse });
      storeToken(response.access_token);
      setToken(response.access_token);
      const currentUser = await apiGet<CurrentUser>("/api/auth/me", response.access_token);
      setBootstrapError(null);
      setUser(currentUser);
      if (response.terms_enabled) {
        const termsSettings = await apiGet<TermsSettings>("/api/terms/content");
        setTermsSettings(termsSettings);
      }
    } finally {
      setIsAuthenticating(false);
    }
  }

  async function bootstrapAdmin(username: string, email: string, password: string) {
    setIsAuthenticating(true);
    try {
      const response = await apiPost<{ username: string; email: string; password: string }, LoginResponse>("/api/auth/bootstrap-admin", {
        username,
        email,
        password,
      });
      storeToken(response.access_token);
      setToken(response.access_token);
      const currentUser = await apiGet<CurrentUser>("/api/auth/me", response.access_token);
      const bootstrap = await apiGet<BootstrapStatus>("/api/auth/bootstrap-status");
      setUser(currentUser);
      setSetupStatus(bootstrap);
      setRequiresSetup(bootstrap.requires_setup);
      setUsersCanRegister(bootstrap.users_can_register);
      setSitename(bootstrap.sitename || "LmPanel");
      setFaviconPath(bootstrap.favicon_path || null);
      setLogoPath(bootstrap.logo_path || null);
      setKnowledgeBaseEnabled(bootstrap.knowledge_base_enabled);
      setCloudflareTurnstileEnabled(bootstrap.cloudflare_turnstile_enabled);
      setCloudflareTurnstileSiteKey(bootstrap.cloudflare_turnstile_site_key || null);
      setBootstrapError(null);
    } finally {
      setIsAuthenticating(false);
    }
  }

  async function register(username: string, email: string, password: string, turnstileResponse?: string) {
    setIsAuthenticating(true);
    try {
      const response = await apiPost<{ username: string; email: string; password: string; turnstile_response?: string }, LoginResponse>("/api/auth/register", {
        username,
        email,
        password,
        turnstile_response: turnstileResponse,
      });
      storeToken(response.access_token);
      setToken(response.access_token);
      const currentUser = await apiGet<CurrentUser>("/api/auth/me", response.access_token);
      const bootstrap = await apiGet<BootstrapStatus>("/api/auth/bootstrap-status");
      setKnowledgeBaseEnabled(bootstrap.knowledge_base_enabled);
      setCloudflareTurnstileEnabled(bootstrap.cloudflare_turnstile_enabled);
      setCloudflareTurnstileSiteKey(bootstrap.cloudflare_turnstile_site_key || null);
      setFaviconPath(bootstrap.favicon_path || null);
      setLogoPath(bootstrap.logo_path || null);
      setBootstrapError(null);
      setUser(currentUser);
      if (response.terms_enabled) {
        const termsSettings = await apiGet<TermsSettings>("/api/terms/content");
        setTermsSettings(termsSettings);
      }
    } finally {
      setIsAuthenticating(false);
    }
  }

  async function updateProfile(payload: { email?: string; password?: string }) {
    if (!token) {
      throw new Error("You must be signed in to update your profile");
    }

    const currentUser = await apiPatch<{ email?: string; password?: string }, CurrentUser>("/api/auth/me", payload, token);
    setUser(currentUser);
    return currentUser;
  }

  function logout() {
    clearStoredToken();
    setToken("");
    setUser(null);
  }

  async function acceptTerms() {
    if (!token) {
      throw new Error("You must be signed in to accept terms");
    }
    await apiPost<{ terms_enabled: boolean }, { status: string }>("/api/terms/accept", { terms_enabled: true }, token);
    if (user) {
      setUser({ ...user, terms_accepted: true });
    }
  }

  async function declineTerms() {
    if (!token) {
      throw new Error("You must be signed in to decline terms");
    }
    await apiPost<{ terms_enabled: boolean }, { status: string }>("/api/terms/decline", { terms_enabled: true }, token);
    logout();
  }

  return (
    <AuthContext.Provider
      value={{
        token,
        user,
        requiresSetup,
        setupStatus,
        bootstrapError,
        isBootstrapping,
        isAuthenticating,
        usersCanRegister,
        sitename,
        faviconPath,
        logoPath,
        knowledgeBaseEnabled,
        cloudflareTurnstileEnabled,
        cloudflareTurnstileSiteKey,
        termsSettings,
        refreshAuthState,
        refreshPublicSettings,
        updateProfile,
        login,
        register,
        bootstrapAdmin,
        logout,
        acceptTerms,
        declineTerms,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
