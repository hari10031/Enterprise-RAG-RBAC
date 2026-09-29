import type { ButtonHTMLAttributes, ReactNode } from "react";

export const inputClass =
  "block w-full min-h-11 rounded border border-rule bg-sheet px-3 py-2 text-ink placeholder:text-graphite/70 " +
  "focus:border-evergreen focus:outline-none focus-visible:outline-2 focus-visible:outline-evergreen";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "quiet" | "danger" };

export function Button({ variant = "primary", className = "", ...props }: ButtonProps) {
  const look = {
    primary: "bg-evergreen text-white hover:bg-evergreen-deep disabled:bg-graphite/40",
    quiet: "border border-rule bg-sheet text-ink hover:bg-wash disabled:text-graphite/60",
    danger: "border border-danger/40 bg-sheet text-danger hover:bg-danger-wash disabled:opacity-50",
  }[variant];
  return (
    <button
      {...props}
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded px-4 font-bold transition-colors duration-150 disabled:cursor-not-allowed ${look} ${className}`}
    />
  );
}

export function Field({ label, htmlFor, hint, children }: { label: string; htmlFor: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={htmlFor} className="mb-1 block font-bold">
        {label}
      </label>
      {children}
      {hint && <p className="mt-1 text-sm text-graphite">{hint}</p>}
    </div>
  );
}

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 border-b border-rule pb-4">
      <h1 className="text-2xl font-bold">{title}</h1>
      {children && <div className="flex flex-wrap gap-2">{children}</div>}
    </header>
  );
}

export function Notice({ tone, children }: { tone: "error" | "info"; children: ReactNode }) {
  const look = tone === "error" ? "border-danger/30 bg-danger-wash text-danger" : "border-rule bg-wash text-ink";
  return (
    <p role={tone === "error" ? "alert" : "status"} className={`rounded border px-3 py-2 text-sm ${look}`}>
      {children}
    </p>
  );
}

/** Group names as quiet pills; unknown ids (deleted groups) show as such rather than disappearing. */
export function GroupList({ ids, names }: { ids: string[]; names: Map<string, string> }) {
  return (
    <span className="flex flex-wrap gap-1">
      {ids.map((id) => (
        <span key={id} className="rounded-full bg-wash px-2 py-0.5 text-sm whitespace-nowrap">
          {names.get(id) ?? "deleted group"}
        </span>
      ))}
    </span>
  );
}

export function GroupPicker({
  groups,
  selected,
  onChange,
  legend,
}: {
  groups: { id: string; name: string }[];
  selected: string[];
  onChange: (ids: string[]) => void;
  legend: string;
}) {
  return (
    <fieldset>
      <legend className="mb-1 font-bold">{legend}</legend>
      <div className="flex flex-wrap gap-2">
        {groups.map((g) => {
          const on = selected.includes(g.id);
          return (
            <label
              key={g.id}
              className={`inline-flex min-h-11 items-center gap-2 rounded border px-3 ${on ? "border-evergreen bg-evergreen-wash" : "border-rule bg-sheet"}`}
            >
              <input
                type="checkbox"
                checked={on}
                onChange={() => onChange(on ? selected.filter((x) => x !== g.id) : [...selected, g.id])}
                className="size-4 accent-evergreen"
              />
              {g.name}
            </label>
          );
        })}
      </div>
      <p className="mt-1 text-sm text-graphite">With no group ticked, only admins can see it.</p>
    </fieldset>
  );
}
