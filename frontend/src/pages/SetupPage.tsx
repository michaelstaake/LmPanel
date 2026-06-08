import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { isValidUsername, sanitizeUsernameInput, USERNAME_VALIDATION_MESSAGE } from "../lib/username";

export default function SetupPage() {
  const navigate = useNavigate();
  const { bootstrapAdmin, isAuthenticating } = useAuth();
  const { showError, showSuccess } = useToast();
  const [username, setUsername] = useState("admin");
  const [email, setEmail] = useState("admin@localhost");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  async function handleBootstrap(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!isValidUsername(username)) {
      showError(USERNAME_VALIDATION_MESSAGE);
      return;
    }

    if (password !== confirmPassword) {
      showError("Passwords do not match.");
      return;
    }

    try {
      await bootstrapAdmin(username, email, password);
      setPassword("");
      setConfirmPassword("");
      showSuccess("Admin account created.");
      navigate("/configuration", { replace: true });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Initial admin creation failed";
      if (message.includes("Request failed: 500")) {
        showError("Initial admin creation failed with a server error. Check backend logs and ensure the ./data directory is writable before retrying.");
      } else {
        showError(message);
      }
    }
  }

  return (
    <section className="grid gap-4">
      <article className="">
        <h3 className="font-display text-lg">Create admin account</h3>
        <form className="mt-5 grid gap-3 md:max-w-xl" onSubmit={handleBootstrap}>
          <label className="grid gap-1 text-sm text-sand/70">
            Username
            <input className=" border border-white/15 bg-white/10 px-3 text-sand py-2 text-sm" value={username} onChange={(event) => setUsername(sanitizeUsernameInput(event.target.value))} autoComplete="username" minLength={4} maxLength={16} pattern="[a-z0-9]{4,16}" />
          </label>
          <label className="grid gap-1 text-sm text-sand/70">
            Email
            <input className=" border border-white/15 bg-white/10 px-3 text-sand py-2 text-sm" type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" />
          </label>
          <label className="grid gap-1 text-sm text-sand/70">
            Password
            <input className=" border border-white/15 bg-white/10 px-3 text-sand py-2 text-sm" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" />
          </label>
          <label className="grid gap-1 text-sm text-sand/70">
            Confirm Password
            <input className=" border border-white/15 bg-white/10 px-3 text-sand py-2 text-sm" type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} autoComplete="new-password" />
          </label>
          <div className="mt-2">
            <button className=" bg-sand px-4 py-2 text-sm font-semibold text-canvas disabled:cursor-not-allowed disabled:opacity-60" type="submit" disabled={isAuthenticating}>
              {isAuthenticating ? "Creating..." : "Get Started"}
            </button>
          </div>
        </form>
      </article>
    </section>
  );
}