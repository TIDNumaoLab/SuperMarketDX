"""order_calc は DB に依存しない純粋な計算(モデル作成用プロジェクトのバックテストからも使う)。"""
from pathlib import Path

import smdx_api.order_calc as order_calc


def test_order_calc_is_pure():
    src = "\n".join(p.read_text(encoding="utf-8") for p in Path(order_calc.__file__).parent.glob("*.py"))
    for forbidden in ("sqlalchemy", "fastapi", "smdx_api.db", "smdx_api.api"):
        assert forbidden not in src
