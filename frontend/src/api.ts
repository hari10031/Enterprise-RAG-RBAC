// Thin client for /api/v1. Every call sends the session cookie; a 401 sends the user back to sign in.

export type Group = { id: string; name: string; description?: string | null };
export type Me = { id: string; email: string; display_name: string; groups: Group[]; is_admin: boolean };
export type Citation = { n: number; chunk_id: string; document_id: string; title: string; page: number | null };
export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  flags: string[];
  created_at?: string;
};
export type Conversation = { id: string; title: string | null; created_at: string };
export type Passage = {
  id: string;
  document_id: string;
  text: string;
  heading_path: string | null;
  page: number | null;
  title: string;
};
export type DocumentRow = {
  id: string;
  source: "upload" | "folder";
  folder_id: string | null;
  path: string | null;
  title: string;
  mime_type: string;
  size_bytes: number;
  status: string;
  indexed_at: string | null;
  acl_groups: string[];
};
export type UserRow = {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  locked_until: string | null;
  group_ids: string[];
};
export type Folder = { id: string; path: string; acl_groups: string[]; last_scanned_at: string | null };

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const res = await fetch(`/api/v1${path}`, init);
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith("/auth/login")) onUnauthorized();
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : (data.detail?.[0]?.msg ?? detail);
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

export type StreamEvent =
  | { event: "meta"; data: { conversation_id: string; message_id: string } }
  | { event: "queued"; data: Record<string, never> }
  | { event: "token"; data: { text: string } }
  | { event: "citations"; data: { citations: Citation[]; flags: string[] } }
  | { event: "done"; data: { message_id: string; flags: string[] } }
  | { event: "error"; data: { message: string } };

/** POST /query and yield its server-sent events. EventSource only supports GET, so this parses the stream itself. */
export async function* streamQuery(
  question: string,
  conversationId: string | null,
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const res = await fetch("/api/v1/query", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ question, conversation_id: conversationId }),
    signal,
  });
  if (!res.ok || !res.body) {
    if (res.status === 401) onUnauthorized();
    let detail = `The question could not be sent (${res.status}).`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += value;
    let end: number;
    while ((end = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      yield { event, data: data ? JSON.parse(data) : {} } as StreamEvent;
    }
  }
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function formatWhen(iso: string | null): string {
  if (!iso) return "Never";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
