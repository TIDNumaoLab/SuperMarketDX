// 在庫入力(/inventory): 部門の商品ごとに在庫数を手入力する(生鮮のみ)。前回の在庫数と基準日時を併記する
// 基準日時を利用者が変えていなければ、保存の時点の現在時刻を使う(画面を開いたまま時間がたっても古い日時にならないように)
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { errorMessage } from "../api/client";
import { getLatestInventory, putInventory } from "../api/inventory";
import { useAuth } from "../auth/AuthContext";
import DepartmentSelect, { selectableDepartments } from "../components/DepartmentSelect";
import ErrorBanner from "../components/ErrorBanner";
import { savebarHint } from "../components/savebarHint";
import { formatShortDateTime, jstNowInput, toJstIso } from "../format";
import styles from "../styles/page.module.css";
import type { InventoryLatest } from "../types/api";

export default function InventoryPage() {
  const { me } = useAuth();
  const [department, setDepartment] = useState(
    selectableDepartments(me?.accessible_departments ?? [], "order")[0]?.code ?? "",
  );
  const [basedAt, setBasedAt] = useState(jstNowInput());
  // 利用者が基準日時を変えたか(変えていなければ保存時の現在時刻にする)
  const [basedAtEdited, setBasedAtEdited] = useState(false);
  const [rows, setRows] = useState<InventoryLatest[]>([]);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async (code: string) => {
    if (!code) return;
    try {
      setRows(await getLatestInventory(code));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    void load(department);
  }, [department, load]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    const entered = rows.filter((r) => (inputs[r.product_code] ?? "").trim() !== "");
    if (entered.length === 0) {
      setError("在庫数を入力してください");
      return;
    }
    if (entered.some((r) => !/^\d+$/.test(inputs[r.product_code].trim()))) {
      setError("在庫数は0以上の整数で入力してください");
      return;
    }
    const at = basedAtEdited ? basedAt : jstNowInput();
    if (!at) {
      setError("基準日時を入力してください");
      return;
    }
    setBasedAt(at);
    try {
      const res = await putInventory({
        department_code: department,
        based_at: toJstIso(at),
        items: entered.map((r) => ({ product_code: r.product_code, quantity: Number(inputs[r.product_code]) })),
      });
      setMessage(`保存しました(${res.saved}件)`);
      setInputs({});
      await load(department);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const filledCount = rows.filter((r) => (inputs[r.product_code] ?? "").trim() !== "").length;
  const hint = savebarHint(error);

  return (
    <section>
      <div className={styles.head}>
        <div>
          <h1>在庫入力</h1>
          <p className={styles.sub}>数えた商品だけ入力すれば保存できます。</p>
        </div>
      </div>
      <ErrorBanner message={error} />
      {/* 入力の検証は画面の文言で出すため、ブラウザの検証は使わない */}
      <form onSubmit={onSubmit} noValidate>
        <div className={styles.toolbar}>
          <DepartmentSelect value={department} onChange={setDepartment} businessType="order" />
          <label className={styles.field}>
            基準日時
            <input
              type="datetime-local"
              value={basedAt}
              onChange={(e) => {
                setBasedAt(e.target.value);
                setBasedAtEdited(true);
              }}
              required
            />
          </label>
          {/* 隣の入力欄と高さをそろえるため、共通の大きさ(36px)のボタンにする */}
          <button
            type="button"
            onClick={() => {
              setBasedAt(jstNowInput());
              setBasedAtEdited(false);
            }}
          >
            現在時刻にする
          </button>
        </div>
        <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>商品</th>
              <th>前回</th>
              <th>在庫数</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.product_code}>
                <td className={styles.name}>{r.product_name}</td>
                <td className={styles.muted}>
                  {r.quantity !== null && r.based_at
                    ? `前回 ${r.quantity}(${formatShortDateTime(r.based_at)})`
                    : "前回 —"}
                </td>
                <td>
                  <input
                    type="number"
                    min={0}
                    step={1}
                    aria-label={`${r.product_name} の在庫数`}
                    className={`${styles.invInput} ${(inputs[r.product_code] ?? "").trim() !== "" ? styles.filled : ""}`}
                    value={inputs[r.product_code] ?? ""}
                    onChange={(e) => setInputs({ ...inputs, [r.product_code]: e.target.value })}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
        {/* 入力件数と保存ボタンは、表が長くても見えるよう画面下に固定する */}
        <div className={styles.savebar}>
          <span>
            <b>{filledCount}件</b>を入力しています
          </span>
          {/* 保存の結果は、ボタンを押した位置で分かるよう帯の中に出す */}
          <span role="status" className={styles.saved}>
            {message}
          </span>
          {hint && <span className={styles.hint}>{hint}</span>}
          <span className={styles.spacer} />
          <button type="submit" className={styles.primary}>
            保存
          </button>
        </div>
      </form>
    </section>
  );
}
