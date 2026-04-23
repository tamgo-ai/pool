"""
Captures oblique aerial views via Google Photorealistic 3D Tiles + CesiumJS + SwiftShader.

capture_all_headings() renders 4 cardinal views (0, 90, 180, 270°) so the pipeline
can pick the one that shows the backyard in the foreground.
"""

import asyncio
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import httpx


HTML_PATH = Path(__file__).parent / "cesium_capture.html"
_SERVER_STARTED = False
_SERVER_PORT    = 8765


def _ensure_server():
    global _SERVER_STARTED
    if _SERVER_STARTED:
        return

    class QuietHandler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(HTML_PATH.parent), **kw)
        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", _SERVER_PORT), QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _SERVER_STARTED = True


async def _get_elevation(lat: float, lng: float) -> float:
    url = f"https://api.open-elevation.com/api/v1/lookup?locations={lat},{lng}"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url)
            return r.json()["results"][0]["elevation"]
    except Exception as e:
        print(f"  [3D] elevation lookup failed ({e}), using 100m fallback")
        return 100.0


async def _capture_one(
    lat: float, lng: float, elev: float,
    api_key: str, output_path: str,
    heading: float, pitch: float = -50, range_m: float = 130,
    width: int = 1920, height: int = 1080,
    timeout_ms: int = 30000,
) -> str | None:
    from playwright.async_api import async_playwright
    from PIL import Image
    import numpy as np

    _ensure_server()
    url = (
        f"http://127.0.0.1:{_SERVER_PORT}/{HTML_PATH.name}"
        f"?lat={lat}&lng={lng}&heading={heading}&pitch={pitch}"
        f"&range={range_m}&elev={elev:.1f}&key={api_key}"
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--use-gl=angle",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
                "--disable-gpu-sandbox",
                "--ignore-gpu-blocklist",
                "--enable-webgl",
            ],
        )
        ctx  = await browser.new_context(viewport={"width": width, "height": height})
        page = await ctx.new_page()
        page.on("console", lambda m: print(f"  [Cesium/{m.type}] {m.text[:200]}") if m.type != "log" or "renderer" in m.text or "ready" in m.text or "error" in m.text.lower() else None)
        page.on("pageerror", lambda e: print(f"  [Cesium/pageerror] {e}"))

        await page.goto(url, wait_until="networkidle", timeout=20000)
        try:
            await page.wait_for_function("window.__ready === true", timeout=timeout_ms)
        except Exception:
            print(f"  [3D h={heading}] timeout waiting for __ready")

        err = await page.evaluate("window.__error")
        if err:
            print(f"  [3D h={heading}] error: {err}")
            await browser.close()
            return None

        await page.screenshot(path=output_path, type="png", timeout=60000)
        await browser.close()

    img = Image.open(output_path).convert("RGB")
    arr = __import__("numpy").array(img, dtype=float)
    std, mean = arr.std(), arr.mean()
    print(f"  [3D h={heading:3.0f}°] brightness={mean:.1f} std={std:.1f}")

    if std < 15:
        print(f"  [3D h={heading:3.0f}°] FAIL — uniform image, tiles did not render")
        return None

    return output_path


async def capture_all_headings(
    lat: float,
    lng: float,
    api_key: str,
    job_dir: str,
    pitch: float = -50,
    range_m: float = 130,
    width: int = 1920,
    height: int = 1080,
    timeout_ms: int = 30000,
) -> dict[int, str | None]:
    """
    Render 4 cardinal views (0°, 90°, 180°, 270°).
    Returns {heading: path_or_None}.
    The caller picks the best view using a vision LLM.
    """
    elev = await _get_elevation(lat, lng)
    print(f"  [3D] terrain elevation={elev:.1f}m — capturing 4 headings")

    results = {}
    for heading in [0, 90, 180, 270]:
        out = f"{job_dir}/view_3d_{heading}.png"
        path = await _capture_one(
            lat, lng, elev, api_key, out,
            heading=heading, pitch=pitch, range_m=range_m,
            width=width, height=height, timeout_ms=timeout_ms,
        )
        results[heading] = path

    ok = sum(1 for v in results.values() if v)
    print(f"  [3D] {ok}/4 headings rendered successfully")
    return results
