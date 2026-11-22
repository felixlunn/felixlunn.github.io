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
