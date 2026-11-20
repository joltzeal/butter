import { useCallback, useEffect, useRef } from "react";

/** Trailing-edge debounce that also flushes on unmount. */
export function useDebouncedCallback<A extends unknown[]>(
  fn: (...args: A) => void | Promise<void>,
  delay = 300,
) {
  const timer = useRef<number | null>(null);
  const pending = useRef<A | null>(null);
  const latest = useRef(fn);
  latest.current = fn;

  const flush = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    const args = pending.current;
    pending.current = null;
    if (args) void latest.current(...args);
  }, []);

  const run = useCallback(
    (...args: A) => {
      pending.current = args;
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        timer.current = null;
        const call = pending.current;
        pending.current = null;
        if (call) void latest.current(...call);
      }, delay);
    },
    [delay],
  );

  useEffect(
    () => () => {
      flush();
    },
    [flush],
  );

  return { run, flush };
}
