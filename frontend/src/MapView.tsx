import { useEffect, useRef } from "react";
import maplibregl, { Map as MLMap, GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { fmt, QCOL } from "./api";

export const BASEMAPS: Record<string, string> = {
  Light: "https://tiles.openfreemap.org/styles/positron",
  Streets: "https://tiles.openfreemap.org/styles/bright",
  Detailed: "https://tiles.openfreemap.org/styles/liberty",
};
const EMPTY: any = { type: "FeatureCollection", features: [] };

export interface MapProps {
  basemap: string; mode: string; ramp: number[]; buildings: any; trees: any; missing: any; shadows: any; cells: any; study: number[] | null;
  show: { buildings: boolean; trees: boolean; shadows: boolean; missing: boolean; extrude: boolean; study: boolean };
  selectedId: string | null; dim: Set<string> | null; fly: { id: number; bounds?: number[]; center?: number[]; zoom?: number } | null;
  draw: boolean; aoi: number[] | null;
  onSelect: (id: string | null) => void; onView: (bbox: number[]) => void; onAoi: (b: number[]) => void;
}

const RAMP_COL = ["#E3EAF6", "#F8DE8C", "#F2A900", "#C77700", "#7A3E00"];
export function fillExpr(mode: string, ramp: number[]): any {
  if (mode === "quality") return ["match", ["get", "quality"], "measured", QCOL.measured, "estimated", QCOL.estimated, QCOL.unverified];
  if (mode === "shading") return ["interpolate", ["linear"], ["get", "shading_loss_pct"], 0, "#F2A900", 3, "#E9873A", 8, "#8E4A9B", 20, "#0B2545"];
  if (mode === "height") return ["interpolate", ["linear"], ["get", "height_m"], 3, "#E3EAF6", 8, "#8FA9D3", 15, "#3B5F9E", 30, "#0B2545"];
  const [a, b, c, d] = ramp;
  return ["interpolate", ["linear"], ["get", "kwh_mid"], a, RAMP_COL[0], b, RAMP_COL[1], c, RAMP_COL[2], d, RAMP_COL[3], d * 1.8, RAMP_COL[4]];
}

export default function MapView(p: MapProps) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const props = useRef(p); props.current = p;
  const hover = useRef<string | null>(null);
  const sel = useRef<string | null>(null);
  const popup = useRef<maplibregl.Popup | null>(null);
  const drag = useRef<{ x: number; y: number; lng: number; lat: number } | null>(null);
  const lastBase = useRef(p.basemap);

  const addAll = () => {
    const m = map.current!; const q = props.current;
    const src = (id: string, data: any, extra: any = {}) => { if (!m.getSource(id)) m.addSource(id, { type: "geojson", data, ...extra }); };
    src("trees", q.trees || EMPTY); src("shadows", q.shadows || EMPTY); src("missing", q.missing || EMPTY); src("cells", q.cells || EMPTY);
    src("buildings", q.buildings || EMPTY, { promoteId: "id" });
    src("study", q.study ? boxGeo(q.study) : EMPTY); src("aoi", q.aoi ? boxGeo(q.aoi) : EMPTY);
    const first = m.getStyle().layers?.find(l => l.type === "symbol")?.id;
    const add = (l: any, before?: string) => { if (!m.getLayer(l.id)) m.addLayer(l, before); };
    add({ id: "study-fill", type: "fill", source: "study", paint: { "fill-color": "#0B2545", "fill-opacity": 0.03 } }, first);
    add({ id: "study-line", type: "line", source: "study", paint: { "line-color": "#0B2545", "line-width": 2, "line-dasharray": [3, 2] } }, first);
    add({ id: "trees-fill", type: "fill", source: "trees", paint: { "fill-color": "#3C8D5A", "fill-opacity": 0.34 } }, first);
    add({ id: "shadow-fill", type: "fill", source: "shadows", paint: { "fill-color": ["match", ["get", "kind"], "tree", "#1F4D3A", "#0B2545"], "fill-opacity": ["match", ["get", "kind"], "tree", 0.2, 0.3] } }, first);
    add({ id: "b-3d", type: "fill-extrusion", source: "buildings", layout: { visibility: "none" }, paint: { "fill-extrusion-color": fillExpr(q.mode, q.ramp), "fill-extrusion-height": ["get", "height_m"], "fill-extrusion-opacity": 0.85 } }, first);
    add({ id: "b-fill", type: "fill", source: "buildings", paint: { "fill-color": fillExpr(q.mode, q.ramp),
      "fill-opacity": ["case", ["boolean", ["feature-state", "dim"], false], 0.12, ["boolean", ["feature-state", "selected"], false], 1, ["boolean", ["feature-state", "hover"], false], 0.95, 0.78] } }, first);
    add({ id: "b-line", type: "line", source: "buildings", paint: {
      "line-color": ["case", ["boolean", ["feature-state", "selected"], false], "#0B2545", ["boolean", ["feature-state", "hover"], false], "#0B2545", "rgba(11,37,69,.45)"],
      "line-width": ["case", ["boolean", ["feature-state", "selected"], false], 3, ["boolean", ["feature-state", "hover"], false], 2.2, 0.6] } }, first);
    add({ id: "missing-line", type: "line", source: "missing", paint: { "line-color": "#C8553D", "line-width": 1.6, "line-dasharray": [2, 2] } }, first);
    add({ id: "cells-fill", type: "fill", source: "cells", paint: { "fill-color": ["match", ["get", "state"], "building", "#0B2545", "tree", "#1F7A4D", "#FFD166"], "fill-opacity": 0.85 } });
    add({ id: "aoi-fill", type: "fill", source: "aoi", paint: { "fill-color": "#F2A900", "fill-opacity": 0.12 } });
    add({ id: "aoi-line", type: "line", source: "aoi", paint: { "line-color": "#B86E00", "line-width": 2.5 } });
    applyVisibility(true); sel.current = null; hover.current = null; applySelection(); applyDim();
  };

  const applyVisibility = (force?: boolean) => {
    const m = map.current; if (!m || (force !== true && !m.isStyleLoaded())) return; const s = props.current.show;
    const v = (id: string, on: boolean) => m.getLayer(id) && m.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    v("b-fill", s.buildings && !s.extrude); v("b-line", s.buildings && !s.extrude); v("b-3d", s.buildings && s.extrude);
    v("trees-fill", s.trees); v("shadow-fill", s.shadows); v("missing-line", s.missing); v("study-line", s.study); v("study-fill", s.study);
    m.setPitch(s.extrude ? Math.max(m.getPitch(), 50) : 0);
  };
  const applySelection = () => {
    const m = map.current; if (!m || !m.getSource("buildings")) return; const id = props.current.selectedId;
    if (sel.current && sel.current !== id) m.setFeatureState({ source: "buildings", id: sel.current }, { selected: false });
    if (id) m.setFeatureState({ source: "buildings", id }, { selected: true });
    sel.current = id;
  };
  const dimmed = useRef<Set<string>>(new Set());
  const applyDim = () => {
    const m = map.current; if (!m || !m.getSource("buildings")) return; const d = props.current.dim;
    dimmed.current.forEach(id => { if (!d || !d.has(id)) m.setFeatureState({ source: "buildings", id }, { dim: false }); });
    if (d) d.forEach(id => { if (!dimmed.current.has(id)) m.setFeatureState({ source: "buildings", id }, { dim: true }); });
    dimmed.current = d ? new Set(d) : new Set();
  };

  useEffect(() => {
    const m = new maplibregl.Map({ container: el.current!, style: BASEMAPS[p.basemap], center: [77.64, 12.979], zoom: 15.4, maxZoom: 20, attributionControl: { compact: true } });
    map.current = m; (window as any).__rse_map = m;
    m.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
    m.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    m.on("style.load", addAll);
    const view = () => { const b = m.getBounds(); props.current.onView([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]); };
    m.on("moveend", view); m.on("load", view);
    m.on("mousemove", "b-fill", e => {
      if (props.current.draw) return; const f = e.features?.[0]; if (!f) return; const id = String(f.properties!.id);
      m.getCanvas().style.cursor = "pointer";
      if (hover.current !== id) { if (hover.current) m.setFeatureState({ source: "buildings", id: hover.current }, { hover: false }); hover.current = id; m.setFeatureState({ source: "buildings", id }, { hover: true }); }
      const q = f.properties as any;
      popup.current?.remove();
      popup.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 }).setLngLat(e.lngLat)
        .setHTML(`<b>Rank ${q.rank}</b> · ${fmt(q.area_m2)} m² · ${fmt(q.height_m, 1)} m<br>${fmt(q.kwh_mid)} kWh/yr (middle)<br><span style="color:#5B6B84">${q.quality}</span>`).addTo(m);
    });
    m.on("mouseleave", "b-fill", () => { m.getCanvas().style.cursor = props.current.draw ? "crosshair" : ""; if (hover.current) m.setFeatureState({ source: "buildings", id: hover.current }, { hover: false }); hover.current = null; popup.current?.remove(); });
    m.on("click", e => {
      if (props.current.draw) return;
      const f = m.queryRenderedFeatures(e.point, { layers: [m.getLayer("b-3d") && m.getLayoutProperty("b-3d", "visibility") === "visible" ? "b-3d" : "b-fill"] })[0];
      props.current.onSelect(f ? String(f.properties!.id) : null);
    });
    // rectangle area selection
    m.on("mousedown", e => {
      if (!props.current.draw) return; e.preventDefault();
      drag.current = { x: e.point.x, y: e.point.y, lng: e.lngLat.lng, lat: e.lngLat.lat };
    });
    m.on("mousemove", e => {
      if (!props.current.draw || !drag.current) return; const d = drag.current;
      (m.getSource("aoi") as GeoJSONSource)?.setData(boxGeo([Math.min(d.lng, e.lngLat.lng), Math.min(d.lat, e.lngLat.lat), Math.max(d.lng, e.lngLat.lng), Math.max(d.lat, e.lngLat.lat)]));
    });
    const end = (ev: MouseEvent) => {
      if (!props.current.draw || !drag.current) return; const d = drag.current; drag.current = null;
      const r = m.getCanvas().getBoundingClientRect(); const x = ev.clientX - r.left, y = ev.clientY - r.top; const ll = m.unproject([x, y]);
      if (Math.abs(x - d.x) > 8 && Math.abs(y - d.y) > 8) props.current.onAoi([Math.min(d.lng, ll.lng), Math.min(d.lat, ll.lat), Math.max(d.lng, ll.lng), Math.max(d.lat, ll.lat)]);
      else (m.getSource("aoi") as GeoJSONSource)?.setData(props.current.aoi ? boxGeo(props.current.aoi) : EMPTY);
    };
    window.addEventListener("mouseup", end);
    return () => { window.removeEventListener("mouseup", end); m.remove(); map.current = null; };
  }, []);

  const setData = (id: string, data: any) => { const s = map.current?.getSource(id) as GeoJSONSource | undefined; s?.setData(data || EMPTY); };
  useEffect(() => { if (map.current?.getSource("buildings")) { setData("buildings", p.buildings); hover.current = null; sel.current = null; dimmed.current = new Set(); applySelection(); applyDim(); } }, [p.buildings]);
  useEffect(() => setData("trees", p.trees), [p.trees]);
  useEffect(() => setData("missing", p.missing), [p.missing]);
  useEffect(() => setData("shadows", p.shadows), [p.shadows]);
  useEffect(() => setData("cells", p.cells), [p.cells]);
  useEffect(() => setData("study", p.study ? boxGeo(p.study) : null), [p.study]);
  useEffect(() => setData("aoi", p.aoi ? boxGeo(p.aoi) : null), [p.aoi]);
  useEffect(() => applyVisibility(), [p.show]);
  useEffect(applySelection, [p.selectedId]);
  useEffect(applyDim, [p.dim]);
  useEffect(() => {
    const m = map.current; if (!m) return;
    m.getCanvas().style.cursor = p.draw ? "crosshair" : "";
    if (p.draw) { m.doubleClickZoom.disable(); m.dragPan.disable(); m.boxZoom.disable(); m.dragRotate.disable(); }
    else { m.doubleClickZoom.enable(); m.dragPan.enable(); m.boxZoom.enable(); m.dragRotate.enable(); }
  }, [p.draw]);
  useEffect(() => {
    const m = map.current; if (!m || !m.getLayer("b-fill")) return; const e = fillExpr(p.mode, p.ramp);
    m.setPaintProperty("b-fill", "fill-color", e); m.setPaintProperty("b-3d", "fill-extrusion-color", e);
  }, [p.mode, p.ramp]);
  useEffect(() => { if (lastBase.current !== p.basemap) { lastBase.current = p.basemap; map.current?.setStyle(BASEMAPS[p.basemap]); } }, [p.basemap]);
  useEffect(() => {
    const m = map.current; const f = p.fly; if (!m || !f) return;
    if (f.bounds) m.fitBounds([[f.bounds[0], f.bounds[1]], [f.bounds[2], f.bounds[3]]], { padding: (() => { const w = m.getContainer().clientWidth, h = m.getContainer().clientHeight; const wide = w > 900; return { top: Math.min(80, h / 6), bottom: Math.min(120, h / 4), left: wide ? 380 : 24, right: wide ? 460 : 24 }; })(), maxZoom: 19.3, duration: 900 });
    else if (f.center) m.flyTo({ center: f.center as [number, number], zoom: f.zoom ?? 16, duration: 900 });
  }, [p.fly?.id]);
  return <div className="map" ref={el} aria-label="Interactive map of Bengaluru" />;
}

export const boxGeo = (b: number[]): any => ({ type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]]]] } }] });
