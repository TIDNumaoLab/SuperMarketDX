"""評価レポート(Markdown)の出力。詳細設計書 F-09 手順7の項目: 版番号、学習期間、検証期間、
各候補とベースラインの WAPE・MAE、条件別 WAPE と日数、バックテスト結果。"""
from collections.abc import Mapping
from datetime import date
from pathlib import Path

import numpy as np

from smdx_training.backtest import BacktestResult
from smdx_training.evaluate import ConditionMetric, Evaluation

NAMES = {"baseline": "ベースライン(前週同曜日)", "random_forest": "ランダムフォレスト", "lightgbm": "LightGBM(勾配ブースティング)"}


def _pct(v: float) -> str:
    return "—" if v is None or not np.isfinite(v) else f"{v * 100:.1f}%"


def _num(v: float) -> str:
    return "—" if v is None or not np.isfinite(v) else f"{v:.2f}"


def _cond(c: ConditionMetric) -> str:
    if c.days == 0:
        return "該当日なし"
    return f"{_pct(c.wape)}({c.days}日{'、参考' if c.reference_only else ''})"


def _yen(v: float | None) -> str:
    return "—" if v is None else f"{v:,.0f}円"


def write_report(
    path: Path,
    *,
    version: str,
    granularity: str,
    train_period: tuple[date, date],
    valid_period: tuple[date, date],
    evaluation: Evaluation,
    backtests: Mapping[str, BacktestResult],
    selected: str | None,
    safety_factor: float = 1.1,
) -> None:
    rows = {"baseline": evaluation.baseline, **evaluation.candidates}
    lines = [
        f"# 評価レポート {version}",
        "",
        f"- 予測の種類: {'日別(生鮮)' if granularity == 'daily' else '時間帯別(惣菜)'}",
        f"- 学習期間: {train_period[0]} 〜 {train_period[1]}",
        f"- 検証期間: {valid_period[0]} 〜 {valid_period[1]}",
        f"- 採用: {NAMES.get(selected, selected) if selected else 'なし(ベースラインを上回るモデルがないため採用しません)'}",
        "",
        "## 予測精度(検証期間)",
        "",
        "主指標は WAPE(=Σ|誤差|/Σ実績)、補助は MAE。条件別の該当日数が7日未満のものは参考扱い。",
        "",
        "| モデル | WAPE | MAE | 雨天日の WAPE | 祝日・行事日の WAPE |",
        "|---|---|---|---|---|",
    ]
    for name, m in rows.items():
        lines.append(f"| {NAMES.get(name, name)} | {_pct(m['wape'])} | {_num(m['mae'])} | {_cond(m['rainy'])} | {_cond(m['holiday_event'])} |")
    lines += [
        "",
        "## バックテスト(検証期間)",
        "",
        f"予測と本体の計算式(安全係数{safety_factor:g})で日々発注・製造した場合の廃棄数・欠品数。金額は 廃棄×原価、欠品×売価。",
        "",
        "| モデル | 廃棄数 | 欠品数 | 廃棄金額 | 欠品金額 |",
        "|---|---|---|---|---|",
    ]
    for name, b in backtests.items():
        lines.append(f"| {NAMES.get(name, name)} | {b.waste_qty} | {b.stockout_qty} | {_yen(b.waste_amount)} | {_yen(b.stockout_amount)} |")
    if backtests and not next(iter(backtests.values())).uses_true_demand:
        lines += ["", "※ 真の需要が無いため販売数を需要とみなした。欠品時に販売数が打ち切られるため、欠品数は過小評価になる。"]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
