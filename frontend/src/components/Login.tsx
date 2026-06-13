import { FormEvent, useState } from "react";
import { api } from "../api";

interface LoginProps {
  onSuccess: (token: string) => void;
}

export function Login({ onSuccess }: LoginProps) {
  const [username, setUsername] = useState("evaluator");
  const [password, setPassword] = useState("password");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<{ access_token: string }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      onSuccess(result.access_token);
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "Unable to sign in",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login-page">
      <section className="login-brand-panel">
        <div className="login-brand-content">
          <div className="brand-lockup brand-lockup-light">
            <span className="brand-mark">S</span>
            <span>
              <strong>Sheldon</strong>
              <small>Evaluation Platform</small>
            </span>
          </div>
          <div className="login-message">
            <p className="eyebrow eyebrow-light">Structured evaluation</p>
            <h1>Every answer, reviewed with clarity.</h1>
            <p>
              A focused workspace for question-by-question, step-by-step answer
              sheet evaluation.
            </p>
          </div>
          <div className="login-stat-row">
            <span>
              <strong>01</strong>
              Paper context
            </span>
            <span>
              <strong>02</strong>
              Step marking
            </span>
            <span>
              <strong>03</strong>
              Live progress
            </span>
          </div>
        </div>
      </section>
      <section className="login-form-panel">
        <form className="login-card" onSubmit={submit}>
          <p className="eyebrow">Evaluator access</p>
          <h2>Welcome back</h2>
          <p className="muted">Sign in to continue your assigned evaluations.</p>
          <label>
            Username
            <input
              autoComplete="username"
              onChange={(event) => setUsername(event.target.value)}
              value={username}
            />
          </label>
          <label>
            Password
            <input
              autoComplete="current-password"
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              value={password}
            />
          </label>
          {error && <p className="form-error">{error}</p>}
          <button className="button-primary button-wide" disabled={busy}>
            {busy ? "Signing in..." : "Sign in"}
          </button>
          <p className="login-hint">
            Demo credentials: <code>evaluator</code> / <code>password</code>
          </p>
        </form>
      </section>
    </main>
  );
}
