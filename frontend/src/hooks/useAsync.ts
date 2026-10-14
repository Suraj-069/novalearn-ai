import { useCallback, useEffect, useRef, useState } from "react";

interface Options<T> {
  /** Re-fetch every `pollMs` while `pollWhile(data)` is true. */
  pollMs?: number;
  pollWhile?: (data: T) => boolean;
}

/** Minimal data-loading hook: { data, error, loading, reload }. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[], opts: Options<T> = {}) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const optsRef = useRef(opts);
  optsRef.current = opts;
  const alive = useRef(true);

  const load = useCallback(async (silent: boolean) => {
    if (!silent) setLoading(true);
    try {
      const result = await fnRef.current();
      if (alive.current) { setData(result); setError(null); }
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      if (alive.current && !silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void load(false);
    return () => { alive.current = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    const { pollMs, pollWhile } = optsRef.current;
    if (!pollMs || !pollWhile || data === null || !pollWhile(data)) return;
    const t = setTimeout(() => void load(true), pollMs);
    return () => clearTimeout(t);
  }, [data, load]);

  return { data, error, loading, reload: () => load(false), setData };
}
