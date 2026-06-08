import { FormEvent, useEffect, useRef, useState } from "react";
import { Navigate, Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { readTurnstileToken, resetTurnstileWidget, turnstileRenderOptions } from "../lib/turnstile";

export default function AuthPage() {
  const { user, requiresSetup, isBootstrapping, isAuthenticating, login, usersCanRegister, cloudflareTurnstileEnabled, cloudflareTurnstileSiteKey } = useAuth();
  const { showError, showSuccess } = useToast();
  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const turnstileRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);
  const turnstileTokenRef = useRef<string | null>(null);

  useEffect(() => {
    if (!cloudflareTurnstileEnabled || !cloudflareTurnstileSiteKey) {
      return;
    }

    if (widgetIdRef.current) {
      return;
    }

    const renderOptions = turnstileRenderOptions(cloudflareTurnstileSiteKey, turnstileTokenRef);

    if (window.turnstile && turnstileRef.current) {
      widgetIdRef.current = window.turnstile.render(turnstileRef.current, renderOptions);
      return;
    }

    const script = document.createElement("script");
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js";
    script.async = true;
    script.defer = true;
    script.onload = () => {
      if (!turnstileRef.current || !window.turnstile) {
        return;
      }
      widgetIdRef.current = window.turnstile.render(turnstileRef.current, renderOptions);
    };
    document.head.appendChild(script);

    return () => {
      if (widgetIdRef.current) {
        window.turnstile?.remove(widgetIdRef.current);
        widgetIdRef.current = null;
        turnstileTokenRef.current = null;
      }
    };
  }, [cloudflareTurnstileEnabled, cloudflareTurnstileSiteKey]);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    let turnstileResponse: string | undefined;
    if (cloudflareTurnstileEnabled && widgetIdRef.current) {
      turnstileResponse = readTurnstileToken(widgetIdRef.current, turnstileTokenRef);
      if (!turnstileResponse) {
        showError("Please complete the security check before signing in.");
        return;
      }
    }

    try {
      await login(loginUsername, loginPassword, turnstileResponse);
      setLoginPassword("");
      showSuccess("Signed in.");
    } catch (error) {
      resetTurnstileWidget(widgetIdRef.current, turnstileTokenRef);
      showError(error instanceof Error ? error.message : "Login failed");
    }
  }

  if (!isBootstrapping && requiresSetup) {
    return <Navigate to="/setup" replace />;
  }

  if (user) {
    return <Navigate to="/" replace />;
  }

  return (
    <section className="mx-auto max-w-xl">
      <article className="surface p-6">
        <h2 className="font-display text-2xl">Sign in</h2>

        <form className="mt-6 grid gap-4" onSubmit={handleLogin}>
          <label className="grid gap-2 text-sm text-sand/70">
            <span className="font-semibold text-sand">Username</span>
            <input className=" field px-4 py-3 text-sm" value={loginUsername} onChange={(event) => setLoginUsername(event.target.value)} autoComplete="username" />
          </label>
          <label className="grid gap-2 text-sm text-sand/70">
            <span className="font-semibold text-sand">Password</span>
            <input className=" field px-4 py-3 text-sm" type="password" value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} autoComplete="current-password" />
          </label>
          {cloudflareTurnstileEnabled && cloudflareTurnstileSiteKey ? (
            <div ref={turnstileRef} className="mt-2 w-64 min-h-[74px]" />
          ) : null}
          <div className="flex items-center justify-between gap-4 mt-2">
            <button className=" bg-sand px-5 py-3 text-sm font-semibold text-canvas disabled:cursor-not-allowed disabled:opacity-60" type="submit" disabled={isAuthenticating}>
              {isAuthenticating ? "Signing in..." : "Sign In"}
            </button>
            {usersCanRegister ? (
              <Link to="/register" className="text-sm text-sand/60 hover:text-sand hover:underline transition">
                Create an account
              </Link>
            ) : null}
          </div>
        </form>
      </article>
    </section>
  );
}
