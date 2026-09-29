import type { ReactNode } from "react";
import type { Citation } from "../api";

export const sourceColor = (n: number) => `var(--color-src-${((n - 1) % 6) + 1})`;

export function SourceChip({ n, onOpen, label }: { n: number; onOpen?: () => void; label?: string }) {
  const style = { backgroundColor: sourceColor(n) };
  const cls =
    "mx-0.5 inline-grid h-5 min-w-5 place-items-center rounded-sm px-1 align-[0.12em] font-sans text-xs font-bold text-white";
  if (!onOpen) return <span className={cls + " opacity-60"} style={style} aria-label={`source ${n}`}>{n}</span>;
  return (
    // The visible chip is small; the ::before pseudo-element widens the hit target to 44px without moving text.
    <button
      type="button"
      onClick={onOpen}
      className={cls + " relative before:absolute before:-inset-3 before:content-['']"}
      style={style}
      aria-label={label ?? `Open source ${n}`}
    >
      {n}
    </button>
  );
}

function inline(text: string, citations: Map<number, Citation>, open: (c: Citation) => void, key: string): ReactNode[] {
  return text.split(/(\[\d+\]|\*\*[^*]+\*\*)/g).map((part, i) => {
    const k = `${key}-${i}`;
    const cite = /^\[(\d+)\]$/.exec(part);
    if (cite) {
      const n = Number(cite[1]);
      const c = citations.get(n);
      return <SourceChip key={k} n={n} onOpen={c ? () => open(c) : undefined} label={c ? `Open source ${n}: ${c.title}` : undefined} />;
    }
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={k}>{part.slice(2, -2)}</strong>;
    return part;
  });
}

/** Renders model output: paragraphs, bullet lists, bold, and [n] markers as source chips. */
export function AnswerText({
  text,
  citations,
  onOpen,
  streaming,
}: {
  text: string;
  citations: Citation[];
  onOpen: (c: Citation) => void;
  streaming?: boolean;
}) {
  const byN = new Map(citations.map((c) => [c.n, c]));
  const blocks: ReactNode[] = [];
  let items: string[] = [];
  const flush = () => {
    if (items.length) {
      const k = `ul-${blocks.length}`;
      blocks.push(
        <ul key={k}>
          {items.map((t, i) => (
            <li key={i}>{inline(t, byN, onOpen, `${k}-${i}`)}</li>
          ))}
        </ul>,
      );
      items = [];
    }
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const bullet = /^([-*•]|\d+[.)])\s+(.*)$/.exec(line);
    if (bullet) {
      items.push(bullet[2]);
    } else if (line) {
      flush();
      const heading = /^#{1,6}\s+(.*)$/.exec(line);
      const k = `p-${blocks.length}`;
      blocks.push(heading ? <p key={k}><strong>{heading[1]}</strong></p> : <p key={k}>{inline(line, byN, onOpen, k)}</p>);
    } else {
      flush();
    }
  }
  flush();
  return <div className={`prose-doc ${streaming ? "streaming" : ""}`}>{blocks.length ? blocks : <p />}</div>;
}
