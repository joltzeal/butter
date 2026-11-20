import { X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useCallback, useEffect, useId, useRef, type ReactNode } from "react";
import { clsx } from "clsx";
import "./dialog.css";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * One dialog shell: Esc, a focus trap, focus restore, and either a plain body
 * or a real `<form>` so Enter submits.
 *
 * Every overlay used to be a hand-rolled div: Esc did nothing, Tab walked out
 * of the dialog into the list behind it, and closing one threw focus to <body>.
 */
export function Dialog({
  open,
  onClose,
  title,
  subtitle,
  icon: Icon,
  size = "sm",
  bare = false,
  panelClass,
  aside,
  footer,
  busy = false,
  onSubmit,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: LucideIcon;
  size?: "sm" | "md";
  /** No head: the child owns the whole panel (command palette). */
  bare?: boolean;
  /** Extra class on the panel (a command palette anchors to the top). */
  panelClass?: string;
  /** Rendered on the right of the head, above the close button. */
  aside?: ReactNode;
  footer?: ReactNode;
  busy?: boolean;
  onSubmit?: () => void;
  children: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const openedAt = useRef(0);

  const close = useCallback(() => {
    if (!busy) onClose();
  }, [busy, onClose]);

  useEffect(() => {
    if (!open) return;
    openedAt.current = Date.now();
    const previous = document.activeElement as HTMLElement | null;

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        event.preventDefault();
        close();
        return;
      }
      if (event.key !== "Tab") return;
      const panel = panelRef.current;
      if (!panel) return;
      const nodes = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (node) => node.offsetParent !== null,
      );
      if (!nodes.length) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      // Focus goes back where it came from, unless the opener is gone.
      if (previous?.isConnected) previous.focus();
    };
  }, [open, close]);

  if (!open) return null;

  // A stray submit from a nested form must not reload the webview.
  const body = bare ? (
    children
  ) : (
    <>
      <header className="modal__head">
        {Icon ? <Icon className="modal__icon" /> : null}
        <div className="modal__title">
          <h2 id={titleId}>{title}</h2>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
        {aside}
        <button type="button" className="modal__close" onClick={close} aria-label="关闭">
          <X />
        </button>
      </header>
      <div className="modal__body">{children}</div>
      {footer ? <footer className="modal__foot">{footer}</footer> : null}
    </>
  );

  return (
    <div
      className={clsx("modal-backdrop", panelClass && "modal-backdrop--anchored")}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && Date.now() - openedAt.current > 150) close();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={bare ? undefined : titleId}
        aria-label={bare ? String(title) : undefined}
        aria-busy={busy || undefined}
        className={clsx("modal", size === "sm" ? "modal--sm" : "modal--md", panelClass)}
        onMouseDown={(event) => event.stopPropagation()}
      >
        {onSubmit ? (
          <form
            className="modal__form"
            onSubmit={(event) => {
              event.preventDefault();
              if (!busy) onSubmit();
            }}
          >
            {body}
          </form>
        ) : (
          body
        )}
      </div>
    </div>
  );
}
