"""Acceptance test from the brief: open app -> covered area -> click a real building -> data/shade/energy/finance shown ->
change time -> shadow layer updates -> select another building -> panel updates. Also area selection."""
import json, sys, time, hashlib
from playwright.sync_api import sync_playwright
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp"
JS_SIG = """() => { const m = window.__rse_map; const f = m.querySourceFeatures('shadows');
  const s = JSON.stringify(f.map(x => x.geometry.coordinates)).length; const n = f.length;
  const coords = JSON.stringify(f.map(x => x.geometry.coordinates)); let h = 0; for (let i = 0; i < coords.length; i += 7) h = (h * 31 + coords.charCodeAt(i)) | 0; return [n, s, h]; }"""
JS_CELLS = "() => { const f = window.__rse_map.querySourceFeatures('cells'); const c = {}; f.forEach(x => c[x.properties.state] = (c[x.properties.state]||0)+1); return c; }"
res = {}
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={"width": 1440, "height": 860})
    pg.goto("http://localhost:8000", wait_until="load", timeout=90000); pg.wait_for_selector(".row", timeout=30000); time.sleep(5)
    pg.fill("input[type=date]", "2026-12-21"); time.sleep(3)
    pg.locator("input[type=range]").first.fill("720"); time.sleep(10); s_noon = pg.evaluate(JS_SIG)
    pg.locator("input[type=range]").first.fill("990"); time.sleep(10); s_aft = pg.evaluate(JS_SIG)
    res["shadow_layer_changes_with_time"] = s_noon != s_aft; res["shadow_signatures"] = {"12:00": s_noon, "16:30": s_aft}
    pg.locator(".row").nth(2).click(); pg.wait_for_selector(".right.open .metric.hero", timeout=20000); time.sleep(2)
    pg.get_by_role("tab", name="Shading", exact=True).click()
    pg.locator("input[type=range]").first.fill("720"); time.sleep(6); res["roof_cells_noon"] = pg.evaluate(JS_CELLS); res["roof_shaded_noon"] = pg.locator(".metric.hero").first.inner_text().replace("\n", " ")
    pg.locator("input[type=range]").first.fill("420"); time.sleep(6); res["roof_cells_0700"] = pg.evaluate(JS_CELLS); res["roof_shaded_0700"] = pg.locator(".metric.hero").first.inner_text().replace("\n", " ")
    pg.screenshot(path=f"{OUT}/a_winter_morning.png")
    t1 = pg.locator(".dhead h2").inner_text(); pg.get_by_role("tab", name="Overview", exact=True).click(); h1 = pg.locator(".metric.hero").first.inner_text().replace("\n", " ")
    pg.locator(".row").nth(40).click(); time.sleep(3); t2 = pg.locator(".dhead h2").inner_text(); h2 = pg.locator(".metric.hero").first.inner_text().replace("\n", " ")
    res["panel_updates_for_second_building"] = (t1, h1) != (t2, h2); res["building_1"] = (t1, h1); res["building_2"] = (t2, h2)
    pg.get_by_role("tab", name="Money", exact=True).click(); time.sleep(1); res["money_table"] = pg.locator("table.t").first.inner_text().replace("\n", " | ")[:260]
    pg.get_by_role("tab", name="Data", exact=True).click(); time.sleep(1); res["data_tab_has_missing_info"] = "Missing information" in pg.locator(".dbody").inner_text()
    # area selection (rectangle drag)
    pg.get_by_text("Select area").click(); box = pg.locator(".map").bounding_box()
    x0, y0 = box["x"] + 450, box["y"] + 150
    pg.mouse.move(x0, y0); pg.mouse.down(); pg.mouse.move(x0 + 250, y0 + 200, steps=6); pg.mouse.up(); time.sleep(2)
    res["aoi_card"] = pg.locator(".card.floating b").first.inner_text() if pg.locator(".card.floating b").count() else None
    res["aoi_stats"] = pg.locator(".card.floating .sub").first.inner_text() if pg.locator(".card.floating .sub").count() else None
    pg.screenshot(path=f"{OUT}/b_area_selection.png")
    b.close()
print(json.dumps(res, indent=1))
