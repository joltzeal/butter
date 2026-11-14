import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "butter.unlock.logs";
const TAPS_REQUIRED = 5;
const WINDOW_MS = 1600;

/**
 * Hidden panel unlock: five taps on "关于" within ~1.6s reveals the events view.
 *
 * The choice is remembered so the menu stays put across restarts once unlocked;
 * clearing the key hides it again.
 */
export function useSecretUnlock() {
  const [unlocked, setUnlocked] = useState(
    () => localStorage.getItem(STORAGE_KEY) === "1",
  );
  const [taps, setTaps] = useState<number[]>([]);

  useEffect(() => {
    if (!unlocked) return;
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === "l") {
        localStorage.removeItem(STORAGE_KEY);
        setUnlocked(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [unlocked]);

  const tapAbout = useCallback(() => {
    const now = Date.now();
    const recent = [...taps, now].filter((t) => now - t <= WINDOW_MS);
    if (recent.length >= TAPS_REQUIRED) {
      localStorage.setItem(STORAGE_KEY, "1");
      setUnlocked(true);
      setTaps([]);
      return true;
    }
    setTaps(recent);
    return false;
  }, [taps]);

  return { tapAbout, unlocked };
}
