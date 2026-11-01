import { useCallback, useEffect, useState } from "react";

import { ApiError } from "./client";

export interface Loadable<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
  setData: (data: T) => void;
}

/** Charge une ressource et expose les états chargement / erreur / données. */
export function useApi<T>(load: () => Promise<T>, deps: unknown[] = []): Loadable<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    load()
      .then((value) => alive && (setData(value), setError(null)))
      .catch((e: unknown) => alive && setError(e instanceof ApiError ? e : new ApiError(0, { message: String(e) })))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload, setData };
}
