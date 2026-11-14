import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
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
  const closedRef = useRef(false);

  const api = useMemo(() => (base ? new Api(base) : null), [base]);

  const push = useCallback((envelope: EventEnvelope) => {
    setLastEvent(envelope);
    setEvents((prev) => {
      const next = [...prev, envelope];
      return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next;
    });
  }, []);

  const connect = useCallback(
    (url: string) => {
      closedRef.current = false;
      socketRef.current?.close();
      const socket = new WebSocket(url);
      socketRef.current = socket;

      socket.onopen = () => {
        retryRef.current = 0;
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
        setState("offline");
        const delay = Math.min(8000, 500 * 2 ** retryRef.current);
        retryRef.current += 1;
        window.setTimeout(() => {
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
    setState("boot");
    setError(null);
    try {
      const resolved = await resolveBaseUrl();
      const probe = new Api(resolved);
      await probe.health();
      setBase(resolved);
      connect(probe.wsUrl());
    } catch (err) {
      setState("offline");
      setError(err instanceof Error ? err.message : "无法连接后端");
    }
  }, [connect]);

  useEffect(() => {
    void boot();
    return () => {
      closedRef.current = true;
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
      reconnect: () => {
        closedRef.current = true;
        socketRef.current?.close();
        void boot();
      },
    }),
    [state, base, api, error, events, lastEvent, boot],
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
