import httpx
import base64
import json
from pathlib import Path
from PIL import Image
import io as _io


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
IMAGE_MODEL = "google/gemini-3.1-flash-image-preview"


class RendererAgent:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://tamgo.ai",
            "X-Title": "Pool AI System",
        }

    def _to_jpeg_b64(self, path: str, max_size: int = 1024) -> str:
        img = Image.open(path).convert("RGB")
        # Resize if too large
        w, h = img.size
        if max(w, h) > max_size:
            ratio = max_size / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return base64.b64encode(buf.getvalue()).decode()

    async def analyze_pool_placement(self, satellite_path: str, anthropic_key: str, media_type: str = "image/png") -> dict:
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
                    {"type": "text", "text": (
                        "Analyze this aerial satellite image of a residential property. "
                        "Identify the backyard and optimal pool placement. "
                        "Respond ONLY with valid JSON: "
                        "{\"has_pool\": bool, \"backyard_location\": \"description\", "
                        "\"pool_placement\": \"precise description of exact location\", "
                        "\"yard_size\": \"small/medium/large\", "
                        "\"house_description\": \"roof color, style, approximate size\", "
                        "\"existing_features\": \"list of things that must NOT be removed: trees, structures, fences, cars, etc.\", "
                        "\"analysis\": \"brief notes\"}"
                    )},
                ],
            }],
        )
        text = response.content[0].text
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            return json.loads(text[start:end])
        except Exception:
            return {"has_pool": False, "pool_placement": "center of backyard", "yard_size": "medium",
                    "house_description": "suburban home", "existing_features": "trees, fence", "analysis": text}

    async def pick_best_backyard_view(self, street_views: list, anthropic_key: str) -> dict:
        if not street_views:
            return {}
        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_key)
        content = []
        for sv in street_views:
            raw = Path(sv["path"]).read_bytes()
            b64 = base64.b64encode(raw).decode()
            mt = "image/png" if raw[:8] == b'\x89PNG\r\n\x1a\n' else "image/jpeg"
            content.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}})
            content.append({"type": "text", "text": f"Image heading {sv['heading']}° ({sv['direction']})"})
        content.append({"type": "text",
                        "text": "Which shows the backyard best? Reply with just the heading number."})
        response = client.messages.create(
            model="claude-opus-4-7", max_tokens=10,
            messages=[{"role": "user", "content": content}],
        )
        heading_str = response.content[0].text.strip()
        for sv in street_views:
            if str(sv["heading"]) in heading_str:
                return sv
        return street_views[0]

    async def render_pool_faithful(
        self,
        satellite_path: str,
        placement: dict,
        output_path: str,
        extra_refs: list = None,   # list of {"path": ..., "label": ...} — street views, multi-zoom
    ) -> str:
        """
        Faithfully render the EXACT property from satellite view with ONLY a pool added.
        Keeps every structure, tree, roof, car, fence IDENTICAL.
        Uses all available reference images for accuracy.
        """
        placement_desc = placement.get("pool_placement", "center of backyard")
        existing = placement.get("existing_features", "trees, fences, structures")
        house_desc = placement.get("house_description", "suburban home")
        yard_size = placement.get("yard_size", "medium")

        # Build message content — satellite first, then any extra refs
        content = []

        # Primary satellite image
        sat_b64 = self._to_jpeg_b64(satellite_path, max_size=1024)
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{sat_b64}"}})
        content.append({"type": "text", "text": "PRIMARY IMAGE — This is the exact satellite aerial view of the target property."})

        # Extra references (multi-zoom or street views)
        if extra_refs:
            for ref in extra_refs[:3]:
                ref_b64 = self._to_jpeg_b64(ref["path"], max_size=768)
                content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{ref_b64}"}})
                content.append({"type": "text", "text": f"REFERENCE — {ref.get('label', 'Additional view')}"})

        prompt = (
            f"TASK: Edit the PRIMARY IMAGE above to add a swimming pool.\n\n"
            f"STRICT RULES — follow all of these exactly:\n"
            f"1. DO NOT change the satellite perspective or viewing angle — keep the exact top-down aerial view.\n"
            f"2. DO NOT change, move, or remove ANY existing element: the house ({house_desc}), roof, walls, windows, "
            f"driveway, trees, hedges, fence, garden features, neighboring houses, streets, or any other structure.\n"
            f"3. ONLY modify the specific area for the pool: {placement_desc}\n"
            f"4. The pool must look like a real installed pool visible from above in satellite style: "
            f"crystal-clear turquoise/blue water, white plaster finish, concrete coping visible at the edges, "
            f"a small pool deck surround (same material as the rest of the yard). "
            f"Add ONE inflatable float or pool toy visible in the water to make it feel alive.\n"
            f"5. The pool size must be proportional to a {yard_size} yard — realistic, not oversized.\n"
            f"6. Keep the satellite image quality and lighting IDENTICAL to the original everywhere except the pool area.\n"
            f"7. Do NOT add solar panels, furniture on the roof, new landscaping, or any other new elements outside the pool area.\n\n"
            f"The result should look like a real Google Maps satellite photo where this house already has a pool.\n"
            f"The existing features to preserve: {existing}"
        )
        content.append({"type": "text", "text": prompt})

        payload = {
            "model": IMAGE_MODEL,
            "messages": [{"role": "user", "content": content}],
        }
        try:
            async with httpx.AsyncClient(timeout=150) as client:
                r = await client.post(OPENROUTER_URL, headers=self.headers, json=payload)
                if r.status_code == 402:
                    raise RuntimeError("OpenRouter 402: out of credits — add funds at openrouter.ai/credits")
                r.raise_for_status()
                data = r.json()

            img_data = self._extract_image(data)
            if img_data:
                raw = base64.b64decode(img_data)
                img = Image.open(_io.BytesIO(raw)).convert("RGB")
                img = img.resize((1024, 1024), Image.LANCZOS)
                img.save(output_path, "JPEG", quality=95)
                return output_path
        except Exception as e:
            if "402" in str(e) or "credits" in str(e).lower():
                print(f"  [Nano Banana] {e}")
                print("  → Falling back to PIL pool overlay (add OpenRouter credits for AI render)")
            else:
                print(f"  [Nano Banana] Error: {e} — using PIL fallback")

        self._add_pool_fallback(satellite_path, output_path)
        return output_path

    def _extract_image(self, response: dict) -> str | None:
        try:
            choices = response.get("choices", [])
            if not choices:
                return None
            msg = choices[0].get("message", {})
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

    def _add_pool_fallback(self, input_path: str, output_path: str):
        """PIL fallback: draw a realistic-looking pool on the satellite image."""
        from PIL import ImageDraw, ImageFilter, ImageEnhance
        img = Image.open(input_path).convert("RGB").resize((1024, 1024), Image.LANCZOS)
        w, h = img.size
        overlay = Image.new("RGBA", img.convert("RGBA").size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Pool rectangle — lower-center of image (backyard area)
        cx, cy = w // 2, int(h * 0.65)
        pw, ph = int(w * 0.17), int(h * 0.10)

        # Pool deck (concrete surround)
        deck_pad = 18
        draw.rounded_rectangle(
            [cx - pw - deck_pad, cy - ph - deck_pad, cx + pw + deck_pad, cy + ph + deck_pad],
            radius=12, fill=(210, 200, 185, 230)
        )
        # Pool water body
        draw.rounded_rectangle(
            [cx - pw, cy - ph, cx + pw, cy + ph],
            radius=8, fill=(20, 160, 220, 235)
        )
        # Water shimmer (lighter center stripe)
        draw.rounded_rectangle(
            [cx - pw + 16, cy - ph + 10, cx + pw - 16, cy + ph - 10],
            radius=6, fill=(60, 210, 255, 160)
        )
        # Pool edge coping (darker border)
        draw.rounded_rectangle(
            [cx - pw, cy - ph, cx + pw, cy + ph],
            radius=8, fill=None, outline=(160, 150, 130, 200), width=4
        )

        blurred = overlay.filter(ImageFilter.GaussianBlur(1))
        result = Image.alpha_composite(img.convert("RGBA"), blurred).convert("RGB")
        result.save(output_path, "JPEG", quality=95)
