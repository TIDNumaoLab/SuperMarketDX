// 提案の表(生鮮は1行1商品、惣菜は1行1商品×時間帯)。空なら空状態の文言を出す(再計算中は計算中の文言)
import pageStyles from "../styles/page.module.css";
import type { AdjustReason, Proposal } from "../types/api";
import ProposalRow from "./ProposalRow";
import styles from "./Proposals.module.css";

interface Props {
  proposals: Proposal[];
  selected: Set<number>;
  skipped: Map<number, string>;
  approveLocked: boolean;
  // 再計算ジョブの実行中
  computing?: boolean;
  onSelect(id: number, checked: boolean): void;
  onSave(p: Proposal, quantity: number, reason: AdjustReason, note: string | undefined): Promise<void>;
  onApprove(p: Proposal): void;
  onCancel(p: Proposal): void;
  onAdopt(p: Proposal): void;
  onDirtyChange?(id: number, dirty: boolean): void;
  // 惣菜の製造計画として表示する場合の、時間帯の表示(時間帯の開始時 → 例: 11:00〜14:00)
  bandLabel?(band: number): string;
}

const ORDER_HEADERS = ["選択", "納品日", "商品", "提案数", "予測値", "天候", "祝日・特売", "前週同曜日", "在庫・発注残・持越見込", "状態", "警告", "差分", "操作"];
const PRODUCTION_HEADERS = ["選択", "時間帯", "製造開始", "商品", "提案数", "予測値", "天候", "祝日・特売", "前週同曜日", "陳列残数", "状態", "警告", "差分", "操作"];

export default function ProposalTable({ proposals, selected, skipped, approveLocked, computing = false, onSelect, onSave, onApprove, onCancel, onAdopt, onDirtyChange, bandLabel }: Props) {
  if (proposals.length === 0) {
    return (
      <p className={pageStyles.muted}>
        {computing ? "最新の予測を計算中です。完了すると表示します。" : "この条件の提案はありません。"}
      </p>
    );
  }
  return (
    <div className={pageStyles.tableWrap}>
    <table className={`${pageStyles.table} ${styles.table}`}>
      <thead>
        <tr>
          {(bandLabel ? PRODUCTION_HEADERS : ORDER_HEADERS).map((h) => (
            <th key={h}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {proposals.map((p) => (
          <ProposalRow
            key={p.id}
            proposal={p}
            selected={selected.has(p.id)}
            skippedReason={skipped.get(p.id) ?? null}
            approveLocked={approveLocked}
            onSelect={(checked) => onSelect(p.id, checked)}
            onSave={(q, r, n) => onSave(p, q, r, n)}
            onApprove={() => onApprove(p)}
            onCancel={() => onCancel(p)}
            onAdopt={() => onAdopt(p)}
            onDirtyChange={onDirtyChange}
            bandLabel={bandLabel && p.time_band !== null ? bandLabel(p.time_band) : undefined}
          />
        ))}
      </tbody>
    </table>
    </div>
  );
}
