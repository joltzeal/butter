import { ClipboardPaste, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useApi } from "../hooks/useRealtime";
import { Button, Field } from "../components/ui";

const FIELD_LABELS: Record<string, string> = {
  first_name: "名字",
  last_name: "姓氏",
  full_name: "姓名",
  phone: "电话",
  street: "街道",
  street2: "公寓",
  city: "城市",
  state: "州/省",
  postal_code: "邮编",
  country_code: "国家",
  card_number: "卡号",
  card_expiry: "有效期",
  card_holder: "持卡人",
  email: "邮箱",
};

export function PasteDialog({
  open,
  onClose,
  onApply,
}: {
  open: boolean;
  onClose: () => void;
  onApply: (fields: Record<string, string>) => void;
}) {
  const api = useApi();
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) {
      setText("");
      setPreview({});
      setError(null);
    }
  }, [open]);

  if (!open) return null;

  const parse = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.parsePaste(text);
      setPreview(result.fields);
      if (result.count === 0) setError("未识别到任何字段，请检查格式");
    } catch (err) {
      setError(err instanceof Error ? err.message : "解析失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal" onMouseDown={(event) => event.stopPropagation()}>
        <header className="modal__head">
          <ClipboardPaste style={{ width: 16, color: "var(--amber)" }} />
          <div>
            <h2>粘贴识别</h2>
            <p>支持中文标签、英文标签、键值流、空行嵌套、卡片块与 JSON</p>
          </div>
          <button className="modal__close" onClick={onClose}>
            <X />
          </button>
        </header>
        <div className="modal__body">
          <textarea
            autoFocus
            placeholder={"First Name: Jane\nLast Name: Doe\nAddress: 5 Oak St\nCity: Austin\nState: TX\nZIP: 78701\nCountry: US"}
            value={text}
            onChange={(event) => setText(event.target.value)}
            onInput={async (event) => {
              const value = (event.target as HTMLTextAreaElement).value;
              if (value.trim().length < 6) return;
              try {
                const result = await api.parsePaste(value);
                setPreview(result.fields);
                setError(null);
              } catch {
                /* keep last good preview */
              }
            }}
          />
          {preview && Object.keys(preview).length > 0 ? (
            <div className="paste-preview">
              {Object.entries(preview).map(([key, value]) => (
                <span className="chip" key={key}>
                  {FIELD_LABELS[key] ?? key} <b>{value}</b>
                </span>
              ))}
            </div>
          ) : null}
          {error ? <div className="field__hint" style={{ color: "var(--danger)" }}>{error}</div> : null}
        </div>
        <footer className="modal__foot">
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button variant="ghost" onClick={parse} disabled={busy || !text.trim()}>
            重新解析
          </Button>
          <Button
            variant="primary"
            disabled={Object.keys(preview).length === 0}
            onClick={() => {
              onApply(preview);
              onClose();
            }}
          >
            填入 {Object.keys(preview).length} 个字段
          </Button>
        </footer>
      </div>
    </div>
  );
}

export function FieldRow({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <Field label={label} hint={hint}>
      {children}
    </Field>
  );
}
