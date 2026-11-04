// 提案の表の1行(生鮮は1商品、惣菜は商品×時間帯)。未承認は提案数を入力でき、数量を変えたら修正理由を選んで保存する
import { useEffect, useState } from "react";
import { formatMonthDay, formatTime, STATUS_LABELS } from "../format";
import pageStyles from "../styles/page.module.css";
import type { AdjustReason, Proposal } from "../types/api";
import AdjustReasonSelect from "./AdjustReasonSelect";
import DiffBadge from "./DiffBadge";
import styles from "./Proposals.module.css";
import WarningBadge from "./WarningBadge";

interface Props {
  proposal: Proposal;
  selected: boolean;
  // 一括承認で除外された理由
  skippedReason: string | null;
  // 再計算中は承認できない(表示中の数量がまもなく置き換わるため)
  approveLocked?: boolean;
  onSelect(checked: boolean): void;
  onSave(quantity: number, reason: AdjustReason, note: string | undefined): Promise<void>;
  onApprove(): void;
  onCancel(): void;
  onAdopt(): void;
  // 保存していない数量の入力があるかが変わったとき(id は提案の ID)
  onDirtyChange?(id: number, dirty: boolean): void;
  // 惣菜の時間帯の表示(例: 11:00〜14:00)。あれば製造計画の行として、納品日と在庫の列の代わりに時間帯・製造開始・陳列残数を出す
  bandLabel?: string;
}

function num(v: number | null, digits?: number): string {
  if (v === null) return "—";
  return digits === undefined ? String(v) : v.toFixed(digits);
}

function weatherText(p: Proposal): string {
  if (p.weather_label === null) return "—";
  const parts = [p.weather_label];
  // 惣菜の時間帯の平均気温は割り切れない値になるため、予測値と同じく小数第1位で表示する
  if (p.temperature !== null) parts.push(`${num(p.temperature, 1)}℃`);
  if (p.precipitation_probability !== null) parts.push(`${p.precipitation_probability}%`);
  return parts.join(" ");
}

export default function ProposalRow({ proposal: p, selected, skippedReason, approveLocked = false, onSelect, onSave, onApprove, onCancel, onAdopt, onDirtyChange, bandLabel }: Props) {
  const [qty, setQty] = useState(String(p.proposed_qty));
  const [reason, setReason] = useState<AdjustReason | "">("");
  const [note, setNote] = useState("");
  // 保存・承認などで提案数や状態が変わったら入力欄を新しい値に戻す。
  // updated_at は再計算で提案数が同じでも変わるため、きっかけにしない(保存していない入力を消さないように)
  useEffect(() => {
    setQty(String(p.proposed_qty));
    setReason("");
    setNote("");
  }, [p.proposed_qty, p.status, p.is_adjusted, p.adjust_reason]);

  const pending = p.status === "pending";
  const approved = p.status === "approved" || p.status === "confirmed";
  const beforeDeadline = Date.now() < new Date(p.deadline).getTime();
  const dirty = qty !== String(p.proposed_qty);
  useEffect(() => {
    onDirtyChange?.(p.id, dirty);
  }, [p.id, dirty, onDirtyChange]);
  // 行が消えたら入力も無くなる
  useEffect(() => () => onDirtyChange?.(p.id, false), [p.id, onDirtyChange]);
  // 惣菜は同じ商品が時間帯ごとに並ぶので、入力欄の名前に時間帯を含める
  const production = bandLabel !== undefined;
  const isInteger = /^\d+$/.test(qty.trim());
  // 生鮮は発注単位(入数)の倍数だけ保存できる(惣菜の製造数は発注単位で丸めない)
  const unitError = !production && isInteger && Number(qty.trim()) % p.order_unit !== 0;
  const valid = isInteger && !unitError;
  const name = production ? `${p.product_name} ${bandLabel}` : p.product_name;

  return (
    <tr className={[p.warnings.length > 0 && styles.warned, approved && styles.done].filter(Boolean).join(" ") || undefined}>
      <td>
        <input
          type="checkbox"
          aria-label={`${name} を選択`}
          checked={selected}
          disabled={!pending}
          onChange={(e) => onSelect(e.target.checked)}
        />
      </td>
      {production ? (
        <>
          <td>{bandLabel}</td>
          <td>{formatTime(p.deadline)}</td>
        </>
      ) : (
        <td>{formatMonthDay(p.target_date)}</td>
      )}
      <td>
        <div className={styles.productName}>{p.product_name}</div>
        <div className={pageStyles.muted}>入数 {p.order_unit}</div>
      </td>
      <td>
        {pending ? (
          <>
            <input
              type="number"
              min={0}
              step={production ? 1 : p.order_unit}
              className={`${styles.qty} ${dirty ? styles.changed : ""}`}
              aria-label={`${name} の提案数`}
              value={qty}
              onChange={(e) => setQty(e.target.value)}
            />
            {dirty && unitError && <div className={styles.skipped}>発注単位({p.order_unit})の倍数で入力してください</div>}
            {dirty && (
              <div className={styles.reason}>
                <AdjustReasonSelect label={`${name} の修正理由`} value={reason} onChange={setReason} />
                <input aria-label={`${name} の修正理由の補足`} placeholder="補足(任意)" maxLength={128} value={note}
                  onChange={(e) => setNote(e.target.value)} />
              </div>
            )}
          </>
        ) : (
          <span className={styles.qtyStatic}>{p.proposed_qty}</span>
        )}
        {p.is_adjusted && <div className={pageStyles.muted}>修正前 {p.original_qty}</div>}
      </td>
      <td className={`${pageStyles.num} ${styles.predict}`}>
        {num(p.predicted_qty, 1)}
        {p.is_baseline && <div className={styles.badge}>ベースライン予測</div>}
      </td>
      <td>{weatherText(p)}</td>
      <td>
        {p.is_holiday && <span className={`${styles.badge} ${styles.holiday}`}>{p.holiday_name ?? "祝日"}</span>}
        {p.is_event_day && <span className={styles.badge}>行事日</span>}
        {p.is_promotion && <span className={styles.badge}>特売</span>}
      </td>
      <td className={pageStyles.num}>{num(p.sales_lag_7d)}</td>
      {production ? (
        <td className={pageStyles.num}>{num(p.display_stock_qty)}</td>
      ) : (
        <td>{`在庫 ${num(p.inventory_qty)} / 発注残 ${num(p.backlog_qty)} / 持越 ${num(p.carry_over_qty)}`}</td>
      )}
      <td>
        {/* 承認者は印の形で出す(確定は塗りつぶし) */}
        <div className={styles.state}>
          {STATUS_LABELS[p.status]}
          {p.approved_by_name && (
            <span className={`${styles.stamp} ${p.status === "confirmed" ? styles.confirmed : ""}`} title={`承認者 ${p.approved_by_name}`}>
              {p.approved_by_name}
            </span>
          )}
        </div>
      </td>
      <td>
        {p.warnings.map((w) => (
          <WarningBadge key={w} code={w} />
        ))}
        {skippedReason && <div className={styles.skipped}>{skippedReason}</div>}
      </td>
      <td>
        <DiffBadge
          proposed={p.proposed_qty}
          recalculated={p.recalculated_qty}
          canAdopt={pending || (p.status === "approved" && beforeDeadline)}
          onAdopt={onAdopt}
        />
      </td>
      <td>
        <div className={styles.actions}>
          {pending && dirty && (
            <button
              type="button"
              className={`${pageStyles.primary} ${pageStyles.small}`}
              disabled={!valid || reason === ""}
              onClick={() => void onSave(Number(qty.trim()), reason as AdjustReason, note.trim() || undefined)}
            >
              保存
            </button>
          )}
          {pending && !dirty && (
            <button type="button" className={`${pageStyles.primary} ${pageStyles.small}`} onClick={onApprove} disabled={approveLocked}>
              承認
            </button>
          )}
          {p.status === "approved" && beforeDeadline && (
            <button type="button" className={pageStyles.quiet} onClick={onCancel}>
              取消
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
