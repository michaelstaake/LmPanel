import { FormEvent, useEffect, useRef, useState } from "react";
import { Navigate, Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { readTurnstileToken, resetTurnstileWidget, turnstileRenderOptions } from "../lib/turnstile";
import { isValidUsername, sanitizeUsernameInput, USERNAME_VALIDATION_MESSAGE } from "../lib/username";

export default function RegisterPage() {
  const { user, requiresSetup, isBootstrapping, isAuthenticating, register, usersCanRegister, cloudflareTurnstileEnabled, cloudflareTurnstileSiteKey } = useAuth();
  const { showError, showSuccess } = useToast();
  const [registerUsername, setRegisterUsername] = useState("");
  const [registerEmail, setRegisterEmail] = useState("");
  const [registerPassword, setRegisterPassword] = useState("");
  const [registerConfirmPassword, setRegisterConfirmPassword] = useState("");
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

  async function handleRegister(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!isValidUsername(registerUsername)) {
      showError(USERNAME_VALIDATION_MESSAGE);
      return;
    }

    if (registerPassword !== registerConfirmPassword) {
      showError("Passwords do not match.");
      return;
    }

    let turnstileResponse: string | undefined;
    if (cloudflareTurnstileEnabled && widgetIdRef.current) {
      turnstileResponse = readTurnstileToken(widgetIdRef.current, turnstileTokenRef);
      if (!turnstileResponse) {
        showError("Please complete the security check before registering.");
        return;
      }
    }

    try {
      await register(registerUsername, registerEmail, registerPassword, turnstileResponse);
      setRegisterPassword("");
      setRegisterConfirmPassword("");
      showSuccess("Account created.");
    } catch (error) {
      resetTurnstileWidget(widgetIdRef.current, turnstileTokenRef);
      showError(error instanceof Error ? error.message : "Registration failed");
    }
  }

  if (!isBootstrapping && requiresSetup) {
    return <Navigate to="/setup" replace />;
  }

  if (user) {
    return <Navigate to="/" replace />;
  }

  if (!isBootstrapping && !usersCanRegister) {
    return <Navigate to="/login" replace />;
  }

  return (
    <section className="mx-auto max-w-xl">
      <article className="-[2rem]">
        <h2 className="font-display text-2xl">Create an account</h2>

        <form className="mt-6 grid gap-4" onSubmit={handleRegister}>
          <label className="grid gap-2 text-sm text-sand/70">
            <span className="font-semibold text-sand">Username</span>
            <input className=" field px-4 py-3 text-sm" value={registerUsername} onChange={(event) => setRegisterUsername(sanitizeUsernameInput(event.target.value))} autoComplete="username" minLength={4} maxLength={16} pattern="[a-z0-9]{4,16}" />
          </label>
          <label className="grid gap-2 text-sm text-sand/70">
            <span className="font-semibold text-sand">Email</span>
            <input className=" field px-4 py-3 text-sm" type="email" value={registerEmail} onChange={(event) => setRegisterEmail(event.target.value)} autoComplete="email" />
          </label>
          <label className="grid gap-2 text-sm text-sand/70">
            <span className="font-semibold text-sand">Password</span>
            <input className=" field px-4 py-3 text-sm" type="password" value={registerPassword} onChange={(event) => setRegisterPassword(event.target.value)} autoComplete="new-password" />
          </label>
          <label className="grid gap-2 text-sm text-sand/70">
            <span className="font-semibold text-sand">Confirm Password</span>
            <input className=" field px-4 py-3 text-sm" type="password" value={registerConfirmPassword} onChange={(event) => setRegisterConfirmPassword(event.target.value)} autoComplete="new-password" />
          </label>
          {cloudflareTurnstileEnabled && cloudflareTurnstileSiteKey ? (
            <div ref={turnstileRef} className="mt-2 w-64 min-h-[74px]" />
          ) : null}
          <div className="flex items-center justify-between gap-4 mt-2">
            <button className=" bg-sand px-5 py-3 text-sm font-semibold text-canvas disabled:cursor-not-allowed disabled:opacity-60" type="submit" disabled={isAuthenticating}>
              {isAuthenticating ? "Creating..." : "Register"}
            </button>
            <Link to="/login" className="text-sm text-sand/60 hover:text-sand hover:underline transition">
              Back to Sign In
            </Link>
          </div>
        </form>
      </article>
    </section>
  );
}