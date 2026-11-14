import { UserPlus, X } from "lucide-react";
import { useState } from "react";
import { Button, Field } from "../components/ui";

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

  if (!open) return null;

  const valid = /.+@.+\..+/.test(email.trim());

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal modal--sm" onMouseDown={(event) => event.stopPropagation()}>
        <header className="modal__head">
          <UserPlus style={{ width: 16, color: "var(--amber)" }} />
          <div>
            <h2>添加账号</h2>
            <p>密码只保存在本机，用于后续自动重登</p>
          </div>
          <button className="modal__close" onClick={onClose}>
            <X />
          </button>
        </header>
        <div className="modal__body">
          <Field label="Apple ID">
            <input
              autoFocus
              type="email"
              placeholder="apple_id@example.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </Field>
          <Field label="密码">
            <input
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>
          <Field
            label="2FA 链接"
            hint="可选。留空则登录到两步验证时弹数字键盘手动输入"
          >
            <input
              type="url"
              placeholder="https://…/getcode?id=123"
              value={codeUrl}
              onChange={(event) => setCodeUrl(event.target.value)}
            />
          </Field>
          <Field label="备注" hint="可选，便于在列表中识别">
            <input placeholder="例如：US 主号" value={note} onChange={(event) => setNote(event.target.value)} />
          </Field>
        </div>
        <footer className="modal__foot">
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button
            variant="primary"
            disabled={!valid}
            onClick={() =>
              void onSubmit({
                email: email.trim(),
                password,
                note,
                code_url: codeUrl.trim(),
              })
            }
          >
            保存并登录
          </Button>
        </footer>
      </div>
    </div>
  );
}
