"""Capacity and financial calculations. Indicative only - see README 'Financial method'."""
from __future__ import annotations
from .config import PVAssumptions, EconAssumptions, ECON_PARAMS, SCENARIOS

KW_DOMESTIC_MAX = 10.0


def usable_area_m2(footprint_m2: float, share: float) -> float:
    if footprint_m2 is None or footprint_m2 < 0:
        raise ValueError("footprint area must be >= 0")
    if not 0 <= share <= 1:
        raise ValueError("usable share must be within [0, 1]")
    return footprint_m2 * share


def capacity_kwp(footprint_m2: float, share: float, ap: PVAssumptions | None = None) -> float:
    """Installed kWp = usable roof area / (roof area needed per kWp). Documented in PVAssumptions."""
    ap = ap or PVAssumptions()
    return usable_area_m2(footprint_m2, share) / ap.roof_area_per_kwp


def scenario_table(footprint_m2: float, ap: PVAssumptions | None = None, shares: dict | None = None) -> dict:
    shares = shares or SCENARIOS
    return {k: {"share": s, "usable_area_m2": usable_area_m2(footprint_m2, s), "capacity_kwp": capacity_kwp(footprint_m2, s, ap)}
            for k, s in shares.items()}


def simple_payback_years(cost_inr: float, annual_savings_inr: float):
    """Simple payback = installation cost / annual savings. None when savings are not positive."""
    if cost_inr is None or annual_savings_inr is None:
        raise ValueError("cost and savings required")
    if cost_inr < 0:
        raise ValueError("cost must be >= 0")
    if annual_savings_inr <= 0:
        return None
    return cost_inr / annual_savings_inr


def _p(name):
    return ECON_PARAMS[name]["value"]


# Overture building subtype -> BESCOM LT tariff schedule (energy-charge parameter name). Unknown -> by system size.
SCHEDULE_BY_USE = {"residential": "lt1", "religious": "lt1", "commercial": "lt3a", "entertainment": "lt3a", "service": "lt3a", "transportation": "lt3a",
                   "civic": "lt3a", "medical": "lt2", "education": "lt2", "industrial": "lt5", "agricultural": "lt1"}


def resolve_rates(kwp: float, ea: EconAssumptions, use: str | None = None):
    """Returns (category, schedule, capex/kW, export tariff, retail energy charge).
    Retail energy charge follows the consumer's BESCOM schedule (from the building use); capex and export tariff follow the
    KERC size/category split (domestic 1-10 kW vs others). Medical/education are assumed private (LT-2); government premises differ."""
    sched = SCHEDULE_BY_USE.get(str(use).lower()) if use else None
    if ea.category == "domestic": sched = "lt1"
    elif ea.category == "non_domestic" and sched in (None, "lt1"): sched = "lt3a"
    if sched is None:
        sched = "lt1" if kwp <= KW_DOMESTIC_MAX else "lt3a"
    cat = "domestic" if (sched == "lt1" and kwp <= KW_DOMESTIC_MAX) else "non_domestic"
    if cat == "domestic":
        capex, exp = _p("capex_inr_per_kw_domestic_1_10kw"), _p("export_tariff_domestic_1_10kw")
    else:
        dcr = ea.module_class == "dcr"
        capex = _p("capex_inr_per_kw_dcr" if dcr else "capex_inr_per_kw_non_dcr")
        exp = _p("export_tariff_dcr" if dcr else "export_tariff_non_dcr")
    ret = _p(f"retail_energy_charge_{sched}")
    return cat, sched, (ea.capex_inr_per_kw or capex), (ea.export_tariff if ea.export_tariff is not None else exp), \
        (ea.retail_energy_charge if ea.retail_energy_charge is not None else ret)


def annual_value_inr(gen_kwh: float, share_retail: float, retail: float, export: float, metering: str, tax: float = 0.0) -> float:
    """Value of one year of generation.

    net_metering / net_billing : share displaces retail ENERGY charge, remainder credited at the KERC PPA tariff
    gross_metering            : all generation sold at the PPA tariff (consumption keeps paying retail -> no avoided retail)
    behind_the_meter          : only the self-consumed share has value; injected energy is unpaid
    Fixed/demand charges and the FY25 true-up are never counted as avoided; the 9% electricity tax on avoided energy charges is (tax arg).
    """
    if gen_kwh < 0 or not 0 <= share_retail <= 1 or tax < 0:
        raise ValueError("invalid generation, share or tax")
    retail = retail * (1.0 + tax)      # electricity tax is levied on the charges payable, so avoiding the charge avoids the tax
    if metering in ("net_metering", "net_billing"):
        return gen_kwh * (share_retail * retail + (1 - share_retail) * export)
    if metering == "gross_metering":
        return gen_kwh * export
    if metering == "behind_the_meter":
        return gen_kwh * share_retail * retail
    raise ValueError(f"unknown metering mechanism: {metering}")


def surya_ghar_subsidy_inr(kwp: float) -> float:
    kw = min(kwp, 3.0)
    s = _p("pm_surya_ghar_subsidy_per_kw_first2") * min(kw, 2.0) + _p("pm_surya_ghar_subsidy_3rd_kw") * max(0.0, kw - 2.0)
    return min(s, _p("pm_surya_ghar_subsidy_cap"))


def economics(kwp: float, annual_kwh: float, ea: EconAssumptions | None = None, use: str | None = None) -> dict:
    ea = ea or EconAssumptions()
    if kwp < 0 or annual_kwh < 0:
        raise ValueError("capacity and generation must be >= 0")
    cat, sched, capex_kw, export, retail = resolve_rates(kwp, ea, use)
    tax = _p("electricity_tax_rate") if ea.include_electricity_tax else 0.0
    cost_mid = kwp * capex_kw
    cost = {"low": cost_mid * (1 - ea.capex_uncertainty), "mid": cost_mid, "high": cost_mid * (1 + ea.capex_uncertainty)}
    if ea.self_consumption_share is not None:
        shares = (ea.self_consumption_share,) * 3
    else:
        shares = tuple(ea.self_consumption_scenarios)
    sav = {k: annual_value_inr(annual_kwh, s, retail, export, ea.metering, tax) for k, s in zip(("low", "mid", "high"), shares)}
    pb = {"best": simple_payback_years(cost["low"], sav["high"]), "mid": simple_payback_years(cost["mid"], sav["mid"]),
          "worst": simple_payback_years(cost["high"], sav["low"])}
    out = {"category": cat, "tariff_schedule": sched.replace("lt", "LT-").upper().replace("LT-3A", "LT-3(a)"), "electricity_tax_applied": tax, "metering": ea.metering, "capex_inr_per_kw": capex_kw, "retail_energy_charge_inr_per_kwh": retail,
           "export_tariff_inr_per_kwh": export, "self_consumption_scenarios": list(shares),
           "cost_inr": cost, "annual_savings_inr": sav, "payback_years": pb, "below_1kw_minimum": kwp < 1.0,
           "note": "Indicative. Fixed charges and the FY25 true-up are not counted as savings; 9% electricity tax on avoided energy charges is included. O&M, degradation, financing and tariff escalation are excluded (simple payback)."}
    if cat == "domestic":
        out["fixed_charge_rebate_inr_per_year"] = _p("srtpv_fixed_charge_rebate") * 12 * kwp      # official LT-1 SRTPV rebate, reported separately
    if ea.include_subsidy_estimate and cat == "domestic":
        sub = surya_ghar_subsidy_inr(kwp)
        out["subsidy"] = {"scheme": "PM Surya Ghar (unverified eligibility)", "amount_inr": sub,
                          "net_cost_inr_mid": max(cost_mid - sub, 0.0),
                          "payback_years_mid_after_subsidy": simple_payback_years(max(cost_mid - sub, 0.0), sav["mid"]),
                          "verified": False}
    return out
