import { useState } from "react";
import { fmt, yrs, QCOL, Q } from "./api";
import { Badge, Thumb } from "./ui";

export interface Filters { minKwh: number; maxShade: number; minUsable: number; minKwp: number; quality: Record<Q, boolean>; }
export const DEFAULT_FILTERS: Filters = { minKwh: 0, maxShade: 100, minUsable: 0, minKwp: 0, quality: { measured: true, estimated: true, unverified: true } };

export default function RankPanel(p: { items: any[]; total: number; selectedId: string | null; onSelect: (id: string) => void; filters: Filters; setFilters: (f: Filters) => void;
  open: boolean; aoiActive: boolean; areaName: string; clearAoi: () => void }) {
  const [n, setN] = useState(100);
  const f = p.filters;
  const num = (k: keyof Filters) => (e: React.ChangeEvent<HTMLInputElement>) => p.setFilters({ ...f, [k]: e.target.value === "" ? (k === "maxShade" ? 100 : 0) : Number(e.target.value) });
  return <aside className={"left" + (p.open ? "" : " closed")} aria-label="Ranked rooftops">
    <div className="left-head">
      <h2>Best rooftops</h2>
      <div className="sub">{p.areaName} · ranked by middle-scenario kWh/year (50% of roof usable)</div>
      <div className="filters">
        <label>Min generation (kWh/yr)<input type="number" min={0} step={1000} value={f.minKwh || ""} onChange={num("minKwh")} placeholder="any" /></label>
        <label>Max shading loss (%)<input type="number" min={0} max={100} value={f.maxShade === 100 ? "" : f.maxShade} onChange={num("maxShade")} placeholder="any" /></label>
        <label>Min usable area (m²)<input type="number" min={0} value={f.minUsable || ""} onChange={num("minUsable")} placeholder="any" /></label>
        <label>Min capacity (kWp)<input type="number" min={0} step={1} value={f.minKwp || ""} onChange={num("minKwp")} placeholder="any" /></label>
      </div>
      <div className="chips">{(["measured", "estimated", "unverified"] as Q[]).map(q =>
        <button key={q} className={"chip" + (f.quality[q] ? " on" : "")} aria-pressed={f.quality[q]} onClick={() => p.setFilters({ ...f, quality: { ...f.quality, [q]: !f.quality[q] } })}>
          <span className="dot" style={{ background: QCOL[q] }} />{q}</button>)}
        {p.aoiActive && <button className="chip on" onClick={p.clearAoi}>Selected area ✕</button>}</div>
      <div className="sub" style={{ marginTop: 8 }}>{fmt(p.items.length)} of {fmt(p.total)} buildings match</div>
    </div>
    <div className="list">
      {p.items.slice(0, n).map(ft => { const q = ft.properties; return (
        <button key={q.id} className={"row" + (p.selectedId === q.id ? " sel" : "")} onClick={() => p.onSelect(q.id)}>
          <span className="rk">{q.rank}</span><Thumb geom={ft.geometry} color={QCOL[q.quality as Q]} />
          <span><span className="l1">{fmt(q.kwh_low)}–{fmt(q.kwh_high)} <span className="sub" style={{ fontWeight: 400 }}>kWh/yr</span></span><br />
            <span className="l2">{fmt(q.kwh_per_kwp)} kWh/kWp · {fmt(q.kwp_mid, 1)} kWp · payback {yrs(q.payback_mid)}</span><br />
            <span className="l2">{fmt(q.area_m2)} m² · shading −{fmt(q.shading_loss_pct, 1)}% </span> <Badge q={q.quality} /></span>
        </button>); })}
      {p.items.length > n && <button className="more" onClick={() => setN(n + 150)}>Show more ({fmt(p.items.length - n)} left)</button>}
      {p.items.length === 0 && <div className="note" style={{ padding: 16 }}>No building matches these filters. Loosen a filter to see results.</div>}
    </div>
  </aside>;
}
