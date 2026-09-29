import { FileText, FolderTree, HeartPulse, LogOut, Menu, Plus, UserRound, Users, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api, type Conversation } from "../api";
import { useAuth } from "../auth";

export type ShellContext = { refreshConversations: () => void };

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `flex min-h-11 items-center gap-3 rounded px-3 ${isActive ? "bg-wash font-bold text-ink" : "text-graphite hover:bg-wash hover:text-ink"}`;

export function Shell() {
  const { me, signOut } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [open, setOpen] = useState(false);

  const refreshConversations = useCallback(() => {
    api.get<Conversation[]>("/conversations").then(setConversations).catch(() => {});
  }, []);
  useEffect(refreshConversations, [refreshConversations]);
  useEffect(() => setOpen(false), [location.pathname]);

  const rail = (
    <nav aria-label="Main" className="flex h-full flex-col gap-6 overflow-y-auto p-4">
      <button
        onClick={() => navigate("/chat")}
        className="flex min-h-11 items-center gap-2 rounded bg-evergreen px-3 font-bold text-white hover:bg-evergreen-deep"
      >
        <Plus aria-hidden size={18} /> New question
      </button>

      <section aria-labelledby="history-heading" className="min-h-0">
        <h2 id="history-heading" className="mb-1 px-3 text-sm text-graphite">
          Your conversations
        </h2>
        {conversations.length === 0 ? (
          <p className="px-3 text-sm text-graphite">Questions you ask are kept here.</p>
        ) : (
          <ul className="space-y-0.5">
            {conversations.map((c) => (
              <li key={c.id}>
                <NavLink to={`/chat/${c.id}`} className={linkClass} title={c.title ?? undefined}>
                  <span className="truncate">{c.title || "Untitled"}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        )}
      </section>

      {me?.is_admin && (
        <section aria-labelledby="admin-heading">
          <h2 id="admin-heading" className="mb-1 px-3 text-sm text-graphite">
            Administration
          </h2>
          <ul className="space-y-0.5">
            <li>
              <NavLink to="/admin/documents" className={linkClass}>
                <FileText aria-hidden size={18} /> Documents
              </NavLink>
            </li>
            <li>
              <NavLink to="/admin/folders" className={linkClass}>
                <FolderTree aria-hidden size={18} /> Shared folders
              </NavLink>
            </li>
            <li>
              <NavLink to="/admin/groups" className={linkClass}>
                <Users aria-hidden size={18} /> People and groups
              </NavLink>
            </li>
            <li>
              <NavLink to="/admin/health" className={linkClass}>
                <HeartPulse aria-hidden size={18} /> System health
              </NavLink>
            </li>
          </ul>
        </section>
      )}

      <div className="mt-auto space-y-0.5 border-t border-rule pt-4">
        <NavLink to="/account" className={linkClass}>
          <UserRound aria-hidden size={18} />
          <span className="truncate">{me?.display_name}</span>
        </NavLink>
        <button onClick={signOut} className={linkClass({ isActive: false }) + " w-full"}>
          <LogOut aria-hidden size={18} /> Sign out
        </button>
      </div>
    </nav>
  );

  return (
    <div className="flex h-dvh">
      <aside className="hidden w-66 shrink-0 border-r border-rule bg-paper md:block">{rail}</aside>

      {open && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-ink/40" onClick={() => setOpen(false)} aria-hidden />
          <aside className="panel-enter absolute inset-y-0 left-0 w-[min(20rem,85vw)] bg-paper shadow-xl">
            <button
              onClick={() => setOpen(false)}
              aria-label="Close menu"
              className="absolute top-3 right-3 grid size-11 place-items-center rounded hover:bg-wash"
            >
              <X aria-hidden size={20} />
            </button>
            <div className="h-full pt-12">{rail}</div>
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-rule px-2 py-1 md:hidden">
          <button
            onClick={() => setOpen(true)}
            aria-label="Open menu"
            className="grid size-11 place-items-center rounded hover:bg-wash"
          >
            <Menu aria-hidden size={20} />
          </button>
          <span className="font-bold">Knowledge Assistant</span>
        </div>
        <Outlet context={{ refreshConversations } satisfies ShellContext} />
      </div>
    </div>
  );
}
