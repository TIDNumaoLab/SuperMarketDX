// 今日の状況の時間軸の計算(詳細設計書「今日の状況(/dashboard)」)。時刻はすべて日本時間で扱う
import type { DashboardDeadline } from "../types/api";

export interface Axis {
  startHour: number;
  endHour: number;
}

// missed: 締め済みで、未承認のまま期限切れになった提案がある(発注・製造の漏れ)
export type MarkState = "done" | "missed" | "ready" | "pending" | "urgent";

// 締めまでこの分数以内で未承認が残っていれば急ぎ(赤)にする
export const URGENT_MINUTES = 60;

// 日本時間の時(小数。例: 14:30 → 14.5)
function jstHours(iso: string): number {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
      .formatToParts(new Date(iso))
      .map((x) => [x.type, x.value]),
  );
  return Number(p.hour) + Number(p.minute) / 60;
}

function clockHours(hhmm: string): number {
  const [h, m] = hhmm.split(":").map(Number);
  return h + m / 60;
}

// 横軸の範囲: 開店と当日の最初の期限の早い方の正時から、閉店(と最後の期限)の遅い方の正時まで
export function timelineAxis(open: string, close: string, deadlines: string[]): Axis {
  const hours = deadlines.map(jstHours);
  return {
    startHour: Math.floor(Math.min(clockHours(open), ...hours)),
    endHour: Math.ceil(Math.max(clockHours(close), ...hours)),
  };
}

export function positionPercent(iso: string, axis: Axis): number {
  return ((jstHours(iso) - axis.startHour) / (axis.endHour - axis.startHour)) * 100;
}

export function minutesLeft(deadline: string, now: Date): number {
  return Math.ceil((new Date(deadline).getTime() - now.getTime()) / 60000);
}

// 時間軸の印。生鮮はリードタイムにより同じ締め時刻に納品日の違うまとまりが並ぶので、同じ期限は1つの印にまとめる
// (惣菜は時間帯ごとに1つの印とし、まとめない)
export interface TimelineMark {
  deadline: string;
  groups: DashboardDeadline[];
  pending: number;
  expired: number;
}

export function marksByDeadline(groups: DashboardDeadline[], merge: boolean): TimelineMark[] {
  const out = new Map<string, TimelineMark>();
  for (const g of groups) {
    const key = merge ? g.deadline : `${g.deadline}-${g.target_date}-${g.time_band}`;
    const m = out.get(key) ?? { deadline: g.deadline, groups: [], pending: 0, expired: 0 };
    m.groups.push(g);
    m.pending += g.pending;
    m.expired += g.expired;
    out.set(key, m);
  }
  return [...out.values()];
}

export function markState(d: Pick<DashboardDeadline, "pending" | "expired" | "deadline">, now: Date): MarkState {
  const left = minutesLeft(d.deadline, now);
  if (left <= 0) return d.expired > 0 ? "missed" : "done";
  if (d.pending === 0) return "ready";
  return left <= URGENT_MINUTES ? "urgent" : "pending";
}

export function formatRemaining(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `あと${m}分`;
  return m === 0 ? `あと${h}時間` : `あと${h}時間${m}分`;
}

// 位置(%)が近くて文字が重なる印を、上下に振り分ける(true は印の上に書く)
export function staggerAbove(positions: number[], minGap: number): boolean[] {
  const out: boolean[] = [];
  let lastBelow = -Infinity;
  for (const p of positions) {
    const above = p - lastBelow < minGap && out[out.length - 1] === false;
    out.push(above);
    if (!above) lastBelow = p;
  }
  return out;
}
