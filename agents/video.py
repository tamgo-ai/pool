import time
import base64
import json
import requests
from pathlib import Path
from PIL import Image
import io


DEFAULT_VIDEO_MODEL = "google/veo-3.1"     # best — recognizes actual property from frames
FALLBACK_VIDEO_MODEL = "alibaba/wan-2.6"  # cheaper fallback if Veo out of credits
OPENROUTER_VIDEO_URL = "https://openrouter.ai/api/v1/videos"


def _img_to_b64(path: str, size=(1024, 1024)) -> str:
    img = Image.open(path).convert("RGB").resize(size, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode()


class VideoAgent:
    def __init__(self, openrouter_key: str):
        self.api_key = openrouter_key
        self.headers = {
            "Authorization": f"Bearer {openrouter_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://tamgo.ai",
            "X-Title": "Pool AI System",
        }

    def create_construction_video(
        self,
        before_path: str,   # original satellite — no pool
        after_path: str,    # render — pool added
        output_path: str,
        premium: bool = True,
    ) -> str:
        """
        frames-to-video: before (no pool) → after (pool installed).
        Veo 3.1 animates the ACTUAL property — no people, no machines.
        """
        try:
            return self._frames_to_video(before_path, after_path, output_path, DEFAULT_VIDEO_MODEL)
        except Exception as e:
            print(f"  [Veo 3.1 error: {e}]")
            if "402" in str(e) or "Payment" in str(e):
                print("  → Add OpenRouter credits at openrouter.ai. Falling back to Wan 2.6...")
                try:
                    return self._frames_to_video(before_path, after_path, output_path, FALLBACK_VIDEO_MODEL)
                except Exception as e2:
                    print(f"  [Wan 2.6 error: {e2}] Using ffmpeg...")
            return self._ffmpeg_video(after_path, output_path)

    def _frames_to_video(self, before_path: str, after_path: str, output_path: str, model: str) -> str:
        first_b64 = _img_to_b64(before_path)
        last_b64 = _img_to_b64(after_path)

        prompt = (
            "Aerial top-down view of a residential backyard. A swimming pool magically builds itself "
            "in the center of the lawn — no people, no machines, no workers. "
            "The grass parts on its own, smooth concrete coping materializes around the edges, "
            "the pool basin forms from below, then crystal-clear turquoise water slowly fills "
            "the pool until it sparkles in the California sun. "
            "The surrounding house, trees, fence, and landscaping remain perfectly still and unchanged. "
            "Only the pool area transforms. Satisfying, magical, self-building reveal. "
            "Cinematic, smooth, photorealistic aerial perspective. 10 seconds. No humans, no equipment."
        )

        payload = {
            "model": model,
            "prompt": prompt,
            "image": f"data:image/jpeg;base64,{first_b64}",
            "last_image": f"data:image/jpeg;base64,{last_b64}",
        }

        r = requests.post(OPENROUTER_VIDEO_URL, headers=self.headers, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        job_id = data.get("id")
        polling_url = data.get("polling_url")
        print(f"  [{model}] Job {job_id} submitted. Polling...")

        deadline = time.time() + 360
        while time.time() < deadline:
            poll = requests.get(polling_url, headers=self.headers, timeout=30)
            sd = poll.json()
            status = sd.get("status")
            print(f"  [{model}] Status: {status}")
            if status == "completed":
                urls = sd.get("unsigned_urls", [])
                if urls:
                    video_r = requests.get(urls[0], headers=self.headers, timeout=180)
                    if video_r.status_code == 200 and len(video_r.content) > 10000:
                        Path(output_path).write_bytes(video_r.content)
                        print(f"  [{model}] Video saved ({len(video_r.content):,} bytes)")
                        return output_path
                raise RuntimeError(f"Download failed or empty")
            elif status == "failed":
                raise RuntimeError(f"Video generation failed: {sd.get('error', 'unknown')}")
            time.sleep(8)

        raise RuntimeError(f"{model} timed out after 6 minutes")

    def _ffmpeg_video(self, render_path: str, output_path: str) -> str:
        import os
        img = Image.open(render_path).convert("RGB").resize((1280, 720), Image.LANCZOS)
        img.save("/tmp/pool_render_hd.jpg", quality=95)
        cmd = (
            'ffmpeg -y -loop 1 -i /tmp/pool_render_hd.jpg '
            '-vf "zoompan=z=\'if(lte(zoom,1.0),1.3,max(1.001,zoom-0.0015))\':'
            'd=150:x=\'iw/2-(iw/zoom/2)\':y=\'ih/2-(ih/zoom/2)\':s=1280x720,'
            'fade=t=in:st=0:d=30,fade=t=out:st=4.5:d=30" '
            '-t 5 -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p '
            f'"{output_path}" 2>/dev/null'
        )
        os.system(cmd)
        return output_path
