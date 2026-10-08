import { useEffect, useState } from "react";

/** Ticks once a second; all timers on a page share the same clock value per render. */
export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

/** The app runs on a fixed calendar day (REFERENCE_DATE for the dataset) but the real time of day,
 * so timers keep ticking live. Deadlines are the end of the due day. */
export function appNow(today: string, now: Date) {
  const d = new Date(`${today}T00:00:00`);
  d.setHours(now.getHours(), now.getMinutes(), now.getSeconds(), now.getMilliseconds());
  return d;
}

function deadline(dueDate: string) {
  return new Date(`${dueDate}T23:59:59`);
}

const pad = (n: number) => String(n).padStart(2, "0");

function span(ms: number) {
  const s = Math.floor(Math.abs(ms) / 1000);
  const d = Math.floor(s / 86400);
  const hms = `${pad(Math.floor((s % 86400) / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
  return { days: d, hms };
}

export default function DealTimer({ dueDate, today, now }: { dueDate: string; today: string; now: Date }) {
  const left = deadline(dueDate).getTime() - appNow(today, now).getTime();
  const late = left < 0;
  const soon = !late && left < 24 * 3600 * 1000;
  const { days, hms } = span(left);
  const state = late ? "late" : soon ? "soon" : "ok";
  const label = late ? "Overdue by" : "Due in";
  return (
    <div className={`deal-timer ${state}`} title={`Follow-up due by end of ${dueDate}`} role="timer" aria-live="off">
      <span className="t-label">
        {late && <span className="t-pulse" />}
        {label}
      </span>
      <span className="t-value">
        {days > 0 && <span className="t-days">{days}d</span>}
        {hms}
      </span>
    </div>
  );
}
