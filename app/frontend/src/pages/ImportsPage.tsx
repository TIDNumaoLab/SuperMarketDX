// データ取込(/imports): 種類と部門を選んで CSV をアップロードし、結果と取込履歴を表示する
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { errorMessage } from "../api/client";
import { listImports, uploadImport } from "../api/imports";
import { useAuth } from "../auth/AuthContext";
import DepartmentSelect from "../components/DepartmentSelect";
import ErrorBanner from "../components/ErrorBanner";
import { formatShortDateTime } from "../format";
import styles from "../styles/page.module.css";
import type { ImportKind, ImportLog } from "../types/api";

export const KIND_LABELS: Record<ImportKind, string> = {
  products: "商品マスタ",
  pos: "POS売上",
  inventory: "在庫",
  waste: "廃棄",
};

export default function ImportsPage() {
  const { me } = useAuth();
  const isManager = me?.role === "manager";
  const kinds: ImportKind[] = isManager ? ["products", "pos", "inventory", "waste"] : ["pos", "inventory", "waste"];
  const [kind, setKind] = useState<ImportKind>("pos");
  const [department, setDepartment] = useState(me?.accessible_departments[0]?.code ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportLog | null>(null);
  const [history, setHistory] = useState<ImportLog[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const deptName = (code: string | null) =>
    code ? (me?.accessible_departments.find((d) => d.code === code)?.name ?? code) : "—";

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await listImports());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await uploadImport(kind, file, kind === "products" ? undefined : department));
      await loadHistory();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <div className={styles.head}>
        <div>
          <h1>データ取込</h1>
          {/* Excel で保存し直すと Shift_JIS や 2026/10/15 の形式になりやすいため、形式を書いておく */}
          <p className={styles.sub}>標準取込形式の CSV(文字コードは UTF-8、日付は YYYY-MM-DD)を選んでください。</p>
        </div>
      </div>
      <ErrorBanner message={error} />
      <div className={styles.cols}>
        {/* 種類・部門・ファイルを選ぶ順に並べる */}
        <form className={styles.panel} onSubmit={onSubmit}>
          <ol className={styles.steps}>
            <li>
              <label className={styles.field}>
                種類
                <select value={kind} onChange={(e) => setKind(e.target.value as ImportKind)}>
                  {kinds.map((k) => (
                    <option key={k} value={k}>
                      {KIND_LABELS[k]}
                    </option>
                  ))}
                </select>
              </label>
            </li>
            {kind !== "products" && (
              <li>
                <DepartmentSelect value={department} onChange={setDepartment} />
              </li>
            )}
            <li>
              <label className={styles.field}>
                CSVファイル
                <input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </label>
            </li>
          </ol>
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
            <button type="submit" className={styles.primary} disabled={!file || busy}>
              取り込む
            </button>
          </div>
        </form>

        <div className={styles.panel}>
          <h2>取込結果</h2>
          {result ? (
            <>
              <div className={result.skipped_count > 0 ? styles.warnNotice : styles.notice}>
                取込 {result.imported_count}件、スキップ {result.skipped_count}件
              </div>
              {result.errors.length > 0 && (
                <>
                  <p className={styles.muted}>スキップした行は直して取り込み直してください。</p>
                  <ul style={{ margin: 0, paddingLeft: 18, fontSize: 14 }}>
                    {result.errors.map((er) => (
                      <li key={er.row}>
                        {er.row}行目: {er.reason}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          ) : (
            <p className={styles.muted}>取り込むと、ここに件数とスキップした行が出ます。</p>
          )}
        </div>
      </div>

      <div className={styles.section}>
        <h2>取込履歴</h2>
        {history.length === 0 ? (
          <p className={styles.muted}>取込履歴はありません。</p>
        ) : (
          <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>日時</th>
                <th>種類</th>
                <th>部門</th>
                <th>ファイル</th>
                <th className={styles.num}>取込</th>
                <th className={styles.num}>スキップ</th>
                <th>取込者</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.id}>
                  <td>{formatShortDateTime(h.finished_at)}</td>
                  <td>{KIND_LABELS[h.kind]}</td>
                  <td>{deptName(h.department_code)}</td>
                  <td>{h.file_name}</td>
                  <td className={styles.num}>{h.imported_count}</td>
                  <td className={styles.num}>{h.skipped_count}</td>
                  <td>{h.imported_by_name ?? "システム"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </div>
    </section>
  );
}
