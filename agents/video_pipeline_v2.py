"""
Pool AI Video Pipeline v2
Uses Google 3D Tiles oblique view → Nano Banana 2-pass → Kling video.
Falls back to satellite top-down when GPU unavailable.

Cost per run:
  Google Maps APIs:   ~$0.02
  Claude Opus+Haiku:  ~$0.05
  Nano Banana x2:     ~$0.10
  Kling O1 (10s):     ~$0.90
  Total:              ~$1.07
"""

import asyncio
import base64
import io
import json
import os
import time
from pathlib import Path

import anthropic
import httpx
from PIL import Image

OPENROUTER_VIDEO_URL = "https://openrouter.ai/api/v1/videos"
IMAGE_MODEL          = "google/gemini-3.1-flash-image-preview"
VIDEO_MODEL          = "kwaivgi/kling-video-o1"   # supports first_frame + last_frame, 10s


def _img_to_jpeg_b64(path: str, max_size: int = 1024) -> str:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if max(w, h) > max_size:
        r = max_size / max(w, h)
        img = img.resize((int(w * r), int(h * r)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode()


def _img_to_b64(path: str) -> str:
    """Full-resolution base64 for video frames (Kling needs the actual image)."""
    ext = Path(path).suffix.lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    data = Path(path).read_bytes()
    # Resize to 1280x720 for 16:9 video compatibility
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img = img.resize((1280, 720), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"


def _load_prompt(name: str) -> str:
    return (Path(__file__).parent.parent / "prompts" / name).read_text()


class VideoPipelineV2:
    def __init__(self, openrouter_key: str, anthropic_key: str, google_key: str):
        self.openrouter_key  = openrouter_key
        self.anthropic_key   = anthropic_key
        self.google_key      = google_key
        self.or_headers = {
            "Authorization": f"Bearer {openrouter_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://tamgo.ai",
            "X-Title": "Pool AI System",
        }

    # ─── Step 1: Analyze placement (now also returns best_camera_heading) ────

    async def analyze_placement(self, satellite_path: str, media_type: str = "image/png") -> dict:
        client = anthropic.Anthropic(api_key=self.anthropic_key)
        b64 = base64.b64encode(Path(satellite_path).read_bytes()).decode()
        prompt_text = (
            "Analyze this aerial satellite image of a residential property. "
            "Respond ONLY with valid JSON:\n"
            "{\n"
            '  "has_pool": bool,\n'
            '  "pool_viable": bool,\n'
            '  "backyard_location": "description",\n'
            '  "pool_placement": "precise location description",\n'
            '  "yard_size": "small/medium/large",\n'
            '  "house_description": "roof color, style, approximate size",\n'
            '  "existing_features": "list of things that must NOT be removed",\n'
            '  "best_camera_heading": 0-359 integer (direction FROM WHICH the backyard is most visible, '
            'e.g. 180 means camera faces north looking at south-facing backyard),\n'
            '  "analysis": "brief notes"\n'
            "}"
        )
        for attempt in range(4):
            try:
                response = client.messages.create(
                    model="claude-opus-4-7",
                    max_tokens=1024,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                            {"type": "text", "text": prompt_text},
                        ],
                    }],
                )
                text = response.content[0].text
                start, end = text.find("{"), text.rfind("}") + 1
                return json.loads(text[start:end])
            except Exception as e:
                if "529" in str(e) or "overloaded" in str(e).lower():
                    wait = (attempt + 1) * 10
                    print(f"  [Claude] overloaded, retry {attempt+1}/4 in {wait}s...")
                    await asyncio.sleep(wait)
                    continue
                break
        return {
            "has_pool": False, "pool_viable": True,
            "pool_placement": "center of backyard", "yard_size": "medium",
            "house_description": "suburban home", "existing_features": "trees, fence",
            "best_camera_heading": 180, "analysis": "fallback — Claude unavailable",
        }

    # ─── Step 2: Nano Banana image edit ──────────────────────────────────────

    async def _nano_banana(self, input_path: str, prompt: str, output_path: str) -> str:
        b64 = _img_to_jpeg_b64(input_path, max_size=1024)
        content = [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": "PRIMARY IMAGE — edit as instructed below."},
            {"type": "text", "text": prompt},
        ]
        payload = {
            "model": IMAGE_MODEL,
            "messages": [{"role": "user", "content": content}],
        }
        for attempt in range(4):
            try:
                async with httpx.AsyncClient(timeout=150) as client:
                    r = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers=self.or_headers, json=payload,
                    )
                    if r.status_code == 402:
                        raise RuntimeError("OpenRouter 402: add credits")
                    r.raise_for_status()
                    data = r.json()

                img_b64 = self._extract_image(data)
                if img_b64:
                    raw = base64.b64decode(img_b64)
                    img = Image.open(io.BytesIO(raw)).convert("RGB").resize((1280, 720), Image.LANCZOS)
                    img.save(output_path, "JPEG", quality=95)
                    print(f"  [Nano Banana] → {output_path}")
                    return output_path
                raise RuntimeError("No image in response")
            except Exception as e:
                if "402" in str(e):
                    raise
                if attempt < 2:
                    await asyncio.sleep(5)
                    continue
                raise

    def _extract_image(self, response: dict) -> str | None:
        try:
            msg = response["choices"][0]["message"]
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

    # ─── Step 3: Clean 3D tile artifacts ─────────────────────────────────────

    async def clean_3d_render(self, input_path: str, output_path: str) -> str:
        prompt = _load_prompt("clean_3d_tiles.txt")
        return await self._nano_banana(input_path, prompt, output_path)

    # ─── Step 4: Add pool ─────────────────────────────────────────────────────

    async def render_pool_oblique(
        self,
        input_path: str,
        placement: dict,
        output_path: str,
    ) -> str:
        template = _load_prompt("frame_finished_oblique.txt")
        prompt = template \
            .replace("{pool_placement}",   placement.get("pool_placement", "center of backyard")) \
            .replace("{house_description}", placement.get("house_description", "suburban home")) \
            .replace("{yard_size}",        placement.get("yard_size", "medium")) \
            .replace("{existing_features}", placement.get("existing_features", "trees, fence"))
        return await self._nano_banana(input_path, prompt, output_path)

    # ─── Step 5: Kling video via OpenRouter ──────────────────────────────────

    async def generate_kling_video(
        self,
        start_path: str,
        end_path: str,
        output_path: str,
        duration: int = 10,
    ) -> str:
        start_b64, start_mime = _img_to_b64(start_path)
        end_b64,   end_mime   = _img_to_b64(end_path)

        prompt = (
            "Locked-off aerial drone shot of a residential backyard. Zero camera movement: "
            "no pan, no tilt, no zoom, no rotation throughout the entire clip. "
            "The only change in the scene is the gradual appearance of a swimming pool in the "
            "backyard lawn. The transformation is smooth and continuous: the grass in the pool "
            "area transitions, then smoothly fills with crystal-clear turquoise water. "
            "Concrete coping and deck appear around the pool edges as the water fills. "
            "The final second shows calm water with subtle sun reflections and a small white "
            "pool float resting on the surface. "
            "Everything else stays pixel-perfect still: the house, roof, driveway, trees, "
            "hedges, fence, neighboring properties, lighting, and shadows do not move. "
            "Photorealistic aerial photography, midday overhead lighting, soft natural shadows. "
            "NO workers, NO people, NO machinery, NO excavators, NO construction vehicles, "
            "NO dust, NO debris, NO hoses, NO tools."
        )
        negative_prompt = (
            "workers, people, humans, machinery, excavators, construction vehicles, dust, "
            "debris, tools, hoses, camera movement, zoom, pan, tilt, rotation, "
            "weather changes, rain, fog, lens flare, color shift, moving shadows"
        )

        payload = {
            "model": VIDEO_MODEL,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "duration": duration,
            "aspect_ratio": "16:9",
            "first_frame": f"data:{start_mime};base64,{start_b64}",
            "last_frame":  f"data:{end_mime};base64,{end_b64}",
        }

        # Submit
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(OPENROUTER_VIDEO_URL, headers=self.or_headers, json=payload)
            if r.status_code == 402:
                raise RuntimeError("OpenRouter 402: add credits")
            r.raise_for_status()
            job = r.json()

        job_id      = job["id"]
        polling_url = job.get("polling_url") or f"{OPENROUTER_VIDEO_URL}/{job_id}"
        print(f"  [Kling O1] submitted job {job_id}")

        # Poll
        deadline = time.time() + 660  # 11 min max
        async with httpx.AsyncClient(timeout=30) as client:
            while time.time() < deadline:
                await asyncio.sleep(10)
                r = await client.get(polling_url, headers=self.or_headers)
                data = r.json()
                status = data.get("status", "unknown")
                print(f"  [Kling O1] {status}")
                if status == "completed":
                    urls = data.get("unsigned_urls") or []
                    video_url = (urls[0] if urls else None) or data.get("video_url")
                    if not video_url:
                        raise RuntimeError(f"No video URL: {data}")
                    break
                if status == "failed":
                    raise RuntimeError(f"Kling failed: {data.get('error', data)}")
            else:
                raise RuntimeError("Kling O1 timed out")

        # Download
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.get(video_url, headers=self.or_headers)
            r.raise_for_status()

        Path(output_path).write_bytes(r.content)
        print(f"  [Kling O1] saved {len(r.content):,} bytes → {output_path}")
        return output_path

    # ─── Full pipeline ────────────────────────────────────────────────────────

    async def run(
        self,
        satellite_path: str,
        placement: dict,
        job_dir: str,
        base_image_path: str,   # the clean oblique view (3D tile or fallback)
    ) -> dict:
        """
        Runs steps 5-7 of the spec given a base oblique image.
        Returns paths to frame_clean, frame_finished, video.
        """
        frame_clean    = f"{job_dir}/frame_clean.jpg"
        frame_finished = f"{job_dir}/frame_finished.jpg"
        video_path     = f"{job_dir}/video.mp4"

        # Step 5: clean 3D tile artifacts (or just enhance satellite fallback)
        print("  [v2] Step 5: cleaning base image with Nano Banana...")
        await self.clean_3d_render(base_image_path, frame_clean)

        # Step 6: add pool
        print("  [v2] Step 6: rendering pool on clean frame...")
        await self.render_pool_oblique(frame_clean, placement, frame_finished)

        # Step 7: Kling video
        print("  [v2] Step 7: generating Kling O1 video (10s)...")
        await self.generate_kling_video(frame_clean, frame_finished, video_path, duration=10)

        return {
            "frame_clean":    frame_clean,
            "frame_finished": frame_finished,
            "video":          video_path,
        }
