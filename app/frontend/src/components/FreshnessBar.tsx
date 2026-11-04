// 鮮度の表示と再計算ボタン。再計算中は進捗を出し、ボタンを無効にする
import { formatFreshness, formatRunning } from "../format";
import pageStyles from "../styles/page.module.css";
import type { Freshness, Job } from "../types/api";
import styles from "./Proposals.module.css";

interface Props {
  freshness: Freshness | null;
  job: Job | null;
  onRecalculate(): void;
}

export default function FreshnessBar({ freshness, job, onRecalculate }: Props) {
  const running = job?.status === "running";
  return (
    <div className={styles.freshness}>
      <span aria-live="polite">
        {running && job ? formatRunning(job) : freshness ? formatFreshness(freshness) : ""}
      </span>
      <button type="button" className={pageStyles.secondary} onClick={onRecalculate} disabled={running}>
        再計算
      </button>
    </div>
  );
}
