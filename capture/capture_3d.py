"""
Captures an oblique aerial view of a property using Google Photorealistic 3D Tiles
rendered via CesiumJS in a headless browser (Playwright + SwiftShader WebGL).

Returns: path to captured PNG, or None if tiles didn't render (GPU unavailable).
"""

import asyncio
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import httpx


HTML_PATH = Path(__file__).parent / "cesium_capture.html"


def _start_local_server(directory: str, port: int = 8765) -> HTTPServer:
    """Serve HTML via localhost so tile.googleapis.com requests have a real origin."""
    class QuietHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)
        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", port), QuietHandler)  # allow_reuse_address=True via HTTPServer default
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


async def _get_elevation(lat: float, lng: float) -> float:
    """Get terrain elevation (metres) via Open-Elevation API (free, no key required)."""
    url = f"https://api.open-elevation.com/api/v1/lookup?locations={lat},{lng}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
            data = r.json()
        elev = data["results"][0]["elevation"]
        print(f"  [3D Tiles] terrain elevation={elev:.1f}m")
        return elev
    except Exception as e:
        print(f"  [3D Tiles] elevation lookup failed ({e}), using 100m fallback")
    return 100.0


async def capture_3d_view(
    lat: float,
    lng: float,
    api_key: str,
    output_path: str,
    heading: float = 180,   # 0=N, 90=E, 180=S, 270=W
    pitch: float = -45,     # degrees below horizon
    distance: float = 150,  # metres from target
    width: int = 1920,
    height: int = 1080,
    timeout_ms: int = 30000,
) -> str | None:
    from playwright.async_api import async_playwright
    from PIL import Image
    import numpy as np

    # Get actual terrain elevation so the camera isn't underground
    elevation = await _get_elevation(lat, lng)

    server = _start_local_server(str(HTML_PATH.parent))

    url = (
        f"http://127.0.0.1:8765/{HTML_PATH.name}"
        f"?lat={lat}&lng={lng}&heading={heading}"
        f"&pitch={pitch}&distance={distance}"
        f"&elev={elevation:.1f}&key={api_key}"
    )
    print(f"  [3D Tiles] loading URL (elev={elevation:.0f}m, dist={distance}m, heading={heading}°)")

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
                # NOTE: --disable-software-rasterizer intentionally absent —
                # SwiftShader IS the software rasterizer; that flag kills it.
            ],
        )
        ctx  = await browser.new_context(viewport={"width": width, "height": height})
        page = await ctx.new_page()

        page.on("console", lambda m: print(f"  [Cesium/{m.type}] {m.text[:240]}"))
        page.on("pageerror", lambda e: print(f"  [Cesium/pageerror] {e}"))

        await page.goto(url, wait_until="networkidle", timeout=20000)

        try:
            await page.wait_for_function("window.cesiumReady === true", timeout=timeout_ms)
        except Exception:
            print("  [3D Tiles] timeout waiting for cesiumReady — taking screenshot anyway")

        error = await page.evaluate("window.cesiumError")
        if error:
            print(f"  [3D Tiles] cesiumError: {error}")

        await asyncio.sleep(2)
        await page.screenshot(path=output_path, type="png", timeout=60000)
        await browser.close()

    server.shutdown()

    img = Image.open(output_path).convert("RGB")
    arr = np.array(img, dtype=float)
    std  = arr.std()
    mean = arr.mean()
    print(f"  [3D Tiles] brightness={mean:.1f}  std={std:.1f}")

    if std < 15:
        print("  [3D Tiles] FAIL: very uniform image — tiles did not render")
        return None

    print(f"  [3D Tiles] OK → {output_path}")
    return output_path
