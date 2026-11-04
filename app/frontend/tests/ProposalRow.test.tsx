import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import ProposalRow from "../src/components/ProposalRow";
import type { Proposal } from "../src/types/api";
import { proposal } from "./proposalFixtures";

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-16T15:10:00+09:00"));
});

afterEach(() => {
  vi.useRealTimers();
});

function renderRow(p: Proposal, over: Partial<Parameters<typeof ProposalRow>[0]> = {}) {
  const handlers = {
    onSave: vi.fn().mockResolvedValue(undefined),
    onApprove: vi.fn(),
    onCancel: vi.fn(),
    onAdopt: vi.fn(),
    onSelect: vi.fn(),
  };
  render(
    <table>
      <tbody>
        <ProposalRow proposal={p} selected={false} skippedReason={null} {...handlers} {...over} />
      </tbody>
    </table>,
  );
  return handlers;
}

test("shows basis of the proposal", () => {
  renderRow(proposal());
  const row = screen.getByRole("row");
  expect(within(row).getByText("10/17")).toBeInTheDocument();
  expect(within(row).getByText("20.0")).toBeInTheDocument(); // 予測値は小数第1位
  expect(within(row).getByText("雨 18.5℃ 70%")).toBeInTheDocument();
  expect(within(row).getByText("特売")).toBeInTheDocument();
  expect(within(row).getByText("在庫 8 / 発注残 0 / 持越 2.5")).toBeInTheDocument();
  expect(within(row).getByText("未承認")).toBeInTheDocument();
  expect(within(row).getByText("ベースライン予測")).toBeInTheDocument();
});

test("temperature is shown to one decimal place", () => {
  // 惣菜の時間帯の平均気温は割り切れない値になる(手動テスト ST-11 で見つかった表示)
  renderRow(proposal({ weather_label: "快晴", temperature: 22.266666666666666, precipitation_probability: 1 }));
  expect(within(screen.getByRole("row")).getByText("快晴 22.3℃ 1%")).toBeInTheDocument();
});

test("whole-number temperature also has one decimal place", () => {
  renderRow(proposal({ weather_label: "快晴", temperature: 20, precipitation_probability: 0 }));
  expect(within(screen.getByRole("row")).getByText("快晴 20.0℃ 0%")).toBeInTheDocument();
});

test("changing quantity requires reason before save", async () => {
  const h = renderRow(proposal());
  const user = userEvent.setup();
  const input = screen.getByLabelText("キャベツ の提案数");
  await user.clear(input);
  await user.type(input, "18");
  const save = screen.getByRole("button", { name: "保存" });
  expect(save).toBeDisabled();
  await user.selectOptions(screen.getByLabelText("キャベツ の修正理由"), "weather");
  expect(save).toBeEnabled();
  await user.click(save);
  expect(h.onSave).toHaveBeenCalledWith(18, "weather", undefined);
});

test("rejects non integer quantity", async () => {
  const h = renderRow(proposal());
  const user = userEvent.setup();
  const input = screen.getByLabelText("キャベツ の提案数");
  await user.clear(input);
  await user.type(input, "1.5");
  await user.selectOptions(screen.getByLabelText("キャベツ の修正理由"), "other");
  expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
  expect(h.onSave).not.toHaveBeenCalled();
});

test("warned row is highlighted with warning text", () => {
  renderRow(proposal({ warnings: ["NO_INVENTORY", "STALE_POS"] }));
  const row = screen.getByRole("row");
  expect(row.className).toContain("warned");
  expect(within(row).getByText("在庫未取込")).toBeInTheDocument();
  expect(within(row).getByText("POS未更新")).toBeInTheDocument();
});

test("approved row before deadline has cancel button; diff row has adopt", async () => {
  const h = renderRow(proposal({ status: "approved", recalculated_qty: 30, approved_by_name: "担当 太郎" }));
  const user = userEvent.setup();
  expect(screen.queryByLabelText("キャベツ の提案数")).not.toBeInTheDocument();
  expect(screen.getByText("再計算: 30(+6)")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "取消" }));
  await user.click(screen.getByRole("button", { name: "採用" }));
  expect(h.onCancel).toHaveBeenCalled();
  expect(h.onAdopt).toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "承認" })).not.toBeInTheDocument();
});

test("approved row after deadline has no cancel button", () => {
  vi.setSystemTime(new Date("2026-10-16T20:00:00+09:00"));
  renderRow(proposal({ status: "approved" }));
  expect(screen.queryByRole("button", { name: "取消" })).not.toBeInTheDocument();
});

test("skipped reason from bulk approve is shown", () => {
  renderRow(proposal({ warnings: ["NO_WEATHER"] }), { skippedReason: "警告があるため一括承認から除外しました" });
  expect(screen.getByText("警告があるため一括承認から除外しました")).toBeInTheDocument();
});

test("approved and confirmed rows are dimmed and show the approver stamp", () => {
  renderRow(proposal({ status: "approved", approved_by_name: "店長" }));
  const row = screen.getByRole("row");
  expect(row).toHaveClass("done");
  expect(within(row).getByTitle("承認者 店長")).not.toHaveClass("confirmed");
});

test("confirmed stamp is filled and pending row is not dimmed", () => {
  renderRow(proposal({ status: "confirmed", approved_by_name: "店長" }));
  expect(screen.getByTitle("承認者 店長")).toHaveClass("confirmed");
});

test("pending row is not dimmed", () => {
  renderRow(proposal());
  expect(screen.getByRole("row")).not.toHaveClass("done");
});

test("fresh quantity must be a multiple of the order unit", async () => {
  // 入数6の生鮮の商品に7は保存できない(本体も 422 で拒否する)
  const h = renderRow(proposal());
  const user = userEvent.setup();
  const input = screen.getByLabelText("キャベツ の提案数");
  await user.clear(input);
  await user.type(input, "7");
  await user.selectOptions(screen.getByLabelText("キャベツ の修正理由"), "other");
  expect(screen.getByText("発注単位(6)の倍数で入力してください")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
  await user.clear(input);
  await user.type(input, "12");
  expect(screen.queryByText("発注単位(6)の倍数で入力してください")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "保存" }));
  expect(h.onSave).toHaveBeenCalledWith(12, "other", undefined);
});

test("deli quantity is not limited by the order unit", async () => {
  const h = renderRow(proposal({ department_code: "DELI", product_name: "唐揚げ", time_band: 14 }), { bandLabel: "14:00〜17:00" });
  const user = userEvent.setup();
  const input = screen.getByLabelText("唐揚げ 14:00〜17:00 の提案数");
  await user.clear(input);
  await user.type(input, "7");
  await user.selectOptions(screen.getByLabelText("唐揚げ 14:00〜17:00 の修正理由"), "other");
  await user.click(screen.getByRole("button", { name: "保存" }));
  expect(h.onSave).toHaveBeenCalledWith(7, "other", undefined);
});
