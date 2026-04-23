import asyncio
import uuid
import os
from pathlib import Path
from dotenv import load_dotenv

from agents.scanner import ScannerAgent
from agents.renderer import RendererAgent
from agents.video import VideoAgent
from agents.video_pipeline import VideoPipeline
from agents.finance import FinanceAgent
from agents.landing import LandingAgent
from agents.postcard import PostcardAgent
from agents.mailer import MailerAgent

load_dotenv()

GOOGLE_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
LOB_KEY = os.getenv("LOB_API_KEY")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
OUTPUT_BASE = os.path.join(os.path.dirname(__file__), "output")

FROM_ADDRESS = {
    "name": "Aqua Dream Pools",
    "address_line1": "1234 Pool Blvd",
    "city": "Los Angeles",
    "state": "CA",
    "zip": "90001",
}


class PoolOrchestrator:
    def __init__(self, progress_callback=None):
        self.scanner = ScannerAgent(GOOGLE_KEY)
        self.renderer = RendererAgent(OPENROUTER_KEY)
        self.video_agent = VideoAgent(OPENROUTER_KEY)
        self.video_pipeline = VideoPipeline(OPENROUTER_KEY)
        self.finance = FinanceAgent(ANTHROPIC_KEY)
        self.postcard = PostcardAgent()
        self.mailer = MailerAgent(LOB_KEY) if LOB_KEY and LOB_KEY != "YOUR_LOB_API_KEY_HERE" else None
        self.progress = progress_callback or (lambda step, msg: print(f"[{step}] {msg}"))

    async def run(self, address: str, send_postcard: bool = False, premium_video: bool = False) -> dict:
        job_id = str(uuid.uuid4())[:8]
        job_dir = f"{OUTPUT_BASE}/{job_id}"
        Path(job_dir).mkdir(parents=True, exist_ok=True)

        result = {"job_id": job_id, "address": address, "status": "running", "steps": {}}

        try:
            # 1. Geocode
            self.progress("geocode", f"Locating {address}...")
            geo = await self.scanner.geocode(address)
            result["geo"] = geo
            self.progress("geocode", f"Found: {geo['formatted']}")

            # 2. Satellite images (primary + multi-zoom) + Street Views in parallel
            self.progress("images", "Capturing satellite images...")
            satellite_path = f"{job_dir}/satellite.png"
            sat_task = self.scanner.get_satellite_image(geo["lat"], geo["lng"], satellite_path, zoom=20)
            zoom_task = self.scanner.get_multi_zoom_satellites(geo["lat"], geo["lng"], job_dir)
            sv_task = self.scanner.get_street_views(geo["lat"], geo["lng"], job_dir)
            satellite_path, zoom_refs, street_views = await asyncio.gather(sat_task, zoom_task, sv_task)

            # Build extra_refs list: extra zooms + best street view
            extra_refs = []
            for z in zoom_refs:
                if z["zoom"] != 20:
                    extra_refs.append({"path": z["path"], "label": f"Satellite zoom {z['zoom']} (closer/wider view)"})
            if street_views:
                for sv in street_views[:2]:
                    extra_refs.append({"path": sv["path"], "label": f"Street view {sv['direction']} ({sv['heading']}°)"})

            self.progress("images", f"Got satellite + {len(zoom_refs)} zoom levels + {len(street_views)} street views")
            result["steps"]["images"] = {
                "satellite": satellite_path, "zoom_refs": len(zoom_refs), "street_views": len(street_views)
            }

            # 3. Analyze placement with Claude
            self.progress("analysis", "Analyzing property with AI...")
            media_type = self.scanner.detect_media_type(satellite_path)
            placement = await self.renderer.analyze_pool_placement(satellite_path, ANTHROPIC_KEY, media_type)
            result["steps"]["analysis"] = placement
            self.progress("analysis", f"Pool placement: {placement.get('pool_placement', '')[:80]}...")

            if placement.get("has_pool"):
                self.progress("analysis", "Property already has a pool — skipping")
                result["status"] = "skipped_has_pool"
                return result

            # 4. Finance estimate (run in parallel with render)
            self.progress("finance", "Calculating investment estimate...")
            finance_task = asyncio.get_event_loop().run_in_executor(
                None,
                self.finance.estimate,
                geo["formatted"],
                placement.get("yard_size", "medium"),
                placement.get("analysis", ""),
            )

            # 5. Render pool faithfully onto satellite
            self.progress("render", "Rendering pool with Nano Banana (faithful to property)...")
            render_path = f"{job_dir}/render.jpg"
            render_task = self.renderer.render_pool_faithful(
                satellite_path, placement, render_path, extra_refs=extra_refs
            )

            render_path, finance_data = await asyncio.gather(render_task, finance_task)
            result["steps"]["render"] = render_path
            result["steps"]["finance"] = finance_data
            self.progress("render", "Render complete")
            self.progress("finance", f"Estimate: ${finance_data.get('price_low',0):,} – ${finance_data.get('price_high',0):,}")

            # 6. Landing page (needs finance + render)
            self.progress("landing", "Building personalized landing page...")
            landing_agent = LandingAgent(BASE_URL, OUTPUT_BASE)
            # Generate landing first with video=False, update after video
            landing_url = landing_agent.generate(job_id, geo["formatted"], finance_data, has_video=False)
            result["steps"]["landing_url"] = landing_url

            # 7. QR code
            self.progress("qr", "Generating QR code...")
            qr_path = f"{job_dir}/qr.png"
            self.postcard.generate_qr(landing_url, qr_path)

            # 8. Video: 3-keyframe pipeline (clean → excavated → finished)
            self.progress("video", "Creating 3-phase construction video (Veo 3.1 x2)...")
            video_path = f"{job_dir}/video.mp4"
            await self.video_pipeline.generate_pool_video(
                satellite_path=satellite_path,
                render_path=render_path,
                placement=placement,
                output_path=video_path,
                job_dir=job_dir,
            )
            has_video = Path(video_path).exists() and Path(video_path).stat().st_size > 10000
            result["steps"]["video"] = video_path if has_video else None
            self.progress("video", "Video ready" if has_video else "Video fallback used")

            # Update landing page with video
            if has_video:
                landing_url = landing_agent.generate(job_id, geo["formatted"], finance_data, has_video=True)

            # 9. Postcard design
            self.progress("postcard", "Designing postcard...")
            front_path = f"{job_dir}/postcard_front.jpg"
            back_path = f"{job_dir}/postcard_back.jpg"
            self.postcard.design_front(render_path, qr_path, landing_url, geo["formatted"], front_path)
            self.postcard.design_back(geo["formatted"], back_path)
            result["steps"]["postcard"] = {"front": front_path, "back": back_path}
            self.progress("postcard", "Postcard ready")

            # 10. Mail (optional)
            if send_postcard and self.mailer:
                self.progress("mail", "Sending postcard via Lob...")
                addr = self.mailer.parse_address(geo["formatted"])
                addr["name"] = "Homeowner"
                lob_result = await self.mailer.send_postcard(front_path, back_path, addr, FROM_ADDRESS)
                result["steps"]["lob"] = lob_result.get("id")
                self.progress("mail", f"Postcard sent! Lob ID: {lob_result.get('id')}")
            else:
                self.progress("mail", "Ready to mail (pass send_postcard=True to send)")

            result["status"] = "complete"
            result["landing_url"] = landing_url

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            self.progress("error", f"Error: {e}")
            raise

        return result


if __name__ == "__main__":
    import sys
    address = sys.argv[1] if len(sys.argv) > 1 else "12249 Appian Dr, Rancho Cucamonga CA 91739"
    result = asyncio.run(PoolOrchestrator().run(address))
    print("\n=== RESULT ===")
    import json
    print(json.dumps(result, indent=2, default=str))
