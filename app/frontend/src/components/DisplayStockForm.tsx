// 惣菜の陳列残数の入力欄(詳細設計書「製造計画(/production)」)。
// 商品ごとに入力し、当日の分を送る(入力時刻は保存時のサーバーの時刻)。入力した商品だけを送り、保存後は返ったジョブを親に渡す
import { useState, type FormEvent } from "react";
import { errorMessage } from "../api/client";
import { putDisplayStock } from "../api/production";
import { formatTime, jstToday } from "../format";
import styles from "../styles/page.module.css";
import type { Job } from "../types/api";
import ErrorBanner from "./ErrorBanner";

interface Props {
  departmentCode: string;
  products: { product_code: string; name: string }[];
  // 保存後に、再計算のジョブと陳列残数を入れた日(当日)を渡す
  onSaved(job: Job, targetDate: string): void;
}

const INVALID = "陳列残数は0以上の整数で入力してください";

export default function DisplayStockForm({ departmentCode, products, onSaved }: Props) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const filled = products.filter((p) => (values[p.product_code] ?? "").trim() !== "");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setMessage(null);
    if (filled.some((p) => !/^\d+$/.test(values[p.product_code].trim()))) {
      setError(INVALID);
      return;
    }
    const target = jstToday();
    setSaving(true);
    setError(null);
    try {
      const res = await putDisplayStock({
        department_code: departmentCode,
        target_date: target,
        items: filled.map((p) => ({ product_code: p.product_code, quantity: Number(values[p.product_code].trim()) })),
      });
      setValues({});
      setMessage(`陳列残数を保存しました(${formatTime(res.entered_at)} 時点)`);
      onSaved(res.job, target);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    // ブラウザの入力検証ではなく、画面の文言で知らせる
    <form className={styles.panel} noValidate onSubmit={(e) => void submit(e)}>
      <h2>陳列残数の入力</h2>
      <p className={styles.muted}>
        保存した時刻の直後の時間帯から差し引き、製造開始前の時間帯を計算し直します。
        各時間帯の製造開始から開始時刻までに保存した分は、その時間帯の製造が始まっているため製造数に反映されません。
      </p>
      <ErrorBanner message={error} />
      {message && <div className={styles.notice}>{message}</div>}
      <div className={styles.toolbar} style={{ marginBottom: 0 }}>
        {products.map((p) => (
          <label key={p.product_code} className={styles.field}>
            {p.name}
            <input
              type="number"
              min={0}
              step={1}
              aria-label={`${p.name} の陳列残数`}
              style={{ width: 110 }}
              value={values[p.product_code] ?? ""}
              onChange={(e) => setValues({ ...values, [p.product_code]: e.target.value })}
            />
          </label>
        ))}
        <button type="submit" className={styles.primary} disabled={saving || filled.length === 0}>
          陳列残数を保存
        </button>
      </div>
    </form>
  );
}
