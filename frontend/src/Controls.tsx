import { useEffect, useState } from "react";
import { get, fmt, QCOL } from "./api";
import { Tabs } from "./ui";

export default function Controls(p: { busy?: boolean; date: string; setDate: (d: string) => void; minutes: number; setMinutes: (m: number) => void; sun: any; shading: boolean;
  show: any; setShow: (s: any) => void; mode: string; setMode: (m: string) => void; ramp: number[]; basemap: string; setBasemap: (b: string) => void; basemaps: string[]; leftOpen: boolean }) {
  const [path, setPath] = useState<any[]>([]);
  const [legend, setLegend] = useState(true);
  useEffect(() => { get(`/api/sunpath?date=${p.date}`).then(d => setPath(d.points)).catch(() => setPath([])); }, [p.date]);
  const hh = (m: number) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
  const W = 280, Hh = 62;
  const pts = path.map(q => { const [h, m] = q.t.split(":").map(Number); return [((h * 60 + m - 300) / 840) * W, Hh - 6 - (Math.max(q.el, 0) / 90) * (Hh - 12)]; });
  const cur = ((p.minutes - 300) / 840) * W;
  const L = (k: string, label: string) => <button key={k} className={"chip" + (p.show[k] ? " on" : "")} aria-pressed={p.show[k]} onClick={() => p.setShow({ ...p.show, [k]: !p.show[k] })}>{label}</button>;
  const modeLabel: Record<string, string> = { rank: "Annual energy", quality: "Data quality", shading: "Shading loss", height: "Height" };
  return <div className="floating ctrl" style={{ ["--lw" as any]: p.leftOpen ? "352px" : "0px", left: p.leftOpen ? undefined : 12 }}>
    <div className="card timebox" aria-label="Shadow time controls">
      <div className="r"><strong style={{ fontFamily: "var(--font-display)" }}>Shadow time</strong>
        <input type="date" value={p.date} onChange={e => p.setDate(e.target.value)} aria-label="Date" /><span className="sunread">IST {hh(p.minutes)}{p.busy ? " · updating shadows…" : ""}</span></div>
      <input type="range" min={300} max={1140} step={10} value={p.minutes} onChange={e => p.setMinutes(Number(e.target.value))} aria-label="Time of day" style={{ width: "100%", accentColor: "#B86E00" }} />
      <svg width="100%" viewBox={`0 0 ${W} ${Hh}`} style={{ maxWidth: 320 }} aria-hidden>
        <line x1="0" y1={Hh - 6} x2={W} y2={Hh - 6} stroke="#D5DDEA" />
        {pts.length > 1 && <path d={pts.map((q, i) => `${i ? "L" : "M"}${q[0].toFixed(1)},${q[1].toFixed(1)}`).join("")} fill="none" stroke="#F2A900" strokeWidth="2.5" />}
        <line x1={cur} y1="2" x2={cur} y2={Hh - 6} stroke="#0B2545" strokeDasharray="3 3" />
        {p.sun && p.sun.elevation > 0 && <circle cx={cur} cy={Hh - 6 - (p.sun.elevation / 90) * (Hh - 12)} r="6" fill="#F2A900" stroke="#0B2545" strokeWidth="2" />}
      </svg>
      <div className="sunread">{p.sun ? (p.sun.elevation > 0 ? `Sun ${fmt(p.sun.elevation, 1)}° high, azimuth ${fmt(p.sun.azimuth, 0)}° — shadows fall away from it` : "Sun is below the horizon: no shadows") : "…"}</div>
    </div>
    <div className="card"><div className="layers">
      {L("buildings", "Buildings")}{L("shadows", "Shadows")}{L("trees", "Tree canopy")}{L("extrude", "3D heights")}{L("missing", "Possibly missing")}{L("study", "Study area")}
    </div>
      <div style={{ marginTop: 8 }}><Tabs cls="chips" items={Object.values(modeLabel)} value={modeLabel[p.mode]} onChange={v => p.setMode(Object.keys(modeLabel).find(k => modeLabel[k] === v)!)} /></div>
      <div style={{ marginTop: 6, display: "flex", gap: 6, alignItems: "center" }}><span className="sub">Basemap</span>
        <select value={p.basemap} onChange={e => p.setBasemap(e.target.value)} aria-label="Basemap">{p.basemaps.map(b => <option key={b}>{b}</option>)}</select>
        <button className="chip" onClick={() => setLegend(!legend)}>{legend ? "Hide legend" : "Legend"}</button></div>
      {legend && <div className="legend" style={{ marginTop: 8 }}>
        {p.mode === "rank" && <><div className="ramp" style={{ background: "linear-gradient(90deg,#E3EAF6,#F8DE8C,#F2A900,#C77700,#7A3E00)" }} /><div style={{ display: "flex", justifyContent: "space-between" }}><span>{fmt(p.ramp[0])}</span><span>{fmt(p.ramp[2])}</span><span>{fmt(p.ramp[3])}+ kWh/yr (middle scenario)</span></div></>}
        {p.mode === "shading" && <><div className="ramp" style={{ background: "linear-gradient(90deg,#F2A900,#E9873A,#8E4A9B,#0B2545)" }} /><div style={{ display: "flex", justifyContent: "space-between" }}><span>0%</span><span>20%+ annual energy lost to shade</span></div></>}
        {p.mode === "height" && <><div className="ramp" style={{ background: "linear-gradient(90deg,#E3EAF6,#8FA9D3,#3B5F9E,#0B2545)" }} /><div style={{ display: "flex", justifyContent: "space-between" }}><span>3 m</span><span>30 m+</span></div></>}
        {p.mode === "quality" && (["measured", "estimated", "unverified"] as const).map(q => <div className="lr" key={q}><span className="sw" style={{ background: QCOL[q] }} />{q === "measured" ? "Measured – field-checked" : q === "estimated" ? "Estimated – documented method" : "Unverified – missing/conflicting data"}</div>)}
        <div className="lr"><span className="sw" style={{ background: "#0B2545", opacity: .3 }} />Building shadow (full)</div>
        <div className="lr"><span className="sw" style={{ background: "#3C8D5A", opacity: .5 }} />Tree canopy (partial shade)</div>
        <div className="lr"><span className="sw" style={{ background: "transparent", borderColor: "#C8553D", borderStyle: "dashed" }} />Structure in another dataset but not analysed</div>
        <div className="lr"><span className="sw" style={{ background: "transparent", borderColor: "#0B2545", borderStyle: "dashed" }} />Study area with calculations</div>
      </div>}
    </div>
  </div>;
}
