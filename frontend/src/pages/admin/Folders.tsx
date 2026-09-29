import { useState, type FormEvent } from "react";
import { api, ApiError, formatWhen, type Folder } from "../../api";
import { Button, Field, GroupList, GroupPicker, inputClass, Notice, PageHeader } from "../../components/ui";
import { useGroups, useLoad } from "../../useLoad";

export function Folders() {
  const { data, error, reload } = useLoad<Folder[]>("/folders");
  const { groups, names } = useGroups();
  const [notice, setNotice] = useState<{ tone: "error" | "info"; text: string } | null>(null);
  const report = (tone: "error" | "info", text: string) => {
    setNotice({ tone, text });
    reload();
  };

  return (
    <div className="overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-6 px-4 py-8 md:px-8">
        <PageHeader title="Shared folders" />
        <p className="max-w-[70ch] text-graphite">
          Files in a mapped folder are indexed automatically and checked for changes every 5 minutes. Each file
          takes the access of the nearest mapped folder above it. Changing access applies to the very next question.
        </p>
        <AddFolder groups={groups} onDone={report} />
        {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
        {error && <Notice tone="error">{error}</Notice>}
        {data && data.length === 0 && <p className="text-graphite">No folders mapped yet. Add one above.</p>}
        <ul className="divide-y divide-rule rounded border border-rule bg-sheet">
          {(data ?? []).map((f) => (
            <FolderItem key={f.id} folder={f} groups={groups} names={names} onDone={report} />
          ))}
        </ul>
      </div>
    </div>
  );
}

function FolderItem({ folder, groups, names, onDone }: {
  folder: Folder;
  groups: { id: string; name: string }[];
  names: Map<string, string>;
  onDone: (tone: "error" | "info", text: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [selected, setSelected] = useState(folder.acl_groups);

  async function save() {
    try {
      await api.put(`/folders/${folder.id}`, { group_ids: selected });
      setEditing(false);
      onDone("info", `Access to ${folder.path} changed.`);
    } catch (e) {
      onDone("error", e instanceof ApiError ? e.message : "Access was not changed.");
    }
  }

  async function remove() {
    try {
      await api.del(`/folders/${folder.id}`);
      onDone("info", `${folder.path} is no longer mapped. Its documents were removed from search.`);
    } catch (e) {
      onDone("error", e instanceof ApiError ? e.message : "The folder was not removed.");
    }
  }

  return (
    <li className="space-y-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-bold break-all">{folder.path}</p>
          <p className="text-sm text-graphite">Last checked: {formatWhen(folder.last_scanned_at)}</p>
          <div className="mt-2"><GroupList ids={folder.acl_groups} names={names} /></div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="quiet" onClick={() => setEditing(!editing)} aria-expanded={editing}>Change access</Button>
          {confirming ? (
            <>
              <Button variant="danger" onClick={remove}>Remove folder and its documents</Button>
              <Button variant="quiet" onClick={() => setConfirming(false)}>Keep</Button>
            </>
          ) : (
            <Button variant="danger" onClick={() => setConfirming(true)}>Remove</Button>
          )}
        </div>
      </div>
      {editing && (
        <div className="space-y-3 rounded bg-paper p-3">
          <GroupPicker legend="Who can see files in this folder" groups={groups} selected={selected} onChange={setSelected} />
          <Button onClick={save}>Save access</Button>
        </div>
      )}
    </li>
  );
}

function AddFolder({ groups, onDone }: {
  groups: { id: string; name: string }[];
  onDone: (tone: "error" | "info", text: string) => void;
}) {
  const [path, setPath] = useState("");
  const [selected, setSelected] = useState<string[]>([]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api.post("/folders", { path, group_ids: selected });
      onDone("info", `${path} mapped. Its files are being indexed now.`);
      setPath("");
      setSelected([]);
    } catch (err) {
      onDone("error", err instanceof ApiError ? err.message : "The folder was not mapped.");
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded border border-rule bg-sheet p-4">
      <h2 className="text-lg font-bold">Map a folder</h2>
      <Field label="Folder path" htmlFor="path" hint="As the server sees it, for example /sources/hr/policies.">
        <input id="path" required value={path} onChange={(e) => setPath(e.target.value)} className={inputClass} />
      </Field>
      <GroupPicker legend="Who can see its files" groups={groups} selected={selected} onChange={setSelected} />
      <Button type="submit" disabled={!path.trim()}>Map folder</Button>
    </form>
  );
}
