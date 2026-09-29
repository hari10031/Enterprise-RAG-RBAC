import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { Button, Field, inputClass, Notice, PageHeader } from "../components/ui";

export function Account() {
  const { me } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [result, setResult] = useState<{ tone: "error" | "info"; text: string } | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setResult(null);
    try {
      await api.post("/auth/password", { current_password: current, new_password: next });
      setCurrent("");
      setNext("");
      setResult({ tone: "info", text: "Password changed." });
    } catch (err) {
      setResult({ tone: "error", text: err instanceof ApiError ? err.message : "The password was not changed." });
    }
  }

  return (
    <div className="overflow-y-auto">
      <div className="mx-auto max-w-[44rem] space-y-8 px-4 py-8 md:px-8">
        <PageHeader title="Your account" />
        <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2">
          <dt className="text-graphite">Name</dt>
          <dd>{me?.display_name}</dd>
          <dt className="text-graphite">Email</dt>
          <dd>{me?.email}</dd>
          <dt className="text-graphite">Groups</dt>
          <dd>{me?.groups.map((g) => g.name).join(", ") || "None yet"}</dd>
        </dl>
        <form onSubmit={submit} className="max-w-sm space-y-4">
          <h2 className="text-lg font-bold">Change password</h2>
          <Field label="Current password" htmlFor="current">
            <input id="current" type="password" autoComplete="current-password" value={current}
              onChange={(e) => setCurrent(e.target.value)} className={inputClass} />
          </Field>
          <Field label="New password" htmlFor="new" hint="At least 12 characters. A short sentence works well.">
            <input id="new" type="password" autoComplete="new-password" minLength={12} value={next}
              onChange={(e) => setNext(e.target.value)} className={inputClass} />
          </Field>
          {result && <Notice tone={result.tone}>{result.text}</Notice>}
          <Button type="submit" disabled={!current || next.length < 12}>Change password</Button>
        </form>
      </div>
    </div>
  );
}
