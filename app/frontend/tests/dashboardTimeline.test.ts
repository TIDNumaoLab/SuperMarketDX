import { expect, test } from "vitest";
import {
  formatRemaining,
  markState,
  minutesLeft,
  positionPercent,
  staggerAbove,
  timelineAxis,
} from "../src/pages/dashboardTimeline";

const now = new Date("2026-10-16T14:20:00+09:00");

test("axis spans from the earlier of opening and first deadline to closing", () => {
  expect(timelineAxis("10:00", "20:00", ["2026-10-16T09:00:00+09:00", "2026-10-16T15:00:00+09:00"])).toEqual({
    startHour: 9,
    endHour: 20,
  });
  expect(timelineAxis("10:00", "20:30", [])).toEqual({ startHour: 10, endHour: 21 });
  // 期限が閉店より後なら、その正時まで広げる
  expect(timelineAxis("10:00", "20:00", ["2026-10-16T21:30:00+09:00"])).toEqual({ startHour: 10, endHour: 22 });
});

test("position is the share of the axis in JST", () => {
  const axis = { startHour: 9, endHour: 20 };
  expect(positionPercent("2026-10-16T09:00:00+09:00", axis)).toBe(0);
  expect(positionPercent("2026-10-16T20:00:00+09:00", axis)).toBe(100);
  expect(positionPercent(now.toISOString(), axis)).toBeCloseTo(48.48, 1);
});

test("mark state by deadline, pending count and remaining time", () => {
  const base = { pending: 2, expired: 0, deadline: "2026-10-16T15:00:00+09:00" };
  expect(markState(base, now)).toBe("urgent");
  expect(markState({ ...base, deadline: "2026-10-16T15:21:00+09:00" }, now)).toBe("pending");
  expect(markState({ ...base, pending: 0 }, now)).toBe("ready");
  // 期限ちょうどは締め済み
  expect(markState({ ...base, deadline: "2026-10-16T14:20:00+09:00" }, now)).toBe("done");
  // 未承認のまま締めを過ぎた提案があれば、締め済み(✓)にしない
  expect(markState({ ...base, expired: 1, deadline: "2026-10-16T14:20:00+09:00" }, now)).toBe("missed");
});

test("remaining time text", () => {
  expect(minutesLeft("2026-10-16T15:00:00+09:00", now)).toBe(40);
  expect(formatRemaining(40)).toBe("あと40分");
  expect(formatRemaining(130)).toBe("あと2時間10分");
  expect(formatRemaining(120)).toBe("あと2時間");
});

test("labels that would overlap alternate above", () => {
  expect(staggerAbove([0, 9.1, 36.4, 63.6], 12)).toEqual([false, true, false, false]);
  expect(staggerAbove([0, 5, 9], 12)).toEqual([false, true, false]);
});
