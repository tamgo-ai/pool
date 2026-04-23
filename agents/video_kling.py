"""
Kling 1.6 Pro image-to-video via fal.ai
Pro supports start + end frame (like Veo) — ensures Kling morphs
from the actual satellite photo to the actual pool render.

Cost: ~$0.14/sec → 5s ≈ $0.70  (still 6x cheaper than Veo 3.1)
"""

import os
import time
from pathlib import Path

import fal_client
import httpx


KLING_PRO_URL = "https://queue.fal.run/fal-ai/kling-video/v1.6/pro/image-to-video"


class KlingAgent:
    def __init__(self, fal_key: str):
        self.fal_key = fal_key
        os.environ["FAL_KEY"] = fal_key
        self.headers = {
            "Authorization": f"Key {fal_key}",
            "Content-Type": "application/json",
        }

    def _upload(self, path: str) -> str:
        url = fal_client.upload_file(path)
        print(f"  [Kling] uploaded {Path(path).name} → {url}")
        return url

    def _submit(self, start_url: str, end_url: str, prompt: str, duration: str = "5") -> tuple[str, str]:
        payload = {
            "image_url": start_url,
            "end_image_url": end_url,
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": "16:9",
            "negative_prompt": (
                "people, workers, construction workers, machines, cranes, excavators, "
                "vehicles, debris, distorted perspective, fisheye, blurry, watermark, text"
            ),
        }
        with httpx.Client(timeout=60) as client:
            r = client.post(KLING_PRO_URL, headers=self.headers, json=payload)
            r.raise_for_status()
            data = r.json()

        request_id = data["request_id"]
        print(f"  [Kling Pro] queued → {request_id}")
        return data["status_url"], data["response_url"]

    def _poll(self, status_url: str, response_url: str, timeout: int = 360) -> str:
        deadline = time.time() + timeout
        with httpx.Client(timeout=30) as client:
            while time.time() < deadline:
                sd = client.get(status_url, headers=self.headers).json()
                status = sd.get("status", "UNKNOWN")
                pos = sd.get("queue_position")
                print(f"  [Kling Pro] {status}" + (f" (#{pos})" if pos else ""))

                if status == "COMPLETED":
                    data = client.get(response_url, headers=self.headers).json()
                    video_url = data.get("video", {}).get("url")
                    if not video_url:
                        raise RuntimeError(f"No video URL in response: {data}")
                    info = data.get("video", {})
                    print(f"  [Kling Pro] {info.get('duration',0):.1f}s — {info.get('file_size',0)/1024/1024:.1f} MB")
                    return video_url

                elif status in ("FAILED", "CANCELLED"):
                    raise RuntimeError(f"Kling Pro {status}: {sd.get('error', sd)}")

                time.sleep(8)

        raise RuntimeError(f"Kling Pro timed out after {timeout}s")

    def create_pool_video(
        self,
        satellite_path: str,
        render_path: str,
        output_path: str,
        placement_desc: str = "center of backyard",
        **_,
    ) -> str:
        """
        Kling Pro: satellite (before) → render (after pool).
        Morphs between the two real frames — no hallucinated houses.
        """
        print(f"  [Kling Pro] uploading frames...")
        start_url = self._upload(satellite_path)
        end_url   = self._upload(render_path)

        prompt = (
            "Aerial satellite top-down view. Camera is locked — zero movement, zero drift. "
            "The backyard transforms: the lawn in the " + placement_desc + " quietly parts on its own, "
            "smooth white concrete coping materializes around the pool edges, "
            "the pool basin forms from below the earth, "
            "then crystal-clear turquoise water slowly fills from the bottom up until it sparkles. "
            "The house, roof color, trees, driveway, fence, and every surrounding detail remain "
            "perfectly identical and still throughout the entire transformation. "
            "No people, no machinery, no workers — the pool self-constructs like magic. "
            "Photorealistic, high-fidelity satellite imagery. Smooth 5-second cinematic reveal."
        )

        status_url, response_url = self._submit(start_url, end_url, prompt, duration="5")
        video_url = self._poll(status_url, response_url)

        with httpx.Client(timeout=180) as client:
            r = client.get(video_url)
            r.raise_for_status()

        Path(output_path).write_bytes(r.content)
        print(f"  [Kling Pro] saved {len(r.content):,} bytes → {output_path}")
        return output_path
