import { ArrowUp, Square, ThumbsDown, ThumbsUp } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useNavigate, useOutletContext, useParams } from "react-router-dom";
import { api, ApiError, streamQuery, type Citation, type Message } from "../api";
import { useAuth } from "../auth";
import { AnswerText, sourceColor } from "../components/Answer";
import type { ShellContext } from "../components/Shell";
import { SourcePanel } from "../components/SourcePanel";

const MAX_QUESTION = 2000;

type Live = {
  question: string;
  text: string;
  citations: Citation[];
  flags: string[];
  messageId: string | null;
  waiting: boolean; // the model is busy with other people's questions
  done: boolean;
};

export function Chat() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const { me } = useAuth();
  const { refreshConversations } = useOutletContext<ShellContext>();

  const [messages, setMessages] = useState<Message[]>([]);
  const [live, setLive] = useState<Live | null>(null);
  const [question, setQuestion] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [source, setSource] = useState<Citation | null>(null);
  const createdHere = useRef<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const busy = live !== null && !live.done;

  // Load history, except for a conversation this page just created: its turns are already on screen.
  useEffect(() => {
    setSource(null);
    setLoadError(null);
    if (!conversationId) {
      createdHere.current = null;
      abort.current?.abort();
      setMessages([]);
      setLive(null);
      return;
    }
    if (conversationId === createdHere.current) return;
    createdHere.current = null;
    setLive(null);
    api
      .get<Message[]>(`/conversations/${conversationId}/messages`)
      .then(setMessages)
      .catch(() => setLoadError("This conversation could not be opened. It may belong to another account."));
  }, [conversationId]);

  useEffect(() => () => abort.current?.abort(), []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [messages.length, live?.text, live?.done]);

  async function ask(e?: FormEvent) {
    e?.preventDefault();
    const q = question.trim();
    if (!q || busy) return;
    setError(null);
    setQuestion("");
    // Finished live turn moves into history before the next question starts.
    if (live?.done) setMessages((m) => [...m, ...liveToMessages(live)]);
    setLive({ question: q, text: "", citations: [], flags: [], messageId: null, waiting: false, done: false });

    const ctrl = new AbortController();
    abort.current = ctrl;
    let waitTimer: number | undefined;
    try {
      for await (const ev of streamQuery(q, conversationId ?? null, ctrl.signal)) {
        if (ev.event === "meta") {
          setLive((l) => l && { ...l, messageId: ev.data.message_id });
          if (!conversationId) {
            createdHere.current = ev.data.conversation_id;
            navigate(`/chat/${ev.data.conversation_id}`, { replace: true });
            refreshConversations();
          }
        } else if (ev.event === "queued") {
          // Only say so if the wait is noticeable.
          waitTimer = window.setTimeout(() => setLive((l) => l && { ...l, waiting: true }), 2000);
        } else if (ev.event === "token") {
          window.clearTimeout(waitTimer);
          setLive((l) => l && { ...l, waiting: false, text: l.text + ev.data.text });
        } else if (ev.event === "citations") {
          // The server drops markers that point past the passages it sent; mirror that on screen.
          const valid = new Set(ev.data.citations.map((c) => c.n));
          const notFound = ev.data.flags.includes("not_found");
          setLive(
            (l) =>
              l && {
                ...l,
                citations: ev.data.citations,
                flags: ev.data.flags,
                text: notFound ? l.text : l.text.replace(/\[(\d+)\]/g, (m, n) => (valid.has(Number(n)) ? m : "")),
              },
          );
        } else if (ev.event === "done") {
          setLive((l) => l && { ...l, done: true });
        } else if (ev.event === "error") {
          setError(ev.data.message || "The answer could not be finished. Ask again, or rephrase the question.");
          setLive((l) => l && { ...l, done: true, flags: [...l.flags, "error"] });
        }
      }
    } catch (err) {
      if (ctrl.signal.aborted) return;
      setError(
        err instanceof ApiError && err.status === 429
          ? "You have asked 10 questions in the last minute. Wait a moment, then ask again."
          : err instanceof ApiError
            ? err.message
            : "The server could not be reached. Check your connection and ask again.",
      );
      setLive((l) => l && { ...l, done: true, flags: [...l.flags, "error"] });
      setQuestion(q);
    } finally {
      window.clearTimeout(waitTimer);
    }
  }

  async function stop() {
    if (live?.messageId) await api.post(`/query/${live.messageId}/stop`).catch(() => {});
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      ask();
    }
  }

  const closeSource = useCallback(() => setSource(null), []);
  const empty = messages.length === 0 && !live && !loadError;

  return (
    <div className="flex min-h-0 flex-1">
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[44rem] px-4 py-8 md:px-8">
            {loadError && <p className="text-danger">{loadError}</p>}
            {empty && (
              <div className="pt-[12vh]">
                <h1 className="font-serif text-[2rem] leading-tight font-semibold tracking-tight">What do you need to find?</h1>
                <p className="mt-3 max-w-[52ch] text-graphite">
                  Ask in your own words. Naming a document, team, form or error code helps. Every answer links each
                  claim to the passage it came from.
                </p>
              </div>
            )}
            <ol className="space-y-10">
              {messages.map((m, i) =>
                m.role === "user" ? (
                  <li key={m.id ?? i}>
                    <Question text={m.content} />
                  </li>
                ) : (
                  <li key={m.id ?? i}>
                    <AnswerBlock
                      text={m.content}
                      citations={m.citations}
                      flags={m.flags}
                      messageId={m.id}
                      onOpen={setSource}
                    />
                  </li>
                ),
              )}
              {live && (
                <>
                  <li>
                    <Question text={live.question} />
                  </li>
                  <li aria-live="polite" aria-busy={!live.done}>
                    {live.waiting && !live.text && (
                      <p className="text-graphite">Waiting for the model. Other questions are ahead of yours.</p>
                    )}
                    {!live.waiting && !live.text && !live.done && <p className="text-graphite">Searching your documents…</p>}
                    {(live.text || live.done) && (
                      <AnswerBlock
                        text={live.text}
                        citations={live.citations}
                        flags={live.flags}
                        messageId={live.done ? live.messageId : null}
                        onOpen={setSource}
                        streaming={!live.done}
                      />
                    )}
                  </li>
                </>
              )}
            </ol>
            <div ref={bottom} />
          </div>
        </div>

        <form onSubmit={ask} className="border-t border-rule bg-paper px-4 pt-3 pb-4 md:px-8">
          <div className="mx-auto max-w-[44rem]">
            {error && (
              <p role="alert" className="mb-2 text-sm text-danger">
                {error}
              </p>
            )}
            <div className="flex items-end gap-2 rounded border border-rule bg-sheet p-2 focus-within:border-evergreen">
              <label htmlFor="question" className="sr-only">
                Your question
              </label>
              <textarea
                id="question"
                rows={1}
                maxLength={MAX_QUESTION}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder="Ask about a policy, process or document"
                className="field-sizing-content max-h-48 min-h-11 flex-1 resize-none bg-transparent px-2 py-2.5 focus:outline-none"
              />
              {busy ? (
                <button
                  type="button"
                  onClick={stop}
                  className="grid size-11 shrink-0 place-items-center rounded border border-rule hover:bg-wash"
                  aria-label="Stop answer"
                >
                  <Square aria-hidden size={16} fill="currentColor" />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!question.trim()}
                  className="grid size-11 shrink-0 place-items-center rounded bg-evergreen text-white hover:bg-evergreen-deep disabled:bg-graphite/30"
                  aria-label="Ask"
                >
                  <ArrowUp aria-hidden size={20} />
                </button>
              )}
            </div>
            <AccessLens groups={me?.groups.map((g) => g.name) ?? []} />
          </div>
        </form>
      </main>
      {source && <SourcePanel citation={source} onClose={closeSource} />}
    </div>
  );
}

function liveToMessages(l: Live): Message[] {
  return [
    { id: `q-${l.messageId}`, role: "user", content: l.question, citations: [], flags: [] },
    { id: l.messageId ?? `a-${Date.now()}`, role: "assistant", content: l.text, citations: l.citations, flags: l.flags },
  ];
}

/** The groups this answer may draw on. The one piece of chrome that is always visible. */
function AccessLens({ groups }: { groups: string[] }) {
  return (
    <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-graphite">
      <span>Answers use documents shared with</span>
      {groups.length ? (
        groups.map((g) => (
          <span key={g} className="rounded-full border border-rule bg-sheet px-2 text-ink">
            {g}
          </span>
        ))
      ) : (
        <span className="text-amber">none of your groups yet. Ask an administrator to add you to one.</span>
      )}
    </p>
  );
}

function Question({ text }: { text: string }) {
  return <p className="border-l-2 border-ink pl-3 text-lg font-bold whitespace-pre-line">{text}</p>;
}

function AnswerBlock({
  text,
  citations,
  flags,
  messageId,
  onOpen,
  streaming,
}: {
  text: string;
  citations: Citation[];
  flags: string[];
  messageId: string | null;
  onOpen: (c: Citation) => void;
  streaming?: boolean;
}) {
  const notFound = flags.includes("not_found");
  return (
    <article>
      <div className={notFound ? "text-graphite" : ""}>
        <AnswerText text={text} citations={citations} onOpen={onOpen} streaming={streaming} />
      </div>
      {notFound && (
        <p className="mt-2 text-sm text-graphite">
          Try other words, or name the document or team. If the file should exist, an administrator can check it is
          indexed and shared with your groups.
        </p>
      )}
      {flags.includes("low_grounding") && (
        <p className="mt-3 rounded border border-amber/30 bg-amber-wash px-3 py-2 text-sm text-amber">
          Some statements in this answer have no source. Check them against the documents before relying on them.
        </p>
      )}
      {flags.includes("stopped") && <p className="mt-2 text-sm text-graphite">You stopped this answer.</p>}

      {citations.length > 0 && (
        <div className="mt-4">
          <h3 className="text-sm text-graphite">Sources</h3>
          <ul className="mt-1 space-y-0.5">
            {citations.map((c) => (
              <li key={c.n}>
                <button
                  onClick={() => onOpen(c)}
                  className="flex min-h-11 w-full items-center gap-3 rounded px-2 text-left hover:bg-wash"
                >
                  <span
                    className="grid h-5 min-w-5 place-items-center rounded-sm text-xs font-bold text-white"
                    style={{ backgroundColor: sourceColor(c.n) }}
                    aria-hidden
                  >
                    {c.n}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{c.title}</span>
                  {c.page && <span className="shrink-0 text-sm text-graphite">page {c.page}</span>}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {messageId && !streaming && !messageId.startsWith("a-") && <Feedback messageId={messageId} />}
    </article>
  );
}

function Feedback({ messageId }: { messageId: string }) {
  const [rating, setRating] = useState<1 | -1 | null>(null);
  const [failed, setFailed] = useState(false);
  async function rate(r: 1 | -1) {
    const next = rating === r ? null : r;
    if (next === null) return;
    setRating(next);
    setFailed(false);
    try {
      await api.post("/feedback", { message_id: messageId, rating: next });
    } catch {
      setFailed(true);
      setRating(null);
    }
  }
  const cls = (on: boolean) =>
    `grid size-11 place-items-center rounded ${on ? "bg-evergreen-wash text-evergreen" : "text-graphite hover:bg-wash hover:text-ink"}`;
  return (
    <div className="mt-2 flex items-center gap-1">
      <button onClick={() => rate(1)} aria-pressed={rating === 1} aria-label="Helpful answer" className={cls(rating === 1)}>
        <ThumbsUp aria-hidden size={18} />
      </button>
      <button onClick={() => rate(-1)} aria-pressed={rating === -1} aria-label="Unhelpful answer" className={cls(rating === -1)}>
        <ThumbsDown aria-hidden size={18} />
      </button>
      <span role="status" className="text-sm text-graphite">
        {failed ? "Your rating was not saved. Try again." : rating ? "Thanks, your rating is saved." : ""}
      </span>
    </div>
  );
}
