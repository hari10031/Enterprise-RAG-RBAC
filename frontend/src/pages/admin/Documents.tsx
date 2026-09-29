import { RefreshCw, Upload } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError, formatBytes, formatWhen, type DocumentRow } from "../../api";
import { Button, GroupList, GroupPicker, inputClass, Notice, PageHeader } from "../../components/ui";
import { useGroups, useLoad } from "../../useLoad";

const STATUS: Record<string, { label: string; cls: string }> = {
  queued: { label: "Waiting", cls: "text-graphite" },
  parsing: { label: "Indexing", cls: "text-evergreen" },
  chunking: { label: "Indexing", cls: "text-evergreen" },
  embedding: { label: "Indexing", cls: "text-evergreen" },
  indexed: { label: "Searchable", cls: "text-ink" },
  failed: { label: "Failed", cls: "text-danger font-bold" },
};

export function Documents() {
  const { data, error, reload } = useLoad<DocumentRow[]>("/documents");
  const { groups, names } = useGroups();
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "error" | "info"; text: string } | null>(null);
  const docs = data ?? [];
  const pending = docs.some((d) => d.status !== "indexed" && d.status !== "failed");

  // Refresh while anything is still being indexed.
  useEffect(() => {
    if (!pending) return;
    const t = window.setInterval(reload, 5000);
    return () => window.clearInterval(t);
  }, [pending, reload]);

  const shown = docs.filter((d) => d.title.toLowerCase().includes(filter.toLowerCase()));

  async function reindex(d: DocumentRow) {
    try {
      await api.post(`/documents/${d.id}/reindex`);
      setNotice({ tone: "info", text: `${d.title} will be indexed again.` });
      reload();
    } catch (e) {
      setNotice({ tone: "error", text: e instanceof ApiError ? e.message : "Re-index failed to start." });
    }
  }

  return (
    <div className="overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-6 px-4 py-8 md:px-8">
        <PageHeader title="Documents" />
        <UploadForm groups={groups} onDone={(text, tone) => { setNotice({ tone, text }); reload(); }} />
        {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
        {error && <Notice tone="error">{error}</Notice>}

        <div className="flex flex-wrap items-end justify-between gap-3">
          <p className="text-graphite">
            {docs.length} documents, {docs.filter((d) => d.status === "indexed").length} searchable
            {pending && ", indexing in progress"}
          </p>
          <label className="w-full sm:w-72">
            <span className="sr-only">Filter by title</span>
            <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by title" className={inputClass} />
          </label>
        </div>

        {docs.length === 0 && data ? (
          <p className="text-graphite">
            No documents yet. Upload a file above, or map a shared folder so its files are indexed automatically.
          </p>
        ) : (
          <div className="overflow-x-auto rounded border border-rule bg-sheet">
            <table className="w-full min-w-[46rem] text-left">
              <thead className="border-b border-rule text-sm text-graphite">
                <tr>
                  <th scope="col" className="px-3 py-2 font-normal">Title</th>
                  <th scope="col" className="px-3 py-2 font-normal">Status</th>
                  <th scope="col" className="px-3 py-2 font-normal">Who can see it</th>
                  <th scope="col" className="px-3 py-2 font-normal">Size</th>
                  <th scope="col" className="px-3 py-2 font-normal">Last indexed</th>
                  <th scope="col" className="px-3 py-2"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {shown.map((d) => (
                  <DocRow
                    key={d.id}
                    doc={d}
                    names={names}
                    groups={groups}
                    editing={editing === d.id}
                    onEdit={() => setEditing(editing === d.id ? null : d.id)}
                    onReindex={() => reindex(d)}
                    onSaved={() => { setEditing(null); setNotice({ tone: "info", text: `Access to ${d.title} changed. It applies to the next question.` }); reload(); }}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function DocRow({ doc, names, groups, editing, onEdit, onReindex, onSaved }: {
  doc: DocumentRow;
  names: Map<string, string>;
  groups: { id: string; name: string }[];
  editing: boolean;
  onEdit: () => void;
  onReindex: () => void;
  onSaved: () => void;
}) {
  const [selected, setSelected] = useState(doc.acl_groups);
  const [error, setError] = useState<string | null>(null);
  const status = STATUS[doc.status] ?? { label: doc.status, cls: "" };

  async function save() {
    try {
      await api.put(`/documents/${doc.id}/acl`, { group_ids: selected });
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Access was not changed.");
    }
  }

  return (
    <>
      <tr className="border-b border-rule last:border-0 align-top">
        <td className="max-w-[22rem] px-3 py-2">
          <span className="block truncate font-bold" title={doc.title}>{doc.title}</span>
          <span className="block truncate text-sm text-graphite" title={doc.path ?? undefined}>
            {doc.source === "upload" ? "Uploaded" : `In folder ${doc.path?.split(/[\\/]/).slice(-2, -1)[0] ?? ""}`}
          </span>
        </td>
        <td className={`px-3 py-2 whitespace-nowrap ${status.cls}`}>{status.label}</td>
        <td className="px-3 py-2"><GroupList ids={doc.acl_groups} names={names} /></td>
        <td className="px-3 py-2 whitespace-nowrap">{formatBytes(doc.size_bytes)}</td>
        <td className="px-3 py-2 whitespace-nowrap">{formatWhen(doc.indexed_at)}</td>
        <td className="px-3 py-1 whitespace-nowrap text-right">
          {doc.source === "upload" && (
            <button onClick={onEdit} aria-expanded={editing} className="min-h-11 rounded px-3 text-evergreen hover:bg-wash">
              Change access
            </button>
          )}
          <button onClick={onReindex} className="inline-flex min-h-11 items-center gap-1 rounded px-3 text-evergreen hover:bg-wash">
            <RefreshCw aria-hidden size={16} /> Re-index
          </button>
        </td>
      </tr>
      {editing && (
        <tr className="border-b border-rule bg-paper">
          <td colSpan={6} className="space-y-3 px-3 py-4">
            <GroupPicker legend={`Who can see ${doc.title}`} groups={groups} selected={selected} onChange={setSelected} />
            {error && <Notice tone="error">{error}</Notice>}
            <div className="flex gap-2">
              <Button onClick={save}>Save access</Button>
              <Button variant="quiet" onClick={onEdit}>Cancel</Button>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function UploadForm({ groups, onDone }: {
  groups: { id: string; name: string }[];
  onDone: (text: string, tone: "error" | "info") => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    if (file.size > 50 * 1024 * 1024) return onDone(`${file.name} is larger than 50 MB. Split it or compress it first.`, "error");
    const form = new FormData();
    form.append("file", file);
    selected.forEach((g) => form.append("group_ids", g));
    setBusy(true);
    try {
      await api.post("/documents", form);
      onDone(`${file.name} uploaded. It becomes searchable once indexing finishes.`, "info");
      setFile(null);
      if (input.current) input.current.value = "";
    } catch (err) {
      onDone(err instanceof ApiError ? err.message : "Upload failed.", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded border border-rule bg-sheet p-4">
      <h2 className="text-lg font-bold">Upload a document</h2>
      <div>
        <label htmlFor="file" className="mb-1 block font-bold">File</label>
        <input
          ref={input}
          id="file"
          type="file"
          accept=".pdf,.docx,.xlsx,.pptx,.html,.htm,.md,.txt"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="block w-full text-sm file:mr-3 file:min-h-11 file:rounded file:border file:border-rule file:bg-wash file:px-4 file:font-bold"
        />
        <p className="mt-1 text-sm text-graphite">PDF, Word, Excel, PowerPoint, HTML, Markdown or text, up to 50 MB.</p>
      </div>
      <GroupPicker legend="Who can see it" groups={groups} selected={selected} onChange={setSelected} />
      <Button type="submit" disabled={!file || busy}>
        <Upload aria-hidden size={18} /> {busy ? "Uploading…" : "Upload"}
      </Button>
    </form>
  );
}
