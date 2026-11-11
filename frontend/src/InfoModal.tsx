import { useEffect, useState } from "react";
import { get, post, fmt } from "./api";
import { Modal, Tabs } from "./ui";

const TABS = ["Methodology", "Validation", "Data status", "Assumptions", "Contribute"];
export default function InfoModal(p: { area: string; meta: any; start: string; selectedId: string | null; onClose: () => void }) {
  const [tab, setTab] = useState(p.start);
  const [val, setVal] = useState<any>(null); const [asm, setAsm] = useState<any>(null); const [missing, setMissing] = useState<number | null>(null);
  const [form, setForm] = useState<any>({ roof_type: "flat RCC", obstructions: [] as string[], tall_trees_nearby: false, photo_url: "", notes: "" });
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { get(`/api/areas/${p.area}/validation`).then(setVal).catch(() => setVal({ error: true })); get("/api/assumptions").then(setAsm).catch(() => setAsm({ error: true })); }, [p.area]);
  useEffect(() => { setMissing(p.meta?.qa?.possible_missing_structures ?? null); }, [p.meta]);
  const m = p.meta;
  const OBS = ["water tank", "stair room", "solar water heater", "AC units", "parapet > 1 m"];
  return <Modal title="Method, data and validation" onClose={p.onClose} tabs={<Tabs items={TABS} value={tab} onChange={setTab} />}>
    {tab === "Methodology" && <>
      <p>This tool estimates how much electricity each rooftop in a study area could generate after shadows from neighbouring buildings and trees. Every number is a modelled estimate. Nothing has been field-validated unless the Validation tab says so.</p>
      <h3>1. Footprints and heights</h3>
      <p>Footprints come from Overture Maps (which conflates OpenStreetMap, Google Open Buildings and Microsoft footprints). Duplicates (overlap &gt; 50%) are removed; the result is cross-checked against Open Buildings V3 and OpenStreetMap and structures found in only one other dataset are listed as “possibly missing”, never added silently. Height priority: field-measured → mapped height tag → Open Buildings 2.5D Temporal raster (2023) → floors × 3 m → footprint model (only with ≥10 real measured buildings) → neighbourhood median flagged <i>unverified</i>.</p>
      <h3>2. Shadows</h3>
      <p>Shadow length = (obstacle height − roof height) ÷ tan(sun elevation), cast opposite the sun azimuth (pvlib/NREL SPA). The obstacle footprint is swept along that vector; a roof cell is shaded if it falls inside any swept region. Roof shaded fraction = shaded cells ÷ total cells (1 m grid, 0.5 m edge setback). Obstacles are spatially indexed (STRtree) up to 150 m; the sun must be ≥3° above the horizon. Ground is assumed flat. Trees come from the Meta/WRI canopy height map (buildings masked out, heights 3–35 m) and block 70% of the beam. Only direct beam is reduced; diffuse and ground-reflected light stays.</p>
      <p>Shade is computed for the 15th of each month at every hour and applied to all hours of that month in the NASA typical year. Results are cached by a hash of the geometry and all inputs.</p>
      <h3>3. Energy</h3>
      <p>NASA POWER hourly GHI/DNI/DHI (2015–2024) form a typical year (per month, the year closest to the 10-year mean). NASA’s components do not sum to its own GHI (4–20% low), so DNI and DHI are rescaled hourly to close the balance with GHI as anchor. This is documented, switchable, and reported in Validation. Plane-of-array irradiance uses the Hay-Davies model, an ASHRAE incidence-angle loss, the SAPM cell-temperature model, PVWatts DC with −0.35%/°C, and PVWatts-style losses (soiling, mismatch, wiring, availability …) plus a 97% inverter. Annual energy = Σ hourly AC energy per kWp × capacity.</p>
      <h3>4. Usable roof and capacity</h3>
      <p>Usable area = footprint × 25% / 50% / 70% (low / middle / high). These shares are assumptions for unknown tanks, stair rooms and setbacks. Capacity = usable area ÷ {m ? fmt(m.pv_assumptions.roof_area_per_kwp, 1) : "7.4"} m² per kWp (540 W module, 65% layout efficiency). Tilt 12°, azimuth south; true roof orientation is unknown. The middle scenario drives the ranking.</p>
      <h3>5. Money</h3>
      <p>Simple payback = cost ÷ annual savings. Under net metering/billing only the share of generation that offsets your own consumption earns the retail <i>energy</i> charge; the rest earns the KERC tariff. Under gross metering all output earns the KERC tariff. Retail energy charges are the official BESCOM FY2026-27 rates for the schedule inferred from the building use (LT-1 ₹5.80, LT-2 ₹6.55, LT-3(a) ₹6.80, LT-5 ₹4.40), plus the 9% electricity tax on avoided charges. Fixed charges and the FY25 true-up are never counted as savings; the ₹25/kW LT-1 solar fixed-charge rebate is shown separately. Consumption is unknown, so three self-consumption scenarios (30/60/90%) give a range. Subsidies are reported separately and unverified.</p>
      <h3>Limitations</h3>
      <ul><li>No rooftop obstruction detection; no roof tilt/orientation data.</li><li>NASA POWER is regional (~0.5°×0.625°); it is not a measurement at the building.</li><li>The 2.5D height raster is ~4 m resolution and ML-derived; small buildings are unreliable.</li><li>Canopy data is about 2018–2020; tree growth and felling since then are not captured.</li><li>Month/hour binning of shade approximates day-to-day variation.</li><li>Missing information makes estimates optimistic.</li></ul>
    </>}
    {tab === "Validation" && (!val ? "Loading…" : val.error ? <div className="warn">Validation report unavailable.</div> : <>
      <div className="warn"><b>{val.claim}</b></div>
      <h3>Unshaded yield vs PVGIS (independent check, not an input)</h3>
      {val.pvgis_comparison ? <table className="t"><tbody>
        <tr><td>PVGIS-ERA5 energy (12°, south, 14% loss)</td><td>{fmt(val.pvgis_comparison.pvgis_E_y_kwh_per_kwp)} kWh/kWp</td></tr>
        <tr><td>This model, same configuration</td><td>{fmt(val.pvgis_comparison.model_E_y_kwh_per_kwp_same_loss)} kWh/kWp ({fmt(val.pvgis_comparison.difference_pct, 1)}%)</td></tr>
        <tr><td>Plane-of-array irradiation: PVGIS vs model</td><td>{fmt(val.pvgis_comparison.pvgis_H_i_y_kwh_m2)} vs {fmt(val.pvgis_comparison.model_poa_kwh_m2)} kWh/m² ({fmt(val.pvgis_comparison.poa_difference_pct, 1)}%)</td></tr>
        <tr><td>Without NASA component-closure correction</td><td>{fmt(val.pvgis_comparison.without_component_closure_correction.E_y)} kWh/kWp ({fmt(val.pvgis_comparison.without_component_closure_correction.difference_pct, 1)}%)</td></tr></tbody></table> : <p>PVGIS result not available.</p>}
      <div className="note">{val.pvgis_comparison?.note}</div>
      <h3>Field validation</h3>
      <table className="t"><tbody>
        <tr><td>Height measurements (need 10–15)</td><td>{val.height_measurements.n_measured} · {val.height_measurements.status}</td></tr>
        <tr><td>Shadow checks (3–5 roofs × 3 times)</td><td>{val.shadow_field_checks.n_checks} · {val.shadow_field_checks.status}</td></tr>
        <tr><td>Footprint QA sample of 20 roofs</td><td style={{ textAlign: "left" }}>{val.footprint_qa_sample_of_20_roofs}</td></tr>
        <tr><td>Footprint-based height model</td><td>{val.height_model.calibrated ? "calibrated" : "not calibrated"} — {val.height_model.reason || ""}</td></tr></tbody></table>
      <h3>Second-pass tree review</h3><pre style={{ whiteSpace: "pre-wrap", fontSize: 13 }}>{typeof val.tree_second_pass === "string" ? val.tree_second_pass : JSON.stringify(val.tree_second_pass, null, 1)}</pre>
      <div className="note">Record field data through POST /api/validation/height-measurements and /shadow-checks, then re-run the pipeline. Errors appear here automatically.</div></>)}
    {tab === "Data status" && m && <>
      <p><b>{m.name}</b> — {fmt(m.bbox_area_km2, 2)} km² analysed, {fmt(m.n_buildings_analysed)} buildings. Outside the dashed boundary the map is a basemap only: no solar calculations exist there.</p>
      <table className="t"><tbody>
        <tr><td>Measured / Estimated / Unverified</td><td>{m.quality_counts.measured} / {m.quality_counts.estimated} / {m.quality_counts.unverified}</td></tr>
        <tr><td>Possibly missing structures (other datasets)</td><td>{missing}</td></tr>
        <tr><td>Shadow-casting buildings / canopy patches</td><td>{fmt(m.n_obstacle_buildings)} / {fmt(m.n_tree_patches)}</td></tr>
        <tr><td>Unshaded yield</td><td>{fmt(m.unshaded_kwh_per_kwp)} kWh/kWp</td></tr>
        <tr><td>Generated</td><td>{m.generated}</td></tr></tbody></table>
      <h3>Height sources</h3><table className="t"><tbody>{Object.entries(m.height_source_counts).map(([k, v]: any) => <tr key={k}><td>{k.replace(/_/g, " ")}</td><td>{fmt(v)}</td></tr>)}</tbody></table>
      <h3>Datasets</h3>
      <ul><li>Overture Maps buildings {m.datasets.overture_release} — ODbL / CDLA-P</li><li>Google Open Buildings V3 polygons — CC BY 4.0 / ODbL</li><li>Open Buildings 2.5D Temporal (2023) — CC BY 4.0</li><li>Meta / WRI Global Canopy Height Map v1 — CC BY 4.0</li><li>NASA POWER hourly — public domain</li><li>PVGIS (comparison only) — © European Union</li><li>Basemap: OpenFreeMap / © OpenStreetMap contributors (ODbL)</li></ul>
      <h3>QA details</h3><pre style={{ whiteSpace: "pre-wrap", fontSize: 12.5, background: "#F3F6FB", padding: 10, borderRadius: 8 }}>{JSON.stringify(m.qa, null, 1)}</pre></>}
    {tab === "Assumptions" && (!asm ? "Loading…" : asm.error ? <div className="warn">Unavailable.</div> : <>
      <p>Every economic parameter, its source and whether it was verified against an official document in this build.</p>
      <table className="t"><thead><tr><th>Parameter</th><th>Value</th><th>Verified</th></tr></thead><tbody>{Object.entries(asm.economic).map(([k, v]: any) => <tr key={k}><td style={{ textAlign: "left" }}>{k.replace(/_/g, " ")}<br /><span className="note">{v.source} · effective {v.effective}</span></td><td>{fmt(v.value, 2)} {v.unit}</td><td>{v.verified ? "yes" : <b style={{ color: "#C8553D" }}>no</b>}</td></tr>)}</tbody></table></>)}
    {tab === "Contribute" && <div className="form">
      <p>Add what you know about a roof. It is stored as <b>unverified</b> and does not change any result until a reviewer checks it.</p>
      {!p.selectedId ? <div className="info">Select a building on the map first.</div> : <>
        <label>Building<input readOnly value={p.selectedId} /></label>
        <label>Roof type<select value={form.roof_type} onChange={e => setForm({ ...form, roof_type: e.target.value })}>{["flat RCC", "sloped tile", "metal sheet", "mixed", "unknown"].map(x => <option key={x}>{x}</option>)}</select></label>
        <div>{OBS.map(o => <label key={o} style={{ display: "inline-flex", gap: 6, marginRight: 12 }}><input type="checkbox" checked={form.obstructions.includes(o)} onChange={e => setForm({ ...form, obstructions: e.target.checked ? [...form.obstructions, o] : form.obstructions.filter((x: string) => x !== o) })} />{o}</label>)}</div>
        <label style={{ display: "flex", gap: 8 }}><input type="checkbox" checked={form.tall_trees_nearby} onChange={e => setForm({ ...form, tall_trees_nearby: e.target.checked })} />Tall trees nearby</label>
        <label>Photo link (optional)<input value={form.photo_url} onChange={e => setForm({ ...form, photo_url: e.target.value })} placeholder="https://…" /></label>
        <label>Notes<textarea rows={3} value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></label>
        <button className="btn amber" onClick={() => post("/api/contributions", { ...form, building_id: p.selectedId }).then(r => setMsg(r.note)).catch(e => setMsg(String(e.message)))}>Submit as unverified</button>
        {msg && <div className="info">{msg}</div>}</>}
    </div>}
  </Modal>;
}
