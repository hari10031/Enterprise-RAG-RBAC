import { useState, type FormEvent } from "react";
import { ApiError } from "../api";
import { useAuth } from "../auth";
import { Button, Field, inputClass } from "../components/ui";

export function Login() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email, password);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "That email and password don't match, or the account is locked for 15 minutes after 5 failed tries."
          : "The server could not be reached. Check your connection and try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-dvh px-4 md:grid-cols-[1fr_minmax(0,28rem)_1fr]">
      <div className="self-center py-12 md:col-start-2">
        <h1 className="font-serif text-[2.5rem] leading-[1.1] font-semibold tracking-tight">
          Ask the company's documents.
        </h1>
        <p className="mt-3 max-w-[38ch] text-graphite">
          Answers come only from files your groups can open, and every claim links back to its source.
        </p>
        <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
          <Field label="Work email" htmlFor="email">
            <input
              id="email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Password" htmlFor="password">
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputClass}
            />
          </Field>
          {error && (
            <p role="alert" className="rounded border border-danger/30 bg-danger-wash px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}
          <Button type="submit" disabled={busy || !email || !password} className="w-full">
            {busy ? "Signing in…" : "Sign in"}
          </Button>
          <p className="text-sm text-graphite">No account yet? Ask an administrator to create one.</p>
        </form>
      </div>
    </main>
  );
}
