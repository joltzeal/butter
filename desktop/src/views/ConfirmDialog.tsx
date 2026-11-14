import { AlertTriangle, X } from "lucide-react";
import { Button } from "../components/ui";

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "确认",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
}) {
  if (!open) return null;
  return (
    <div className="modal-backdrop" onMouseDown={onCancel}>
      <div className="modal modal--sm" onMouseDown={(event) => event.stopPropagation()}>
        <header className="modal__head">
          <AlertTriangle style={{ width: 16, color: "var(--danger)" }} />
          <h2>{title}</h2>
          <button className="modal__close" onClick={onCancel}>
            <X />
          </button>
        </header>
        <div className="modal__body">
          <p className="muted" style={{ fontSize: 12.5 }}>
            {description}
          </p>
        </div>
        <footer className="modal__foot">
          <Button variant="ghost" onClick={onCancel}>
            取消
          </Button>
          <Button variant="danger" onClick={() => void onConfirm()}>
            {confirmLabel}
          </Button>
        </footer>
      </div>
    </div>
  );
}
