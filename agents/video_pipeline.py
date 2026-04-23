"""
Pool construction video pipeline.

Single-pass Veo 3.1 with frames-to-video:
  first_frame = satellite (no pool)
  last_frame  = Nano Banana render (pool added)

No intermediate excavation keyframe — Veo interpolates directly.
No silent ffmpeg-zoompan fallback: if Veo fails, we raise. A failed video
is better than a fake one that looks like a success to the pipeline.
"""

import asyncio
import base64
import io
import time
from pathlib import Path

import requests
from PIL import Image


OPENROUTER_VIDEO_URL = "https://openrouter.ai/api/v1/videos"
VIDEO_MODEL = "google/veo-3.1"

VIDEO_PROMPT = (
    "Aerial top-down satellite view of a residential backyard. "
    "Locked camera throughout the entire clip — absolutely zero camera movement, "
    "zero zoom, zero pan, zero tilt, zero rotation. Framing is pixel-identical from "
    "first frame to last frame. "
    "The only change in the scene occurs inside the rectangular pool area in the "
    "backyard lawn. Over 8 seconds, the grass in that specific area smoothly transitions "
    "into a fully installed swimming pool: crystal-clear turquoise water with natural "
    "transparency, white concrete coping around the rim, and a small concrete deck "
    "surrounding the pool. In the final second, the water surface settles with subtle "
    "sun reflections and a single small white pool float resting on the water. "
    "Everything else stays pixel-perfect identical to the first frame: the house, "
    "roof, driveway, trees, hedges, fence, neighboring properties, surrounding lawn. "
    "Shadows do not move. Vegetation does not sway. Lighting is constant midday sun. "
    "Photorealistic aerial imagery matching Google Maps satellite view. No weather "
    "changes, no lens flares, no color grading shifts. "
    "Explicitly NO workers, NO people, NO machinery, NO excavators, NO construction "
    "vehicles, NO trucks, NO dust, NO debris, NO hoses, NO tools, NO dirt piles."
)


def _img_to_jpeg_b64(path: str, target_size: int = 1280) -> str:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if max(w, h) > target_size:
        ratio = target_size / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
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
        satellite_path: str,
        render_path: str,
        placement: dict,
        output_path: str,
        job_dir: str,
    ) -> str:
        """
        Generate an 8-second pool construction video using Veo 3.1 frames-to-video.
        Raises RuntimeError on any failure — no silent fallback.
        """
        first_b64 = _img_to_jpeg_b64(satellite_path)
        last_b64  = _img_to_jpeg_b64(render_path)

        payload = {
            "model": VIDEO_MODEL,
            "prompt": VIDEO_PROMPT,
            "image": f"data:image/jpeg;base64,{first_b64}",
            "last_image": f"data:image/jpeg;base64,{last_b64}",
        }

        print("  [Veo 3.1] submitting job...")
        r = requests.post(OPENROUTER_VIDEO_URL, headers=self.headers, json=payload, timeout=60)
        if r.status_code == 402:
            raise RuntimeError("OpenRouter 402: out of credits. Add funds at openrouter.ai/credits")
        if r.status_code != 200:
            raise RuntimeError(f"Veo submit failed {r.status_code}: {r.text[:500]}")
        data = r.json()
        job_id      = data.get("id")
        polling_url = data.get("polling_url")
        if not polling_url:
            raise RuntimeError(f"Veo response missing polling_url: {data}")
        print(f"  [Veo 3.1] job {job_id} submitted")

        deadline = time.time() + 480  # 8 minutes
        while time.time() < deadline:
            await asyncio.sleep(10)
            poll   = requests.get(polling_url, headers=self.headers, timeout=30)
            sd     = poll.json()
            status = sd.get("status")
            print(f"  [Veo 3.1] {status}")

            if status == "completed":
                urls = sd.get("unsigned_urls", [])
                if not urls:
                    raise RuntimeError(f"Veo completed but no video URL: {sd}")
                video_r = requests.get(urls[0], headers=self.headers, timeout=180)
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

        raise RuntimeError(f"Veo job timed out after 8 minutes (job_id={job_id})")
