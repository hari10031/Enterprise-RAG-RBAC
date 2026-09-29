import { RefreshCw } from "lucide-react";
import { Button, Notice, PageHeader } from "../../components/ui";
import { useLoad } from "../../useLoad";

type HealthData = {
  database: string;
  llm: string;
  worker: string;
  jobs?: { queued: number; running: number; failed: number; oldest_ready_s: number | null };
  documents?: { status: string; n: number }[];
};
type Analytics = {
  summary: {
    queries: number;
    not_found_rate: number | null;
    low_grounding_rate: number | null;
    p95_first_token_ms: number | null;
    p95_latency_ms: number | null;
    p95_queue_ms: number | null;
  };
  top_unanswered: { query: string; times: number }[];
  feedback: { up: number; down: number };
};

const pct = (v: number | null) => (v == null ? "No data" : `${Math.round(v * 100)}%`);
const secs = (ms: number | null) => (ms == null ? "No data" : `${(ms / 1000).toFixed(1)} s`);

export function Health() {
  const health = useLoad<HealthData>("/health");
  const stats = useLoad<Analytics>("/analytics/queries?days=30");
  const h = health.data;
  const s = stats.data?.summary;

  const services = h
    ? [
        { name: "Database", state: h.database, fix: "Check that PostgreSQL is running and reachable from the API." },
        { name: "Language model", state: h.llm, fix: "Check LLM_BASE_URL and LLM_API_KEY, and the provider's status page." },
        { name: "Ingestion worker", state: h.worker, fix: "Documents are waiting. Start or restart the worker process." },
      ]
    : [];

  // Targets from the v0.1 evaluation plan; "lower is better" for every row.
  const rows: [string, string, string, boolean | null][] = s
    ? [
        ["Time to first word (p95)", secs(s.p95_first_token_ms), "5 s or less", s.p95_first_token_ms == null ? null : s.p95_first_token_ms <= 5000],
        ["Full answer time (p95)", secs(s.p95_latency_ms), "30 s or less", s.p95_latency_ms == null ? null : s.p95_latency_ms <= 30000],
        ["Waiting for the model (p95)", secs(s.p95_queue_ms), "5 s or less", s.p95_queue_ms == null ? null : s.p95_queue_ms <= 5000],
        ["Answers with unsourced statements", pct(s.low_grounding_rate), "8% or less", s.low_grounding_rate == null ? null : s.low_grounding_rate <= 0.08],
        ["Questions with no answer found", pct(s.not_found_rate), "Watch the trend", null],
      ]
    : [];

  return (
    <div className="overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-8 px-4 py-8 md:px-8">
        <PageHeader title="System health">
          <Button variant="quiet" onClick={() => { health.reload(); stats.reload(); }}>
            <RefreshCw aria-hidden size={16} /> Check again
          </Button>
        </PageHeader>
        {health.error && <Notice tone="error">{health.error}</Notice>}

        <section aria-labelledby="svc">
          <h2 id="svc" className="mb-3 text-lg font-bold">Services</h2>
          <ul className="divide-y divide-rule rounded border border-rule bg-sheet">
            {services.map((svc) => {
              const ok = svc.state === "ok";
              return (
                <li key={svc.name} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 p-4">
                  <span className="w-44 font-bold">{svc.name}</span>
                  <span className={ok ? "text-evergreen" : "font-bold text-danger"}>
                    {ok ? "Working" : `Not working (${svc.state})`}
                  </span>
                  {!ok && <span className="basis-full text-sm text-graphite">{svc.fix}</span>}
                </li>
              );
            })}
          </ul>
          {h?.jobs && (
            <p className="mt-3 text-graphite">
              Indexing queue: {h.jobs.queued} waiting, {h.jobs.running} running, {h.jobs.failed} failed.
              {h.documents?.length ? ` Documents: ${h.documents.map((d) => `${d.n} ${d.status}`).join(", ")}.` : ""}
            </p>
          )}
        </section>

        <section aria-labelledby="q">
          <h2 id="q" className="mb-1 text-lg font-bold">Answers in the last 30 days</h2>
          <p className="mb-3 text-graphite">
            {s ? `${s.queries} answers. ` : ""}
            {stats.data ? `${stats.data.feedback.up} rated helpful, ${stats.data.feedback.down} rated unhelpful.` : ""}
          </p>
          {stats.error && <Notice tone="error">{stats.error}</Notice>}
          <div className="overflow-x-auto rounded border border-rule bg-sheet">
            <table className="w-full min-w-[34rem] text-left">
              <thead className="border-b border-rule text-sm text-graphite">
                <tr>
                  <th scope="col" className="px-4 py-2 font-normal">Measure</th>
                  <th scope="col" className="px-4 py-2 font-normal">Now</th>
                  <th scope="col" className="px-4 py-2 font-normal">Target</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(([label, value, target, met]) => (
                  <tr key={label} className="border-b border-rule last:border-0">
                    <th scope="row" className="px-4 py-2 font-normal">{label}</th>
                    <td className={`px-4 py-2 font-bold tabular-nums ${met === false ? "text-danger" : ""}`}>
                      {value}
                      {met === false && <span className="ml-2 font-normal">(misses target)</span>}
                    </td>
                    <td className="px-4 py-2 text-graphite">{target}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section aria-labelledby="gap">
          <h2 id="gap" className="mb-1 text-lg font-bold">Questions with no answer</h2>
          <p className="mb-3 text-graphite">
            Frequent ones point at missing documents, or documents not shared with the people asking.
          </p>
          {stats.data && stats.data.top_unanswered.length === 0 ? (
            <p className="text-graphite">Every question in the last 30 days found an answer.</p>
          ) : (
            <ol className="divide-y divide-rule rounded border border-rule bg-sheet">
              {stats.data?.top_unanswered.map((u) => (
                <li key={u.query} className="flex items-baseline justify-between gap-4 px-4 py-2">
                  <span className="min-w-0 break-words">{u.query}</span>
                  <span className="shrink-0 text-graphite tabular-nums">asked {u.times}×</span>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </div>
  );
}
