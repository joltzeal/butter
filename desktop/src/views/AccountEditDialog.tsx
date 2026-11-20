import { Save, UserPen } from "lucide-react";
import { useEffect, useState } from "react";
import { Button, Field } from "../components/ui";
import { Dialog } from "../components/Dialog";
import { useAccountActions } from "../hooks/useAccounts";
import type { Account } from "../api/client";

/**
 * Edit the stored credentials of one account.
 *
 * The password is shown in the clear and is editable in place: this is a local
 * single-user tool, and hiding it behind dots only meant retyping it.
 */
export function AccountEditDialog({
  account,
  onClose,
  onRenamed,
}: {
  account: Account | null;
  onClose: () => void;
  /** Fired with the new address so the caller's selection follows the key. */
  onRenamed: (email: string) => void;
}) {
  const actions = useAccountActions();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [note, setNote] = useState("");

  // Seeded per address, not per object: the list re-fetches every 10s and a
  // new object identity used to reset the fields mid-edit.
  const key = account?.email ?? "";
  const passwordPlain = account?.password_plain ?? "";
  const savedNote = account?.note ?? "";

  useEffect(() => {
    if (!account) return;
    setEmail(account.email);
    setPassword(account.password_plain ?? "");
    setNote(account.note ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const open = Boolean(account);
  const nextEmail = email.trim();

  const emailChanged = nextEmail.toLowerCase() !== key.toLowerCase();
  const dirty = emailChanged || password !== passwordPlain || note !== savedNote;
  const valid = nextEmail.includes("@") && dirty && !actions.update.isPending;

  const save = async () => {
    if (!account || !valid) return;
    const patch: { email?: string; password?: string; note?: string } = {};
    if (emailChanged) patch.email = nextEmail;
    if (password !== passwordPlain) patch.password = password;
    if (note !== savedNote) patch.note = note;
    try {
      // The path keeps the *old* address; the payload carries the new one.
      await actions.update.mutateAsync({ key, patch });
      if (patch.email) onRenamed(patch.email);
      onClose();
    } catch {
      /* toast already raised — keep the dialog so the edit is not lost */
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="编辑账号"
      subtitle={key}
      icon={UserPen}
      busy={actions.update.isPending}
      onSubmit={save}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={actions.update.isPending}>
            取消
          </Button>
          <Button
            icon={Save}
            variant="primary"
            type="submit"
            disabled={!valid}
            loading={actions.update.isPending}
          >
            保存
          </Button>
        </>
      }
    >
      <Field label="Apple ID">
        <input
          name="email"
          type="email"
          autoComplete="username"
          spellCheck={false}
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </Field>
      <Field label="密码" hint={account?.has_password ? "明文显示，可直接改" : "尚未保存"}>
        <input
          name="password"
          type="text"
          autoComplete="current-password"
          spellCheck={false}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder="输入密码"
        />
      </Field>
      <Field label="备注">
        <input name="note" value={note} onChange={(event) => setNote(event.target.value)} />
      </Field>
      <p className="dim tiny" style={{ margin: 0, lineHeight: 1.6 }}>
        改邮箱后旧会话失效，需要重新登录一次。
      </p>
    </Dialog>
  );
}
