// 特売・チラシ(/promotions): 期間で絞り込んだ一覧と登録フォーム。行ごとに編集・削除
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { errorMessage } from "../api/client";
import { listProducts } from "../api/products";
import { createPromotion, deletePromotion, listPromotions, updatePromotion } from "../api/promotions";
import { useAuth } from "../auth/AuthContext";
import ConfirmDialog from "../components/ConfirmDialog";
import ErrorBanner from "../components/ErrorBanner";
import { jstToday } from "../format";
import styles from "../styles/page.module.css";
import type { Product, Promotion, PromotionInput } from "../types/api";

const DEFAULT_RANGE_DAYS = 30;
const shortDate = (iso: string) => `${iso.slice(5, 7)}/${iso.slice(8, 10)}`;

export default function PromotionsPage() {
  const { me } = useAuth();
  const accessible = new Set((me?.accessible_departments ?? []).map((d) => d.code));
  const [from, setFrom] = useState(jstToday());
  const [to, setTo] = useState(jstToday(DEFAULT_RANGE_DAYS));
  const [rows, setRows] = useState<Promotion[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [form, setForm] = useState<PromotionInput>({ product_code: "", start_date: "", end_date: "", description: "" });
  const [editingId, setEditingId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<Promotion | null>(null);
  const [error, setError] = useState<string | null>(null);

  const ownProducts = products.filter((p) => accessible.has(p.department_code));

  const load = useCallback(async () => {
    try {
      setRows(await listPromotions({ date_from: from, date_to: to }));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [from, to]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    listProducts()
      .then(setProducts)
      .catch((e) => setError(errorMessage(e)));
  }, []);

  // 商品が未選択なら、選べる最初の商品にする
  const productCode = form.product_code || ownProducts[0]?.product_code || "";

  function resetForm() {
    setForm({ product_code: "", start_date: "", end_date: "", description: "" });
    setEditingId(null);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const body = { ...form, product_code: productCode, description: form.description.trim() };
    if (!body.product_code || !body.start_date || !body.end_date || !body.description) {
      setError("商品・開始日・終了日・内容を入力してください");
      return;
    }
    if (body.end_date < body.start_date) {
      setError("終了日は開始日以降にしてください");
      return;
    }
    try {
      if (editingId === null) {
        await createPromotion(body);
      } else {
        await updatePromotion(editingId, body);
      }
      resetForm();
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  function startEdit(p: Promotion) {
    setEditingId(p.id);
    setForm({ product_code: p.product_code, start_date: p.start_date, end_date: p.end_date, description: p.description });
  }

  async function onDelete() {
    if (!deleting) return;
    const target = deleting;
    setDeleting(null);
    try {
      await deletePromotion(target.id);
      if (editingId === target.id) resetForm();
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <section>
      <div className={styles.head}>
        <div>
          <h1>特売・チラシ</h1>
          <p className={styles.sub}>登録した期間は予測に特売として反映されます。</p>
        </div>
      </div>
      <ErrorBanner message={error} />

      <form className={styles.panel} onSubmit={onSubmit} noValidate>
        <h2>{editingId === null ? "特売を登録" : "特売を編集"}</h2>
        <div className={styles.toolbar} style={{ marginBottom: 0 }}>
        <label className={styles.field}>
          商品
          <select value={productCode} onChange={(e) => setForm({ ...form, product_code: e.target.value })}>
            {ownProducts.map((p) => (
              <option key={p.product_code} value={p.product_code}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          開始日
          <input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
        </label>
        <label className={styles.field}>
          終了日
          <input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
        </label>
        <label className={styles.field} style={{ flex: 1 }}>
          内容
          <input value={form.description} maxLength={128} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </label>
        <button type="submit" className={styles.primary}>
          {editingId === null ? "登録" : "更新"}
        </button>
        {editingId !== null && (
          <button type="button" onClick={resetForm}>
            取消
          </button>
        )}
        </div>
      </form>

      <div className={styles.toolbar}>
        <label className={styles.field}>
          表示期間(開始)
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className={styles.field}>
          表示期間(終了)
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
      </div>

      {rows.length === 0 ? (
        <p className={styles.muted}>この期間の特売・チラシはありません。</p>
      ) : (
        <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>商品</th>
              <th>部門</th>
              <th>期間</th>
              <th>内容</th>
              <th>登録者</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id}>
                <td className={styles.name}>{p.product_name}</td>
                <td>{p.department_name}</td>
                <td>
                  {shortDate(p.start_date)}〜{shortDate(p.end_date)}
                </td>
                <td>{p.description}</td>
                <td>{p.created_by_name ?? "システム"}</td>
                <td>
                  {accessible.has(p.department_code) && (
                    <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                      <button type="button" className={styles.secondary} onClick={() => startEdit(p)}>
                        編集
                      </button>
                      <button type="button" className={styles.secondary} onClick={() => setDeleting(p)}>
                        削除
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}

      <ConfirmDialog
        open={deleting !== null}
        message="この特売を削除しますか?"
        onConfirm={onDelete}
        onCancel={() => setDeleting(null)}
      />
    </section>
  );
}
