"""
Pool construction video — Veo 3.1 via OpenRouter.

Input:  the pool-edited oblique render (Nano Banana output).
Output: cinematic 8-second drone push-in toward the pool.

Key gotcha from spec:
  - Payload uses `input_references`, NOT `image`/`last_image`
  - Download MUST use GET /api/v1/videos/{id}/content WITH auth header
    (unsigned_urls[0] returns 401 for Veo)
"""

import asyncio
import base64
import io
import time
from pathlib import Path

import requests
from PIL import Image


OPENROUTER_VIDEO_URL = "https://openrouter.ai/api/v1/videos"
VIDEO_MODEL          = "google/veo-3.1"

VIDEO_PROMPT = (
    "Cinematic real-estate drone shot of the EXACT property shown in the reference image. "
    "The house architecture, roof, walls, windows, trees, driveway, fences, neighbors, "
    "and pool shape/position MUST remain faithful to the input image — do not invent a "
    "different house, do not restyle, do not move the pool. "
    "Camera move: starts as a high-angle drone shot matching the reference image (~55° "
    "looking down). Smoothly pushes in and gently descends toward the backyard, ending "
    "closer to the pool with the back of the house as the backdrop behind the pool. "
    "Single continuous shot — no cuts, no orbit around the house, no whip pans. "
    "The pool stays in the backyard for the entire shot. "
    "Atmosphere: warm golden-hour lighting, sparkling blue pool water with gentle ripples "
    "and light caustics, subtle breeze in the trees. "
    "High-end real-estate listing style. Photorealistic."
)


def _to_b64(path: str) -> str:
    img = Image.open(path).convert("RGB")
    img = img.resize((1280, 720), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    return base64.b64encode(buf.getvalue()).decode()


class VideoPipeline:
    def __init__(self, openrouter_key: str):
        self.api_key = openrouter_key
        self.headers = {
            "Authorization": f"Bearer {openrouter_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://tamgo.ai",
            "X-Title": "Pool AI System",
        }

    async def generate_pool_video(
        self,
        satellite_path: str,   # unused in this impl — kept for interface compat
        render_path: str,      # the pool-edited oblique image
        placement: dict,
        output_path: str,
        job_dir: str,
    ) -> str:
        """
        Generate 8s cinematic video from the pool render.
        Raises RuntimeError on any failure — no silent fallback.
        """
        b64         = _to_b64(render_path)
        render_hint = placement.get("render_prompt", "")

        payload = {
            "model":  VIDEO_MODEL,
            "prompt": VIDEO_PROMPT + (" " + render_hint if render_hint else ""),
            "input_references": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            ],
            "aspect_ratio": "16:9",
            "duration":     8,
            "resolution":   "720p",
        }

        print("  [Veo 3.1] submitting job...")
        r = requests.post(OPENROUTER_VIDEO_URL, headers=self.headers, json=payload, timeout=60)
        if r.status_code == 402:
            raise RuntimeError("OpenRouter 402: out of credits — add funds at openrouter.ai/credits")
        if r.status_code != 200:
            raise RuntimeError(f"Veo submit failed {r.status_code}: {r.text[:500]}")

        data        = r.json()
        job_id      = data.get("id")
        polling_url = data.get("polling_url") or f"{OPENROUTER_VIDEO_URL}/{job_id}"
        if not job_id:
            raise RuntimeError(f"Veo response missing id: {data}")
        print(f"  [Veo 3.1] job {job_id} submitted — polling...")

        deadline = time.time() + 600  # 10 min
        while time.time() < deadline:
            await asyncio.sleep(10)
            poll   = requests.get(polling_url, headers=self.headers, timeout=30)
            sd     = poll.json()
            status = sd.get("status", "unknown")
            print(f"  [Veo 3.1] {status}")

            if status == "completed":
                # Spec: use authenticated /content endpoint, NOT unsigned_urls (401)
                content_url = f"{OPENROUTER_VIDEO_URL}/{job_id}/content"
                video_r     = requests.get(content_url, headers=self.headers, timeout=180)
                if video_r.status_code != 200 or len(video_r.content) < 10_000:
                    raise RuntimeError(
                        f"Video download failed: status={video_r.status_code}, "
                        f"size={len(video_r.content)}"
                    )
                Path(output_path).write_bytes(video_r.content)
                print(f"  [Veo 3.1] saved {len(video_r.content):,} bytes → {output_path}")
                return output_path

            if status == "failed":
                raise RuntimeError(f"Veo job failed: {sd.get('error', sd)}")

        raise RuntimeError(f"Veo 3.1 timed out after 10 minutes (job_id={job_id})")
