import { AlertTriangle } from "lucide-react";
import { useState } from "react";
import { Button } from "../components/ui";
import { Dialog } from "../components/Dialog";

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
  /** Resolve `true` to close; `false` keeps the dialog open after a failure. */
  onConfirm: () => boolean | Promise<boolean>;
  onCancel: () => void;
}) {
  const [busy, setBusy] = useState(false);

  const confirm = async () => {
    setBusy(true);
    try {
      if ((await onConfirm()) !== false) onCancel();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title={title}
      icon={AlertTriangle}
      busy={busy}
      onSubmit={confirm}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            取消
          </Button>
          <Button variant="danger" type="submit" loading={busy}>
            {busy ? "处理中…" : confirmLabel}
          </Button>
        </>
      }
    >
      <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.7 }}>
        {description}
      </p>
    </Dialog>
  );
}
