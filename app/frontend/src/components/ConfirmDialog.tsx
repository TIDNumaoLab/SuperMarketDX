// 確認ダイアログ(削除や、警告付きの提案の承認などで使う)
import pageStyles from "../styles/page.module.css";

interface Props {
  open: boolean;
  message: string;
  onConfirm(): void;
  onCancel(): void;
}

export default function ConfirmDialog({ open, message, onConfirm, onCancel }: Props) {
  if (!open) {
    return null;
  }
  return (
    <div
      style={{ position: "fixed", inset: 0, background: "rgba(29,43,40,0.35)", zIndex: 20, display: "flex", alignItems: "center", justifyContent: "center" }}
    >
      <div role="dialog" aria-modal="true" style={{ background: "var(--surface)", padding: 24, borderRadius: 10, minWidth: 360, boxShadow: "0 10px 30px rgba(31,61,54,0.2)" }}>
        <p style={{ marginTop: 0 }}>{message}</p>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button type="button" onClick={onCancel}>
            いいえ
          </button>
          <button type="button" className={pageStyles.primary} onClick={onConfirm} autoFocus>
            はい
          </button>
        </div>
      </div>
    </div>
  );
}
