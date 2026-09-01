import { useCallback, useEffect, useRef, useState } from "../react-shim.js";

/**
 * Runs an abortable async fetcher and exposes {data, status, error, reload}.
 * `fetcher` receives an AbortSignal and must return a Promise. Re-runs
 * whenever `deps` change; stale responses (superseded by a newer call or an
 * unmount) are ignored to avoid race conditions.
 */
export function useAsync(fetcher, deps = []) {
  const [state, setState] = useState({ status: "loading", data: null, error: null });
  const requestId = useRef(0);

  const run = useCallback(() => {
    const id = ++requestId.current;
    const controller = new AbortController();
    setState((prev) => ({ ...prev, status: "loading", error: null }));
    Promise.resolve()
      .then(() => fetcher(controller.signal))
      .then((data) => {
        if (requestId.current !== id) return;
        setState({ status: "success", data, error: null });
      })
      .catch((err) => {
        if (err && err.name === "AbortError") return;
        if (requestId.current !== id) return;
        setState({ status: "error", data: null, error: err });
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => run(), [run]);

  return { ...state, reload: run, isLoading: state.status === "loading" };
}

/** Simple debounce hook for search inputs. */
export function useDebouncedValue(value, delayMs = 300) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
