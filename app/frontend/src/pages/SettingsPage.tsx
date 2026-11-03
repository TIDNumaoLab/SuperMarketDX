// 設定(/settings): 設定項目(詳細設計書「設定項目」)を一覧で表示し、店長が変更・保存する。
// 保存は変更した項目だけを送る。時間帯の区切りを変えたら時間帯別モデルの再学習が必要な旨を出す
import { useEffect, useState, type FormEvent } from "react";
import { errorMessage, statusOf } from "../api/client";
import { getSettings, putSettings } from "../api/settings";
import { useAuth } from "../auth/AuthContext";
import ErrorBanner from "../components/ErrorBanner";
import styles from "../styles/page.module.css";
import type { Settings } from "../types/api";

type Kind = "time" | "number" | "hours" | "bands" | "start";

interface Item {
  key: string;
  label: string;
  kind: Kind;
}

const BANDS_ERROR = "時間帯の区切りは開始時(整数)をカンマ区切りで入力してください";
const RETRAIN = "時間帯別モデルの再学習が必要です";

// 画面上のまとまり。部門別の安全係数は、部門の業務(生鮮/惣菜)のまとまりに入れる
const GROUPS = ["店舗", "生鮮の発注", "惣菜の製造"] as const;
type Group = (typeof GROUPS)[number];

function groupOf(key: string, types: Record<string, string>): Group {
  if (key === "business_hours" || key === "weather_stale_hours") return "店舗";
  if (key.startsWith("deli_")) return "惣菜の製造";
  if (key.startsWith("safety_factor.") && types[key.slice("safety_factor.".length)] === "production") return "惣菜の製造";
  return "生鮮の発注";
}

// 設定のキーから表示する項目の一覧を作る(部門別の項目は部門名を付ける)
function itemsOf(s: Settings, names: Record<string, string>): Item[] {
  const items: Item[] = [{ key: "business_hours", label: "営業時間", kind: "hours" }];
  const byDept = (prefix: string, label: string, kind: Kind) =>
    Object.keys(s)
      .filter((k) => k.startsWith(`${prefix}.`))
      .sort()
      .forEach((k) => {
        const code = k.slice(prefix.length + 1);
        items.push({ key: k, label: `${label}(${names[code] ?? code})`, kind });
      });
  byDept("safety_factor", "安全係数", "number");
  byDept("order_cutoff", "発注締め時刻", "time");
  byDept("delivery_time", "納品時刻", "time");
  items.push({ key: "deli_time_bands", label: "時間帯の区切り", kind: "bands" });
  items.push({ key: "deli_production_start", label: "製造開始時刻", kind: "start" });
  items.push({ key: "weather_stale_hours", label: "再計算の判定時間(時間)", kind: "number" });
  return items;
}

// 画面の入力値(文字列)。営業時間は .open/.close、製造開始時刻は .<時間帯> を付けたキーで持つ
function toInputs(s: Settings): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(s)) {
    if (k === "business_hours") {
      const h = v as { open: string; close: string };
      out["business_hours.open"] = h.open;
      out["business_hours.close"] = h.close;
    } else if (k === "deli_time_bands") {
      out[k] = (v as number[]).join(",");
    } else if (k === "deli_production_start") {
      for (const [band, t] of Object.entries(v as Record<string, string>)) out[`${k}.${band}`] = t;
    } else {
      out[k] = String(v);
    }
  }
  return out;
}

function parseBands(v: string): number[] | null {
  const parts = v.split(",").map((x) => x.trim());
  return parts.every((x) => /^\d+$/.test(x)) ? parts.map(Number) : null;
}

export default function SettingsPage() {
  const { me } = useAuth();
  const editable = me?.role === "manager";
  const names = Object.fromEntries((me?.accessible_departments ?? []).map((d) => [d.code, d.name]));
  const types = Object.fromEntries((me?.accessible_departments ?? []).map((d) => [d.code, d.business_type]));
  const [settings, setSettings] = useState<Settings | null>(null);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [retrain, setRetrain] = useState(false);

  useEffect(() => {
    getSettings()
      .then((s) => {
        setSettings(s);
        setInputs(toInputs(s));
      })
      .catch((e) => setError(errorMessage(e)));
  }, []);

  if (!settings) {
    return (
      <section>
        <h1>設定</h1>
        <ErrorBanner message={error} />
      </section>
    );
  }
  const original = toInputs(settings);
  const items = itemsOf(settings, names);
  const set = (k: string, v: string) => setInputs({ ...inputs, [k]: v });

  function changes(): Settings | null {
    const out: Settings = {};
    const errs: Record<string, string> = {};
    for (const item of items) {
      const k = item.key;
      if (item.kind === "hours") {
        if (inputs[`${k}.open`] !== original[`${k}.open`] || inputs[`${k}.close`] !== original[`${k}.close`]) {
          out[k] = { open: inputs[`${k}.open`], close: inputs[`${k}.close`] };
        }
      } else if (item.kind === "start") {
        const changed = Object.keys(original)
          .filter((x) => x.startsWith(`${k}.`) && inputs[x] !== original[x])
          .map((x) => [x.slice(k.length + 1), inputs[x]]);
        if (changed.length > 0) out[k] = Object.fromEntries(changed);
      } else if (inputs[k] !== original[k]) {
        if (item.kind === "bands") {
          const bands = parseBands(inputs[k]);
          if (bands === null) errs[k] = BANDS_ERROR;
          else out[k] = bands;
        } else if (item.kind === "number") {
          const n = Number(inputs[k]);
          if (inputs[k].trim() === "" || Number.isNaN(n)) errs[k] = "数値を入力してください";
          else out[k] = n;
        } else {
          out[k] = inputs[k];
        }
      }
    }
    setFieldErrors(errs);
    return Object.keys(errs).length > 0 ? null : out;
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    setRetrain(false);
    const body = changes();
    if (body === null) return;
    if (Object.keys(body).length === 0) {
      setMessage("変更はありません");
      return;
    }
    try {
      const saved = await putSettings(body);
      setSettings(saved);
      setInputs(toInputs(saved));
      setMessage("保存しました");
      setRetrain("deli_time_bands" in body);
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
      if (statusOf(err) === 422 && Array.isArray(detail)) {
        setFieldErrors(Object.fromEntries(detail.map((d: { key: string; msg: string }) => [d.key, d.msg])));
      } else {
        setError(errorMessage(err));
      }
    }
  }

  function input(id: string, kind: "time" | "number" | "text", label?: string) {
    return (
      <input
        id={id}
        aria-label={label}
        type={kind}
        step={kind === "number" ? "any" : undefined}
        value={inputs[id] ?? ""}
        onChange={(e) => set(id, e.target.value)}
      />
    );
  }

  function valueCell(item: Item) {
    const k = item.key;
    if (!editable) {
      if (item.kind === "hours") return `${original[`${k}.open`]}〜${original[`${k}.close`]}`;
      if (item.kind === "start") {
        return Object.keys(original)
          .filter((x) => x.startsWith(`${k}.`))
          .map((x) => `${x.slice(k.length + 1)}時〜: ${original[x]}`)
          .join("、");
      }
      return original[k];
    }
    if (item.kind === "hours") {
      return (
        <>
          {input(`${k}.open`, "time", "開店時刻")}〜{input(`${k}.close`, "time", "閉店時刻")}
        </>
      );
    }
    if (item.kind === "start") {
      return Object.keys(original)
        .filter((x) => x.startsWith(`${k}.`))
        .map((x) => (
          <span key={x} style={{ marginRight: 12 }}>
            {x.slice(k.length + 1)}時〜 {input(x, "time", `製造開始時刻(${x.slice(k.length + 1)}時〜)`)}
          </span>
        ));
    }
    return input(k, item.kind === "bands" ? "text" : item.kind);
  }

  // 自分の input に label を付ける項目(営業時間・製造開始時刻は入力欄ごとに aria-label を付ける)
  const labelled = (item: Item) => editable && item.kind !== "hours" && item.kind !== "start";

  return (
    <section>
      <h1>設定</h1>
      <ErrorBanner message={error} />
      {message && <div className={styles.notice}>{message}</div>}
      {retrain && <div className={styles.warnNotice}>{RETRAIN}</div>}
      <form onSubmit={onSubmit} noValidate>
        {GROUPS.map((group) => {
          const rows = items.filter((item) => groupOf(item.key, types) === group);
          if (rows.length === 0) return null;
          return (
            <div key={group} style={{ marginBottom: 18 }}>
              <h2 style={{ fontSize: 16 }}>{group}</h2>
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <tbody>
                    {rows.map((item) => (
                      <tr key={item.key}>
                        <th style={{ width: 240, fontWeight: 400 }}>
                          {labelled(item) ? <label htmlFor={item.key}>{item.label}</label> : item.label}
                        </th>
                        <td>{valueCell(item)}</td>
                        <td role={fieldErrors[item.key] ? "alert" : undefined} style={{ color: "var(--stamp)", fontSize: 13 }}>
                          {fieldErrors[item.key] ?? ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })}
        {editable && (
          <div className={styles.savebar}>
            <span className={styles.muted}>変えた項目だけが保存されます。</span>
            <span className={styles.spacer} />
            <button type="submit" className={styles.primary}>
              保存
            </button>
          </div>
        )}
      </form>
    </section>
  );
}
