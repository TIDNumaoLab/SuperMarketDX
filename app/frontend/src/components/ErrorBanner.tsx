// 画面上部に出すエラー文言(API 呼び出しの失敗など)
import styles from "../styles/page.module.css";

interface Props {
  message: string | null;
}

export default function ErrorBanner({ message }: Props) {
  if (!message) {
    return null;
  }
  return (
    <div role="alert" className={styles.error}>
      {message}
    </div>
  );
}
