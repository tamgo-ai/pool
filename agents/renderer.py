"""
Renderer agent: analyzes placement (Claude Opus) and renders the pool (Nano Banana Pro).

Key fixes vs previous version:
1. Analysis prompt adds 'pool_viable' so we can skip unviable lots early.
2. ONLY the primary satellite goes to Nano Banana — no zoom variants, no
   street views. Multiple references made it mix perspectives.
3. Float is specified precisely to stop flamingo/unicorn hallucinations.
4. On Nano Banana failure we raise. No PIL cartoon pool fallback.
"""

import base64
import io as _io
import json
from pathlib import Path

import httpx
from PIL import Image


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
IMAGE_MODEL    = "google/gemini-3.1-flash-image-preview"

ANALYSIS_PROMPT = (
    "Analyze this aerial satellite image of a residential property. "
    "Identify the backyard and optimal pool placement. "
    "Respond ONLY with valid JSON:\n"
    "{\n"
    '  "has_pool": bool,\n'
    '  "pool_viable": bool,\n'
    '  "backyard_location": "description (e.g. south side of house)",\n'
    '  "pool_placement": "precise description of exact location in the yard",\n'
    '  "yard_size": "small|medium|large",\n'
    '  "house_description": "roof color, architectural style, approximate size",\n'
    '  "existing_features": "things that must NOT be removed: trees, structures, fences, cars, sheds",\n'
    '  "analysis": "brief notes on why this placement works"\n'
    "}\n\n"
    "Rules for pool_viable:\n"
    "- false if the yard cannot fit a 12x24ft pool with 3ft deck setback\n"
    "- false if the backyard is completely obstructed by trees/slopes/structures\n"
    "- false if there is no visible backyard (apartment, commercial property)\n"
    "- true otherwise, even if the yard is tight but workable"
)


def _to_jpeg_b64(path: str, max_size: int = 1024) -> str:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if max(w, h) > max_size:
        ratio = max_size / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    buf = _io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode()


class RendererAgent:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://tamgo.ai",
            "X-Title": "Pool AI System",
        }

    async def analyze_pool_placement(
        self,
        satellite_path: str,
        anthropic_key: str,
        media_type: str = "image/png",
    ) -> dict:
        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_key)
        b64 = base64.b64encode(Path(satellite_path).read_bytes()).decode()

        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": ANALYSIS_PROMPT},
                ],
            }],
        )
        text = response.content[0].text
        try:
            start = text.find("{")
            end   = text.rfind("}") + 1
            return json.loads(text[start:end])
        except Exception:
            return {
                "has_pool": False,
                "pool_viable": True,
                "backyard_location": "rear of property",
                "pool_placement": "center of backyard",
                "yard_size": "medium",
                "house_description": "suburban home",
                "existing_features": "trees, fence",
                "analysis": "fallback — Claude response could not be parsed",
            }

    async def render_pool_faithful(
        self,
        satellite_path: str,
        placement: dict,
        output_path: str,
    ) -> str:
        """
        Add a pool to the satellite image, preserving every other element.
        Raises RuntimeError on failure — no PIL cartoon fallback.
        """
        placement_desc = placement.get("pool_placement", "center of backyard")
        existing       = placement.get("existing_features", "trees, fences, structures")
        house_desc     = placement.get("house_description", "suburban home")
        yard_size      = placement.get("yard_size", "medium")

        sat_b64 = _to_jpeg_b64(satellite_path, max_size=1024)

        content = [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{sat_b64}"}},
            {"type": "text", "text": "PRIMARY IMAGE — This is the exact satellite aerial view of the target property."},
            {"type": "text", "text": (
                f"TASK: Edit the PRIMARY IMAGE above to add a swimming pool.\n\n"
                f"STRICT RULES — follow all of these exactly:\n"
                f"1. Keep the exact top-down aerial satellite perspective. Do NOT change the viewpoint, zoom, or angle.\n"
                f"2. DO NOT change, move, or remove ANY existing element: the house ({house_desc}), "
                f"roof, walls, windows, driveway, trees, hedges, fence, garden features, "
                f"neighboring houses, streets, or any other structure.\n"
                f"3. ONLY modify this specific area: {placement_desc}\n"
                f"4. The pool must look like a real installed pool visible from above in satellite style:\n"
                f"   - Rectangular shape, approximately 12x24 feet (proportional to a {yard_size} yard)\n"
                f"   - Crystal-clear turquoise/blue water with natural transparency\n"
                f"   - White plaster finish visible through the water at pool edges\n"
                f"   - Smooth white concrete coping around the entire rim\n"
                f"   - Small concrete pool deck surround (~3 feet wide) matching the existing yard aesthetic\n"
                f"   - ONE plain white circular pool float (simple round shape, solid white, "
                f"no flamingo/animal/character shapes, no bright colors)\n"
                f"5. Pool size must be proportional to a {yard_size} yard — realistic, not oversized.\n"
                f"6. Keep satellite image quality and lighting IDENTICAL to the original everywhere except the pool area.\n"
                f"7. Do NOT add solar panels, furniture, umbrellas, new landscaping, people, or vehicles.\n\n"
                f"The result should look like a real Google Maps satellite photo where this house already has a pool.\n"
                f"Existing features to preserve: {existing}"
            )},
        ]

        payload = {
            "model": IMAGE_MODEL,
            "messages": [{"role": "user", "content": content}],
        }

        async with httpx.AsyncClient(timeout=150) as client:
            r = await client.post(OPENROUTER_URL, headers=self.headers, json=payload)
            if r.status_code == 402:
                raise RuntimeError("OpenRouter 402: out of credits. Add funds at openrouter.ai/credits")
            r.raise_for_status()
            data = r.json()

        img_data = self._extract_image(data)
        if not img_data:
            raise RuntimeError(f"Nano Banana returned no image. Response: {str(data)[:500]}")

        raw = base64.b64decode(img_data)
        img = Image.open(_io.BytesIO(raw)).convert("RGB")
        img = img.resize((1024, 1024), Image.LANCZOS)
        img.save(output_path, "JPEG", quality=95)
        return output_path

    def _extract_image(self, response: dict) -> str | None:
        try:
            choices = response.get("choices", [])
            if not choices:
                return None
            msg    = choices[0].get("message", {})
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
