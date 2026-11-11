export type Q = "measured" | "estimated" | "unverified";
export const get = async (url: string): Promise<any> => {
  const r = await fetch(url);
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch { /* ignore */ } throw new Error(m); }
  return r.json();
};
export const post = async (url: string, body: any): Promise<any> => {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch { /* ignore */ } throw new Error(m); }
  return r.json();
};
export const fmt = (n: number | null | undefined, d = 0) => n == null || !isFinite(n) ? "–" : n.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
export const inr = (n: number | null | undefined) => n == null ? "–" : "₹" + (n >= 1e7 ? fmt(n / 1e7, 2) + " Cr" : n >= 1e5 ? fmt(n / 1e5, 2) + " L" : fmt(n));
export const yrs = (n: number | null | undefined) => n == null ? "–" : fmt(n, 1) + " y";
export const QCOL: Record<Q, string> = { measured: "#1F8A70", estimated: "#F2A900", unverified: "#8C96A8" };
export const GLOSS: Record<string, string> = {
  kWp: "Kilowatt-peak: the rated DC power of the panels under standard test conditions.",
  "kWh/kWp/year": "Specific yield: annual AC electricity per kWp installed. Lets you compare roofs independent of size.",
  GHI: "Global Horizontal Irradiance: total sunlight on a flat horizontal surface.",
  DNI: "Direct Normal Irradiance: the sun's direct beam measured facing the sun.",
  DHI: "Diffuse Horizontal Irradiance: sunlight scattered by the sky; it still reaches a roof in a direct-beam shadow.",
  "shaded fraction": "Shaded roof cells ÷ all roof cells at one moment (geometric, from building and tree shadows).",
  "beam loss": "Share of direct sunlight blocked. Building shadows block all of it; tree shadows only partly (default 70%).",
  "payback": "Simple payback = installation cost ÷ annual savings. Ignores financing, O&M, degradation and tariff changes.",
  "net metering": "Exports offset your imports; surplus is bought by the utility at the KERC tariff. Fixed charges still apply.",
  "net billing": "Imports billed at retail, exports credited at the KERC tariff, netted monthly.",
  "gross metering": "All generation is sold to the utility at the KERC tariff; consumption is billed at retail.",
  "self-consumption": "Share of generation that displaces retail energy charges. Unknown per building, so three labelled scenarios are shown.",
  "usable area": "Share of the roof footprint assumed free for panels after tanks, stair rooms, setbacks. A modelling assumption, not a measurement.",
};
