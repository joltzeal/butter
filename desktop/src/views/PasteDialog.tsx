import { ClipboardPaste } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useOptionalApi } from "../hooks/useRealtime";
import { Button, Field } from "../components/ui";
import { Dialog } from "../components/Dialog";

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
  const api = useOptionalApi();
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);
  const inflight = useRef<{ seq: number; controller: AbortController } | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    if (open) return;
    setText("");
    setPreview({});
    setError(null);
  }, [open]);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
      inflight.current?.controller.abort();
    },
    [],
  );

  const parse = async (value: string) => {
    if (!api) return;
    inflight.current?.controller.abort();
    const controller = new AbortController();
    const mine = ++seq.current;
    inflight.current = { seq: mine, controller };
    setBusy(true);
    try {
      const result = await api.parsePaste(value, controller.signal);
      // A slow response must not overwrite a newer preview.
      if (mine !== seq.current) return;
      setPreview(result.fields);
      if (result.count === 0) setError("未识别到任何字段，请检查格式");
      else setError(null);
    } catch (err) {
      if (mine !== seq.current) return;
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : "解析失败");
    } finally {
      if (mine === seq.current) setBusy(false);
    }
  };

  // Typing is debounced; "重新解析" forces an immediate pass.
  const schedule = (value: string) => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      timer.current = null;
      if (value.trim().length >= 6) void parse(value);
    }, 300);
  };

  const apply = () => {
    onApply(preview);
    onClose();
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="粘贴识别"
      icon={ClipboardPaste}
      size="md"
      busy={busy}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button variant="ghost" onClick={() => void parse(text)} disabled={busy || !text.trim()}>
            重新解析
          </Button>
          <Button variant="primary" onClick={apply} disabled={Object.keys(preview).length === 0}>
            填入 {Object.keys(preview).length} 个字段
          </Button>
        </>
      }
    >
      <Field label="粘贴内容" hint={busy ? "识别中…" : undefined}>
        <textarea
          name="paste"
          autoFocus
          rows={8}
          spellCheck={false}
          className="paste-area"
          placeholder={"First Name: Jane\nLast Name: Doe\nAddress: 5 Oak St\nCity: Austin\nState: TX\nZIP: 78701\nCountry: US"}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            schedule(event.target.value);
          }}
        />
      </Field>
      {Object.keys(preview).length > 0 ? (
        <div className="paste-preview">
          {Object.entries(preview).map(([key, value]) => (
            <span className="chip" key={key}>
              {FIELD_LABELS[key] ?? key} <b>{value}</b>
            </span>
          ))}
        </div>
      ) : null}
      {error ? <div className="field__hint field__hint--error">{error}</div> : null}
    </Dialog>
  );
}
