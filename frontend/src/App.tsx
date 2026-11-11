import { useEffect, useMemo, useRef, useState } from "react";
import MapView, { BASEMAPS } from "./MapView";
import RankPanel, { DEFAULT_FILTERS, Filters } from "./RankPanel";
import DetailPanel from "./DetailPanel";
import Controls from "./Controls";
import InfoModal from "./InfoModal";
import SettingsPop, { DEFAULT_SETTINGS, Settings } from "./Settings";
import AnalyzeDialog from "./AnalyzeDialog";
import { get, post, fmt } from "./api";
import { useLS } from "./ui";

const today = () => new Date().toLocaleDateString("en-CA");
const bounds = (g: any) => { const r: number[][] = g.type === "Polygon" ? g.coordinates[0] : g.coordinates[0][0]; const x = r.map(c => c[0]), y = r.map(c => c[1]); return [Math.min(...x), Math.min(...y), Math.max(...x), Math.max(...y)]; };
const q = (a: number[], f: number) => a[Math.min(a.length - 1, Math.floor(a.length * f))];

export default function App() {
  const [areas, setAreas] = useState<any[]>([]); const [areaId, setAreaId] = useState<string | null>(null);
  const [meta, setMeta] = useState<any>(null); const [bld, setBld] = useState<any>(null); const [trees, setTrees] = useState<any>(null); const [missing, setMissing] = useState<any>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null); const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState("rank"); const [basemap, setBasemap] = useState("Light");
  const [show, setShow] = useState({ buildings: true, trees: true, shadows: true, missing: false, extrude: false, study: true });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<any>(null); const [dLoading, setDLoading] = useState(false); const [dErr, setDErr] = useState<string | null>(null);
  const [roof, setRoof] = useState<any>(null); const [shadows, setShadows] = useState<any>(null); const [sun, setSun] = useState<any>(null);
  const [view, setView] = useState<number[] | null>(null); const [busy, setBusy] = useState(false);
  const [date, setDate] = useState(today()); const [minutes, setMinutes] = useState(660);
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [settings, setSettings] = useLS<Settings>("rse-settings", DEFAULT_SETTINGS);
  const [leftOpen, setLeftOpen] = useState(window.innerWidth > 900);
  const [modal, setModal] = useState<string | null>(null); const [settingsOpen, setSettingsOpen] = useState(false);
  const [draw, setDraw] = useState(false); const [aoi, setAoi] = useState<number[] | null>(null); const [analyze, setAnalyze] = useState(false);
  const [fly, setFly] = useState<any>(null); const flyN = useRef(0);
  const [sq, setSq] = useState(""); const [sres, setSres] = useState<any[]>([]); const [serr, setSerr] = useState<string | null>(null);

  const timeIso = `${date}T${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
  const doFly = (f: any) => setFly({ ...f, id: ++flyN.current });

  // ---- areas
  useEffect(() => { get("/api/areas").then(a => { setAreas(a); if (a.length) setAreaId(a[0].area_id); else { setLoading(false); setLoadErr("No analysed area found. Run scripts/run_pilot.py first."); } }).catch(e => { setLoading(false); setLoadErr("Cannot reach the API: " + e.message); }); }, []);
  useEffect(() => {
    if (!areaId) return; setLoading(true); setLoadErr(null); setSelectedId(null); setAoi(null);
    Promise.all([get(`/api/areas/${areaId}/meta`), get(`/api/areas/${areaId}/buildings`), get(`/api/areas/${areaId}/trees`), get(`/api/areas/${areaId}/missing`)])
      .then(([m, b, t, ms]) => { setMeta(m); setBld(b); setTrees(t); setMissing(ms); setLoading(false); doFly({ bounds: m.bbox }); })
      .catch(e => { setLoadErr(e.message); setLoading(false); });
  }, [areaId]);

  // ---- derived
  const feats: any[] = useMemo(() => bld?.features ?? [], [bld]);
  const ramp = useMemo(() => { if (!feats.length) return [0, 1, 2, 3]; const v = feats.map(f => f.properties.kwh_mid).sort((a, b) => a - b); return [q(v, .1), q(v, .5), q(v, .9), q(v, .99)]; }, [feats]);
  const cen = useMemo(() => { const m = new Map<string, number[]>(); feats.forEach(f => { const b = bounds(f.geometry); m.set(f.properties.id, [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]); }); return m; }, [feats]);
  const inAoi = (id: string) => { if (!aoi) return true; const c = cen.get(id)!; return c[0] >= aoi[0] && c[0] <= aoi[2] && c[1] >= aoi[1] && c[1] <= aoi[3]; };
  const items = useMemo(() => feats.filter(f => { const p = f.properties; return p.kwh_mid >= filters.minKwh && p.shading_loss_pct <= filters.maxShade && p.usable_mid_m2 >= filters.minUsable && p.kwp_mid >= filters.minKwp && filters.quality[p.quality as "measured"] && inAoi(p.id); }).sort((a, b) => a.properties.rank - b.properties.rank), [feats, filters, aoi, cen]);
  const dim = useMemo(() => { const hasF = items.length !== feats.length; if (!hasF) return null; return new Set<string>(feats.filter(f => !items.includes(f)).map(f => f.properties.id)); }, [items, feats]);
  const aoiStats = useMemo(() => { if (!aoi) return null; const inside = feats.filter(f => inAoi(f.properties.id)); const km2 = (aoi[2] - aoi[0]) * 111.32 * Math.cos(12.98 * Math.PI / 180) * (aoi[3] - aoi[1]) * 110.57; return { n: inside.length, kwh: inside.reduce((s, f) => s + f.properties.kwh_mid, 0), km2 }; }, [aoi, feats]);

  // ---- shadows (debounced)
  useEffect(() => {
    if (!areaId || !view || !meta) return; let live = true;
    const t = setTimeout(() => { setBusy(true); get(`/api/areas/${areaId}/shadows?time=${timeIso}&west=${view[0]}&south=${view[1]}&east=${view[2]}&north=${view[3]}`).then(r => { if (live) { setSun(r.sun); setShadows(show.shadows ? r : null); setBusy(false); } }).catch(() => { if (live) setBusy(false); }); }, 350);
    return () => { live = false; clearTimeout(t); };
  }, [areaId, view, timeIso, show.shadows, meta]);
  // ---- selected building: roof shade at time
  useEffect(() => {
    if (!areaId || !selectedId) { setRoof(null); return; } let live = true;
    const t = setTimeout(() => get(`/api/areas/${areaId}/buildings/${selectedId}/shade?time=${timeIso}`).then(r => live && setRoof(r)).catch(() => {}), 200);
    return () => { live = false; clearTimeout(t); };
  }, [areaId, selectedId, timeIso]);
  // ---- selected building: detail (recalculated with settings)
  useEffect(() => {
    if (!areaId || !selectedId) { setDetail(null); setDErr(null); return; } let live = true; setDLoading(true);
    const clean = (o: any) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== null && v !== ""));
    const t = setTimeout(() => post(`/api/areas/${areaId}/buildings/${selectedId}/recalculate`, { economics: clean(settings.econ), pv: clean(settings.pv) })
      .then(d => { if (live) { setDetail(d); setDErr(null); setDLoading(false); } }).catch(e => { if (live) { setDErr(e.message); setDLoading(false); } }), 250);
    return () => { live = false; clearTimeout(t); };
  }, [areaId, selectedId, settings]);

  const select = (id: string | null, flyTo = false) => {
    setSelectedId(id); if (id && flyTo) { const f = feats.find(x => x.properties.id === id); if (f) doFly({ bounds: bounds(f.geometry) }); }
  };
  // ---- search
  useEffect(() => {
    if (sq.trim().length < 3) { setSres([]); setSerr(null); return; }
    const t = setTimeout(() => get(`/api/search?q=${encodeURIComponent(sq)}`).then(r => { setSres(r); setSerr(r.length ? null : "No match. Try a neighbourhood or lat, lon."); }).catch(e => { setSres([]); setSerr(e.message); }), 600);
    return () => clearTimeout(t);
  }, [sq]);

  const outsideStudy = aoi && meta && !(aoi[0] >= meta.bbox[0] && aoi[1] >= meta.bbox[1] && aoi[2] <= meta.bbox[2] && aoi[3] <= meta.bbox[3]);
  const mq = meta?.quality_counts;

  return <div className="app">
    <header className="top">
      <div className="brand"><svg width="30" height="30" viewBox="0 0 30 30" aria-hidden><circle cx="15" cy="15" r="14" fill="#F2A900" /><path d="M5 20 L15 9 L25 20 Z" fill="#0B2545" /><rect x="9" y="19" width="12" height="5" fill="#0B2545" /></svg><span>Rooftop Solar Estimator</span></div>
      <div className="search"><input value={sq} onChange={e => setSq(e.target.value)} placeholder="Search a place, address or lat, lon" aria-label="Search location" />
        {(sres.length > 0 || serr) && sq.length > 2 && <div className="results">{serr && <div className="note" style={{ padding: 10 }}>{serr}</div>}{sres.map((r, i) => <button key={i} onClick={() => { doFly(r.bbox ? { bounds: r.bbox } : { center: [r.lon, r.lat], zoom: 16.5 }); setSres([]); setSq(""); }}>{r.name}</button>)}</div>}</div>
      <label className="tb" title="Area with calculations"><span className="lbl">Area</span>
        <select value={areaId ?? ""} onChange={e => setAreaId(e.target.value)} aria-label="Analysed area">{areas.map(a => <option key={a.area_id} value={a.area_id}>{a.name} · {fmt(a.bbox_area_km2, 1)} km²</option>)}</select></label>
      <button className={"tb" + (draw ? " on" : "")} onClick={() => { setDraw(!draw); if (draw) setAoi(null); }}>▭ <span className="lbl">{draw ? "Drawing…" : "Select area"}</span></button>
      <div className="spacer" />
      {mq && <button className="tb" onClick={() => setModal("Data status")} title="Data quality of analysed buildings"><span className="dot" style={{ background: "#F2A900" }} />{mq.estimated} est. <span className="dot" style={{ background: "#8C96A8" }} />{mq.unverified} unv. <span className="dot" style={{ background: "#1F8A70" }} />{mq.measured} meas.</button>}
      <button className="tb" onClick={() => setModal("Methodology")}>ⓘ <span className="lbl">Method &amp; validation</span></button>
      <button className={"tb" + (settingsOpen ? " on" : "")} onClick={() => setSettingsOpen(!settingsOpen)} aria-label="Settings">⚙ <span className="lbl">Settings</span></button>
    </header>
    {settingsOpen && <SettingsPop s={settings} set={setSettings} onClose={() => setSettingsOpen(false)} />}
    <main className="main">
      <MapView basemap={basemap} mode={mode} ramp={ramp} buildings={bld} trees={trees} missing={missing} shadows={shadows} cells={roof?.cells ?? null} study={meta?.bbox ?? null}
        show={show} selectedId={selectedId} dim={dim} fly={fly} draw={draw} aoi={aoi}
        onSelect={id => select(id)} onView={setView} onAoi={b => { setAoi(b); setDraw(false); }} />
      <button className="fab" onClick={() => setLeftOpen(!leftOpen)}>{leftOpen ? "Show map" : "Ranked list"}</button>
      <RankPanel items={items} total={feats.length} selectedId={selectedId} onSelect={id => { select(id, true); if (window.innerWidth <= 900) setLeftOpen(false); }} filters={filters} setFilters={setFilters}
        open={leftOpen} aoiActive={!!aoi} areaName={meta?.name ?? "…"} clearAoi={() => setAoi(null)} />
      <Controls busy={busy} date={date} setDate={setDate} minutes={minutes} setMinutes={setMinutes} sun={sun} shading={show.shadows} show={show} setShow={setShow} mode={mode} setMode={setMode} ramp={ramp}
        basemap={basemap} setBasemap={setBasemap} basemaps={Object.keys(BASEMAPS)} leftOpen={leftOpen} />
      {draw && <div className="hint">Drag on the map to draw a rectangle</div>}
      {aoi && aoiStats && <div className="card floating" style={{ top: 12, left: "50%", transform: "translateX(-50%)", display: "grid", gap: 6, minWidth: 260 }}>
        <b style={{ fontFamily: "var(--font-display)" }}>Selected area · {fmt(aoiStats.km2, 2)} km²</b>
        <span className="sub">{fmt(aoiStats.n)} analysed buildings · {fmt(aoiStats.kwh / 1e6, 2)} GWh/yr (middle scenario)</span>
        {outsideStudy && <span className="warn" style={{ margin: 0 }}>Part of this rectangle has no solar calculations yet.</span>}
        <div style={{ display: "flex", gap: 8 }}>{outsideStudy && <button className="btn amber" onClick={() => setAnalyze(true)}>Analyse this area</button>}<button className="btn alt" onClick={() => setAoi(null)}>Clear</button></div></div>}
      {(loading || loadErr) && <div className="card floating" style={{ top: 70, left: "50%", transform: "translateX(-50%)", zIndex: 40 }}>{loading ? "Loading analysed buildings…" : <span className="warn" style={{ display: "block", margin: 0 }}>{loadErr}</span>}</div>}
      <DetailPanel d={detail} loading={dLoading} err={dErr} onClose={() => setSelectedId(null)} roof={roof} timeIso={timeIso} econSettings={settings.econ}
        openContribute={() => setModal("Contribute")} openSettings={() => setSettingsOpen(true)} />
    </main>
    {modal && areaId && <InfoModal area={areaId} meta={meta} start={modal} selectedId={selectedId} onClose={() => setModal(null)} />}
    {analyze && aoi && <AnalyzeDialog bbox={aoi} km2={aoiStats?.km2 ?? 0} onClose={() => setAnalyze(false)} onDone={id => { setAnalyze(false); get("/api/areas").then(a => { setAreas(a); setAreaId(id); }); }} />}
  </div>;
}
