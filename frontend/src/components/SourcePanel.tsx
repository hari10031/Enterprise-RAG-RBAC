import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, ApiError, type Citation, type Passage } from "../api";
import { sourceColor } from "./Answer";

/** The cited passage, loaded fresh each time so a revoked permission takes effect immediately. */
export function SourcePanel({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  const [passage, setPassage] = useState<Passage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    setPassage(null);
    setError(null);
    api
      .get<Passage>(`/chunks/${citation.chunk_id}`)
      .then(setPassage)
      .catch((e) =>
        setError(
          e instanceof ApiError && e.status === 404
            ? "This passage is no longer available to you. The document may have been re-indexed or your access changed."
            : "The passage could not be loaded. Try opening it again.",
        ),
      );
    heading.current?.focus();
  }, [citation.chunk_id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const color = sourceColor(citation.n);
  return (
    <aside
      aria-labelledby="source-title"
      className="panel-enter fixed inset-0 z-30 flex flex-col bg-sheet lg:static lg:inset-auto lg:w-[26rem] lg:shrink-0 lg:border-l lg:border-rule"
    >
      <div className="flex items-start gap-3 border-b border-rule p-4">
        <span
          className="mt-0.5 grid h-7 min-w-7 place-items-center rounded-sm font-bold text-white"
          style={{ backgroundColor: color }}
          aria-hidden
        >
          {citation.n}
        </span>
        <div className="min-w-0 flex-1">
          <h2 id="source-title" ref={heading} tabIndex={-1} className="font-bold break-words focus:outline-none">
            {citation.title}
          </h2>
          <p className="text-sm text-graphite">
            Source {citation.n}
            {citation.page ? `, page ${citation.page}` : ""}
          </p>
        </div>
        <button onClick={onClose} aria-label="Close source" className="-m-2 grid size-11 place-items-center rounded hover:bg-wash">
          <X aria-hidden size={20} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4" aria-live="polite">
        {error && <p className="text-danger">{error}</p>}
        {!error && !passage && <p className="text-graphite">Loading passage…</p>}
        {passage && (
          <>
            {passage.heading_path && <p className="mb-3 text-sm text-graphite">{passage.heading_path.split(" > ").join(" / ")}</p>}
            <blockquote className="prose-doc border-l-4 pl-4 whitespace-pre-line" style={{ borderColor: color }}>
              {passage.text}
            </blockquote>
          </>
        )}
      </div>
    </aside>
  );
}
