import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Api, resolveBaseUrl, type EventEnvelope } from "../api/client";

export type ConnectionState = "boot" | "online" | "offline";

interface RealtimeValue {
  state: ConnectionState;
  base: string;
  api: Api | null;
  error: string | null;
  events: EventEnvelope[];
  lastEvent: EventEnvelope | null;
  reconnect: () => void;
  /** True once a connection has succeeded; the boot overlay stops after that. */
  ready: boolean;
}

const RealtimeContext = createContext<RealtimeValue | null>(null);

const MAX_EVENTS = 400;

export function RealtimeProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<ConnectionState>("boot");
  const [base, setBase] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [lastEvent, setLastEvent] = useState<EventEnvelope | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  // Once a connection has succeeded the app is usable, so the overlay only has
  // to cover the very first attempt.
  const everOnlineRef = useRef(false);
  const [ready, setReady] = useState(false);
  // Boot is single-flight: StrictMode's double mount must not run two 45s
  // resolve loops and two health probes.
  const bootingRef = useRef<AbortController | null>(null);
  const retryTimerRef = useRef<number | null>(null);
  const closedRef = useRef(false);

  const api = useMemo(() => (base ? new Api(base) : null), [base]);

  const seqRef = useRef(0);
  const push = useCallback((envelope: EventEnvelope) => {
    seqRef.current += 1;
    const stamped = { ...envelope, id: seqRef.current };
    setLastEvent(stamped);
    setEvents((prev) => {
      const next = [...prev, stamped];
      return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next;
    });
  }, []);

  const clearRetry = () => {
    if (retryTimerRef.current !== null) {
      window.clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  };

  const connect = useCallback(
    (url: string) => {
      closedRef.current = false;
      clearRetry();
      socketRef.current?.close();
      const socket = new WebSocket(url);
      socketRef.current = socket;

      socket.onopen = () => {
        retryRef.current = 0;
        everOnlineRef.current = true;
        setReady(true);
        setState("online");
        setError(null);
      };

      socket.onmessage = (message) => {
        try {
          const envelope = JSON.parse(message.data) as EventEnvelope;
          if (envelope.event === "pong" || envelope.event === "hello") return;
          push(envelope);
        } catch {
          /* ignore malformed frames */
        }
      };

      socket.onclose = () => {
        if (closedRef.current) return;
        // A stale socket (StrictMode remount, or a reconnect that replaced it)
        // must not drag the shared state to offline — that is what made the boot
        // overlay strobe over a perfectly working UI.
        if (socketRef.current !== socket) return;
        setState("offline");
        const delay = Math.min(8000, 500 * 2 ** retryRef.current);
        retryRef.current += 1;
        clearRetry();
        retryTimerRef.current = window.setTimeout(() => {
          retryTimerRef.current = null;
          if (!closedRef.current) connect(url);
        }, delay);
      };

      socket.onerror = () => {
        setError("实时通道断开，正在重连…");
      };
    },
    [push],
  );

  const boot = useCallback(async () => {
    bootingRef.current?.abort();
    const controller = new AbortController();
    bootingRef.current = controller;
    setState("boot");
    setError(null);
    try {
      const resolved = await resolveBaseUrl(controller.signal);
      const probe = new Api(resolved);
      await probe.health(controller.signal);
      if (controller.signal.aborted) return;
      setBase(resolved);
      connect(probe.wsUrl());
    } catch (err) {
      if (controller.signal.aborted) return;
      const aborted = err instanceof DOMException && err.name === "AbortError";
      if (aborted) return;
      setState("offline");
      setError(err instanceof Error ? err.message : "无法连接后端");
    } finally {
      if (bootingRef.current === controller) bootingRef.current = null;
    }
  }, [connect]);

  useEffect(() => {
    void boot();
    return () => {
      closedRef.current = true;
      bootingRef.current?.abort();
      clearRetry();
      socketRef.current?.close();
    };
  }, [boot]);

  const value = useMemo<RealtimeValue>(
    () => ({
      state,
      base,
      api,
      error,
      events,
      lastEvent,
      ready,
      reconnect: () => {
        closedRef.current = true;
        clearRetry();
        socketRef.current?.close();
        void boot();
      },
    }),
    [state, base, api, error, events, lastEvent, ready, boot],
  );

  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>;
}

export function useRealtime(): RealtimeValue {
  const ctx = useContext(RealtimeContext);
  if (!ctx) throw new Error("useRealtime must be used inside RealtimeProvider");
  return ctx;
}

/** Nullable variant so views can render a boot state without throwing. */
export function useOptionalApi(): Api | null {
  return useRealtime().api;
}

export function useApi(): Api {
  const { api } = useRealtime();
  if (!api) throw new Error("api not ready");
  return api;
}
