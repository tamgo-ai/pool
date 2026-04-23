"""
3-keyframe pool construction video pipeline.

Frames:
  frame_clean      = original satellite (no pool)
  frame_excavated  = Nano Banana edit   (hole dug, no water, no workers)
  frame_finished   = existing render    (pool complete, water filled)

Veo passes:
  Pass A (4s): frame_clean      → frame_excavated
  Pass B (4s): frame_excavated  → frame_finished

Result: 8-second concat via ffmpeg.
"""

import asyncio
import base64
import io
import os
import subprocess
import time
from pathlib import Path

import httpx
import requests
from PIL import Image


OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_VIDEO_URL = "https://openrouter.ai/api/v1/videos"
IMAGE_MODEL = "google/gemini-3.1-flash-image-preview"
VIDEO_MODEL = "google/veo-3.1"

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text()


def _img_to_b64(path: str, size: tuple = (1024, 1024)) -> str:
    img = Image.open(path).convert("RGB").resize(size, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode()


def _to_jpeg_b64_from_path(path: str, max_size: int = 1024) -> str:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if max(w, h) > max_size:
        ratio = max_size / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
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

    # ─── Step 1: Generate frame_excavated via Nano Banana ────────────────────

    async def _generate_excavated_frame(
        self,
        satellite_path: str,
        placement: dict,
        output_path: str,
        retries: int = 2,
    ) -> str:
        placement_desc = placement.get("pool_placement", "center of backyard")
        existing = placement.get("existing_features", "trees, fences, structures")
        yard_size = placement.get("yard_size", "medium")

        prompt_template = _load_prompt("frame_excavated.txt")
        prompt = prompt_template.replace("{placement}", placement_desc) \
                                .replace("{yard_size}", yard_size) \
                                .replace("{existing}", existing)

        sat_b64 = _to_jpeg_b64_from_path(satellite_path, max_size=1024)
        content = [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{sat_b64}"}},
            {"type": "text", "text": "PRIMARY IMAGE — Exact satellite aerial view of target property."},
            {"type": "text", "text": prompt},
        ]
        payload = {
            "model": IMAGE_MODEL,
            "messages": [{"role": "user", "content": content}],
        }

        last_err = None
        for attempt in range(retries + 1):
            try:
                async with httpx.AsyncClient(timeout=150) as client:
                    r = await client.post(OPENROUTER_CHAT_URL, headers=self.headers, json=payload)
                    if r.status_code == 402:
                        raise RuntimeError("OpenRouter 402: add credits at openrouter.ai/credits")
                    r.raise_for_status()
                    data = r.json()

                img_b64 = self._extract_image(data)
                if img_b64:
                    raw = base64.b64decode(img_b64)
                    img = Image.open(io.BytesIO(raw)).convert("RGB").resize((1024, 1024), Image.LANCZOS)
                    img.save(output_path, "JPEG", quality=95)
                    print(f"  [excavated frame] saved → {output_path}")
                    return output_path
                raise RuntimeError("No image in Nano Banana response")
            except Exception as e:
                last_err = e
                if "402" in str(e) or "credits" in str(e).lower():
                    raise
                if attempt < retries:
                    print(f"  [excavated frame] attempt {attempt+1} failed: {e} — retrying...")
                    await asyncio.sleep(5)

        print(f"  [excavated frame] all retries failed: {last_err} — using PIL fallback")
        self._excavated_fallback(satellite_path, output_path, placement)
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

    def _excavated_fallback(self, satellite_path: str, output_path: str, placement: dict):
        from PIL import ImageDraw, ImageFilter
        img = Image.open(satellite_path).convert("RGB").resize((1024, 1024), Image.LANCZOS)
        w, h = img.size
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        cx, cy = w // 2, int(h * 0.65)
        pw, ph = int(w * 0.17), int(h * 0.10)
        # Dirt/soil mound at edges
        draw.rounded_rectangle(
            [cx - pw - 20, cy - ph - 20, cx + pw + 20, cy + ph + 20],
            radius=6, fill=(139, 115, 85, 200)
        )
        # Excavated hole (darker)
        draw.rounded_rectangle(
            [cx - pw, cy - ph, cx + pw, cy + ph],
            radius=4, fill=(80, 55, 30, 240)
        )
        blurred = overlay.filter(ImageFilter.GaussianBlur(1))
        result = Image.alpha_composite(img.convert("RGBA"), blurred).convert("RGB")
        result.save(output_path, "JPEG", quality=95)

    # ─── Step 2: Veo pass (4 seconds, locked camera) ─────────────────────────

    def _submit_veo(self, first_b64: str, last_b64: str, prompt: str) -> tuple[str, str]:
        payload = {
            "model": VIDEO_MODEL,
            "prompt": prompt,
            "image": f"data:image/jpeg;base64,{first_b64}",
            "last_image": f"data:image/jpeg;base64,{last_b64}",
        }
        r = requests.post(OPENROUTER_VIDEO_URL, headers=self.headers, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        return data["id"], data["polling_url"]

    def _poll_veo(self, polling_url: str, label: str, timeout: int = 360) -> bytes:
        deadline = time.time() + timeout
        while time.time() < deadline:
            poll = requests.get(polling_url, headers=self.headers, timeout=30)
            sd = poll.json()
            status = sd.get("status")
            print(f"  [Veo {label}] {status}")
            if status == "completed":
                urls = sd.get("unsigned_urls", [])
                if not urls:
                    raise RuntimeError(f"Veo {label}: completed but no URLs")
                video_r = requests.get(urls[0], headers=self.headers, timeout=180)
                if video_r.status_code == 200 and len(video_r.content) > 10_000:
                    return video_r.content
                raise RuntimeError(f"Veo {label}: download failed or empty ({video_r.status_code})")
            elif status == "failed":
                raise RuntimeError(f"Veo {label} failed: {sd.get('error', 'unknown')}")
            time.sleep(8)
        raise RuntimeError(f"Veo {label} timed out after {timeout}s")

    def _run_veo_pass(self, first_path: str, last_path: str, prompt: str, output_path: str, label: str, retries: int = 1) -> str:
        first_b64 = _img_to_b64(first_path)
        last_b64 = _img_to_b64(last_path)
        last_err = None
        for attempt in range(retries + 1):
            try:
                job_id, polling_url = self._submit_veo(first_b64, last_b64, prompt)
                print(f"  [Veo {label}] job {job_id} submitted")
                video_bytes = self._poll_veo(polling_url, label)
                Path(output_path).write_bytes(video_bytes)
                print(f"  [Veo {label}] saved {len(video_bytes):,} bytes → {output_path}")
                return output_path
            except Exception as e:
                last_err = e
                if "402" in str(e) or "Payment" in str(e):
                    raise
                if attempt < retries:
                    print(f"  [Veo {label}] attempt {attempt+1} failed: {e} — retrying...")
                    time.sleep(10)
        raise RuntimeError(f"Veo {label} failed after {retries+1} attempts: {last_err}")

    # ─── Step 3: ffmpeg concat ────────────────────────────────────────────────

    def _ffmpeg_concat(self, clip_a: str, clip_b: str, output_path: str) -> str:
        # Try stream copy first (fast, no re-encode)
        list_file = output_path + ".txt"
        Path(list_file).write_text(f"file '{clip_a}'\nfile '{clip_b}'\n")
        cmd_copy = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_file, "-c", "copy", output_path
        ]
        ret = subprocess.run(cmd_copy, capture_output=True)
        Path(list_file).unlink(missing_ok=True)
        if ret.returncode == 0 and Path(output_path).stat().st_size > 10_000:
            print(f"  [ffmpeg] concat (copy) → {output_path}")
            return output_path

        # Fallback: re-encode with filter_complex
        cmd_filter = [
            "ffmpeg", "-y",
            "-i", clip_a, "-i", clip_b,
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[outv]",
            "-map", "[outv]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p",
            output_path
        ]
        ret2 = subprocess.run(cmd_filter, capture_output=True)
        if ret2.returncode == 0:
            print(f"  [ffmpeg] concat (re-encode) → {output_path}")
            return output_path

        raise RuntimeError(f"ffmpeg concat failed:\n{ret2.stderr.decode()[:500]}")

    # ─── Public entry point ───────────────────────────────────────────────────

    async def generate_pool_video(
        self,
        satellite_path: str,    # frame_clean  (original satellite)
        render_path: str,        # frame_finished (Nano Banana result)
        placement: dict,         # from Claude placement analysis
        output_path: str,        # final 8s MP4
        job_dir: str,            # temp files go here
    ) -> str:
        """
        Generate 8-second pool construction video:
          clean satellite → excavated → finished pool
        Falls back to single ffmpeg zoom on any Veo billing error.
        """
        excavated_path = f"{job_dir}/frame_excavated.jpg"
        clip_a_path = f"{job_dir}/veo_pass_a.mp4"
        clip_b_path = f"{job_dir}/veo_pass_b.mp4"

        try:
            # 1. Generate mid-excavation frame
            print("  [video pipeline] Step 1/3: generating excavation frame...")
            await self._generate_excavated_frame(satellite_path, placement, excavated_path)

            # 2. Veo pass A: clean → excavated
            print("  [video pipeline] Step 2/3: Veo pass A (excavation)...")
            prompt_a = _load_prompt("veo_pass_a.txt")
            self._run_veo_pass(satellite_path, excavated_path, prompt_a, clip_a_path, "pass-A")

            # 3. Veo pass B: excavated → finished
            print("  [video pipeline] Step 3/3: Veo pass B (water fill)...")
            prompt_b = _load_prompt("veo_pass_b.txt")
            self._run_veo_pass(excavated_path, render_path, prompt_b, clip_b_path, "pass-B")

            # 4. Concat A + B
            result = self._ffmpeg_concat(clip_a_path, clip_b_path, output_path)

            # 5. Cleanup temp clips
            for tmp in [clip_a_path, clip_b_path]:
                Path(tmp).unlink(missing_ok=True)

            return result

        except Exception as e:
            if "402" in str(e) or "credits" in str(e).lower() or "Payment" in str(e):
                print(f"  [video pipeline] billing error: {e}")
                print("  → Add OpenRouter credits. Falling back to ffmpeg zoom...")
            else:
                print(f"  [video pipeline] error: {e} — falling back to ffmpeg zoom")
            return self._ffmpeg_fallback(render_path, output_path)

    def _ffmpeg_fallback(self, render_path: str, output_path: str) -> str:
        img = Image.open(render_path).convert("RGB").resize((1280, 720), Image.LANCZOS)
        img.save("/tmp/pool_render_hd.jpg", quality=95)
        cmd = (
            'ffmpeg -y -loop 1 -i /tmp/pool_render_hd.jpg '
            '-vf "zoompan=z=\'if(lte(zoom,1.0),1.3,max(1.001,zoom-0.0015))\':'
            'd=200:x=\'iw/2-(iw/zoom/2)\':y=\'ih/2-(ih/zoom/2)\':s=1280x720,'
            'fade=t=in:st=0:d=30,fade=t=out:st=6:d=30" '
            '-t 8 -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p '
            f'"{output_path}" 2>/dev/null'
        )
        os.system(cmd)
        print(f"  [ffmpeg fallback] → {output_path}")
        return output_path
