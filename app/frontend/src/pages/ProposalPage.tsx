// 提案の画面の共通部分。発注(/orders、生鮮)と製造計画(/production、惣菜)で使う(詳細設計書「発注(/orders)」「製造計画(/production)」)。
// 製造計画は行を「商品×時間帯」とし、時間帯・製造開始(=承認期限)・陳列残数の列と、陳列残数の入力欄を出す
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { errorMessage, statusOf } from "../api/client";
import {
  adjustProposal,
  adoptRecalculated,
  approveBulk,
  approveProposal,
  cancelApproval,
  type AdjustInput,
} from "../api/proposals";
import { listProducts } from "../api/products";
import { getSettings } from "../api/settings";
import { useAuth } from "../auth/AuthContext";
import BulkApproveButton from "../components/BulkApproveButton";
import ConfirmDialog from "../components/ConfirmDialog";
import DepartmentSelect, { selectableDepartments } from "../components/DepartmentSelect";
import DisplayStockForm from "../components/DisplayStockForm";
import ErrorBanner from "../components/ErrorBanner";
import FreshnessBar from "../components/FreshnessBar";
import ProposalTable from "../components/ProposalTable";
import proposalStyles from "../components/Proposals.module.css";
import { confirmMessage, formatMonthDay, jstToday, STATUS_LABELS } from "../format";
import { useProposals } from "../hooks/useProposals";
import styles from "../styles/page.module.css";
import type { Job, Product, Proposal, ProposalStatus, Settings } from "../types/api";

export type ProposalMode = "order" | "production";

// 時間帯の表示(例: 11:00〜14:00)。終わりは次の区切りの開始時、最後の時間帯は閉店時刻
function bandLabels(settings: Settings | null): ((band: number) => string) | null {
  const bands = settings?.deli_time_bands;
  const close = (settings?.business_hours as { close?: string } | undefined)?.close;
  if (!Array.isArray(bands) || typeof close !== "string") return null;
  const sorted = [...(bands as number[])].sort((a, b) => a - b);
  const hh = (h: number) => `${String(h).padStart(2, "0")}:00`;
  return (band) => {
    const next = sorted.find((b) => b > band);
    return `${hh(band)}〜${next === undefined ? close : hh(next)}`;
  };
}

export default function ProposalPage({ mode }: { mode: ProposalMode }) {
  const production = mode === "production";
  const { me } = useAuth();
  // 今日の状況から開いたときは、URL の部門(department)と対象日(target_date)を選んだ状態にする
  const [params] = useSearchParams();
  const [department, setDepartment] = useState(() => {
    const options = selectableDepartments(me?.accessible_departments ?? [], mode);
    const requested = params.get("department");
    return options.find((d) => d.code === requested)?.code ?? options[0]?.code ?? "";
  });
  const [products, setProducts] = useState<Product[]>([]);
  // URL の対象日は、YYYY-MM-DD で当日〜15日先のときだけ使う(開いたまま日付が変わった古いリンク等は無視する)
  const [targetDate, setTargetDate] = useState(() => {
    const requested = params.get("target_date") ?? "";
    const valid = /^\d{4}-\d{2}-\d{2}$/.test(requested) && requested >= jstToday() && requested <= jstToday(15);
    return valid ? requested : "";
  });
  const [status, setStatus] = useState<ProposalStatus | "">("");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [skipped, setSkipped] = useState<Map<number, string>>(new Map());
  const [confirming, setConfirming] = useState<Proposal | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  // 保存していない数量の入力がある提案。ある間は再計算の結果で一覧を差し替えない
  const dirtyIds = useRef<Set<number>>(new Set());
  // 入力が無くなったときに、差し替えを待っている結果があれば反映する(描画ごとの値を ref で参照する)
  const pendingApply = useRef<(() => Promise<void>) | null>(null);
  const onDirtyChange = useCallback((id: number, dirty: boolean) => {
    if (dirty) dirtyIds.current.add(id);
    else dirtyIds.current.delete(id);
    if (dirtyIds.current.size === 0 && pendingApply.current) void pendingApply.current();
  }, []);

  const { data, error, job, reload, recalculate, hasUpdate, applyUpdate, trackJob } = useProposals(
    { departmentCode: department, targetDate: targetDate || undefined, status: status || undefined },
    { holdUpdates: () => dirtyIds.current.size > 0 },
  );
  pendingApply.current = hasUpdate ? applyUpdate : null;

  useEffect(() => {
    getSettings()
      .then(setSettings)
      .catch((e) => setActionError(errorMessage(e)));
  }, []);

  // 製造計画: 陳列残数の入力欄の商品。部門を切り替えたら前の部門の商品は出さず、遅れて届いた前の部門の結果も使わない
  useEffect(() => {
    if (!production || !department) return;
    let stale = false;
    setProducts([]);
    listProducts(department)
      .then((rows) => {
        if (!stale) setProducts(rows.filter((p) => p.is_active));
      })
      .catch((e) => {
        if (!stale) setActionError(errorMessage(e));
      });
    return () => {
      stale = true;
    };
  }, [production, department]);

  const bandLabel = useMemo(() => (production ? bandLabels(settings) : null), [production, settings]);

  // 陳列残数は当日の計画に効く。当日の一覧を出していなければ切り替え(一覧が実行中のジョブを返す)、出していれば返ったジョブを追う
  function onDisplayStockSaved(saved: Job, target: string) {
    if (targetDate !== target) setTargetDate(target);
    else trackJob(saved);
  }

  // 条件を変えたら選択と一括承認の結果を消す
  useEffect(() => {
    setSelected(new Set());
    setSkipped(new Map());
  }, [department, targetDate, status]);

  async function run(fn: () => Promise<unknown>) {
    setActionError(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setActionError(errorMessage(e));
      // 状態や数量が変わっていた(409): 新しい内容を見せるため一覧を取り直す
      if (statusOf(e) === 409) await reload();
    }
  }

  async function save(p: Proposal, quantity: number, reason: AdjustInput["reason"], note: string | undefined) {
    const body: AdjustInput = note ? { quantity, reason, reason_note: note } : { quantity, reason };
    await run(() => adjustProposal(p.id, body));
  }

  function approve(p: Proposal) {
    if (p.warnings.length > 0) {
      setConfirming(p);
    } else {
      void run(() => approveProposal(p.id, p.proposed_qty, false));
    }
  }

  async function bulk() {
    await run(async () => {
      const shown = data?.proposals ?? [];
      const items = shown.filter((p) => selected.has(p.id)).map((p) => ({ id: p.id, expected_qty: p.proposed_qty }));
      const res = await approveBulk(items);
      setSkipped(new Map(res.skipped.map((s) => [s.id, s.reason])));
      setSelected(new Set());
    });
  }

  const recalculating = job?.status === "running";
  const cutoff = production ? undefined : settings?.[`order_cutoff.${department}`];
  // 製造計画の対象日(一覧の応答の対象日。提案が0件でも出す)
  const planDate = data?.target_date;

  return (
    <section>
      <h1>{production ? "製造計画" : "発注"}</h1>
      <ErrorBanner message={actionError ?? error} />
      {typeof cutoff === "string" && <p className={proposalStyles.cutoff}>発注締め {cutoff} まで</p>}
      {/* 製造開始の列は時刻だけなので、どの日の計画かを出す(最初の時間帯の製造開始以後の既定表示は翌日) */}
      {production && planDate && <p className={proposalStyles.cutoff}>{formatMonthDay(planDate)} の製造計画</p>}
      <div className={styles.toolbar}>
        <DepartmentSelect value={department} onChange={setDepartment} businessType={mode} />
        <label className={styles.field}>
          対象日
          <input type="date" value={targetDate} onChange={(e) => setTargetDate(e.target.value)} />
        </label>
        <label className={styles.field}>
          状態
          <select value={status} onChange={(e) => setStatus(e.target.value as ProposalStatus | "")}>
            <option value="">すべて</option>
            {(Object.keys(STATUS_LABELS) as ProposalStatus[]).map((s) => (
              <option key={s} value={s}>
                {STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        </label>
        <BulkApproveButton count={selected.size} disabled={recalculating} onClick={() => void bulk()} />
      </div>
      {production && department && (
        <DisplayStockForm
          departmentCode={department}
          products={products.map((p) => ({ product_code: p.product_code, name: p.name }))}
          onSaved={onDisplayStockSaved}
        />
      )}
      <FreshnessBar freshness={data?.freshness ?? null} job={job} onRecalculate={() => void recalculate()} />
      {data?.notice && <div className={styles.notice}>{data.notice}</div>}
      {hasUpdate && (
        <div className={styles.notice}>
          <span>新しい計算結果があります。</span>{" "}
          <button type="button" onClick={() => void applyUpdate()}>
            反映する
          </button>
          (提案数が変わった行の保存していない入力は、新しい提案数に戻ります)
        </div>
      )}
      {data && (
        <ProposalTable
          proposals={data.proposals}
          selected={selected}
          skipped={skipped}
          approveLocked={recalculating}
          computing={recalculating}
          onSelect={(id, checked) => {
            const next = new Set(selected);
            if (checked) next.add(id);
            else next.delete(id);
            setSelected(next);
          }}
          onSave={save}
          onApprove={approve}
          onCancel={(p) => void run(() => cancelApproval(p.id))}
          onAdopt={(p) => void run(() => adoptRecalculated(p.id))}
          onDirtyChange={onDirtyChange}
          bandLabel={bandLabel ?? undefined}
        />
      )}
      <ConfirmDialog
        open={confirming !== null}
        message={confirming ? confirmMessage(confirming.warnings) : ""}
        onCancel={() => setConfirming(null)}
        onConfirm={() => {
          const p = confirming;
          setConfirming(null);
          if (p) void run(() => approveProposal(p.id, p.proposed_qty, true));
        }}
      />
    </section>
  );
}
