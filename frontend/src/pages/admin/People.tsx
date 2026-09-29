import { useState, type FormEvent } from "react";
import { api, ApiError, type UserRow } from "../../api";
import { useAuth } from "../../auth";
import { Button, Field, GroupList, GroupPicker, inputClass, Notice, PageHeader } from "../../components/ui";
import { useGroups, useLoad } from "../../useLoad";

type Report = (tone: "error" | "info", text: string) => void;
const message = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

export function People() {
  const users = useLoad<UserRow[]>("/users");
  const { groups, names, reload: reloadGroups } = useGroups();
  const [notice, setNotice] = useState<{ tone: "error" | "info"; text: string } | null>(null);
  const report: Report = (tone, text) => {
    setNotice({ tone, text });
    users.reload();
    reloadGroups();
  };

  return (
    <div className="overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-8 px-4 py-8 md:px-8">
        <PageHeader title="People and groups" />
        <p className="max-w-[70ch] text-graphite">
          People see documents shared with any of their groups. Membership changes apply to their next question.
        </p>
        {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}

        <section className="grid gap-6 lg:grid-cols-2">
          <AddUser groups={groups} onDone={report} />
          <Groups groups={groups} onDone={report} />
        </section>

        <section aria-labelledby="people-heading">
          <h2 id="people-heading" className="mb-3 text-lg font-bold">People</h2>
          {users.error && <Notice tone="error">{users.error}</Notice>}
          <ul className="divide-y divide-rule rounded border border-rule bg-sheet">
            {(users.data ?? []).map((u) => (
              <UserItem key={u.id} user={u} groups={groups} names={names} onDone={report} />
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

function UserItem({ user, groups, names, onDone }: {
  user: UserRow;
  groups: { id: string; name: string }[];
  names: Map<string, string>;
  onDone: Report;
}) {
  const { me } = useAuth();
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState(user.group_ids);
  const locked = user.locked_until && new Date(user.locked_until) > new Date();

  async function saveGroups() {
    const add = selected.filter((g) => !user.group_ids.includes(g));
    const remove = user.group_ids.filter((g) => !selected.includes(g));
    try {
      await Promise.all([
        ...add.map((g) => api.post(`/groups/${g}/members`, { user_id: user.id })),
        ...remove.map((g) => api.del(`/groups/${g}/members/${user.id}`)),
      ]);
      setEditing(false);
      onDone("info", `${user.display_name}'s groups were updated.`);
    } catch (e) {
      onDone("error", message(e, "Groups were not updated."));
    }
  }

  async function deactivate() {
    try {
      await api.del(`/users/${user.id}`);
      onDone("info", `${user.display_name} can no longer sign in.`);
    } catch (e) {
      onDone("error", message(e, "The account was not deactivated."));
    }
  }

  return (
    <li className={`space-y-3 p-4 ${user.is_active ? "" : "opacity-60"}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-bold">
            {user.display_name}
            {!user.is_active && <span className="ml-2 font-normal text-graphite">(deactivated)</span>}
            {locked && <span className="ml-2 font-normal text-amber">(locked after failed sign-ins)</span>}
          </p>
          <p className="text-sm break-all text-graphite">{user.email}</p>
          <div className="mt-2">
            {user.group_ids.length ? <GroupList ids={user.group_ids} names={names} /> : <span className="text-sm text-amber">In no group: sees no documents</span>}
          </div>
        </div>
        {user.is_active && (
          <div className="flex flex-wrap gap-2">
            <Button variant="quiet" onClick={() => setEditing(!editing)} aria-expanded={editing}>Change groups</Button>
            {user.id !== me?.id && <Button variant="danger" onClick={deactivate}>Deactivate</Button>}
          </div>
        )}
      </div>
      {editing && (
        <div className="space-y-3 rounded bg-paper p-3">
          <GroupPicker legend={`Groups for ${user.display_name}`} groups={groups} selected={selected} onChange={setSelected} />
          <Button onClick={saveGroups}>Save groups</Button>
        </div>
      )}
    </li>
  );
}

function AddUser({ groups, onDone }: { groups: { id: string; name: string }[]; onDone: Report }) {
  const [form, setForm] = useState({ email: "", display_name: "", password: "" });
  const [selected, setSelected] = useState<string[]>([]);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api.post("/users", { ...form, group_ids: selected });
      onDone("info", `Account created for ${form.display_name}. Share the password with them directly.`);
      setForm({ email: "", display_name: "", password: "" });
      setSelected([]);
    } catch (err) {
      onDone("error", message(err, "The account was not created."));
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded border border-rule bg-sheet p-4">
      <h2 className="text-lg font-bold">Add a person</h2>
      <Field label="Name" htmlFor="u-name">
        <input id="u-name" required value={form.display_name} onChange={set("display_name")} className={inputClass} />
      </Field>
      <Field label="Work email" htmlFor="u-email">
        <input id="u-email" type="email" required value={form.email} onChange={set("email")} className={inputClass} />
      </Field>
      <Field label="First password" htmlFor="u-pass" hint="At least 12 characters. They can change it after signing in.">
        <input id="u-pass" type="text" autoComplete="off" required minLength={12} value={form.password} onChange={set("password")} className={inputClass} />
      </Field>
      <GroupPicker legend="Groups" groups={groups} selected={selected} onChange={setSelected} />
      <Button type="submit" disabled={!form.email || !form.display_name || form.password.length < 12}>Add person</Button>
    </form>
  );
}

function Groups({ groups, onDone }: { groups: { id: string; name: string; description?: string | null }[]; onDone: Report }) {
  const [name, setName] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await api.post("/groups", { name: name.trim() });
      onDone("info", `Group ${name.trim()} created.`);
      setName("");
    } catch (err) {
      onDone("error", message(err, "The group was not created."));
    }
  }

  async function remove(id: string, groupName: string) {
    try {
      await api.del(`/groups/${id}`);
      setConfirming(null);
      onDone("info", `Group ${groupName} deleted. Documents shared only with it are now hidden from everyone but admins.`);
    } catch (err) {
      onDone("error", message(err, "The group was not deleted."));
    }
  }

  return (
    <div className="space-y-4 rounded border border-rule bg-sheet p-4">
      <h2 className="text-lg font-bold">Groups</h2>
      <ul className="divide-y divide-rule">
        {groups.map((g) => (
          <li key={g.id} className="flex min-h-11 flex-wrap items-center justify-between gap-2 py-1">
            <span className="font-bold">{g.name}</span>
            {g.name === "admins" ? (
              <span className="text-sm text-graphite">Built in</span>
            ) : confirming === g.id ? (
              <span className="flex gap-2">
                <Button variant="danger" onClick={() => remove(g.id, g.name)}>Delete {g.name}</Button>
                <Button variant="quiet" onClick={() => setConfirming(null)}>Keep</Button>
              </span>
            ) : (
              <button onClick={() => setConfirming(g.id)} className="min-h-11 rounded px-3 text-danger hover:bg-danger-wash">
                Delete
              </button>
            )}
          </li>
        ))}
      </ul>
      <form onSubmit={create} className="flex items-end gap-2">
        <div className="flex-1">
          <Field label="New group" htmlFor="g-name">
            <input id="g-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="for example finance" className={inputClass} />
          </Field>
        </div>
        <Button type="submit" disabled={!name.trim()}>Create group</Button>
      </form>
    </div>
  );
}
