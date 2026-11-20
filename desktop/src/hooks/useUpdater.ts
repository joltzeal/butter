import { useCallback, useRef, useState } from "react";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";
import { isTauri } from "../api/client";

export type UpdateState = "idle" | "checking" | "available" | "downloading" | "ready" | "current" | "error";

/**
 * Release updates through the Tauri updater.
 *
 * The repository is private, so a read-only token has to ride along; without
 * one the release asset answers 404. Signatures are verified by the shell
 * against the compiled-in public key, so a tampered download cannot install.
 */
const headers: Record<string, string> = { Accept: "application/octet-stream" };
const token = import.meta.env.VITE_UPDATE_TOKEN as string | undefined;
if (token) headers.Authorization = `Bearer ${token}`;

export interface UpdateInfo {
  version: string;
  notes: string;
  date: string;
}

export function useUpdater() {
  const [state, setState] = useState<UpdateState>("idle");
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState(0);
  const updateRef = useRef<Update | null>(null);

  const find = useCallback(async () => {
    if (!isTauri()) {
      setState("error");
      setError("浏览器预览不支持自动更新，请在应用窗口里检查");
      return null;
    }
    setState("checking");
    setError("");
    try {
      const update = await check({ headers, timeout: 20_000 });
      if (!update) {
        updateRef.current = null;
        setInfo(null);
        setState("current");
        return null;
      }
      updateRef.current = update;
      setInfo({ version: update.version, notes: update.body ?? "", date: update.date ?? "" });
      setState("available");
      return update;
    } catch (err) {
      setState("error");
      setError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }, []);

  const download = useCallback(async () => {
    const update = updateRef.current;
    if (!update) return;
    setState("downloading");
    setProgress(0);
    let total = 0;
    let got = 0;
    try {
      await update.downloadAndInstall((event) => {
        if (event.event === "Started") total = event.data.contentLength ?? 0;
        else if (event.event === "Progress") {
          got += event.data.chunkLength;
          setProgress(total ? Math.min(100, Math.round((got / total) * 100)) : 0);
        }
      });
      setProgress(100);
      setState("ready");
    } catch (err) {
      setState("error");
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const restart = useCallback(() => relaunch(), []);

  return { state, info, error, progress, find, download, restart };
}
