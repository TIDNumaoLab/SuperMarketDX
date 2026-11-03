// 再計算値との差分と「採用」ボタン(再計算値があるときだけ表示)
import { formatDiff } from "../format";
import pageStyles from "../styles/page.module.css";
import styles from "./Proposals.module.css";

interface Props {
  proposed: number;
  recalculated: number | null;
  canAdopt: boolean;
  onAdopt(): void;
}

export default function DiffBadge({ proposed, recalculated, canAdopt, onAdopt }: Props) {
  if (recalculated === null) {
    return null;
  }
  return (
    <>
      <span className={styles.diff}>{formatDiff(proposed, recalculated)}</span>
      {canAdopt && (
        <button type="button" className={pageStyles.quiet} onClick={onAdopt}>
          採用
        </button>
      )}
    </>
  );
}
