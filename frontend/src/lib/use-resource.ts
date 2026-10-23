"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api/client";

export interface Resource<T> {
  data: T | undefined;
  error: ApiError | Error | null;
  loading: boolean;
  reload: () => Promise<void>;
}

/**
 * Minimal data-fetching hook: loads on mount and whenever `key` changes,
 * ignores responses from superseded requests, and exposes `reload` for after mutations.
 */
export function useResource<T>(key: string | null, fetcher: (signal: AbortSignal) => Promise<T>) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [loading, setLoading] = useState(key !== null);
  const fetcherRef = useRef(fetcher);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const load = useCallback(async () => {
    if (key === null) return;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    try {
      const result = await fetcherRef.current(controller.signal);
      if (!controller.signal.aborted) {
        setData(result);
        setError(null);
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(err instanceof Error ? err : new Error(String(err)));
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [key]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetching on key change is the purpose of this hook
    void load();
    return () => controllerRef.current?.abort();
  }, [load]);

  return { data, error, loading, reload: load } satisfies Resource<T>;
}
