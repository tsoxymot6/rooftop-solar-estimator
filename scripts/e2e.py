"""Headless-browser acceptance test: open app -> pilot loads -> click ranked building -> detail panel -> change time -> shadows update."""
import json, sys, time
from playwright.sync_api import sync_playwright
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp"
logs = []
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    pg = b.new_page(viewport={"width": 1440, "height": 860})
    pg.on("console", lambda m: logs.append((m.type, m.text[:200])) if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: logs.append(("pageerror", str(e)[:300])))
    shadow_calls = []
    pg.on("request", lambda r: shadow_calls.append(r.url) if "/shadows?" in r.url else None)
    pg.goto("http://localhost:8000", wait_until="networkidle", timeout=60000)
    pg.wait_for_selector(".row", timeout=30000); time.sleep(4)
    pg.screenshot(path=f"{OUT}/1_map.png")
    rows = pg.locator(".row").count(); print("rows rendered", rows)
    pg.locator(".row").nth(2).click(); pg.wait_for_selector(".right.open .metric.hero", timeout=20000); time.sleep(3)
    print("detail title:", pg.locator(".dhead h2").inner_text()); print("hero:", pg.locator(".metric.hero").first.inner_text().replace("\n", " "))
    pg.screenshot(path=f"{OUT}/2_detail.png")
    n0 = len(shadow_calls)
    pg.locator("input[type=range]").first.fill("480"); time.sleep(3); n1 = len(shadow_calls)
    print("shadow requests after time change:", n1 - n0, "| sun text:", pg.locator(".sunread").last.inner_text())
    pg.get_by_role("tab", name="Shading", exact=True).click(); time.sleep(2.5); pg.screenshot(path=f"{OUT}/3_shading.png")
    print("roof shaded text:", pg.locator(".metric.hero").first.inner_text().replace("\n", " "))
    pg.get_by_role("tab", name="Money", exact=True).click(); time.sleep(1); pg.screenshot(path=f"{OUT}/4_money.png")
    pg.get_by_role("tab", name="Energy", exact=True).click(); time.sleep(1.5); pg.screenshot(path=f"{OUT}/5_energy.png")
    pg.locator(".row").nth(9).click(); time.sleep(2.5)
    print("second building title:", pg.locator(".dhead h2").inner_text())
    pg.get_by_text("Method & validation").click(); time.sleep(1.5); pg.get_by_role("tab", name="Validation", exact=True).click(); time.sleep(2); pg.screenshot(path=f"{OUT}/6_validation.png")
    b.close()
print("console problems:", json.dumps(logs[:15], indent=0))
