"""モデルの読み込みと、ファイルの差し替え時の読み直し(詳細設計書「適合テスト」)。"""
import os
import time

import joblib

from smdx_api.predictor.registry import ModelRegistry, ModelStatus
from tests.predictor.conftest import model_dict


def test_missing_file(tmp_path):
    reg = ModelRegistry({"daily": tmp_path / "daily.joblib", "time_band": tmp_path / "tb.joblib"})
    assert reg.get("daily") is None
    assert reg.status("daily") == ModelStatus(False, None, "モデルファイルがありません")


def test_incompatible_file_reports_reason(registry_with):
    reg = registry_with(model_dict(meta={"granularity": "time_band"}))
    assert reg.get("daily") is None
    assert reg.status("daily") == ModelStatus(False, None, "granularity が部門と合いません")


def test_registry_reloads_when_file_changes(tmp_path):
    p = tmp_path / "daily.joblib"
    joblib.dump(model_dict(), p)
    reg = ModelRegistry({"daily": p, "time_band": tmp_path / "x"})
    assert reg.get("daily").version == "daily-2026.11.01-1"
    assert reg.status("daily") == ModelStatus(True, "daily-2026.11.01-1", None)
    joblib.dump(model_dict(meta={"version": "daily-2026.11.08-1"}), p)
    later = time.time() + 5
    os.utime(p, (later, later))
    assert reg.get("daily").version == "daily-2026.11.08-1"


def test_registry_notices_file_removed(tmp_path):
    p = tmp_path / "daily.joblib"
    joblib.dump(model_dict(), p)
    reg = ModelRegistry({"daily": p, "time_band": tmp_path / "x"})
    assert reg.get("daily") is not None
    p.unlink()
    assert reg.get("daily") is None


def test_app_has_registry_and_reports_on_start(app):
    reg = app.state.model_registry
    # 試験の設定ではモデルファイルが無いので、どちらも未接続(ベースライン予測)
    assert reg.status("daily").loaded is False and reg.status("time_band").loaded is False
