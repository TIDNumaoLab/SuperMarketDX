import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import * as proposalsApi from "../src/api/proposals";
import * as settingsApi from "../src/api/settings";
import OrdersPage from "../src/pages/OrdersPage";
import { DELI, FISH, VEG, renderPage, staff } from "./helpers";
import { listResponse, proposal, running } from "./proposalFixtures";

vi.mock("../src/api/auth");
vi.mock("../src/api/proposals");
vi.mock("../src/api/settings");

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-16T15:10:00+09:00"));
  vi.mocked(settingsApi.getSettings).mockResolvedValue({ "order_cutoff.VEG": "20:00", "order_cutoff.FISH": "19:00" });
  vi.mocked(proposalsApi.listProposals).mockResolvedValue(listResponse([proposal()]));
});

afterEach(() => {
  vi.useRealTimers();
});

test("shows cutoff, freshness and proposals; only order departments selectable", async () => {
  await renderPage(<OrdersPage />, staff(VEG, FISH, DELI), "発注");
  expect(await screen.findByText("発注締め 20:00 まで")).toBeInTheDocument();
  expect(screen.getByText("予測作成 10/16 15:00、予報取得 15:00、在庫 14:30時点")).toBeInTheDocument();
  expect(screen.getByText("キャベツ")).toBeInTheDocument();
  const options = within(screen.getByLabelText("部門")).getAllByRole("option").map((o) => o.textContent);
  expect(options).toEqual(["青果", "鮮魚"]);
  expect(proposalsApi.listProposals).toHaveBeenCalledWith({ departmentCode: "VEG", targetDate: undefined, status: undefined });
});

test("shows empty state", async () => {
  vi.mocked(proposalsApi.listProposals).mockResolvedValue(listResponse([]));
  await renderPage(<OrdersPage />, staff(VEG), "発注");
  expect(await screen.findByText("この条件の提案はありません。")).toBeInTheDocument();
});

test("shows computing message instead of empty state while the first job runs", async () => {
  vi.mocked(proposalsApi.listProposals).mockResolvedValue(listResponse([], running(0, 6)));
  vi.mocked(proposalsApi.getJob).mockReturnValue(new Promise(() => {}));
  await renderPage(<OrdersPage />, staff(VEG), "発注");
  expect(await screen.findByText("最新の予測を計算中です。完了すると表示します。")).toBeInTheDocument();
  expect(screen.queryByText("この条件の提案はありません。")).not.toBeInTheDocument();
});

test("recalc button disabled while job running and shows progress", async () => {
  vi.mocked(proposalsApi.listProposals).mockResolvedValue(listResponse([proposal()], running(3, 6)));
  vi.mocked(proposalsApi.getJob).mockReturnValue(new Promise(() => {}));
  await renderPage(<OrdersPage />, staff(VEG), "発注");
  expect(await screen.findByText("最新の予測を計算中… (3/6)")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "再計算" })).toBeDisabled();
});

test("filters by target date and status", async () => {
  await renderPage(<OrdersPage />, staff(VEG), "発注");
  await screen.findByText("キャベツ");
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("対象日"), "2026-10-20");
  await user.selectOptions(screen.getByLabelText("状態"), "approved");
  await waitFor(() =>
    expect(proposalsApi.listProposals).toHaveBeenLastCalledWith({ departmentCode: "VEG", targetDate: "2026-10-20", status: "approved" }),
  );
});

test("saving an adjusted quantity sends quantity and reason", async () => {
  vi.mocked(proposalsApi.adjustProposal).mockResolvedValue(proposal({ proposed_qty: 18, is_adjusted: true }));
  await renderPage(<OrdersPage />, staff(VEG), "発注");
  const user = userEvent.setup();
  const input = await screen.findByLabelText("キャベツ の提案数");
  await user.clear(input);
  await user.type(input, "18");
  await user.selectOptions(screen.getByLabelText("キャベツ の修正理由"), "weather");
  await user.click(screen.getByRole("button", { name: "保存" }));
  expect(proposalsApi.adjustProposal).toHaveBeenCalledWith(1, { quantity: 18, reason: "weather" });
  await waitFor(() => expect(proposalsApi.listProposals).toHaveBeenCalledTimes(2));
});

test("api error keeps entered quantity", async () => {
  vi.mocked(proposalsApi.adjustProposal).mockRejectedValue({ response: { status: 409, data: { detail: "承認済みの提案は修正できません" } } });
  await renderPage(<OrdersPage />, staff(VEG), "発注");
  const user = userEvent.setup();
  const input = await screen.findByLabelText("キャベツ の提案数");
  await user.clear(input);
  await user.type(input, "18");
  await user.selectOptions(screen.getByLabelText("キャベツ の修正理由"), "other");
  await user.click(screen.getByRole("button", { name: "保存" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("承認済みの提案は修正できません");
  expect(screen.getByLabelText("キャベツ の提案数")).toHaveValue(18);
});

test("approving warned row shows confirm dialog with inventory message", async () => {
  vi.mocked(proposalsApi.listProposals).mockResolvedValue(listResponse([proposal({ warnings: ["NO_INVENTORY"] })]));
  vi.mocked(proposalsApi.approveProposal).mockResolvedValue(proposal({ status: "approved" }));
  await renderPage(<OrdersPage />, staff(VEG), "発注");
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "承認" }));
  const dialog = screen.getByRole("dialog");
  expect(dialog).toHaveTextContent("在庫が取り込まれていません。このまま承認しますか?");
  await user.click(within(dialog).getByRole("button", { name: "はい" }));
  expect(proposalsApi.approveProposal).toHaveBeenCalledWith(1, 24, true);
});

test("approving row without warnings needs no dialog", async () => {
  vi.mocked(proposalsApi.approveProposal).mockResolvedValue(proposal({ status: "approved" }));
  await renderPage(<OrdersPage />, staff(VEG), "発注");
  await userEvent.setup().click(await screen.findByRole("button", { name: "承認" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(proposalsApi.approveProposal).toHaveBeenCalledWith(1, 24, false);
});

test("approval rejected because quantity changed shows the reason and reloads", async () => {
  // 裏の再計算で数量が変わっていた: 画面に新しい数量を出すため一覧を取り直す
  vi.mocked(proposalsApi.approveProposal).mockRejectedValue({
    response: { status: 409, data: { detail: "数量が更新されました。一覧を取り直してから承認してください" } },
  });
  await renderPage(<OrdersPage />, staff(VEG), "発注");
  await userEvent.setup().click(await screen.findByRole("button", { name: "承認" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("数量が更新されました。一覧を取り直してから承認してください");
  await waitFor(() => expect(proposalsApi.listProposals).toHaveBeenCalledTimes(2));
});

test("bulk approve reports skipped rows", async () => {
  vi.mocked(proposalsApi.listProposals).mockResolvedValue(
    listResponse([proposal(), proposal({ id: 2, product_code: "VEG-002", product_name: "トマト", warnings: ["NO_WEATHER"] })]),
  );
  vi.mocked(proposalsApi.approveBulk).mockResolvedValue({
    approved_ids: [1],
    skipped: [{ id: 2, reason: "警告があるため一括承認から除外しました" }],
  });
  await renderPage(<OrdersPage />, staff(VEG), "発注");
  const user = userEvent.setup();
  const bulk = await screen.findByRole("button", { name: "一括承認" });
  expect(bulk).toBeDisabled();
  await user.click(screen.getByLabelText("キャベツ を選択"));
  await user.click(screen.getByLabelText("トマト を選択"));
  await user.click(bulk);
  expect(proposalsApi.approveBulk).toHaveBeenCalledWith([
    { id: 1, expected_qty: 24 },
    { id: 2, expected_qty: 24 },
  ]);
  const row = (await screen.findByText("警告があるため一括承認から除外しました")).closest("tr")!;
  expect(within(row).getByText("トマト")).toBeInTheDocument();
});

test("cancel and adopt call the api", async () => {
  vi.mocked(proposalsApi.listProposals).mockResolvedValue(
    listResponse([proposal({ status: "approved", recalculated_qty: 30 })]),
  );
  vi.mocked(proposalsApi.cancelApproval).mockResolvedValue(proposal());
  vi.mocked(proposalsApi.adoptRecalculated).mockResolvedValue(proposal());
  await renderPage(<OrdersPage />, staff(VEG), "発注");
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "取消" }));
  await user.click(screen.getByRole("button", { name: "採用" }));
  expect(proposalsApi.cancelApproval).toHaveBeenCalledWith(1);
  expect(proposalsApi.adoptRecalculated).toHaveBeenCalledWith(1);
});

test("approve buttons are disabled while recalculating", async () => {
  // 再計算中は表示中の数量がまもなく置き換わるため、見えていない数量を承認しないよう承認を止める
  vi.mocked(proposalsApi.listProposals).mockResolvedValue(listResponse([proposal()], running(0, 1)));
  vi.mocked(proposalsApi.getJob).mockReturnValue(new Promise(() => {}));
  await renderPage(<OrdersPage />, staff(VEG), "発注");
  expect(await screen.findByRole("button", { name: "承認" })).toBeDisabled();
  await userEvent.setup().click(screen.getByLabelText("キャベツ を選択"));
  expect(screen.getByRole("button", { name: "一括承認" })).toBeDisabled();
});

test("unsaved input is kept when a recalculation finishes, until the user applies it", async () => {
  // 保存していない入力がある間は差し替えず「反映する」を出す(PR #6 の軽微な課題)
  vi.mocked(proposalsApi.listProposals)
    .mockResolvedValueOnce(listResponse([proposal({ proposed_qty: 24 })], running(0, 1)))
    .mockResolvedValueOnce(listResponse([proposal({ proposed_qty: 30, updated_at: "2026-10-16T15:12:00+09:00" })]));
  vi.mocked(proposalsApi.getJob).mockResolvedValue({ id: 5, status: "succeeded", processed: 1, total: 1, error: null, notice: null });
  await renderPage(<OrdersPage />, staff(VEG), "発注");
  const input = await screen.findByLabelText("キャベツ の提案数");
  const user = userEvent.setup();
  await user.clear(input);
  await user.type(input, "20");
  expect(await screen.findByText("新しい計算結果があります。", undefined, { timeout: 4000 })).toBeInTheDocument();
  expect(screen.getByLabelText("キャベツ の提案数")).toHaveValue(20);
  expect(proposalsApi.listProposals).toHaveBeenCalledTimes(1);
  await user.click(screen.getByRole("button", { name: "反映する" }));
  await waitFor(() => expect(screen.getByLabelText("キャベツ の提案数")).toHaveValue(30));
  expect(screen.queryByText("新しい計算結果があります。")).not.toBeInTheDocument();
});

test("applying keeps the input of rows whose quantity did not change", async () => {
  // 再計算で updated_at だけが変わった行(提案数は同じ)は、反映しても入力を残す(PR #7 レビューの必須1)
  vi.mocked(proposalsApi.listProposals)
    .mockResolvedValueOnce(listResponse([proposal({ proposed_qty: 24 })], running(0, 1)))
    .mockResolvedValueOnce(listResponse([proposal({ proposed_qty: 24, updated_at: "2026-10-16T15:12:00+09:00" })]));
  vi.mocked(proposalsApi.getJob).mockResolvedValue({ id: 5, status: "succeeded", processed: 1, total: 1, error: null, notice: null });
  await renderPage(<OrdersPage />, staff(VEG), "発注");
  const input = await screen.findByLabelText("キャベツ の提案数");
  const user = userEvent.setup();
  await user.clear(input);
  await user.type(input, "20");
  expect(await screen.findByText("新しい計算結果があります。", undefined, { timeout: 4000 })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "反映する" }));
  await waitFor(() => expect(proposalsApi.listProposals).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.queryByText("新しい計算結果があります。")).not.toBeInTheDocument());
  expect(screen.getByLabelText("キャベツ の提案数")).toHaveValue(20);
});

test("held update is applied automatically once no unsaved input remains", async () => {
  // 入力を元に戻して保存前の入力が無くなったら、お知らせを残さず自動で反映する(PR #7 レビューの指摘5)
  vi.mocked(proposalsApi.listProposals)
    .mockResolvedValueOnce(listResponse([proposal({ proposed_qty: 24 })], running(0, 1)))
    .mockResolvedValueOnce(listResponse([proposal({ proposed_qty: 30, updated_at: "2026-10-16T15:12:00+09:00" })]));
  vi.mocked(proposalsApi.getJob).mockResolvedValue({ id: 5, status: "succeeded", processed: 1, total: 1, error: null, notice: null });
  await renderPage(<OrdersPage />, staff(VEG), "発注");
  const input = await screen.findByLabelText("キャベツ の提案数");
  const user = userEvent.setup();
  await user.clear(input);
  await user.type(input, "20");
  await screen.findByText("新しい計算結果があります。", undefined, { timeout: 4000 });
  await user.clear(input);
  await user.type(input, "24");
  await waitFor(() => expect(screen.getByLabelText("キャベツ の提案数")).toHaveValue(30));
  expect(screen.queryByText("新しい計算結果があります。")).not.toBeInTheDocument();
});

test("opens with the department and target date from the dashboard link", async () => {
  await renderPage(<OrdersPage />, staff(VEG, FISH), "発注", "/orders?department=FISH&target_date=2026-10-18");
  await screen.findByText("キャベツ");
  expect(proposalsApi.listProposals).toHaveBeenCalledWith({ departmentCode: "FISH", targetDate: "2026-10-18", status: undefined });
  expect(screen.getByLabelText("部門")).toHaveValue("FISH");
  expect(screen.getByLabelText("対象日")).toHaveValue("2026-10-18");
});

test("ignores a target date from the URL that is malformed or out of range", async () => {
  for (const bad of ["2026-10-15", "2026-11-01", "abc"]) {
    const view = await renderPage(<OrdersPage />, staff(VEG), "発注", `/orders?department=VEG&target_date=${bad}`);
    await screen.findByText("キャベツ");
    expect(proposalsApi.listProposals).toHaveBeenLastCalledWith({ departmentCode: "VEG", targetDate: undefined, status: undefined });
    view.unmount();
  }
});

test("ignores a department from the URL that cannot be selected", async () => {
  await renderPage(<OrdersPage />, staff(VEG, DELI), "発注", "/orders?department=DELI");
  await screen.findByText("キャベツ");
  expect(proposalsApi.listProposals).toHaveBeenCalledWith({ departmentCode: "VEG", targetDate: undefined, status: undefined });
});
