import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import * as dashboardApi from "../src/api/dashboard";
import DashboardPage from "../src/pages/DashboardPage";
import type { Dashboard, DashboardDeadline } from "../src/types/api";
import { DELI, FISH, VEG, manager, renderPage, staff } from "./helpers";

vi.mock("../src/api/auth");
vi.mock("../src/api/dashboard");

function deadline(over: Partial<DashboardDeadline>): DashboardDeadline {
  return {
    department_code: "VEG",
    deadline: "2026-10-16T15:00:00+09:00",
    target_date: "2026-10-17",
    time_band: null,
    pending: 0,
    approved: 0,
    confirmed: 0,
    expired: 0,
    bulk_approvable: 0,
    warnings: [],
    ...over,
  };
}

function dashboard(over: Partial<Dashboard> = {}): Dashboard {
  return {
    now: "2026-10-16T14:20:00+09:00",
    business_hours: { open: "10:00", close: "20:00" },
    departments: [
      { department_code: "DELI", department_name: "惣菜", business_type: "production", job: null, last_job: null },
      { department_code: "FISH", department_name: "鮮魚", business_type: "order", job: null, last_job: null },
      { department_code: "VEG", department_name: "青果", business_type: "order", job: null, last_job: null },
    ],
    deadlines: [
      deadline({ department_code: "DELI", deadline: "2026-10-16T09:00:00+09:00", target_date: "2026-10-16", time_band: 10, confirmed: 5 }),
      deadline({ pending: 2, approved: 3, bulk_approvable: 1, warnings: [{ code: "NO_INVENTORY", count: 1 }] }),
      deadline({ department_code: "FISH", deadline: "2026-10-16T16:30:00+09:00", pending: 4, bulk_approvable: 3 }),
      deadline({ department_code: "DELI", deadline: "2026-10-17T09:00:00+09:00", target_date: "2026-10-17", time_band: 10, pending: 18, bulk_approvable: 18 }),
    ],
    tomorrow: {
      date: "2026-10-17",
      weather: { weather_code: 61, weather_label: "雨", temperature: 14, temperature_min: 9, precipitation: 6, fetched_at: "2026-10-16T10:05:00+09:00" },
      promotions: [{ department_name: "青果", product_name: "りんご", start_date: "2026-10-16", end_date: "2026-10-18", description: "2割引" }],
      calendar: [{ kind: "event", name: "ハロウィン" }],
    },
    data_status: [
      { department_code: "DELI", pos_latest_date: "2026-10-15", pos_imported_at: "2026-10-16T07:40:00+09:00", inventory_based_at: null, stale_pos: false },
      { department_code: "FISH", pos_latest_date: "2026-10-15", pos_imported_at: null, inventory_based_at: "2026-10-16T08:15:00+09:00", stale_pos: false },
      { department_code: "VEG", pos_latest_date: "2026-10-13", pos_imported_at: null, inventory_based_at: "2026-10-15T19:00:00+09:00", stale_pos: true },
    ],
    ...over,
  };
}

beforeEach(() => {
  vi.mocked(dashboardApi.getDashboard).mockResolvedValue(dashboard());
});

afterEach(() => {
  vi.clearAllMocks();
});

test("shows the time of the snapshot", async () => {
  await renderPage(<DashboardPage />, manager(), "今日の状況");
  expect(await screen.findByText("10月16日(金) 14:20 現在")).toBeInTheDocument();
  expect(screen.getByText("画面を開いた時点の内容です")).toBeInTheDocument();
});

test("timeline marks link to the department screen with the target date", async () => {
  await renderPage(<DashboardPage />, manager(), "今日の状況");
  const veg = await screen.findByRole("link", { name: "青果 10/17 納品分 発注締め 15:00 未承認2件 あと40分" });
  expect(veg).toHaveAttribute("href", "/orders?department=VEG&target_date=2026-10-17");
  expect(within(veg).getByText("2")).toBeInTheDocument();
  const deli = screen.getByRole("link", { name: "惣菜 10/16 10時の部 製造開始 09:00 締め済み" });
  expect(deli).toHaveAttribute("href", "/production?department=DELI&target_date=2026-10-16");
  expect(within(deli).getByText("✓")).toBeInTheDocument();
  // 翌日の期限は時間軸に出さない(下の一覧にだけ出す)
  expect(screen.queryByRole("link", { name: /10\/17 10時の部 製造開始/ })).not.toBeInTheDocument();
});

test("a closed deadline with expired proposals is not shown as done", async () => {
  vi.mocked(dashboardApi.getDashboard).mockResolvedValue(
    dashboard({ deadlines: [deadline({ deadline: "2026-10-16T09:00:00+09:00", target_date: "2026-10-16", approved: 3, expired: 2 })] }),
  );
  await renderPage(<DashboardPage />, manager(), "今日の状況");
  const veg = await screen.findByRole("link", { name: "青果 10/16 納品分 発注締め 09:00 締め済み 期限切れ2件" });
  expect(within(veg).getByText("!2")).toBeInTheDocument();
  expect(within(veg).queryByText("✓")).not.toBeInTheDocument();
});

test("groups with the same deadline in a lane share one mark", async () => {
  vi.mocked(dashboardApi.getDashboard).mockResolvedValue(
    dashboard({
      deadlines: [
        deadline({ pending: 2 }),
        deadline({ target_date: "2026-10-18", pending: 1, expired: 0 }),
      ],
    }),
  );
  await renderPage(<DashboardPage />, manager(), "今日の状況");
  const veg = await screen.findByRole("link", { name: "青果 10/17・10/18 納品分 発注締め 15:00 未承認3件 あと40分" });
  // 納品日の違うまとまりは、対象日を選ばず既定表示で開く
  expect(veg).toHaveAttribute("href", "/orders?department=VEG");
  expect(within(veg).getByText("3")).toBeInTheDocument();
});

test("a merged mark with expired proposals opens the earliest expired delivery date", async () => {
  vi.mocked(dashboardApi.getDashboard).mockResolvedValue(
    dashboard({
      deadlines: [
        deadline({ deadline: "2026-10-16T09:00:00+09:00", target_date: "2026-10-17", approved: 2 }),
        deadline({ deadline: "2026-10-16T09:00:00+09:00", target_date: "2026-10-18", expired: 1 }),
      ],
    }),
  );
  await renderPage(<DashboardPage />, manager(), "今日の状況");
  const veg = await screen.findByRole("link", { name: "青果 10/17・10/18 納品分 発注締め 09:00 締め済み 期限切れ1件" });
  expect(veg).toHaveAttribute("href", "/orders?department=VEG&target_date=2026-10-18");
});

test("deli bands with the same production start keep separate marks", async () => {
  vi.mocked(dashboardApi.getDashboard).mockResolvedValue(
    dashboard({
      deadlines: [
        deadline({ department_code: "DELI", deadline: "2026-10-16T16:00:00+09:00", target_date: "2026-10-16", time_band: 17, pending: 1 }),
        deadline({ department_code: "DELI", deadline: "2026-10-16T16:00:00+09:00", target_date: "2026-10-16", time_band: 18, pending: 2 }),
      ],
    }),
  );
  await renderPage(<DashboardPage />, manager(), "今日の状況");
  expect(await screen.findByRole("link", { name: "惣菜 10/16 17時の部 製造開始 16:00 未承認1件" })).toHaveAttribute(
    "href",
    "/production?department=DELI&target_date=2026-10-16",
  );
  expect(screen.getByRole("link", { name: "惣菜 10/16 18時の部 製造開始 16:00 未承認2件" })).toBeInTheDocument();
});

test("lists pending groups by deadline with warnings and bulk count", async () => {
  await renderPage(<DashboardPage />, manager(), "今日の状況");
  const list = await screen.findByRole("list", { name: "締めが近い順の未承認" });
  const items = within(list).getAllByRole("listitem");
  expect(items.map((li) => li.querySelector("[data-when]")?.textContent)).toEqual([
    "15:00あと40分",
    "16:30あと2時間10分",
    "明日 09:00あと18時間40分",
  ]);
  expect(within(items[0]).getByText("青果 10/17 納品分 未承認2件")).toBeInTheDocument();
  expect(within(items[0]).getByText("在庫未取込 1件")).toBeInTheDocument();
  expect(within(items[0]).getByText(/警告付きは一括承認から外れます/)).toBeInTheDocument();
  // 警告があっても一括承認できる件数を出す
  expect(within(items[0]).getByText("うち1件は一括承認できます。")).toBeInTheDocument();
  expect(within(items[1]).getByText("うち3件は一括承認できます。")).toBeInTheDocument();
  expect(within(items[2]).getByText("惣菜 10/17 10時の部 未承認18件")).toBeInTheDocument();
  expect(within(items[2]).getByRole("link", { name: "製造計画を開く" })).toHaveAttribute(
    "href",
    "/production?department=DELI&target_date=2026-10-17",
  );
});

test("shows tomorrow conditions and data status", async () => {
  await renderPage(<DashboardPage />, manager(), "今日の状況");
  expect(await screen.findByText("明日 10/17(土)の条件")).toBeInTheDocument();
  expect(screen.getByText("雨")).toBeInTheDocument();
  expect(screen.getByText("最高 14℃ / 最低 9℃、降水量 6mm(10:05 取得)")).toBeInTheDocument();
  expect(screen.getByText("青果 りんご 2割引(10/16〜10/18)")).toBeInTheDocument();
  expect(screen.getByText("ハロウィン")).toBeInTheDocument();
  const status = screen.getByRole("table", { name: "データの状態" });
  const veg = within(status).getByRole("row", { name: /青果/ });
  expect(within(veg).getByText("POS未更新")).toBeInTheDocument();
  expect(within(veg).getByText("今日の在庫が未取込です")).toBeInTheDocument();
  const fish = within(status).getByRole("row", { name: /鮮魚/ });
  expect(within(fish).getByText("10/16 08:15")).toBeInTheDocument();
  const deli = within(status).getByRole("row", { name: /惣菜/ });
  expect(within(deli).getByText("10/15 分まで(10/16 07:40 取込)")).toBeInTheDocument();
});

test("shows computing and failed jobs", async () => {
  const d = dashboard();
  d.departments[2].job = { id: 1, status: "running", processed: 0, total: 3, error: null, notice: null };
  d.departments[1].last_job = { status: "failed", finished_at: "2026-10-16T14:00:00+09:00", error: "タイムアウトしました" };
  vi.mocked(dashboardApi.getDashboard).mockResolvedValue(d);
  await renderPage(<DashboardPage />, manager(), "今日の状況");
  expect(await screen.findByText("計算中(画面を開くと最新の結果を表示します)")).toBeInTheDocument();
  expect(screen.getByText("最新の予測の計算に失敗しました: タイムアウトしました")).toBeInTheDocument();
});

test("empty states", async () => {
  vi.mocked(dashboardApi.getDashboard).mockResolvedValue(
    dashboard({
      deadlines: [],
      tomorrow: { date: "2026-10-17", weather: null, promotions: [], calendar: [] },
    }),
  );
  await renderPage(<DashboardPage />, staff(VEG, FISH, DELI), "今日の状況");
  expect(await screen.findByText("締めが近い未承認はありません。")).toBeInTheDocument();
  expect(screen.getByText("予報はまだ取得していません。")).toBeInTheDocument();
  expect(screen.getAllByText("なし")).toHaveLength(2);
});

test("no department", async () => {
  vi.mocked(dashboardApi.getDashboard).mockResolvedValue(dashboard({ departments: [], deadlines: [], data_status: [] }));
  await renderPage(<DashboardPage />, staff(), "今日の状況");
  expect(
    await screen.findByText("表示できる部門がありません。管理者に所属部門の登録を依頼してください。"),
  ).toBeInTheDocument();
});

test("shows API error", async () => {
  vi.mocked(dashboardApi.getDashboard).mockRejectedValue({ response: { status: 500, data: { detail: "失敗" } } });
  await renderPage(<DashboardPage />, manager(), "今日の状況");
  expect(await screen.findByRole("alert")).toHaveTextContent("失敗");
});
