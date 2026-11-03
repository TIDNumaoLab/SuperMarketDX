// 画面上部に出すエラー文言(API 呼び出しの失敗など)
interface Props {
  message: string | null;
}

export default function ErrorBanner({ message }: Props) {
  if (!message) {
    return null;
  }
  return (
    <div
      role="alert"
      style={{ background: "var(--stamp-soft)", color: "#8a1c1c", padding: "10px 14px", borderRadius: 8, marginBottom: 14 }}
    >
      {message}
    </div>
  );
}
