import { UserPlus } from "lucide-react";
import { useEffect, useState } from "react";
import { Button, Field } from "../components/ui";
import { Dialog } from "../components/Dialog";

export function AddAccountDialog({
  open,
  onClose,
  onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: (payload: {
    email: string;
    password: string;
    note: string;
    code_url: string;
  }) => Promise<void>;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [note, setNote] = useState("");
  const [codeUrl, setCodeUrl] = useState("");
  const [busy, setBusy] = useState(false);

  // The dialog stays mounted, so opening it again used to show the previous
  // account's credentials.
  useEffect(() => {
    if (!open) return;
    setEmail("");
    setPassword("");
    setNote("");
    setCodeUrl("");
    setBusy(false);
  }, [open]);

  const valid = /.+@.+\..+/.test(email.trim());

  const submit = async () => {
    if (!valid || busy) return;
    setBusy(true);
    try {
      await onSubmit({ email: email.trim(), password, note, code_url: codeUrl.trim() });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="添加账号"
      icon={UserPlus}
      busy={busy}
      onSubmit={submit}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button variant="primary" type="submit" disabled={!valid} loading={busy}>
            保存
          </Button>
        </>
      }
    >
      <Field label="Apple ID">
        <input
          autoFocus
          name="email"
          type="email"
          autoComplete="username"
          placeholder="apple_id@example.com"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </Field>
      <Field label="密码">
        <input
          name="password"
          type="text"
          autoComplete="current-password"
          spellCheck={false}
          placeholder="••••••••"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </Field>
      <Field label="2FA 链接">
        <input
          name="code_url"
          type="url"
          placeholder="https://…/getcode?id=123"
          value={codeUrl}
          onChange={(event) => setCodeUrl(event.target.value)}
        />
      </Field>
      <Field label="备注">
        <input name="note" placeholder="例如：US 主号" value={note} onChange={(event) => setNote(event.target.value)} />
      </Field>
    </Dialog>
  );
}
