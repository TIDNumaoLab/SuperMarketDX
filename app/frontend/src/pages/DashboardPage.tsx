// 今日の状況(/dashboard): ログイン後のホーム画面(詳細設計書「今日の状況(/dashboard)」)。
// 表示は開いた時点の内容で、進捗の取得や自動の取り直しはしない。最新の提案は各画面を開いたときに表示する
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { errorMessage } from "../api/client";
import { getDashboard } from "../api/dashboard";
import ErrorBanner from "../components/ErrorBanner";
import proposalStyles from "../components/Proposals.module.css";
import { WARNING_LABELS, formatMonthDay, formatShortDateTime, formatTime, jstToday } from "../format";
import type { Dashboard, DashboardDeadline, DashboardDepartment } from "../types/api";
import styles from "./Dashboard.module.css";
import {
  type Axis,
  type MarkState,
  type TimelineMark,
  formatRemaining,
  marksByDeadline,
  markState,
  minutesLeft,
  positionPercent,
  staggerAbove,
  timelineAxis,
} from "./dashboardTimeline";

const WEEKDAYS = ["日", "月", "火", "水", "木", "金", "土"];

// 日付(YYYY-MM-DD)の曜日。曜日の計算だけに使うので UTC で日付を作る
function weekday(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  return WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
}

function jstDate(iso: string): string {
  return jstToday(0, new Date(iso));
}

function headline(now: string): string {
  const date = jstDate(now);
  const [, m, d] = date.split("-").map(Number);
  return `${m}月${d}日(${weekday(date)}) ${formatTime(now)} 現在`;
}

function isProduction(d: DashboardDepartment): boolean {
  return d.business_type === "production";
}

// 例: 10/17 納品分、10/17 10時の部
function targetLabel(g: DashboardDeadline): string {
  const day = formatMonthDay(g.target_date);
  return g.time_band === null ? `${day} 納品分` : `${day} ${g.time_band}時の部`;
}

function screenLink(d: DashboardDepartment, g: DashboardDeadline): string {
  const params = new URLSearchParams({ department: d.department_code, target_date: g.target_date });
  return `${isProduction(d) ? "/production" : "/orders"}?${params}`;
}

// まとめた印の対象。例: 10/17 納品分、10/17・10/18 納品分
function markTargetLabel(m: TimelineMark): string {
  if (m.groups.length === 1) return targetLabel(m.groups[0]);
  return `${m.groups.map((g) => formatMonthDay(g.target_date)).join("・")} 納品分`;
}

// 納品日の違うまとまりをまとめた印は、対象日を選ばず既定表示(各商品の最も早い納品日)で開く
function markLink(d: DashboardDepartment, m: TimelineMark): string {
  if (m.groups.length === 1) return screenLink(d, m.groups[0]);
  return `${isProduction(d) ? "/production" : "/orders"}?${new URLSearchParams({ department: d.department_code })}`;
}

function stateText(state: MarkState, g: TimelineMark, now: Date): string {
  if (state === "done") return "締め済み";
  if (state === "missed") return `締め済み 期限切れ${g.expired}件`;
  if (state === "ready") return "全件承認済み";
  const text = `未承認${g.pending}件`;
  return state === "urgent" ? `${text} ${formatRemaining(minutesLeft(g.deadline, now))}` : text;
}

// 印の中: 未承認の件数。締め済み・全件承認済みは ✓、期限切れがあれば「!」と期限切れの件数
function pinText(state: MarkState, g: TimelineMark): string {
  if (state === "missed") return `!${g.expired}`;
  return state === "done" || state === "ready" ? "✓" : String(g.pending);
}

const LANE_NOTE = { order: "発注締め", production: "今日の製造開始" } as const;

function Timeline({ data, axis }: { data: Dashboard; axis: Axis }) {
  const now = new Date(data.now);
  const today = jstDate(data.now);
  const nowPos = positionPercent(data.now, axis);
  const hours = Array.from({ length: axis.endHour - axis.startHour + 1 }, (_, i) => axis.startHour + i);
  return (
    <section className={styles.day} aria-labelledby="day-h">
      <h2 id="day-h">今日の締め時刻</h2>
      <p className={styles.lead}>印の中の数字は未承認の件数です(「!」は未承認のまま締めを過ぎた件数)。印を押すとその部門の画面を開きます。</p>
      <div className={styles.axis} aria-hidden="true">
        <div />
        <div className={styles.track}>
          {hours.map((h) => (
            <span key={h} style={{ left: `${((h - axis.startHour) / (axis.endHour - axis.startHour)) * 100}%` }}>
              {h}時
            </span>
          ))}
        </div>
      </div>
      <div className={styles.lanes}>
        {data.departments.map((d) => {
          const marks = marksByDeadline(
            data.deadlines.filter((g) => g.department_code === d.department_code && jstDate(g.deadline) === today),
          );
          const positions = marks.map((m) => positionPercent(m.deadline, axis));
          const above = staggerAbove(positions, 12);
          return (
            <div key={d.department_code} className={styles.lane}>
              <div className={styles.name}>
                {d.department_name}
                <small>{LANE_NOTE[d.business_type]}</small>
              </div>
              <div className={styles.laneTrack}>
                {marks.map((g, i) => {
                  const state = markState(g, now);
                  const kind = isProduction(d) ? "製造開始" : "発注締め";
                  const band = g.groups[0].time_band;
                  const label = `${formatTime(g.deadline)} ${band === null ? "締め" : `${band}時の部`}`;
                  return (
                    <Link
                      key={g.deadline}
                      to={markLink(d, g)}
                      className={`${styles.mark} ${styles[state]} ${above[i] ? styles.above : ""}`}
                      style={{ left: `${positions[i]}%` }}
                      aria-label={`${d.department_name} ${markTargetLabel(g)} ${kind} ${formatTime(g.deadline)} ${stateText(state, g, now)}`}
                    >
                      <span className={styles.pin}>{pinText(state, g)}</span>
                      <span className={styles.t}>
                        {label}
                        {state === "urgent" && ` ${formatRemaining(minutesLeft(g.deadline, now))}`}
                        {state === "missed" && ` 期限切れ${g.expired}件`}
                      </span>
                    </Link>
                  );
                })}
              </div>
            </div>
          );
        })}
        {nowPos >= 0 && nowPos <= 100 && (
          <div className={styles.nowline} style={{ left: `calc(var(--name-width) + var(--gutter) + (100% - var(--name-width) - 2 * var(--gutter)) * ${nowPos / 100})` }}>
            <span>{formatTime(data.now)}</span>
          </div>
        )}
      </div>
      <div className={styles.legend} aria-hidden="true">
        <span className={styles.lDone}>締め済み</span>
        <span className={styles.lMissed}>期限切れあり</span>
        <span className={styles.lReady}>全件承認済み</span>
        <span className={styles.lPending}>未承認あり</span>
        <span className={styles.lUrgent}>締めまで1時間以内</span>
      </div>
    </section>
  );
}

function PendingList({ data }: { data: Dashboard }) {
  const now = new Date(data.now);
  const today = jstDate(data.now);
  const tomorrow = jstToday(1, now);
  const byCode = new Map(data.departments.map((d) => [d.department_code, d]));
  const rows = data.deadlines.filter((g) => g.pending > 0 && new Date(g.deadline) >= now);
  return (
    <section aria-labelledby="todo-h">
      <h2 id="todo-h" className={styles.h2}>
        締めが近い順の未承認
      </h2>
      {rows.length === 0 ? (
        <p className={styles.empty}>締めが近い未承認はありません。</p>
      ) : (
        <ol className={styles.todo} aria-labelledby="todo-h">
          {rows.map((g) => {
            const d = byCode.get(g.department_code);
            if (!d) return null;
            const left = minutesLeft(g.deadline, now);
            const day = jstDate(g.deadline);
            const prefix = day === today ? "" : day === tomorrow ? "明日 " : `${formatMonthDay(day)} `;
            const warned = g.warnings.length > 0;
            return (
              <li key={`${g.department_code}-${g.deadline}-${g.target_date}-${g.time_band}`} className={left <= 60 ? styles.urgent : ""}>
                <div className={styles.when} data-when>
                  {prefix}
                  {formatTime(g.deadline)}
                  <small>{formatRemaining(left)}</small>
                </div>
                <div className={styles.what}>
                  <span>{`${d.department_name} ${targetLabel(g)} 未承認${g.pending}件`}</span>
                  {g.warnings.map((w) => (
                    <span key={w.code} className={proposalStyles.warning}>{`${WARNING_LABELS[w.code]} ${w.count}件`}</span>
                  ))}
                  <small>
                    {`うち${g.bulk_approvable}件は一括承認できます。`}
                  </small>
                  {warned && <small>警告付きは一括承認から外れます。画面で確認してください。</small>}
                </div>
                <Link className={isProduction(d) ? styles.btnSub : styles.btn} to={screenLink(d, g)}>
                  {isProduction(d) ? "製造計画を開く" : "発注を開く"}
                </Link>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

function Tomorrow({ data }: { data: Dashboard }) {
  const t = data.tomorrow;
  const w = t.weather;
  const deg = (v: number | null) => (v === null ? "—" : `${v}℃`);
  return (
    <section aria-labelledby="facts-h">
      <h2 id="facts-h" className={styles.h2}>{`明日 ${formatMonthDay(t.date)}(${weekday(t.date)})の条件`}</h2>
      <dl className={styles.facts}>
        <div>
          <dt>天気</dt>
          <dd>
            {w ? (
              <>
                <span>{w.weather_label}</span>
                <small>
                  {`最高 ${deg(w.temperature)} / 最低 ${deg(w.temperature_min)}、降水量 ${w.precipitation ?? "—"}mm(${formatTime(w.fetched_at)} 取得)`}
                </small>
              </>
            ) : (
              "予報はまだ取得していません。"
            )}
          </dd>
        </div>
        <div>
          <dt>特売・チラシ</dt>
          <dd>
            {t.promotions.length === 0
              ? "なし"
              : t.promotions.map((p, i) => (
                  <span key={i}>
                    {`${p.department_name} ${p.product_name} ${p.description}(${formatMonthDay(p.start_date)}〜${formatMonthDay(p.end_date)})`}
                  </span>
                ))}
          </dd>
        </div>
        <div>
          <dt>祝日・行事</dt>
          <dd>{t.calendar.length === 0 ? "なし" : t.calendar.map((c, i) => <span key={i}>{c.name}</span>)}</dd>
        </div>
      </dl>
    </section>
  );
}

function jobText(d: DashboardDepartment): string {
  if (d.job?.status === "running") return "計算中(画面を開くと最新の結果を表示します)";
  if (d.last_job?.status === "failed") return `最新の予測の計算に失敗しました: ${d.last_job.error ?? ""}`;
  if (d.last_job?.finished_at) return `${formatShortDateTime(d.last_job.finished_at)} 計算済み`;
  return "—";
}

function DataStatus({ data }: { data: Dashboard }) {
  const today = jstDate(data.now);
  const byCode = new Map(data.departments.map((d) => [d.department_code, d]));
  return (
    <section aria-labelledby="data-h">
      <h2 id="data-h" className={styles.h2}>
        データの状態
      </h2>
      <table className={styles.status} aria-labelledby="data-h">
        <thead>
          <tr>
            <th>部門</th>
            <th>POS売上</th>
            <th>在庫</th>
            <th>提案の計算</th>
          </tr>
        </thead>
        <tbody>
          {data.data_status.map((s) => {
            const d = byCode.get(s.department_code);
            if (!d) return null;
            const pos = s.pos_latest_date
              ? `${formatMonthDay(s.pos_latest_date)} 分まで${s.pos_imported_at ? `(${formatShortDateTime(s.pos_imported_at)} 取込)` : ""}`
              : "未取込";
            const failed = !d.job && d.last_job?.status === "failed";
            return (
              <tr key={s.department_code}>
                <th scope="row">{d.department_name}</th>
                <td>
                  <span>{pos}</span>
                  {s.stale_pos && <span className={proposalStyles.warning}>POS未更新</span>}
                </td>
                <td>
                  {isProduction(d) ? (
                    "対象外"
                  ) : s.inventory_based_at && jstDate(s.inventory_based_at) === today ? (
                    <span>{formatShortDateTime(s.inventory_based_at)}</span>
                  ) : (
                    <>
                      <span className={styles.stale}>今日の在庫が未取込です</span>
                      {s.inventory_based_at && <small>{`(前回 ${formatShortDateTime(s.inventory_based_at)})`}</small>}
                    </>
                  )}
                </td>
                <td className={failed ? styles.stale : undefined}>{jobText(d)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDashboard()
      .then(setData)
      .catch((e) => setError(errorMessage(e)));
  }, []);

  const today = data ? jstDate(data.now) : "";
  const axis = data
    ? timelineAxis(
        data.business_hours.open,
        data.business_hours.close,
        data.deadlines.filter((g) => jstDate(g.deadline) === today).map((g) => g.deadline),
      )
    : null;

  return (
    <section>
      <div className={styles.head}>
        <h1>今日の状況</h1>
        {data && <span className={styles.now}>{headline(data.now)}</span>}
        <span className={styles.refresh}>画面を開いた時点の内容です</span>
      </div>
      <ErrorBanner message={error} />
      {data && data.departments.length === 0 && (
        <p className={styles.empty}>表示できる部門がありません。管理者に所属部門の登録を依頼してください。</p>
      )}
      {data && data.departments.length > 0 && (
        <>
          {axis && <Timeline data={data} axis={axis} />}
          <div className={styles.below}>
            <PendingList data={data} />
            <div>
              <Tomorrow data={data} />
              <DataStatus data={data} />
            </div>
          </div>
        </>
      )}
    </section>
  );
}
