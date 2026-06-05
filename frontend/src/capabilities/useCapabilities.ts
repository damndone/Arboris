import { useCallback, useEffect, useRef, useState } from "react";
import { fetchCapabilities } from "./api";
import type { Capabilities } from "./types";

export interface UseCapabilitiesResult {
  data: Capabilities | null;
  loading: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useCapabilities(): UseCapabilitiesResult {
  const [data, setData] = useState<Capabilities | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);
  const mountedRef = useRef(true);

  const refetch = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const payload = await fetchCapabilities();
        if (cancelled || !mountedRef.current) return;
        setData(payload);
        setError(null);
      } catch (err) {
        if (cancelled || !mountedRef.current) return;
        setData(null);
        setError(err instanceof Error ? err : new Error(String(err)));
      } finally {
        if (!cancelled && mountedRef.current) {
          setLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [tick]);

  return { data, loading, error, refetch };
}
