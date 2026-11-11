"""All tunable assumptions live here, each with a provenance record.

Nothing in this file is a measurement of an individual building. Defaults are
documented modelling assumptions; every one can be overridden through the API.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
CACHE = DATA / "cache"
for _p in (RAW, PROCESSED, CACHE):
    _p.mkdir(parents=True, exist_ok=True)

IST_OFFSET_HOURS = 5.5
TZ = "Asia/Kolkata"

# Pilot study area (~2 km2, Kumaraswamy Layout, Bengaluru). lon_min, lat_min, lon_max, lat_max
PILOT = {
    "id": "kumaraswamy-layout",
    "name": "Kumaraswamy Layout pilot",
    "city": "Bengaluru",
    "bbox": (77.5529, 12.9002, 77.5661, 12.9132),
}
# Earlier pilot, kept as a second analysed area
INDIRANAGAR = {"id": "indiranagar-pilot", "name": "Indiranagar–Domlur pilot", "city": "Bengaluru", "bbox": (77.634, 12.973, 77.647, 12.986)}
OBSTACLE_PAD_DEG = 0.0015  # ~165 m ring of neighbouring buildings/trees kept as shadow casters

SCENARIOS = {"low": 0.25, "middle": 0.50, "high": 0.70}  # usable share of roof (presentation)


@dataclass
class PVAssumptions:
    tilt_deg: float = 12.0              # ~latitude of Bengaluru, typical low-tilt flat-roof racking
    azimuth_deg: float = 180.0          # due south; roof orientation is NOT known per building
    albedo: float = 0.20
    module_wp: float = 540.0            # typical mono PERC module (cf. KERC Regs 2026 illustration)
    module_area_m2: float = 2.583       # 2278 x 1134 mm
    layout_efficiency: float = 0.65     # share of usable roof that is module area (row spacing, walkways)
    gamma_pdc: float = -0.0035          # power temperature coefficient (1/degC)
    temperature_model: str = "open_rack_glass_polymer"
    dc_ac_ratio: float = 1.15
    inverter_efficiency: float = 0.97
    iam_b: float = 0.05                 # ASHRAE incidence-angle modifier
    # PVWatts-style loss categories (percent); shading is modelled explicitly, so it is 0 here
    soiling: float = 3.0
    mismatch: float = 2.0
    wiring: float = 2.0
    connections: float = 0.5
    lid: float = 1.5
    nameplate_rating: float = 1.0
    availability: float = 2.0
    # shadow model
    tree_opacity: float = 0.70          # fraction of direct beam blocked by a tree-canopy shadow
    max_shadow_m: float = 150.0         # shadows longer than this are ignored (far-field cut-off)
    min_sun_elevation_deg: float = 3.0  # below this, direct beam is negligible / shadows unreliable
    cell_size_m: float = 1.0
    roof_setback_m: float = 0.5         # edge setback (parapet / fire lane) excluded from roof cells
    max_cells_per_roof: int = 400

    @property
    def module_efficiency(self) -> float:
        return self.module_wp / (1000.0 * self.module_area_m2)

    @property
    def roof_area_per_kwp(self) -> float:
        """Usable roof m2 needed per kWp (module area / layout efficiency)."""
        return (self.module_area_m2 / (self.module_wp / 1000.0)) / self.layout_efficiency

    def to_dict(self):
        d = asdict(self)
        d["module_efficiency"] = self.module_efficiency
        d["roof_area_per_kwp"] = self.roof_area_per_kwp
        return d


# ---------------------------------------------------------------------------
# Economic parameters with source + effective date. 'verified' says whether the
# value was read from an official document in this build (True) or comes from
# secondary sources / analyst assumption (False) and MUST be re-checked.
# ---------------------------------------------------------------------------
KERC_ORDER = "KERC Order dated 25.08.2026 (generic DSPV tariff), hosted at srtpv.bescom.org"
KERC_REGS = "KERC (Grid Interactive DSPV Plants) Regulations, 2026, Notification KERC/F-34/V-38/2026-27/2395 dated 19.08.2026"

BESCOM_TARIFF = "BESCOM 'Electricity Tariff 2026 to 2028' booklet (KERC order dated 27.03.2025) - read from the official PDF supplied by the user"

ECON_PARAMS = {
    "capex_inr_per_kw_domestic_1_10kw": {
        "value": 45000, "unit": "INR/kW", "verified": True,
        "source": KERC_ORDER + " - para 6 'Capital Cost' (MNRE benchmark basis)", "effective": "2026-08-25"},
    "capex_inr_per_kw_non_dcr": {
        "value": 27090, "unit": "INR/kW", "verified": True,
        "source": KERC_ORDER + " - para 6 (market prices Apr-2026, JMK Research; incl. GST)", "effective": "2026-08-25"},
    "capex_inr_per_kw_dcr": {
        "value": 36015, "unit": "INR/kW", "verified": True,
        "source": KERC_ORDER + " - para 6 (DCR cells)", "effective": "2026-08-25"},
    "export_tariff_domestic_1_10kw": {
        "value": 3.89, "unit": "INR/kWh", "verified": True,
        "source": KERC_ORDER + " - order (ii)(a): domestic 1-10 kW, without capital subsidy", "effective": "2026-08-25"},
    "export_tariff_non_dcr": {
        "value": 2.34, "unit": "INR/kWh", "verified": True,
        "source": KERC_ORDER + " - order (ii)(c)", "effective": "2026-08-25"},
    "export_tariff_dcr": {
        "value": 3.11, "unit": "INR/kWh", "verified": True,
        "source": KERC_ORDER + " - order (ii)(c)", "effective": "2026-08-25"},
    "export_tariff_pm_surya_ghar_le2kw": {
        "value": 1.96, "unit": "INR/kWh", "verified": True,
        "source": KERC_ORDER + " - order (ii)(b), with PM Surya Ghar capital subsidy", "effective": "2026-08-25"},
    "retail_energy_charge_lt1": {
        "value": 5.80, "unit": "INR/kWh", "verified": True,
        "source": BESCOM_TARIFF + " - Tariff Schedule LT-1 (domestic), FY2026-27 energy charge 580 paise; fixed Rs150/kW/month", "effective": "2026-04-01"},
    "retail_energy_charge_lt2": {
        "value": 6.55, "unit": "INR/kWh", "verified": True,
        "source": BESCOM_TARIFF + " - Tariff Schedule LT-2 (private professional/educational institutions, nursing homes, private hospitals), FY2026-27: 655 paise; fixed Rs195/kW/month", "effective": "2026-04-01"},
    "retail_energy_charge_lt3a": {
        "value": 6.80, "unit": "INR/kWh", "verified": True,
        "source": BESCOM_TARIFF + " - Tariff Schedule LT-3(a) (commercial), FY2026-27: 680 paise; fixed Rs215/kW/month (Rs235 demand-based option)", "effective": "2026-04-01"},
    "retail_energy_charge_lt5": {
        "value": 4.40, "unit": "INR/kWh", "verified": True,
        "source": BESCOM_TARIFF + " - Tariff Schedule LT-5 (industrial), FY2026-27: 440 paise; fixed Rs150/HP/month", "effective": "2026-04-01"},
    "electricity_tax_rate": {
        "value": 0.09, "unit": "fraction", "verified": True,
        "source": BESCOM_TARIFF + " - 'Electricity Tax': 9% ad valorem on charges payable (Govt of Karnataka Notification No.24 of 19.07.2018). Applied to avoided energy charges.", "effective": "2018-07-19"},
    "srtpv_fixed_charge_rebate": {
        "value": 25, "unit": "INR/kW/month", "verified": True,
        "source": BESCOM_TARIFF + " - LT-1 note (b): LT domestic installations up to 10 kW with rooftop solar get a Rs25/kW rebate in fixed charges on installed SRTPV capacity. Reported separately, not in savings.", "effective": "2025-04-01"},
    "fy25_true_up_charge": {
        "value": 0.56, "unit": "INR/kWh", "verified": False,
        "source": "KERC true-up order 17-Apr-2026 as reported by Deccan Herald etc. (not in the tariff booklet; unverified): recovered May-2026..Apr-2027 on FY2024-25 consumption -> NOT treated as avoided by solar",
        "effective": "2026-05-01"},
    "fixed_charge_avoided": {
        "value": 0.0, "unit": "INR/kW/month", "verified": True,
        "source": KERC_REGS + " - Reg 5.1.6/5.1.7: injected kWh only offsets kWh; fixed/demand charges and levies remain payable -> never counted as savings",
        "effective": "2026-08-24"},
    "pm_surya_ghar_subsidy_per_kw_first2": {
        "value": 30000, "unit": "INR/kW", "verified": False,
        "source": "MNRE PM Surya Ghar guideline (recalled, not re-fetched this build). Eligibility must be verified. Reported separately, never netted from base cost.",
        "effective": "2024-02-29"},
    "pm_surya_ghar_subsidy_3rd_kw": {
        "value": 18000, "unit": "INR/kW", "verified": False,
        "source": "as above", "effective": "2024-02-29"},
    "pm_surya_ghar_subsidy_cap": {
        "value": 78000, "unit": "INR", "verified": False, "source": "as above", "effective": "2024-02-29"},
    "kerc_reference_cuf": {
        "value": 0.19, "unit": "fraction", "verified": True,
        "source": KERC_ORDER + " - CUF 19% for DSPV (regulatory norm, used only as a reasonableness reference)", "effective": "2026-08-25"},
}


@dataclass
class EconAssumptions:
    metering: str = "net_metering"      # net_metering | net_billing | gross_metering | behind_the_meter
    category: str = "auto"              # auto | domestic | non_domestic
    module_class: str = "non_dcr"       # non_dcr | dcr   (non-domestic cost / export tariff)
    capex_inr_per_kw: float | None = None
    retail_energy_charge: float | None = None
    export_tariff: float | None = None
    # Share of annual generation that displaces retail energy charges. Consumption is unknown, so
    # three labelled scenarios are evaluated; the user can override with a single value.
    self_consumption_scenarios: tuple = (0.30, 0.60, 0.90)
    self_consumption_share: float | None = None
    capex_uncertainty: float = 0.10     # +/- analyst assumption for installed-cost spread
    include_subsidy_estimate: bool = False
    include_electricity_tax: bool = True   # 9% tax is levied on charges payable, so avoided energy charges also avoid it

    def to_dict(self):
        return asdict(self)
