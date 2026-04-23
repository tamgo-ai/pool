"""
Pool construction video — Kling O1 via OpenRouter (~$0.90/run).

Input:  the pool-edited oblique render (Nano Banana output).
Output: 10-second locked aerial shot showing pool appearing in backyard.

first_frame = satellite (before), last_frame = pool render (after).
"""

import asyncio
import base64
import io
import time
from pathlib import Path

import requests
from PIL import Image


OPENROUTER_VIDEO_URL = "https://openrouter.ai/api/v1/videos"
VIDEO_MODEL          = "kwaivgi/kling-video-o1"

VIDEO_PROMPT = (
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
    "Photorealistic aerial photography, midday overhead lighting, soft natural shadows."
)

NEGATIVE_PROMPT = (
    "workers, people, humans, machinery, excavators, construction vehicles, dust, "
    "debris, tools, hoses, camera movement, zoom, pan, tilt, rotation, "
    "weather changes, rain, fog, lens flare, color shift, moving shadows"
)


def _to_b64(path: str) -> tuple[str, str]:
    img = Image.open(path).convert("RGB")
    img = img.resize((1280, 720), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"


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
        Generate 10s pool appearance video using Kling O1 (first + last frame).
        Raises RuntimeError on any failure — no silent fallback.
        """
        start_b64, start_mime = _to_b64(satellite_path)
        end_b64,   end_mime   = _to_b64(render_path)

        payload = {
            "model":           VIDEO_MODEL,
            "prompt":          VIDEO_PROMPT,
            "negative_prompt": NEGATIVE_PROMPT,
            "duration":        10,
            "aspect_ratio":    "16:9",
            "first_frame":     f"data:{start_mime};base64,{start_b64}",
            "last_frame":      f"data:{end_mime};base64,{end_b64}",
        }

        print("  [Kling O1] submitting job...")
        r = requests.post(OPENROUTER_VIDEO_URL, headers=self.headers, json=payload, timeout=60)
        if r.status_code == 402:
            raise RuntimeError("OpenRouter 402: out of credits — add funds at openrouter.ai/credits")
        if r.status_code not in (200, 202):
            raise RuntimeError(f"Kling submit failed {r.status_code}: {r.text[:500]}")

        data        = r.json()
        job_id      = data.get("id")
        polling_url = data.get("polling_url") or f"{OPENROUTER_VIDEO_URL}/{job_id}"
        if not job_id:
            raise RuntimeError(f"Kling response missing id: {data}")
        print(f"  [Kling O1] job {job_id} submitted — polling...")

        deadline = time.time() + 660  # 11 min
        while time.time() < deadline:
            await asyncio.sleep(10)
            poll   = requests.get(polling_url, headers=self.headers, timeout=30)
            sd     = poll.json()
            status = sd.get("status", "unknown")
            print(f"  [Kling O1] {status}")

            if status == "completed":
                urls      = sd.get("unsigned_urls") or []
                video_url = (urls[0] if urls else None) or sd.get("video_url")
                if not video_url:
                    raise RuntimeError(f"Kling completed but no video URL: {sd}")
                video_r = requests.get(video_url, headers=self.headers, timeout=180)
                if video_r.status_code != 200 or len(video_r.content) < 10_000:
                    raise RuntimeError(
                        f"Video download failed: status={video_r.status_code}, "
                        f"size={len(video_r.content)}"
                    )
                Path(output_path).write_bytes(video_r.content)
                print(f"  [Kling O1] saved {len(video_r.content):,} bytes → {output_path}")
                return output_path

            if status == "failed":
                raise RuntimeError(f"Kling failed: {sd.get('error', sd)}")

        raise RuntimeError(f"Kling O1 timed out after 11 minutes (job_id={job_id})")
