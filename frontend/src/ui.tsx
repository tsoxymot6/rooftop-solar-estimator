import { ReactNode, useState } from "react";
import { GLOSS, Q } from "./api";

export const Term = ({ t, children }: { t: string; children?: ReactNode }) => <span className="term" title={GLOSS[t] || t} tabIndex={0}>{children ?? t}</span>;
export const Badge = ({ q }: { q: Q }) => <span className={`badge ${q}`} title={q === "measured" ? "Supported by actual field measurements" : q === "estimated" ? "Obtained through a documented estimation method" : "Missing, conflicting or not adequately checked"}>
  {q === "measured" ? "● Measured" : q === "estimated" ? "◐ Estimated" : "○ Unverified"}</span>;
export const Metric = ({ k, v, u, hero }: { k: ReactNode; v: ReactNode; u?: string; hero?: boolean }) =>
  <div className={"metric" + (hero ? " hero" : "")}><div className="k">{k}</div><div className="v">{v} {u && <span className="u">{u}</span>}</div></div>;
export const Modal = ({ title, onClose, children, tabs }: { title: string; onClose: () => void; children: ReactNode; tabs?: ReactNode }) =>
  <div className="modal-bg" onMouseDown={e => e.target === e.currentTarget && onClose()}><div className="modal" role="dialog" aria-label={title}>
    <div className="mh"><h2 style={{ flex: 1, fontSize: 20 }}>{title}</h2><button className="btn alt" onClick={onClose}>Close</button></div>{tabs}<div className="mb">{children}</div></div></div>;
export const Tabs = ({ items, value, onChange, cls = "mtabs" }: { items: string[]; value: string; onChange: (v: string) => void; cls?: string }) =>
  <div className={cls} role="tablist">{items.map(i => <button key={i} role="tab" aria-selected={i === value} className={i === value ? "on" : ""} onClick={() => onChange(i)}>{i}</button>)}</div>;
export function useLS<T>(k: string, d: T): [T, (v: T) => void] {
  const [v, s] = useState<T>(() => { try { const r = localStorage.getItem(k); return r ? JSON.parse(r) : d; } catch { return d; } });
  return [v, (x: T) => { s(x); try { localStorage.setItem(k, JSON.stringify(x)); } catch { /* ignore */ } }];
}
export function Thumb({ geom, color }: { geom: any; color: string }) {
  const ring: number[][] = geom.type === "Polygon" ? geom.coordinates[0] : geom.coordinates[0][0];
  const xs = ring.map(c => c[0]), ys = ring.map(c => c[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const s = Math.max(x1 - x0, y1 - y0) || 1;
  const d = ring.map((c, i) => `${i ? "L" : "M"}${(((c[0] - x0) / s) * 38 + 4).toFixed(1)},${(((y1 - c[1]) / s) * 38 + 4).toFixed(1)}`).join("") + "Z";
  return <svg width="46" height="46" viewBox="0 0 46 46" aria-hidden><rect width="46" height="46" rx="6" fill="#F3F6FB" /><path d={d} fill={color} stroke="#0B2545" strokeWidth="1" /></svg>;
}
