import { clsx } from "clsx";
import { Check, Loader2, type LucideIcon, X } from "lucide-react";
import type { ReactNode } from "react";

type Variant = "primary" | "ghost" | "danger" | "sm" | "icon" | "default";

export function Button({
  children,
  icon: Icon,
  onClick,
  disabled,
  loading,
  variant = "default",
  title,
  ariaLabel,
  type = "button",
  className,
}: {
  children?: ReactNode;
  icon?: LucideIcon;
  onClick?: () => void;
  disabled?: boolean;
  /** Swaps the icon for a spinner and blocks a second press. */
  loading?: boolean;
  ariaLabel?: string;
  variant?: Variant | Variant[];
  title?: string;
  type?: "button" | "submit";
  className?: string;
}) {
  const variants = Array.isArray(variant) ? variant : [variant];
  return (
    <button
      type={type}
      title={title}
      aria-label={ariaLabel}
      onClick={onClick}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={clsx(
        "btn",
        variants.includes("primary") && "btn--primary",
        variants.includes("ghost") && "btn--ghost",
        variants.includes("danger") && "btn--danger",
        variants.includes("sm") && "btn--sm",
        variants.includes("icon") && "btn--icon",
        className,
      )}
    >
      {loading ? <Loader2 className="spin" /> : Icon ? <Icon /> : null}
      {children}
    </button>
  );
}

export function Badge({
  children,
  tone = "idle",
  dot = false,
  pulse = false,
}: {
  children: ReactNode;
  tone?: "online" | "offline" | "idle" | "card" | "noc" | "warn";
  dot?: boolean;
  pulse?: boolean;
}) {
  return (
    <span className={clsx("badge", `badge--${tone}`)}>
      {dot ? <i className={clsx("dot", pulse && "dot--pulse")} /> : null}
      {children}
    </span>
  );
}

export function Checkbox({
  on,
  onChange,
  label,
}: {
  on: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={on}
      aria-label={label}
      title={label}
      data-on={on}
      className="checkbox"
      onClick={(event) => {
        event.stopPropagation();
        onChange(!on);
      }}
    >
      {on ? <Check /> : null}
    </button>
  );
}

export function Field({
  label,
  hint,
  children,
  span,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  span?: 1 | 2 | 3;
}) {
  return (
    <label className="field" style={span ? { gridColumn: `span ${span}` } : undefined}>
      <span className="field__label">{label}</span>
      {children}
      {hint ? <span className="field__hint">{hint}</span> : null}
    </label>
  );
}

export function Panel({
  title,
  subtitle,
  actions,
  children,
  footer,
  className,
  bodyClassName,
  scroll,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
  bodyClassName?: string;
  scroll?: boolean;
}) {
  return (
    <section className={clsx("panel", className)}>
      {title ? (
        <header className="panel__head">
          <div>
            <div className="panel__title">{title}</div>
            {subtitle ? <div className="panel__sub">{subtitle}</div> : null}
          </div>
          <div style={{ marginLeft: "auto" }} className="row">
            {actions}
          </div>
        </header>
      ) : null}
      <div className={clsx("panel__body", bodyClassName)} style={scroll ? { overflowY: "auto" } : undefined}>
        {children}
      </div>
      {footer ? <footer className="panel__foot">{footer}</footer> : null}
    </section>
  );
}

export function Empty({
  icon: Icon,
  title,
  children,
  action,
}: {
  icon: LucideIcon;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty__icon">
        <Icon />
      </div>
      <h3>{title}</h3>
      {children ? <p>{children}</p> : null}
      {action}
    </div>
  );
}

export function Skeleton({ height = 12, width = "100%" }: { height?: number; width?: number | string }) {
  return <div className="skel" style={{ height, width }} />;
}

export function Toasts({
  toasts,
  dismiss,
}: {
  toasts: Array<{
    id: number;
    kind: "ok" | "error" | "info";
    title: string;
    detail?: string;
    /** Closing only hides the toast; the action is a separate button. */
    action?: { label: string; run: () => void };
  }>;
  dismiss: (id: number) => void;
}) {
  return (
    <div className="toasts" role="status" aria-live="polite" aria-relevant="additions text">
      {toasts.map((toast) => (
        <div key={toast.id} className={clsx("toast", `toast--${toast.kind}`)}>
          <div className="toast__bar" />
          <div className="toast__body">
            <strong>{toast.title}</strong>
            {toast.detail ? <span>{toast.detail}</span> : null}
            {toast.action ? (
              <button type="button" className="toast__action" onClick={toast.action.run}>
                {toast.action.label}
              </button>
            ) : null}
          </div>
          <button
            type="button"
            className="toast__close"
            onClick={() => dismiss(toast.id)}
            aria-label="关闭通知"
          >
            <X />
          </button>
        </div>
      ))}
    </div>
  );
}
