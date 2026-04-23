"""
Google Photorealistic 3D Tiles screenshot via CesiumJS + Playwright.
Renders the actual property in 3D from a backyard-facing oblique angle.
"""

import asyncio
import math
from pathlib import Path


CESIUM_VERSION = "1.105"
CESIUM_JS  = f"https://ajax.googleapis.com/ajax/libs/cesiumjs/{CESIUM_VERSION}/Build/Cesium/Cesium.js"
CESIUM_CSS = f"https://ajax.googleapis.com/ajax/libs/cesiumjs/{CESIUM_VERSION}/Build/Cesium/Widgets/widgets.css"


def _backyard_camera(lat: float, lng: float, backyard_direction: str) -> dict:
    """
    Compute camera position offset to look at the backyard from outside.
    backyard_direction: 'N', 'S', 'E', 'W' — which side the backyard is on.
    Camera is placed on that side, looking inward at 35° pitch, 80m altitude.
    """
    # Degrees per meter at this latitude
    deg_per_m_lat = 1 / 111_320
    deg_per_m_lng = 1 / (111_320 * math.cos(math.radians(lat)))

    offset_m = 40  # meters from house to camera position

    offsets = {
        "N": ( offset_m, 0),
        "S": (-offset_m, 0),
        "E": (0,  offset_m),
        "W": (0, -offset_m),
    }
    heading_map = {"N": 180, "S": 0, "E": 270, "W": 90}

    dlat, dlng = offsets.get(backyard_direction, (-offset_m, 0))
    cam_lat = lat + dlat * deg_per_m_lat
    cam_lng = lng + dlng * deg_per_m_lng

    return {
        "lat": cam_lat,
        "lng": cam_lng,
        "alt": 80,
        "heading": heading_map.get(backyard_direction, 180),
        "pitch": -35,
    }


def _build_html(lat: float, lng: float, api_key: str, camera: dict, width=1280, height=720) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <script src="{CESIUM_JS}"></script>
  <link href="{CESIUM_CSS}" rel="stylesheet">
  <style>
    * {{ margin:0; padding:0; }}
    html, body, #c {{ width:{width}px; height:{height}px; overflow:hidden; background:#000; }}
    .cesium-widget-credits {{ display:none !important; }}
  </style>
</head>
<body>
<div id="c"></div>
<script>
Cesium.Ion.defaultAccessToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.stub';

const viewer = new Cesium.Viewer('c', {{
  imageryProvider: false, baseLayerPicker: false,
  animation: false, timeline: false, geocoder: false,
  homeButton: false, sceneModePicker: false,
  navigationHelpButton: false, infoBox: false,
  selectionIndicator: false, fullscreenButton: false,
  requestRenderMode: false,
}});

viewer.scene.globe.show = false;
viewer.scene.skyBox.show = false;
viewer.scene.skyAtmosphere.show = false;
viewer.scene.backgroundColor = Cesium.Color.BLACK;

async function init() {{
  let tileset;
  try {{
    tileset = await Cesium.Cesium3DTileset.fromUrl(
      "https://tile.googleapis.com/v1/3dtiles/root.json?key={api_key}",
      {{ maximumScreenSpaceError: 2 }}
    );
  }} catch(e) {{
    console.error("Tileset load error: " + e);
    setTimeout(function() {{ window._tilesLoaded = true; }}, 500);
    return;
  }}
  viewer.scene.primitives.add(tileset);

  viewer.camera.setView({{
    destination: Cesium.Cartesian3.fromDegrees({camera['lng']}, {camera['lat']}, {camera['alt']}),
    orientation: {{
      heading: Cesium.Math.toRadians({camera['heading']}),
      pitch:   Cesium.Math.toRadians({camera['pitch']}),
      roll: 0.0
    }}
  }});

  tileset.allTilesLoaded.addEventListener(function() {{
    window._tilesLoaded = true;
  }});

  // Fallback after 10s
  setTimeout(function() {{ window._tilesLoaded = true; }}, 10000);
}}
init();
</script>
</body>
</html>"""


async def capture_3d_view(
    lat: float,
    lng: float,
    api_key: str,
    output_path: str,
    backyard_direction: str = "S",
    width: int = 1280,
    height: int = 720,
    wait_tiles_ms: int = 10000,
) -> str:
    """
    Capture a photorealistic 3D screenshot of a property using Google 3D Tiles.
    backyard_direction: compass direction the backyard faces (S = camera looks north).
    """
    from playwright.async_api import async_playwright

    camera = _backyard_camera(lat, lng, backyard_direction)
    html = _build_html(lat, lng, api_key, camera, width, height)

    html_path = str(Path(output_path).resolve().parent / "_3dtiles_viewer.html")
    Path(html_path).write_text(html)

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=[
            "--no-sandbox",
            "--headless=new",
            "--ignore-gpu-blocklist",
            "--enable-gpu",
            "--enable-webgl",
            "--use-gl=angle",
            "--use-angle=swiftshader",
            "--disable-software-rasterizer",
        ])
        context = await browser.new_context(viewport={"width": width, "height": height})
        page = await context.new_page()

        page.on("console", lambda m: print(f"  [Cesium] {m.text[:150]}") if m.type == "log" else None)

        # set_content with networkidle ensures external CDN scripts (CesiumJS) fully load
        await page.set_content(html, wait_until="networkidle", timeout=20000)

        # Wait for tiles to load then settle
        try:
            await page.wait_for_function("window._tilesLoaded === true", timeout=wait_tiles_ms)
            print(f"  [3D Tiles] tiles loaded — waiting for render...")
        except Exception:
            print(f"  [3D Tiles] tile load timeout — taking screenshot anyway")

        await asyncio.sleep(2)

        await page.screenshot(path=output_path, type="jpeg", quality=95)
        await browser.close()

    Path(html_path).unlink(missing_ok=True)
    size = Path(output_path).stat().st_size
    print(f"  [3D Tiles] saved {size:,} bytes → {output_path}")
    return output_path


def infer_backyard_direction(placement: dict) -> str:
    """Guess backyard compass direction from Claude placement analysis."""
    text = (placement.get("backyard_location", "") + " " + placement.get("pool_placement", "")).lower()
    for direction, keywords in [
        ("N", ["north", "northern", "rear north"]),
        ("S", ["south", "southern", "rear south"]),
        ("E", ["east", "eastern"]),
        ("W", ["west", "western"]),
    ]:
        if any(k in text for k in keywords):
            return direction
    return "S"  # default: most US homes have backyard to the south or rear


if __name__ == "__main__":
    import sys, os
    from dotenv import load_dotenv
    load_dotenv()

    lat, lng = 34.10065, -117.59314
    key = os.getenv("GOOGLE_MAPS_API_KEY")
    out = sys.argv[1] if len(sys.argv) > 1 else "output/11c426ba/view_3d.jpg"

    print(f"Capturing 3D view for ({lat}, {lng})...")
    asyncio.run(capture_3d_view(lat, lng, key, out, backyard_direction="S"))
    print(f"Done: {out}")
    print(f"View: http://31.97.142.91:8000/{out}")
