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
    <div className={pageStyles.overlay}>
      <div role="dialog" aria-modal="true" className={pageStyles.dialog}>
        <p>{message}</p>
        <div className={pageStyles.dialogButtons}>
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
