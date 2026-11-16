"use client";
import { useCallback, useEffect, useRef, useState } from "react";

/** Fetch on mount and whenever `key` changes; `reload()` refetches (keeps showing old data meanwhile). */
export function useAsync<T>(fn: () => Promise<T>, deps: readonly unknown[] = []) {
  const [state, set] = useState<{ data?: T; error?: Error; loading: boolean }>({ loading: true });
  const fnRef = useRef(fn);
  useEffect(() => { fnRef.current = fn; });
  const [tick, setTick] = useState(0);
  const key = JSON.stringify(deps);

  useEffect(() => {
    let live = true;
    fnRef.current().then(
      (data) => live && set({ data, loading: false }),
      (error) => live && set((s) => ({ data: s.data, error, loading: false })),
    );
    return () => { live = false; };
  }, [key, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}
