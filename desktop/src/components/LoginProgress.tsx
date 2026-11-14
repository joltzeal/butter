import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useRealtime } from "../hooks/useRealtime";

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
};

interface Progress {
  email: string;
  stage: string;
  index?: number;
  total?: number;
}

/**
 * Floating job indicator for long-running logins.
 *
 * Login and relogin take tens of seconds with nothing on screen otherwise, so
 * this pins a spinner in the lower-right with a human-readable stage and, for
 * batches, a counter. It listens to the same event stream the logs view uses.
 */
export function LoginProgress() {
  const { lastEvent } = useRealtime();
  const [job, setJob] = useState<Progress | null>(null);

  useEffect(() => {
    if (!lastEvent) return;
    const payload = lastEvent.payload as Record<string, unknown>;
    const email = String(payload.email ?? "");
    const stage = String(payload.stage ?? "");

    switch (lastEvent.event) {
      case "login.progress":
        setJob({
          email,
          stage,
          index: typeof payload.index === "number" ? payload.index : undefined,
          total: typeof payload.total === "number" ? payload.total : undefined,
        });
        break;
      case "batch.progress":
      case "bulk.progress":
        setJob({
          email,
          stage: "connect",
          index: typeof payload.index === "number" ? payload.index : undefined,
          total: typeof payload.total === "number" ? payload.total : undefined,
        });
        break;
      case "login.done":
      case "batch.done":
      case "bulk.done":
      case "billing.fetched":
      case "billing.failed":
        setJob(null);
        break;
      default:
        break;
    }
  }, [lastEvent]);

  if (!job) return null;

  const label = STAGE_LABEL[job.stage] ?? "正在处理";
  const counter =
    job.index !== undefined && job.total !== undefined ? `${job.index}/${job.total}` : "";

  return (
    <div className="job-indicator" role="status" aria-live="polite">
      <Loader2 className="spin" style={{ width: 15 }} />
      <div className="job-indicator__body">
        <strong>{label}…</strong>
        <span>
          {counter ? `${counter} · ` : ""}
          {job.email}
        </span>
      </div>
    </div>
  );
}
