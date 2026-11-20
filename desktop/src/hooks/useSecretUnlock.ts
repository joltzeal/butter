import { useCallback, useSyncExternalStore } from "react";

const STORAGE_KEY = "butter.unlock.logs";
const TAPS_REQUIRED = 5;
const WINDOW_MS = 1600;

/**
 * Hidden panel unlock: five taps on "关于" within ~1.6s reveals the events view.
 *
 * The flag is a module-level store rather than component state: the rail and the
 * settings panel are different trees, and local state meant the menu only
 * appeared after a reload.
 */
let unlocked = typeof localStorage !== "undefined" && localStorage.getItem(STORAGE_KEY) === "1";
let taps: number[] = [];

const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function setUnlocked(next: boolean) {
  if (unlocked === next) return;
  unlocked = next;
  emit();
}

// Another window (or the dev reload) can flip the flag; follow it.
if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key !== STORAGE_KEY) return;
    unlocked = event.newValue === "1";
    emit();
  });
}

/** Leaving the hidden state also clears the stored choice. */
export function lockLogs() {
  localStorage.removeItem(STORAGE_KEY);
  setUnlocked(false);
}

// One listener for the whole app: ⌘⇧L / Ctrl+Shift+L hides the panel again.
// It lived in a hook effect before, so it only worked while a component that
// happened to be mounted was listening.
if (typeof window !== "undefined") {
  window.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === "l") {
      event.preventDefault();
      lockLogs();
    }
  });
}

export function useSecretUnlock() {
  const value = useSyncExternalStore(subscribe, () => unlocked, () => false);

  const tapAbout = useCallback(() => {
    const now = Date.now();
    const recent = [...taps, now].filter((stamp) => now - stamp <= WINDOW_MS);
    if (recent.length >= TAPS_REQUIRED) {
      localStorage.setItem(STORAGE_KEY, "1");
      taps = [];
      setUnlocked(true);
      return true;
    }
    taps = recent;
    return false;
  }, []);

  return { tapAbout, unlocked: value };
}
