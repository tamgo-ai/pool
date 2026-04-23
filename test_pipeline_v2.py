"""
Test Pool AI Pipeline v2.
Usage: python3 test_pipeline_v2.py [address] [job_id]

Runs: 3D capture → clean → pool render → Kling video
"""
import asyncio, os, sys, time, json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

GOOGLE_KEY      = os.getenv("GOOGLE_MAPS_API_KEY")
OPENROUTER_KEY  = os.getenv("OPENROUTER_API_KEY")
ANTHROPIC_KEY   = os.getenv("ANTHROPIC_API_KEY")

address = sys.argv[1] if len(sys.argv) > 1 else "12249 Appian Dr, Rancho Cucamonga CA 91739"
job_id  = sys.argv[2] if len(sys.argv) > 2 else "11c426ba"
job_dir = f"output/{job_id}"
Path(job_dir).mkdir(parents=True, exist_ok=True)

satellite_path = f"{job_dir}/satellite.png"
if not Path(satellite_path).exists():
    print(f"ERROR: {satellite_path} not found — run a full job first or pass a valid job_id")
    sys.exit(1)

from agents.video_pipeline_v2 import VideoPipelineV2
from capture.capture_3d import capture_3d_view

async def main():
    t0 = time.time()
    pipeline = VideoPipelineV2(OPENROUTER_KEY, ANTHROPIC_KEY, GOOGLE_KEY)

    # 1. Analyze placement
    print("\n[1/4] Analyzing placement with Claude Opus...")
    from agents.scanner import ScannerAgent
    scanner = ScannerAgent(GOOGLE_KEY)
    media_type = scanner.detect_media_type(satellite_path)
    placement = await pipeline.analyze_placement(satellite_path, media_type)
    print(f"      heading={placement.get('best_camera_heading')}° "
          f"viable={placement.get('pool_viable')} has_pool={placement.get('has_pool')}")
    print(f"      placement: {placement.get('pool_placement','')[:80]}")

    if placement.get("has_pool"):
        print("      → Property already has pool. Stopping.")
        return

    if not placement.get("pool_viable", True):
        print("      → Pool not viable (yard too small/obstructed). Stopping.")
        return

    # 2. Try 3D capture
    print("\n[2/4] Attempting 3D tile capture...")
    geo_path = f"{job_dir}/view_3d_capture.png"

    # Need geocoords — use existing satellite center
    lat, lng = 34.1416676, -117.5378141  # 12249 Appian Dr, Rancho Cucamonga CA 91739
    heading = placement.get("best_camera_heading", 180)

    base_image = await capture_3d_view(lat, lng, GOOGLE_KEY, geo_path, heading=heading)

    if base_image is None:
        print("      → 3D capture failed (no GPU). Using satellite as fallback.")
        base_image = satellite_path

    # 3-4. Clean → pool render → video
    print("\n[3/4] Running Nano Banana + Kling pipeline...")
    result = await pipeline.run(
        satellite_path=satellite_path,
        placement=placement,
        job_dir=job_dir,
        base_image_path=base_image,
    )

    elapsed = time.time() - t0
    print(f"\n✓ Done in {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"  frame_clean:    http://31.97.142.91:8000/{result['frame_clean']}")
    print(f"  frame_finished: http://31.97.142.91:8000/{result['frame_finished']}")
    print(f"  video:          http://31.97.142.91:8000/{result['video']}")

asyncio.run(main())
