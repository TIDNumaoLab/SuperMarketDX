// カレンダー(/calendar、店長のみ): 月表示で祝日・行事日を表示し、行事日を登録・削除する
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { createCalendarDay, deleteCalendarDay, listCalendar } from "../api/calendar";
import { errorMessage } from "../api/client";
import ConfirmDialog from "../components/ConfirmDialog";
import ErrorBanner from "../components/ErrorBanner";
import { jstToday } from "../format";
import styles from "../styles/page.module.css";
import type { CalendarDay } from "../types/api";
import calStyles from "./Calendar.module.css";
import { monthGrid } from "./calendarGrid";

const WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"];

export default function CalendarPage() {
  const today = jstToday();
  const [year, setYear] = useState(Number(today.slice(0, 4)));
  const [month, setMonth] = useState(Number(today.slice(5, 7)));
  const [days, setDays] = useState<CalendarDay[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [newDate, setNewDate] = useState("");
  const [newName, setNewName] = useState("");
  const [deleting, setDeleting] = useState<CalendarDay | null>(null);

  const load = useCallback(async (y: number) => {
    try {
      setDays(await listCalendar(y));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    void load(year);
  }, [year, load]);

  function move(delta: number) {
    const m = month + delta;
    if (m < 1) {
      setYear(year - 1);
      setMonth(12);
    } else if (m > 12) {
      setYear(year + 1);
      setMonth(1);
    } else {
      setMonth(m);
    }
  }

  async function onRegister(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!newDate || !newName.trim()) {
      setError("日付と名称を入力してください");
      return;
    }
    try {
      await createCalendarDay({ date: newDate, kind: "event", name: newName.trim() });
      setNewDate("");
      setNewName("");
      await load(year);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function onDelete() {
    if (!deleting) return;
    const target = deleting;
    setDeleting(null);
    try {
      await deleteCalendarDay(target.id);
      await load(year);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const byDate = new Map<string, CalendarDay[]>();
  for (const d of days) {
    byDate.set(d.date, [...(byDate.get(d.date) ?? []), d]);
  }

  // 曜日の列は月曜始まり(土曜は5、日曜は6)
  function dayClass(date: string | null, col: number): string {
    if (!date) return calStyles.out;
    const names = [];
    if (col === 5) names.push(calStyles.sat);
    if (col === 6) names.push(calStyles.sun);
    if ((byDate.get(date) ?? []).some((d) => d.kind === "holiday")) names.push(calStyles.hol);
    if (date === today) names.push(calStyles.today);
    return names.join(" ");
  }

  return (
    <section>
      <div className={styles.head}>
        <div>
          <h1>カレンダー</h1>
          <p className={styles.sub}>行事日は予測に反映されます。</p>
        </div>
      </div>
      <ErrorBanner message={error} />
      <div className={calStyles.layout}>
      <div>
      <div className={calStyles.monthnav}>
        <button type="button" className={styles.secondary} onClick={() => move(-1)}>
          前月
        </button>
        <strong>
          {year}年{month}月
        </strong>
        <button type="button" className={styles.secondary} onClick={() => move(1)}>
          翌月
        </button>
      </div>
      <div className={styles.tableWrap}>
      <table className={`${styles.table} ${calStyles.cal}`}>
        <thead>
          <tr>
            {WEEKDAYS.map((w) => (
              <th key={w}>{w}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {monthGrid(year, month).map((week, i) => (
            <tr key={i}>
              {week.map((date, j) => (
                <td key={j} className={dayClass(date, j)} aria-current={date === today ? "date" : undefined}>
                  {date && (
                    <>
                      <div className={calStyles.d}>
                        {Number(date.slice(8, 10))}
                        {/* 今日は色だけでなく文字でも示す */}
                        {date === today && <span className={calStyles.todayLabel}>今日</span>}
                      </div>
                      {(byDate.get(date) ?? []).map((d) => (
                        <div key={d.id} className={`${calStyles.ev} ${d.kind === "holiday" ? calStyles.holiday : ""}`}>
                          {d.name}
                          {d.kind === "event" && (
                            <button type="button" aria-label={`${d.name} を削除`} onClick={() => setDeleting(d)}>
                              削除
                            </button>
                          )}
                        </div>
                      ))}
                    </>
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      </div>

      <form className={`${styles.panel} ${calStyles.form}`} onSubmit={onRegister}>
        <h2 className={styles.bare}>行事日の登録</h2>
        <label className={styles.field}>
          日付
          <input type="date" value={newDate} onChange={(e) => setNewDate(e.target.value)} />
        </label>
        <label className={styles.field}>
          名称
          <input value={newName} maxLength={64} onChange={(e) => setNewName(e.target.value)} />
        </label>
        <button type="submit" className={styles.primary}>
          行事日を登録
        </button>
        <span className={styles.muted}>祝日は公開データから取り込みます(管理コマンド import_holidays)。</span>
      </form>
      </div>

      <ConfirmDialog
        open={deleting !== null}
        message={deleting ? `行事日「${deleting.name}」(${deleting.date})を削除しますか?` : ""}
        onConfirm={onDelete}
        onCancel={() => setDeleting(null)}
      />
    </section>
  );
}
