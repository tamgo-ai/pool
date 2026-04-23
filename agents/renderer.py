"""
Renderer agent: two-pass Claude vision + Nano Banana Pro image edit.

Pass 1 — analyze_placement():
  Satellite top-down → Claude Opus → placement JSON (backyard description,
  pool position, obstructions, best cardinal heading estimate).

Pass 2 — select_best_heading():
  4 oblique 3D renders → Claude Opus → picks the render where the backyard
  is in the foreground (camera sitting in the backyard, house in background).

Edit — render_pool():
  Chosen oblique render → Nano Banana Pro → pool added to foreground grass.
"""

import base64
import io as _io
import json
from pathlib import Path

import httpx
from PIL import Image


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
IMAGE_MODEL    = "google/gemini-3.1-flash-image-preview"

# ─── Placement analysis prompt (spec verbatim) ───────────────────────────────

ANALYSIS_PROMPT = """\
You are a landscape architect. This is a top-down satellite image of a residential property. North is up.

CRITICAL: The FRONT of the house is the side that faces the road/street and contains the driveway. \
The BACKYARD is the OPPOSITE side — typically enclosed, often with grass, away from the street. \
Never confuse them.

1. Identify which compass side of the house is the FRONT (street/driveway side).
2. Identify the BACKYARD (opposite side from the front).
3. Identify obstructions in the backyard (trees, sheds, AC units, slopes, patios, existing structures).
4. Recommend the ideal location, shape, and approximate size for an inground swimming pool — STRICTLY IN THE BACKYARD.
5. Describe the pool position relative to the house using clear directional language.
6. Determine the compass direction FROM the center of the house TOWARD the backyard (0–360°, 0=N, 90=E, 180=S, 270=W).

Respond ONLY in JSON:
{
  "has_pool": bool,
  "pool_viable": bool,
  "front_side": "...",
  "backyard": "...",
  "obstructions": "...",
  "pool_recommendation": "...",
  "render_prompt": "...",
  "backyard_camera_heading": <0-359 integer>,
  "yard_size": "small|medium|large",
  "house_description": "..."
}

pool_viable = false if:
- yard cannot fit a 12x24ft pool with 3ft deck setback
- backyard is completely obstructed
- no visible backyard (apartment, commercial)
"""

# ─── Heading selector prompt (spec verbatim) ─────────────────────────────────

SELECTOR_PROMPT_TEMPLATE = """\
I have 4 oblique 3D aerial views of the same target house (the one closest to the center of each frame), \
captured at compass headings 0° (camera north of target, looking south), \
90° (camera east, looking west), 180° (camera south, looking north), and 270° (camera west, looking east).

Backyard description (from satellite): {backyard}.
Front (street) description: {front_side}.

Pick which of the 4 views best shows the BACK of the target house — the view where the backyard/back \
wall of the house is in the FOREGROUND (bottom portion of the image), and the front door/driveway/street \
are hidden behind or beside the house.

The images are attached in order: heading 0°, 90°, 180°, 270°.

Respond ONLY in JSON: {{ "chosen_heading": <0|90|180|270>, "reason": "..." }}
"""

# ─── Nano Banana edit prompt ─────────────────────────────────────────────────
# No foreground/background language — it's ambiguous with oblique views.
# Instead: explicit backyard description + hard rules about what NOT to touch.

EDIT_PROMPT_TEMPLATE = """\
Add a photorealistic inground swimming pool to the BACKYARD of the target house in this aerial image.

BACKYARD LOCATION: {backyard}
POOL DETAILS: {render_prompt}

STRICT RULES — follow every one:
1. The pool goes ONLY in the open grass/lawn area of the BACKYARD described above.
2. DO NOT place the pool near the driveway, street, front yard, or between the house and any road.
3. DO NOT modify, move, or remove the house — roof, walls, windows, and footprint must stay IDENTICAL.
4. DO NOT touch any neighbor's lot.
5. The pool must look like a real installed pool viewed from above: crystal-clear turquoise water, \
white concrete coping around the rim, small concrete deck surround (~3 ft wide), proportional to the yard size.
6. Keep everything else pixel-identical: trees, fences, driveway, neighbors, camera angle, lighting, shadows.
7. Do NOT add people, furniture, umbrellas, or vehicles.

The result must look like a real aerial photo of the same property — just with a pool already installed in the backyard.
"""


def _to_b64(path: str, max_size: int = 1024) -> str:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if max(w, h) > max_size:
        r = max_size / max(w, h)
        img = img.resize((int(w * r), int(h * r)), Image.LANCZOS)
    buf = _io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode()


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        pass
    m = __import__("re").search(r'\{[\s\S]*\}', text)
    if m:
        return json.loads(m.group())
    raise ValueError(f"No JSON found in: {text[:300]}")


class RendererAgent:
    def __init__(self, openrouter_key: str):
        self.or_key = openrouter_key
        self.or_headers = {
            "Authorization": f"Bearer {openrouter_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://tamgo.ai",
            "X-Title": "Pool AI System",
        }

    async def analyze_placement(
        self,
        satellite_path: str,
        anthropic_key: str,
    ) -> dict:
        """Pass 1: satellite → Claude Opus → placement JSON."""
        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_key)
        b64    = base64.b64encode(Path(satellite_path).read_bytes()).decode()
        media  = "image/png" if satellite_path.endswith(".png") else "image/jpeg"

        for attempt in range(3):
            try:
                resp = client.messages.create(
                    model="claude-opus-4-7",
                    max_tokens=1024,
                    messages=[{"role": "user", "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}},
                        {"type": "text",  "text": ANALYSIS_PROMPT},
                    ]}],
                )
                return _extract_json(resp.content[0].text)
            except Exception as e:
                if "529" in str(e) or "overloaded" in str(e).lower():
                    await asyncio.sleep((attempt + 1) * 10)
                    continue
                raise

        return {  # safe fallback
            "has_pool": False, "pool_viable": True,
            "front_side": "unknown", "backyard": "rear of property",
            "obstructions": "none visible", "pool_recommendation": "center of backyard",
            "render_prompt": "Add a rectangular pool in the center of the backyard grass.",
            "backyard_camera_heading": 180, "yard_size": "medium",
            "house_description": "suburban home",
        }

    def select_best_heading(
        self,
        renders: dict,
        analysis: dict,
        anthropic_key: str = None,
    ) -> int:
        """
        Pick the cardinal heading whose camera sits IN the backyard.

        The `backyard_camera_heading` from analysis is the compass direction FROM
        the house center TOWARD the backyard. That is exactly where we want the
        camera: heading=180 means camera is south of house, looking north, with
        the south backyard between camera and house (backyard in foreground).

        Claude vision tends to confuse this geometry, so we snap mathematically.
        """
        estimated = analysis.get("backyard_camera_heading", 180)
        cardinals  = [0, 90, 180, 270]
        available  = [h for h in cardinals if renders.get(h)]

        def angular_dist(a, b):
            return min(abs(a - b), 360 - abs(a - b))

        candidates = available if available else cardinals
        chosen     = min(candidates, key=lambda c: angular_dist(c, estimated))
        print(f"  [renderer] heading: {chosen}° (backyard at {estimated}°, snapped to nearest available cardinal)")
        return chosen

    async def render_pool(
        self,
        oblique_path: str,
        analysis: dict,
        output_path: str,
    ) -> str:
        """Nano Banana Pro: add pool to foreground grass of the chosen oblique render."""
        render_prompt = analysis.get("render_prompt", "Add a rectangular inground pool in the center of the backyard.")
        backyard      = analysis.get("backyard", "rear of property, the grassy area opposite the driveway")
        prompt        = EDIT_PROMPT_TEMPLATE.format(render_prompt=render_prompt, backyard=backyard)
        b64    = _to_b64(oblique_path, max_size=1024)

        payload = {
            "model": IMAGE_MODEL,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": "PRIMARY IMAGE — oblique 3D aerial view of the target property."},
                {"type": "text", "text": prompt},
            ]}],
        }

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=150) as client:
                    r = await client.post(OPENROUTER_URL, headers=self.or_headers, json=payload)
                    if r.status_code == 402:
                        raise RuntimeError("OpenRouter 402: out of credits")
                    r.raise_for_status()
                    data = r.json()

                img_b64 = self._extract_image(data)
                if not img_b64:
                    raise RuntimeError(f"No image in response: {str(data)[:300]}")

                raw = base64.b64decode(img_b64)
                img = Image.open(_io.BytesIO(raw)).convert("RGB")
                img.save(output_path, "JPEG", quality=95)
                print(f"  [Nano Banana] render saved → {output_path}")
                return output_path

            except Exception as e:
                if "402" in str(e):
                    raise
                if attempt < 2:
                    await asyncio.sleep(5)
                    continue
                raise

    def _extract_image(self, response: dict) -> str | None:
        try:
            msg    = response["choices"][0]["message"]
            images = msg.get("images") or []
            if images:
                url = images[0].get("image_url", {}).get("url", "")
                if "base64," in url:
                    return url.split("base64,")[1]
            content = msg.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "image_url":
                        url = block["image_url"]["url"]
                        if "base64," in url:
                            return url.split("base64,")[1]
        except Exception:
            pass
        return None


import asyncio  # noqa: E402 — needed for analyze_placement retry sleep
