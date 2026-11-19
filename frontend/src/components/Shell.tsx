import { Check, FileText, FolderTree, HeartPulse, LogOut, Menu, MoreHorizontal, PanelLeftClose, PanelLeftOpen, Pencil, Plus, Trash2, UserRound, Users, X } from "lucide-react";
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
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const saved = window.localStorage.getItem("sidebar-width");
    const width = saved ? Number(saved) : 264;
    return Number.isFinite(width) ? Math.min(420, Math.max(180, width)) : 264;
  });
  const [resizing, setResizing] = useState(false);
  const [deleting, setDeleting] = useState<string[]>([]);
  const [menuId, setMenuId] = useState<string | null>(null);
  const [menuPosition, setMenuPosition] = useState<{ left: number; top: number } | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameTitle, setRenameTitle] = useState("");
  const [toast, setToast] = useState<{ text: string; tone: "success" | "error" } | null>(null);

  const refreshConversations = useCallback(() => {
    api.get<Conversation[]>("/conversations").then(setConversations).catch(() => {});
  }, []);
  useEffect(refreshConversations, [refreshConversations]);
  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    setMenuId(null);
    setMenuPosition(null);
    setRenamingId(null);
  }, [location.pathname]);
  useEffect(() => {
    if (!menuId) return;
    const closeMenu = (event: MouseEvent) => {
      if (!(event.target as HTMLElement).closest("[data-chat-actions]") &&
          !(event.target as HTMLElement).closest("[data-chat-actions-menu]")) {
        setMenuId(null);
        setMenuPosition(null);
      }
    };
    const closeWithEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuId(null);
        setMenuPosition(null);
      }
    };
    const closeOnResize = () => {
      setMenuId(null);
      setMenuPosition(null);
    };
    document.addEventListener("mousedown", closeMenu);
    document.addEventListener("keydown", closeWithEscape);
    window.addEventListener("resize", closeOnResize);
    return () => {
      document.removeEventListener("mousedown", closeMenu);
      document.removeEventListener("keydown", closeWithEscape);
      window.removeEventListener("resize", closeOnResize);
    };
  }, [menuId]);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2600);
    return () => window.clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    window.localStorage.setItem("sidebar-width", String(sidebarWidth));
  }, [sidebarWidth]);
  useEffect(() => {
    if (!resizing) return;
    const onMove = (event: PointerEvent) => {
      const width = Math.min(420, Math.max(180, event.clientX));
      setSidebarWidth(width);
    };
    const onUp = () => {
      setResizing(false);
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp, { once: true });
    return () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [resizing]);

  function startRename(conversation: Conversation) {
    setMenuId(null);
    setMenuPosition(null);
    setRenamingId(conversation.id);
    setRenameTitle(conversation.title || "");
  }

  async function saveRename(conversationId: string) {
    const title = renameTitle.trim();
    if (!title) return;
    try {
      await api.put(`/conversations/${conversationId}`, { title });
      setConversations((items) =>
        items.map((item) => (item.id === conversationId ? { ...item, title } : item)),
      );
      setRenamingId(null);
      setRenameTitle("");
      setToast({ text: "Chat renamed", tone: "success" });
    } catch {
      setToast({ text: "The chat name could not be changed", tone: "error" });
    }
  }

  async function deleteConversation(conversationId: string) {
    if (!window.confirm("Permanently delete this chat and all of its messages?")) return;
    setMenuId(null);
    setMenuPosition(null);
    setDeleting((ids) => [...ids, conversationId]);
    try {
      await api.del(`/conversations/${conversationId}`);
      setConversations((items) => items.filter((item) => item.id !== conversationId));
      if (location.pathname === `/chat/${conversationId}`) navigate("/chat");
      setToast({ text: "Chat deleted permanently", tone: "success" });
    } catch {
      setToast({ text: "The chat could not be deleted", tone: "error" });
    } finally {
      setDeleting((ids) => ids.filter((id) => id !== conversationId));
    }
  }

  const rail = (
    <nav aria-label="Main" className="flex h-full min-h-0 flex-col gap-3 overflow-hidden p-4">
      <div className="flex items-center gap-2">
        <button
          onClick={() => navigate("/chat")}
          className="flex min-h-11 w-full items-center gap-2 rounded bg-evergreen px-3 font-bold text-white hover:bg-evergreen-deep"
        >
          <Plus aria-hidden size={18} /> New question
        </button>
      </div>

      <section aria-labelledby="history-heading" className="min-h-0 flex-1 overflow-hidden">
        <h2 id="history-heading" className="mb-1 px-3 text-sm text-graphite">
          Your conversations
        </h2>
        {conversations.length === 0 ? (
          <p className="px-3 text-sm text-graphite">Questions you ask are kept here.</p>
        ) : (
          <ul className="space-y-0.5">
            {conversations.map((c) => (
                  <li key={c.id} data-chat-actions className="group relative grid min-h-9 min-w-0 grid-cols-[minmax(0,1fr)_38px] items-center gap-0.5">
                    {renamingId === c.id ? (
                      <form
                        className="flex min-w-0 flex-1 items-center gap-1"
                        onSubmit={(event) => {
                          event.preventDefault();
                          saveRename(c.id);
                        }}
                      >
                        <input
                          autoFocus
                          value={renameTitle}
                          maxLength={80}
                          onChange={(event) => setRenameTitle(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === "Escape") setRenamingId(null);
                          }}
                          aria-label="Chat name"
                          className="min-h-11 min-w-0 flex-1 rounded border border-evergreen bg-sheet px-2"
                        />
                        <button
                          type="submit"
                          disabled={!renameTitle.trim()}
                          className="min-h-11 rounded px-2 text-evergreen hover:bg-wash"
                        >
                          Save
                        </button>
                      </form>
                    ) : (
                      <NavLink to={`/chat/${c.id}`} className={linkClass + " min-h-9 min-w-0 px-2 py-1"} aria-label={c.title || "Untitled chat"}>
                        <span className="block min-w-0 truncate">{c.title || "Untitled"}</span>
                      </NavLink>
                    )}
                    {renamingId !== c.id && (
                      <button
                        type="button"
                        onClick={(event) => {
                          if (menuId === c.id) {
                            setMenuId(null);
                            setMenuPosition(null);
                            return;
                          }
                          const rect = event.currentTarget.getBoundingClientRect();
                          const menuWidth = 176;
                          const menuHeight = 92;
                          const preferredLeft = rect.right + 8;
                          const left = preferredLeft + menuWidth <= window.innerWidth
                            ? preferredLeft
                            : Math.max(8, rect.left - menuWidth - 8);
                          const top = rect.bottom + menuHeight <= window.innerHeight
                            ? rect.bottom + 4
                            : Math.max(8, rect.top - menuHeight - 4);
                          setMenuId(c.id);
                          setMenuPosition({ left, top });
                        }}
                        aria-label={`Open actions for ${c.title || "Untitled"}`}
                        aria-expanded={menuId === c.id}
                        className="grid size-[38px] place-items-center justify-self-end rounded-lg text-graphite opacity-0 transition-opacity hover:bg-wash hover:text-ink group-hover:opacity-100 focus:opacity-100"
                      >
                        <MoreHorizontal aria-hidden size={18} />
                      </button>
                    )}
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
    <>
      <div className="flex h-dvh">
        <aside
          className={`relative hidden shrink-0 border-r border-rule bg-paper md:block ${
            sidebarCollapsed ? "w-0 overflow-hidden border-r-0" : "overflow-visible"
          }`}
          style={sidebarCollapsed ? undefined : { width: sidebarWidth }}
        >
          {rail}
          {!sidebarCollapsed && (
            <div
              role="separator"
              aria-label="Resize sidebar"
              aria-orientation="vertical"
              onPointerDown={(event) => {
                event.preventDefault();
                setResizing(true);
              }}
              className={`sidebar-resize-handle absolute inset-y-0 -right-1 z-30 w-2 cursor-col-resize ${
                resizing ? "is-resizing" : ""
              }`}
              title="Drag to resize sidebar"
            />
          )}
        </aside>

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
          <div className="flex items-center gap-2 border-b border-rule px-2 py-1">
            <button
              onClick={() => setOpen(true)}
              aria-label="Open menu"
              className="grid size-11 place-items-center rounded hover:bg-wash md:hidden"
            >
              <Menu aria-hidden size={20} />
            </button>
            <span className="font-bold md:hidden">Knowledge Assistant</span>
          </div>
          <Outlet context={{ refreshConversations } satisfies ShellContext} />
        </div>
        <button
          type="button"
          onClick={() => {
            setMenuId(null);
            setMenuPosition(null);
            setSidebarCollapsed((collapsed) => !collapsed);
          }}
          aria-label={sidebarCollapsed ? "Open sidebar" : "Close sidebar"}
          aria-expanded={!sidebarCollapsed}
          title={sidebarCollapsed ? "Open sidebar" : "Close sidebar"}
          className="sidebar-toggle fixed z-[60] hidden size-11 place-items-center rounded-full border border-rule bg-sheet text-graphite shadow-lg transition-[left,transform,background-color,color] duration-200 hover:bg-evergreen hover:text-white md:grid"
          style={{ left: sidebarCollapsed ? 12 : sidebarWidth + 8, top: 12 }}
        >
          {sidebarCollapsed
            ? <PanelLeftOpen aria-hidden size={20} />
            : <PanelLeftClose aria-hidden size={20} />}
        </button>
      </div>
      {menuId && menuPosition && (() => {
        const conversation = conversations.find((item) => item.id === menuId);
        if (!conversation) return null;
        return (
          <div
            data-chat-actions-menu
            className="chat-actions-menu fixed z-[65] w-44 rounded-xl border border-rule bg-sheet p-1 shadow-xl"
            style={{ left: menuPosition.left, top: menuPosition.top }}
          >
            <button
              type="button"
              onClick={() => startRename(conversation)}
              className="flex min-h-10 w-full items-center gap-2 rounded px-3 text-left text-ink hover:bg-wash"
            >
              <Pencil aria-hidden size={16} /> Rename
            </button>
            <button
              type="button"
              onClick={() => deleteConversation(conversation.id)}
              disabled={deleting.includes(conversation.id)}
              className="flex min-h-10 w-full items-center gap-2 rounded px-3 text-left text-danger hover:bg-danger-wash disabled:opacity-40"
            >
              <Trash2 aria-hidden size={16} /> Delete
            </button>
          </div>
        );
      })()}
      {toast && (
        <div
          role="status"
          aria-live="polite"
          className={`chat-toast fixed bottom-5 left-1/2 z-[70] flex -translate-x-1/2 items-center gap-2 rounded-full px-4 py-3 text-sm font-bold shadow-xl ${
            toast.tone === "success"
              ? "bg-evergreen text-white"
              : "border border-danger/30 bg-danger-wash text-danger"
          }`}
        >
          {toast.tone === "success" && <Check aria-hidden size={17} />}
          {toast.text}
        </div>
      )}
    </>
  );
}
