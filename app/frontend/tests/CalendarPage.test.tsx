import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import * as calendarApi from "../src/api/calendar";
import CalendarPage from "../src/pages/CalendarPage";
import { monthGrid } from "../src/pages/calendarGrid";
import { manager, renderPage } from "./helpers";

vi.mock("../src/api/auth");
vi.mock("../src/api/calendar");

test("monthGrid starts on Monday", () => {
  const g = monthGrid(2026, 10); // 2026-10-01 は木曜
  expect(g[0]).toEqual([null, null, null, "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]);
  expect(g.flat().filter(Boolean)).toHaveLength(31);
  expect(g.every((week) => week.length === 7)).toBe(true);
  expect(monthGrid(2026, 2)[0]).toEqual([null, null, null, null, null, null, "2026-02-01"]); // 日曜始まりの月
});

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-10T12:00:00+09:00"));
  vi.mocked(calendarApi.listCalendar).mockResolvedValue([
    { id: 1, date: "2026-11-03", kind: "holiday", name: "文化の日" },
    { id: 2, date: "2026-11-15", kind: "event", name: "七五三" },
  ]);
});

afterEach(() => {
  vi.useRealTimers();
});

test("calendar shows holiday and event, delete only for event", async () => {
  await renderPage(<CalendarPage />, manager(), "2026年11月");
  // 一覧の読み込みは描画の後に走るため、表示されるのを待ってから呼び出しを確かめる
  expect(await screen.findByText("文化の日")).toBeInTheDocument();
  expect(calendarApi.listCalendar).toHaveBeenCalledWith(2026);
  expect(screen.queryByRole("button", { name: "文化の日 を削除" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "七五三 を削除" })).toBeInTheDocument();
});

test("delete event asks confirmation then reloads", async () => {
  vi.mocked(calendarApi.deleteCalendarDay).mockResolvedValue();
  await renderPage(<CalendarPage />, manager(), "2026年11月");
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "七五三 を削除" }));
  const dialog = screen.getByRole("dialog");
  expect(dialog).toHaveTextContent("行事日「七五三」(2026-11-15)を削除しますか?");
  await user.click(within(dialog).getByRole("button", { name: "はい" }));
  expect(calendarApi.deleteCalendarDay).toHaveBeenCalledWith(2);
  expect(calendarApi.listCalendar).toHaveBeenCalledTimes(2);
});

test("register event and move months", async () => {
  vi.mocked(calendarApi.createCalendarDay).mockResolvedValue({ id: 3, date: "2026-11-20", kind: "event", name: "感謝祭" });
  await renderPage(<CalendarPage />, manager(), "2026年11月");
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("日付"), "2026-11-20");
  await user.type(screen.getByLabelText("名称"), "感謝祭");
  await user.click(screen.getByRole("button", { name: "行事日を登録" }));
  expect(calendarApi.createCalendarDay).toHaveBeenCalledWith({ date: "2026-11-20", kind: "event", name: "感謝祭" });
  await user.click(screen.getByRole("button", { name: "翌月" }));
  expect(screen.getByText("2026年12月")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "翌月" }));
  expect(await screen.findByText("2027年1月")).toBeInTheDocument();
  expect(calendarApi.listCalendar).toHaveBeenLastCalledWith(2027);
});

test("calendar marks weekends, holidays and today", async () => {
  await renderPage(<CalendarPage />, manager(), "2026年11月");
  await screen.findByText("文化の日");
  const cell = (day: string) => screen.getAllByRole("cell").find((c) => c.querySelector("div")?.firstChild?.textContent === day)!;
  expect(cell("3")).toHaveClass("hol"); // 祝日(火曜)
  expect(cell("7")).toHaveClass("sat");
  expect(cell("8")).toHaveClass("sun");
  expect(cell("9").className).toBe(""); // 平日は色分けなし
  // 今日は色だけでなく文字と aria-current でも示す
  expect(cell("10")).toHaveClass("today");
  expect(cell("10")).toHaveAttribute("aria-current", "date");
  expect(within(cell("10")).getByText("今日")).toBeInTheDocument();
  expect(cell("11")).not.toHaveAttribute("aria-current");
});
