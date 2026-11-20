import { Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useOptionalApi, useRealtime } from "../hooks/useRealtime";
import { useToasts } from "../hooks/useToasts";

/** Operator-facing wording for each backend stage. No internals leak out. */
const STAGE_LABEL: Record<string, string> = {
  connect: "正在连接",
  init: "正在验证账号",
  complete: "正在验证账号",
  hsa2: "等待验证码",
  trust: "正在完成验证",
  store: "正在同步商店信息",
  repair: "正在修复账号",
  retry: "正在重试",
  check: "正在检测会话",
};

/** A job that stops reporting for this long is presumed dead. */
const STALE_MS = 180_000;

interface Job {
  kind: "login" | "session";
  email: string;
  stage: string;
  index?: number;
  total?: number;
  at: number;
}

/**
 * Floating job indicator for long-running logins.
 *
 * Keyed by address: two logins used to overwrite one shared job, so the first
 * one's progress vanished.
 */
export function LoginProgress() {
  const { lastEvent } = useRealtime();
  const api = useOptionalApi();
  const { push } = useToasts();
  const [jobs, setJobs] = useState<Job[]>([]);
  // Hidden cards keep running: closing is "get out of the way", cancelling is
  // its own button.
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!lastEvent) return;
    const payload = lastEvent.payload as Record<string, unknown>;
    const email = String(payload.email ?? "");
    const stage = String(payload.stage ?? "");
    const index = typeof payload.index === "number" ? payload.index : undefined;
    const total = typeof payload.total === "number" ? payload.total : undefined;

    const upsert = (job: Job) => {
      setJobs((prev) => {
        const rest = prev.filter((item) => item.email !== job.email);
        return [...rest, job];
      });
      setHidden((prev) => {
        if (!prev.has(job.email)) return prev;
        const next = new Set(prev);
        next.delete(job.email);
        return next;
      });
    };

    let clearAll = false;
    switch (lastEvent.event) {
      case "login.progress":
        if (!email) return;
        upsert({ kind: "login", email, stage, index, total, at: Date.now() });
        break;
      case "session.progress":
        // A session check walks accounts too, and it deserves the same
        // indicator: closing the toast must not hide the work.
        if (!email) return;
        upsert({ kind: "session", email, stage: "check", index, total, at: Date.now() });
        break;
      case "batch.progress":
      case "bulk.progress":
        if (!email) return;
        upsert({ kind: "login", email, stage: "connect", index, total, at: Date.now() });
        break;
      case "session.done":
        setJobs((prev) => prev.filter((item) => item.kind !== "session"));
        break;
      case "login.done":
        if (email) setJobs((prev) => prev.filter((item) => item.email !== email));
        break;
      case "batch.done":
      case "bulk.done":
        clearAll = true;
        break;
      case "billing.fetched":
      case "billing.failed":
        if (email) setJobs((prev) => prev.filter((item) => item.email !== email));
        else clearAll = true;
        break;
      default:
        break;
    }
    if (clearAll) setJobs([]);
  }, [lastEvent]);

  // Drop jobs that stopped reporting (a missed terminal frame used to spin).
  useEffect(() => {
    if (!jobs.length) return;
    const timer = window.setInterval(() => {
      const now = Date.now();
      setJobs((prev) => prev.filter((job) => now - job.at < STALE_MS));
    }, 5_000);
    return () => window.clearInterval(timer);
  }, [jobs.length]);

  const visible = jobs.filter((job) => !hidden.has(job.email));
  if (!visible.length) return null;

  const cancel = async (job: Job) => {
    try {
      if (job.kind === "session") {
        const result = await api?.cancelCheck();
        push({
          kind: "info",
          title: result?.ok ? "已请求停止检测" : "检测已经结束",
          detail: result?.ok ? "当前账号跑完就停" : undefined,
        });
        return;
      }
      const result = await api?.cancelLogin(job.email);
      push({
        kind: "info",
        title: result?.ok ? "已取消" : "没有可取消的步骤",
        detail: result?.ok ? job.email : "流程可能已经结束",
      });
      if (result?.ok) setJobs((prev) => prev.filter((item) => item.email !== job.email));
    } catch (err) {
      push({ kind: "error", title: "取消失败", detail: String(err) });
    }
  };

  return (
    <div className="jobs" role="status" aria-live="polite">
      {visible.map((job) => {
        const counter = job.index !== undefined && job.total !== undefined ? `${job.index}/${job.total}` : "";
        return (
          <div className="job-indicator" key={job.email}>
            <Loader2 className="spin" style={{ width: 15 }} />
            <div className="job-indicator__body">
              <strong>{STAGE_LABEL[job.stage] ?? "正在处理"}…</strong>
              <span title={job.email}>
                {counter ? `${counter} · ` : ""}
                {job.email}
              </span>
            </div>
            <button type="button" className="job-indicator__cancel" onClick={() => void cancel(job)}>
              取消
            </button>
            <button
              type="button"
              className="job-indicator__close"
              onClick={() =>
                setHidden((prev) => {
                  const next = new Set(prev);
                  next.add(job.email);
                  return next;
                })
              }
              aria-label="收起这条进度"
            >
              <X />
            </button>
          </div>
        );
      })}
    </div>
  );
}
