import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis, LineChart } from "recharts";
import { fmt, inr, yrs, Q } from "./api";
import { Badge, Metric, Tabs, Term } from "./ui";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const TABS = ["Overview", "Shading", "Energy", "Money", "Data"];
const SC = ["low", "middle", "high"] as const;

function Heat({ m, month, hourUtc }: { m: number[][]; month: number; hourUtc: number }) {
  const rows = Array.from({ length: 13 }, (_, h) => h); // UTC interval start 0..12 => IST mid-interval 06:00..18:00
  const col = (v: number) => { const t = Math.min(v / 100, 1); const a = [255, 244, 214], b = [11, 37, 69]; return `rgb(${a.map((x, i) => Math.round(x + (b[i] - x) * t)).join(",")})`; };
  return <svg viewBox="0 0 300 232" width="100%" role="img" aria-label="Roof shading by month and hour">
    {rows.map(h => <text key={h} x="24" y={22 + h * 15 + 10} fontSize="9" textAnchor="end" fill="#5B6B84">{String((h + 6) % 24).padStart(2, "0")}h</text>)}
    {MONTHS.map((n, i) => <text key={n} x={32 + i * 22 + 10} y="12" fontSize="9" textAnchor="middle" fill="#5B6B84">{n[0]}</text>)}
    {rows.map(h => MONTHS.map((n, i) => { const v = m[i][h] ?? 0; return <rect key={n + h} x={30 + i * 22} y={20 + h * 15} width="21" height="14" rx="2" fill={col(v)} stroke={i === month && h === hourUtc ? "#F2A900" : "none"} strokeWidth="2.5"><title>{`${n} ${String((h + 6) % 24).padStart(2, "0")}:00 IST: ${v}% of direct sunlight blocked`}</title></rect>; }))}
    <text x="30" y="228" fontSize="9" fill="#5B6B84">Light = full sun · navy = direct beam blocked</text>
  </svg>;
}

export default function DetailPanel(p: { d: any | null; loading: boolean; err: string | null; onClose: () => void; roof: any | null; timeIso: string; econSettings: any; openContribute: () => void; openSettings: () => void }) {
  const [tab, setTab] = useState("Overview");
  const d = p.d;
  const open = !!(d || p.loading || p.err);
  const body = () => {
    if (p.err) return <div className="warn">{p.err}</div>;
    if (!d) return <div className="note">Loading analysis…</div>;
    const mid = d.energy.scenarios.middle, fin = d.financial, sh = d.shading;
    const month = Number(p.timeIso.slice(5, 7)) - 1;
    const hrIst = Number(p.timeIso.slice(11, 13)) + Number(p.timeIso.slice(14, 16)) / 60;
    const hUtc = Math.round(hrIst - 6.0);
    const retailOk = d.financial.middle.retail_energy_charge_inr_per_kwh;
    if (tab === "Overview") return <>
      <div className="metrics">
        <Metric hero k={<>Estimated annual generation, <Term t="usable area">middle scenario</Term></>} v={fmt(mid.annual_kwh)} u="kWh / year" />
        <Metric k="Range (low – high)" v={`${fmt(d.energy.scenarios.low.annual_kwh)}–${fmt(d.energy.scenarios.high.annual_kwh)}`} u="kWh" />
        <Metric k={<><Term t="kWh/kWp/year" /></>} v={fmt(d.energy.kwh_per_kwp_year)} />
        <Metric k={<><Term t="kWp">Capacity</Term> (middle)</>} v={fmt(mid.capacity_kwp, 1)} u="kWp" />
        <Metric k="Annual shading loss" v={fmt(sh.annual_energy_loss_pct, 1)} u="%" />
        <Metric k={<><Term t="payback">Payback</Term> (mid)</>} v={yrs(fin.middle.payback_years.mid)} />
        <Metric k="Rank in area" v={`#${d.rank}`} />
      </div>
      <h3 className="sec">Building</h3>
      <table className="t"><tbody>
        <tr><td>ID</td><td>{d.id.slice(0, 18)}…</td></tr>
        <tr><td>Address / name</td><td>{d.address || d.name || "not mapped"}</td></tr>
        <tr><td>Footprint</td><td>{fmt(d.building.footprint_m2, 1)} m²</td></tr>
        <tr><td>Height</td><td>{fmt(d.building.height_m, 1)} m ({fmt(d.building.height_range_m[0], 1)}–{fmt(d.building.height_range_m[1], 1)})</td></tr>
        <tr><td>Floors</td><td>{d.building.floors ?? "not available"}</td></tr>
        <tr><td>Height source</td><td>{d.building.height_source.replace(/_/g, " ")}</td></tr>
        <tr><td>Data quality</td><td><Badge q={d.transparency.quality as Q} /></td></tr>
      </tbody></table>
      <h3 className="sec">Roof and capacity</h3>
      <table className="t"><thead><tr><th></th><th>Usable share</th><th>Area m²</th><th>kWp</th></tr></thead><tbody>
        {SC.map(k => <tr key={k}><td style={{ textTransform: "capitalize" }}>{k}</td><td>{fmt(d.roof.scenarios[k].share * 100)}%</td><td>{fmt(d.roof.scenarios[k].usable_area_m2, 1)}</td><td>{fmt(d.roof.scenarios[k].capacity_kwp, 1)}</td></tr>)}
      </tbody></table>
      <div className="note" style={{ marginTop: 6 }}>Usable shares are modelling assumptions for tanks, stair rooms and setbacks, not measurements of this roof.</div>
    </>;
    if (tab === "Shading") {
      const rs = p.roof;
      const daily = Array.from({ length: 13 }, (_, h) => ({ h: `${String((h + 6) % 24).padStart(2, "0")}h`, loss: sh.matrix_beam_loss_pct[month][h], buildings: sh.matrix_building_pct[month][h], trees: Math.round(sh.matrix_tree_pct[month][h] * 0.7) }));
      return <>
        <div className="metrics">
          <Metric hero k={<>Roof in direct shadow at the selected time (<Term t="shaded fraction" />)</>} v={rs ? fmt(rs.fractions.shaded_fraction * 100, 0) : "…"} u="%" />
          <Metric k="from buildings" v={rs ? fmt(rs.fractions.building_fraction * 100, 0) : "…"} u="%" /><Metric k="from trees (partial)" v={rs ? fmt(rs.fractions.tree_fraction * 100, 0) : "…"} u="%" />
        </div>
        <div className="note">Move the shadow-time slider on the map; the roof cells on the map turn navy (building shadow), green (tree shadow) or amber (sunlit).</div>
        <h3 className="sec">Shadow sources right now</h3>
        {rs && rs.sources.length ? <table className="t"><thead><tr><th>Source</th><th>Height</th><th>Distance</th><th>Shadow length</th></tr></thead><tbody>
          {rs.sources.map((s: any) => <tr key={s.id}><td>{s.type}</td><td>{fmt(s.height_m, 1)} m</td><td>{fmt(s.distance_m, 0)} m</td><td>{fmt(s.shadow_length_m, 0)} m</td></tr>)}</tbody></table>
          : <div className="note">{rs && rs.sun.elevation <= 0 ? "Sun is below the horizon." : "No taller building or tree is close enough to reach this roof at this time."}</div>}
        <h3 className="sec">Seasonal and daily pattern</h3>
        <Heat m={sh.matrix_beam_loss_pct} month={month} hourUtc={hUtc} />
        <div className="note">Month × hour of day (IST) on the 15th of each month. Outlined cell = the selected time.</div>
        <div style={{ height: 150, marginTop: 8 }}><ResponsiveContainer><LineChart data={daily}><CartesianGrid stroke="#E8EDF5" /><XAxis dataKey="h" fontSize={11} /><YAxis unit="%" fontSize={11} domain={[0, 100]} /><Tooltip /><Line dataKey="loss" name={`Direct beam blocked, ${MONTHS[month]}`} stroke="#0B2545" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></div>
        <table className="t" style={{ marginTop: 8 }}><thead><tr><th>Season</th><th>Share of year</th><th>Shading loss</th></tr></thead><tbody>
          {Object.entries(sh.seasons).map(([k, v]: any) => <tr key={k}><td>{k}</td><td>{fmt(v.share_of_year * 100, 0)}%</td><td>{fmt(v.shading_loss_pct, 1)}%</td></tr>)}</tbody></table>
        <div className="info">Trees block {fmt(sh.tree_share_of_loss_pct, 0)}% of this roof's beam loss. Tree shadows are treated as 70% opaque; canopy data is from about 2018–2020 and unchecked in the field. Diffuse sunlight is kept even inside a direct shadow.</div>
      </>;
    }
    if (tab === "Energy") {
      const data = MONTHS.map((n, i) => ({ n, shaded: mid.monthly_kwh[i], unshaded: d.energy.monthly_kwh_per_kwp_unshaded[i] * mid.capacity_kwp }));
      return <>
        <div className="metrics">
          <Metric hero k="Annual generation after shading and losses" v={fmt(mid.annual_kwh)} u="kWh" />
          <Metric k={<>Specific yield</>} v={fmt(d.energy.kwh_per_kwp_year)} u="kWh/kWp/yr" /><Metric k="Shading loss" v={fmt(sh.annual_energy_loss_pct, 1)} u="%" />
        </div>
        <h3 className="sec">Monthly generation (middle scenario)</h3>
        <div style={{ height: 210 }}><ResponsiveContainer><ComposedChart data={data}><CartesianGrid stroke="#E8EDF5" vertical={false} /><XAxis dataKey="n" fontSize={11} /><YAxis fontSize={11} width={44} /><Tooltip formatter={(v: any) => fmt(Number(v)) + " kWh"} /><Legend />
          <Bar dataKey="shaded" name="With shading" fill="#F2A900" radius={[3, 3, 0, 0]} /><Line dataKey="unshaded" name="Unshaded" stroke="#0B2545" strokeDasharray="4 3" dot={false} /></ComposedChart></ResponsiveContainer></div>
        <h3 className="sec">Three roof-area scenarios</h3>
        <table className="t"><thead><tr><th></th><th>kWp</th><th>kWh/yr</th><th>Unshaded</th></tr></thead><tbody>
          {SC.map(k => <tr key={k}><td style={{ textTransform: "capitalize" }}>{k}</td><td>{fmt(d.energy.scenarios[k].capacity_kwp, 1)}</td><td>{fmt(d.energy.scenarios[k].annual_kwh)}</td><td>{fmt(d.energy.scenarios[k].annual_kwh_unshaded)}</td></tr>)}</tbody></table>
        <div className="note" style={{ marginTop: 6 }}>Panels: {d.energy.pv_assumptions.tilt_deg}° tilt, azimuth {d.energy.pv_assumptions.azimuth_deg}° (roof orientation is unknown), total system loss {fmt(d.energy.pv_assumptions.system_loss * 100, 1)}%. Irradiance: NASA POWER typical year, regional ~50 km grid. The unshaded value is a resource, not what this roof generates.</div>
      </>;
    }
    if (tab === "Money") {
      const f = fin.middle;
      return <>
        <div className="info">Indicative estimate. Retail energy charge ₹{f.retail_energy_charge_inr_per_kwh}/kWh ({f.tariff_schedule}, BESCOM Tariff 2026–28, FY2026-27) and a 9% electricity tax on avoided charges are from the official BESCOM tariff book. Export tariff ₹{f.export_tariff_inr_per_kwh}/kWh and capital cost ₹{fmt(f.capex_inr_per_kw)}/kW come from the KERC order of 25 Aug 2026. The tariff schedule is inferred from the building use, not from the real connection.</div>
        <table className="t"><thead><tr><th></th><th>Cost</th><th>Savings / yr</th><th>Payback</th></tr></thead><tbody>
          {SC.map(k => { const e = fin[k]; return <tr key={k}><td style={{ textTransform: "capitalize" }}>{k}<br /><span className="note">{fmt(d.energy.scenarios[k].capacity_kwp, 1)} kWp</span></td>
            <td>{inr(e.cost_inr.low)}–{inr(e.cost_inr.high)}</td><td>{inr(e.annual_savings_inr.low)}–{inr(e.annual_savings_inr.high)}</td><td>{yrs(e.payback_years.best)}–{yrs(e.payback_years.worst)}</td></tr>; })}</tbody></table>
        <h3 className="sec">Assumptions behind the range</h3>
        <table className="t"><tbody>
          <tr><td><Term t="net metering">Metering</Term></td><td>{f.metering.replace(/_/g, " ")}</td></tr>
          <tr><td>Consumer category</td><td>{f.category.replace(/_/g, "-")} (by system size)</td></tr>
          <tr><td>Avoided retail energy charge</td><td>₹{f.retail_energy_charge_inr_per_kwh}/kWh</td></tr>
          <tr><td>Export compensation</td><td>₹{f.export_tariff_inr_per_kwh}/kWh</td></tr>
          <tr><td><Term t="self-consumption">Self-consumption scenarios</Term></td><td>{f.self_consumption_scenarios.map((x: number) => fmt(x * 100) + "%").join(" / ")} (low / mid / high)</td></tr>
          <tr><td>Tariff schedule</td><td>{f.tariff_schedule}</td></tr>
          <tr><td>Fixed charges</td><td>not counted as savings</td></tr>
          {f.fixed_charge_rebate_inr_per_year != null && <tr><td>LT-1 solar fixed-charge rebate (₹25/kW/month)</td><td>{inr(f.fixed_charge_rebate_inr_per_year)}/yr, shown separately</td></tr>}</tbody></table>
        {f.below_1kw_minimum && <div className="warn">This roof's capacity is below the 1 kW minimum for net metering.</div>}
        {f.subsidy && <div className="info">Possible PM Surya Ghar subsidy (eligibility <b>not verified</b>): {inr(f.subsidy.amount_inr)}. Shown separately — net cost {inr(f.subsidy.net_cost_inr_mid)}, payback {yrs(f.subsidy.payback_years_mid_after_subsidy)}.</div>}
        <div className="note" style={{ marginTop: 8 }}>{f.note}</div>
        <button className="btn alt" style={{ marginTop: 10 }} onClick={p.openSettings}>Change financial assumptions</button>
      </>;
    }
    const t = d.transparency;
    return <>
      <div style={{ marginBottom: 10 }}><Badge q={t.quality} /></div>
      <div className="info">Missing information can make these estimates too optimistic. Status levels: <b>Measured</b> = field measurement; <b>Estimated</b> = documented method; <b>Unverified</b> = missing, conflicting or unchecked.</div>
      {t.flags.length > 0 && <><h3 className="sec">Flags</h3><ul>{t.flags.map((x: string) => <li key={x}>{x.replace(/_/g, " ")}</li>)}</ul></>}
      <h3 className="sec">Sources</h3>
      <table className="t"><tbody>
        <tr><td>Footprint</td><td style={{ textAlign: "left" }}>{t.sources.footprint}</td></tr>
        <tr><td>Cross-checks</td><td style={{ textAlign: "left" }}>Open Buildings V3 overlap: {t.sources.footprint_crosschecks.open_buildings_v3_overlap ? "yes" : "no"} · OSM overlap: {t.sources.footprint_crosschecks.osm_direct_overlap ? "yes" : "no"}</td></tr>
        <tr><td>Height</td><td style={{ textAlign: "left" }}>{t.sources.height.replace(/_/g, " ")}</td></tr>
        <tr><td>Canopy</td><td style={{ textAlign: "left" }}>{t.sources.canopy}</td></tr>
        <tr><td>Irradiance</td><td style={{ textAlign: "left" }}>{t.sources.irradiance}</td></tr>
        {Object.entries(t.sources.dataset_dates).map(([k, v]: any) => <tr key={k}><td>{k.replace(/_/g, " ")}</td><td style={{ textAlign: "left" }}>{v}</td></tr>)}</tbody></table>
      <h3 className="sec">Uncertainties</h3><ul>{t.uncertainties.map((x: string) => <li key={x}>{x}</li>)}</ul>
      <h3 className="sec">Missing information</h3><ul>{t.missing.map((x: string) => <li key={x}>{x}</li>)}</ul>
      <button className="btn amber" onClick={p.openContribute}>Contribute roof details</button>
      <div className="note" style={{ marginTop: 6 }}>Contributions stay unverified until checked and never change calculations automatically.</div>
    </>;
  };
  return <aside className={"right" + (open ? " open" : "")} aria-label="Building analysis">
    <div className="dhead" style={{ position: "relative" }}>
      <button className="x" onClick={p.onClose} aria-label="Close building analysis">✕</button>
      <div style={{ fontSize: 12.5, color: "#B9C6DC" }}>Rooftop analysis</div>
      <h2>{d ? (d.address || d.name || `Building #${d.rank}`) : "Loading…"}</h2>
      {d && <div style={{ marginTop: 6 }}><Badge q={d.transparency.quality} /> <span style={{ fontSize: 13, color: "#B9C6DC" }}>{fmt(d.building.footprint_m2)} m² · {fmt(d.building.height_m, 1)} m</span></div>}
    </div>
    <Tabs items={TABS} value={tab} onChange={setTab} cls="tabs" />
    <div className="dbody">{body()}</div>
  </aside>;
}
