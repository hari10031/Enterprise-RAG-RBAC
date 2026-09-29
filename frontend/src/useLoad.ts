import { useCallback, useEffect, useState } from "react";
import { api, type Group } from "./api";

/** GET a path; `reload` refetches after a change. */
export function useLoad<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    api
      .get<T>(path)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(e.message || "Could not load this page."));
  }, [path]);
  useEffect(reload, [reload]);
  return { data, error, reload };
}

export function useGroups() {
  const { data, reload } = useLoad<Group[]>("/groups");
  const groups = data ?? [];
  return { groups, names: new Map(groups.map((g) => [g.id, g.name])), reload };
}
