"""モデル作成用プロジェクトの試験の共通部品。"""
from datetime import date

import pytest


@pytest.fixture(scope="session")
def sample_dir(tmp_path_factory):
    """120日分のサンプルデータ(終端日 2026-10-15、シード42)。"""
    from smdx_sample.export import generate

    out = tmp_path_factory.mktemp("sample")
    generate(date(2026, 10, 15), out, days=120)
    return out
