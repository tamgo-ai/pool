"""
Test Kling on existing job.
Usage: python3 test_kling.py [job_id]
"""
import sys, os, time
from dotenv import load_dotenv
load_dotenv()

from agents.video_kling import KlingAgent

job_id = sys.argv[1] if len(sys.argv) > 1 else "11c426ba"
fal_key = os.getenv("FAL_API_KEY")
if not fal_key:
    print("ERROR: FAL_API_KEY not set in .env")
    sys.exit(1)

print(f"Testing Kling on job {job_id}...")
t0 = time.time()

agent = KlingAgent(fal_key)
result = agent.create_pool_video(
    satellite_path=f"output/{job_id}/satellite.png",
    render_path=f"output/{job_id}/render.jpg",
    output_path=f"output/{job_id}/video_kling.mp4",
    job_id=job_id,
    placement_desc="center of the backyard",
)

elapsed = time.time() - t0
size_mb = os.path.getsize(result) / 1024 / 1024
print(f"\n✓ Done in {elapsed:.0f}s")
print(f"  File: {result}")
print(f"  Size: {size_mb:.1f} MB")
print(f"  View: http://31.97.142.91:8000/output/{job_id}/video_kling.mp4")
