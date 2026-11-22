import { useEffect, useState } from "react";

/**
 * A string state remembered in this browser (localStorage), e.g. the last tab or a setting. Storage can be blocked
 * (private windows, previews) or hold an out-of-date value: then ``initial`` is used, and changes last for the visit.
 * ``allowed`` limits it to known values.
 */
export function usePersistentState<T extends string>(key: string, initial: T, allowed?: readonly T[]): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const v = localStorage.getItem(key) as T | null;
      return v !== null && (!allowed || allowed.includes(v)) ? v : initial;
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try { localStorage.setItem(key, value); } catch { /* kept for this visit only */ }
  }, [key, value]);
  return [value, setValue];
}

/** Settings saved under the project's old name ("whips.mySeat" etc.) move to their current keys ("dash."), once. */
export function migrateStoredSettings(store: Pick<Storage, "getItem" | "setItem" | "removeItem" | "key" | "length"> = localStorage): void {
  try {
    const old = Array.from({ length: store.length }, (_, i) => store.key(i)).filter((k): k is string => !!k?.startsWith("whips."));
    for (const k of old) {
      const to = `dash.${k.slice("whips.".length)}`;
      const v = store.getItem(k);
      if (v !== null && store.getItem(to) === null) store.setItem(to, v);
      store.removeItem(k);
    }
  } catch { /* storage blocked: nothing to move */ }
}
