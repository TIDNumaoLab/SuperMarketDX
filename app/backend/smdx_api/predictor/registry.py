"""読み込んだモデルの保持。ファイルの更新日時が変わったら次の利用時に読み直して適合確認する(詳細設計書「適合テスト」)。"""
import logging
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from smdx_api.predictor.loader import Granularity, LoadedModel, ModelIncompatible, load_model_file

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelStatus:
    loaded: bool
    version: str | None
    reason: str | None


class ModelRegistry:
    def __init__(self, paths: Mapping[Granularity, Path]) -> None:
        self._paths = {g: Path(p) for g, p in paths.items()}
        # granularity → (読み込んだときの更新日時。ファイルが無ければ None, モデル, 理由)
        self._state: dict[str, tuple[float | None, LoadedModel | None, str | None]] = {}
        self._lock = threading.Lock()

    def _refresh(self, granularity: Granularity) -> tuple[LoadedModel | None, str | None]:
        path = self._paths[granularity]
        try:
            mtime: float | None = path.stat().st_mtime
        except OSError:
            mtime = None
        with self._lock:
            cached = self._state.get(granularity)
            if cached is not None and cached[0] == mtime:
                return cached[1], cached[2]
            try:
                model, reason = load_model_file(path, granularity), None
                log.info("モデルを読み込みました: %s %s", granularity, model.version)
            except ModelIncompatible as e:
                model, reason = None, e.reason
                log.warning("モデルを使えないためベースラインで予測します: %s %s(%s)", granularity, path, e.reason)
            self._state[granularity] = (mtime, model, reason)
            return model, reason

    def get(self, granularity: Granularity) -> LoadedModel | None:
        return self._refresh(granularity)[0]

    def status(self, granularity: Granularity) -> ModelStatus:
        model, reason = self._refresh(granularity)
        return ModelStatus(model is not None, model.version if model else None, reason)
