// ログイン画面(/login)
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { errorMessage, statusOf } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { HOME_PATH } from "../auth/routes";
import ErrorBanner from "../components/ErrorBanner";
import styles from "./LoginPage.module.css";

const LOGIN_FAILED = "ログインIDまたはパスワードが正しくありません。";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [loginId, setLoginId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(loginId, password);
      navigate(HOME_PATH, { replace: true });
    } catch (err) {
      setError(statusOf(err) === 401 ? LOGIN_FAILED : errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className={styles.page}>
      <form className={styles.form} onSubmit={onSubmit}>
        <h1 className={styles.title}>発注アシスタント</h1>
        <ErrorBanner message={error} />
        <label className={styles.field}>
          ログインID
          <input value={loginId} onChange={(e) => setLoginId(e.target.value)} autoComplete="username" required />
        </label>
        <label className={styles.field}>
          パスワード
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        <button type="submit" className={styles.submit} disabled={submitting}>
          ログイン
        </button>
      </form>
    </main>
  );
}
