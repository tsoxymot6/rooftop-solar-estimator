import { fmt } from "./api";

export interface Settings { econ: any; pv: any }
export const DEFAULT_SETTINGS: Settings = { econ: { metering: "net_metering", category: "auto", module_class: "non_dcr", include_subsidy_estimate: false }, pv: {} };

export default function SettingsPop({ s, set, onClose }: { s: Settings; set: (s: Settings) => void; onClose: () => void }) {
  const e = s.econ, v = s.pv;
  const ne = (k: string, val: any) => set({ ...s, econ: { ...e, [k]: val } });
  const np = (k: string, val: any) => set({ ...s, pv: { ...v, [k]: val } });
  const num = (x: string) => (x === "" ? null : Number(x));
  return <div className="card pop" role="dialog" aria-label="Settings">
    <div style={{ display: "flex", alignItems: "center" }}><h3 style={{ flex: 1 }}>Assumptions</h3><button className="btn alt" onClick={onClose}>Done</button></div>
    <p className="note">Leave a field empty to use the sourced default. Changes recalculate the open building instantly.</p>
    <div className="form">
      <label>Metering arrangement<select value={e.metering} onChange={x => ne("metering", x.target.value)}>
        <option value="net_metering">Net metering</option><option value="net_billing">Net billing</option><option value="gross_metering">Gross metering</option><option value="behind_the_meter">Behind the meter (no export pay)</option></select></label>
      <label>Consumer category<select value={e.category} onChange={x => ne("category", x.target.value)}><option value="auto">Auto (from building use)</option><option value="domestic">Domestic</option><option value="non_domestic">Non-domestic</option></select></label>
      <label>Module class (non-domestic)<select value={e.module_class} onChange={x => ne("module_class", x.target.value)}><option value="non_dcr">Non-DCR (₹27,090/kW)</option><option value="dcr">DCR (₹36,015/kW)</option></select></label>
      <label>Installation cost (₹/kW)<input type="number" placeholder="sourced default" value={e.capex_inr_per_kw ?? ""} onChange={x => ne("capex_inr_per_kw", num(x.target.value))} /></label>
      <label>Retail energy charge avoided (₹/kWh) — BESCOM tariff<input type="number" step="0.01" placeholder="by building use (LT-1 5.80 · LT-3(a) 6.80)" value={e.retail_energy_charge ?? ""} onChange={x => ne("retail_energy_charge", num(x.target.value))} /></label>
      <label>Export compensation (₹/kWh)<input type="number" step="0.01" placeholder="KERC 2.34 / 3.89" value={e.export_tariff ?? ""} onChange={x => ne("export_tariff", num(x.target.value))} /></label>
      <label>Self-consumption share (%, overrides the 30/60/90 scenarios)<input type="number" min={0} max={100} placeholder="scenarios" value={e.self_consumption_share == null ? "" : fmt(e.self_consumption_share * 100)} onChange={x => ne("self_consumption_share", x.target.value === "" ? null : Number(x.target.value) / 100)} /></label>
      <label>Total system loss, performance-ratio driver (%)<input type="number" min={0} max={60} placeholder={`default ≈ ${fmt(11.6, 1)}`} value={v.system_loss_pct ?? ""} onChange={x => np("system_loss_pct", num(x.target.value))} /></label>
      <label>Panel tilt (°)<input type="number" min={0} max={60} placeholder="12" value={v.tilt_deg ?? ""} onChange={x => np("tilt_deg", num(x.target.value))} /></label>
      <label>Panel azimuth (° from north, 180 = south)<input type="number" min={0} max={360} placeholder="180" value={v.azimuth_deg ?? ""} onChange={x => np("azimuth_deg", num(x.target.value))} /></label>
      <label style={{ display: "flex", gap: 8 }}><input type="checkbox" checked={e.include_electricity_tax !== false} onChange={x => ne("include_electricity_tax", x.target.checked)} />Include 9% electricity tax on avoided charges</label>
      <label style={{ display: "flex", gap: 8 }}><input type="checkbox" checked={!!e.include_subsidy_estimate} onChange={x => ne("include_subsidy_estimate", x.target.checked)} />Show possible subsidy separately (unverified)</label>
    </div></div>;
}
