"""サンプルデータ一式の投入(詳細設計書「管理コマンド」import_sample)。

順序: products → pos・inventory・waste(商品の部門ごとに分けて CSV 取込と同じ処理)→ weather.csv → weather_actuals
→ calendar.csv の行事日 → calendar_days → promotions.csv → promotions。最後に特売・カレンダーの変更日時を記録する。
祝日は import_holidays で入れる(calendar.csv の祝日は取り込まない。詳細設計書「管理コマンド」)。
取込者は空(システム)とする(詳細設計書「データ項目定義」の import_logs)。何度実行しても同じ状態になる。
"""
import argparse
import csv
import io
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import delete, select, tuple_
from sqlalchemy.orm import Session

from smdx_api.clock import JST
from smdx_api.clock import now as clock_now
from smdx_api.commands import CommandError, open_session
from smdx_api.db.models import CalendarDay, Department, Product, Promotion
from smdx_api.imports.service import run_import
from smdx_api.settings.service import EVENTS_CHANGED_KEY, touch_internal
from smdx_api.weather_client.client import HourlyWeather
from smdx_api.weather_client.store import save_actuals

FILES = {"products": "products.csv", "pos": "pos_sales.csv", "inventory": "inventory.csv", "waste": "waste.csv"}


def _read(path: Path) -> list[list[str]]:
    return list(csv.reader(path.read_text(encoding="utf-8-sig").splitlines()))


def _to_bytes(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue().encode("utf-8")


def _split_by_department(rows: list[list[str]], dept_of: dict[str, str]) -> dict[str, list[list[str]]]:
    header, body = rows[0], rows[1:]
    i = header.index("product_code")
    groups: dict[str, list[list[str]]] = {}
    for r in body:
        dept = dept_of.get(r[i]) if i < len(r) else None
        if dept is not None:
            groups.setdefault(dept, [header]).append(r)
    return groups


def _opt_float(v: str) -> float | None:
    return float(v) if v.strip() else None


def _import_weather(db: Session, path: Path) -> int:
    rows = _read(path)
    h = {name: i for i, name in enumerate(rows[0])}
    hourly = [
        HourlyWeather(
            time=datetime.strptime(r[h["observed_time"]], "%Y-%m-%d %H:%M").replace(tzinfo=JST),
            weather_code=int(r[h["weather_code"]]),
            temperature=float(r[h["temperature"]]),
            precipitation_probability=_opt_float(r[h["precipitation_probability"]]),
            precipitation=_opt_float(r[h["precipitation"]]),
        )
        for r in rows[1:]
        if r
    ]
    return save_actuals(db, hourly, source="archive")


def _import_events(db: Session, path: Path) -> int:
    rows = _read(path)
    h = {name: i for i, name in enumerate(rows[0])}
    events = {(date.fromisoformat(r[h["date"]]), r[h["name"]][:64]) for r in rows[1:] if r and r[h["kind"]] == "event"}
    if events:
        days = [d for d, _ in events]
        db.execute(delete(CalendarDay).where(CalendarDay.kind == "event", CalendarDay.date.in_(days)))
        db.add_all(CalendarDay(date=d, kind="event", name=n) for d, n in sorted(events))
        db.flush()
    return len(events)


def _import_promotions(db: Session, path: Path) -> int:
    rows = _read(path)
    h = {name: i for i, name in enumerate(rows[0])}
    ids = dict(db.execute(select(Product.product_code, Product.id)).all())
    wanted = {
        (ids[r[h["product_code"]]], date.fromisoformat(r[h["start_date"]]), date.fromisoformat(r[h["end_date"]]),
         r[h["description"]][:128])
        for r in rows[1:]
        if r and r[h["product_code"]] in ids
    }
    if not wanted:
        return 0
    existing = set(db.execute(
        select(Promotion.product_id, Promotion.start_date, Promotion.end_date, Promotion.description).where(
            tuple_(Promotion.product_id, Promotion.start_date).in_([(p, s) for p, s, _, _ in wanted]))
    ).all())
    new = sorted(wanted - existing)
    db.add_all(Promotion(product_id=p, start_date=s, end_date=e, description=d, created_by=None) for p, s, e, d in new)
    db.flush()
    return len(new)


def import_sample(db: Session, folder: Path, now: datetime) -> dict[str, int]:
    folder = Path(folder)
    for name in [*FILES.values(), "weather.csv", "calendar.csv", "promotions.csv"]:
        if not (folder / name).exists():
            raise CommandError(f"{name} がありません: {folder}")

    counts: dict[str, int] = {}
    products_csv = folder / FILES["products"]
    counts["products"] = run_import(db, "products", products_csv.name, products_csv.read_bytes(), None, None, lambda: now).imported_count

    departments = {d.code: d for d in db.scalars(select(Department))}
    dept_of = dict(db.execute(select(Product.product_code, Department.code).join(Department, Product.department_id == Department.id)).all())
    for kind in ("pos", "inventory", "waste"):
        path = folder / FILES[kind]
        counts[kind] = 0
        # 部門に該当する行が1行も無い種類は取込を呼ばない(取込履歴を作らない)
        for code, rows in sorted(_split_by_department(_read(path), dept_of).items()):
            log = run_import(db, kind, path.name, _to_bytes(rows), departments[code], None, lambda: now)
            counts[kind] += log.imported_count

    counts["weather"] = _import_weather(db, folder / "weather.csv")
    counts["calendar"] = _import_events(db, folder / "calendar.csv")
    counts["promotions"] = _import_promotions(db, folder / "promotions.csv")
    touch_internal(db, EVENTS_CHANGED_KEY, now)
    return counts


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("import_sample", help="サンプルデータ一式を投入する")
    p.add_argument("--folder", required=True, type=Path, help="サンプルデータの出力フォルダ")
    p.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    with open_session() as db:
        try:
            counts = import_sample(db, args.folder, clock_now())
        except CommandError as e:
            print(e, file=sys.stderr)
            return 1
        db.commit()
    print("サンプルデータを投入しました: " + "、".join(f"{k} {v}件" for k, v in counts.items()))
    return 0
