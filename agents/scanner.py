import httpx
import base64
from pathlib import Path


class ScannerAgent:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def geocode(self, address: str) -> dict:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        async with httpx.AsyncClient() as client:
            r = await client.get(url, params={"address": address, "key": self.api_key})
            data = r.json()
        if not data.get("results"):
            raise ValueError(f"No geocode results for: {address}")
        loc = data["results"][0]["geometry"]["location"]
        return {
            "lat": loc["lat"],
            "lng": loc["lng"],
            "formatted": data["results"][0]["formatted_address"],
        }

    async def get_satellite_image(self, lat: float, lng: float, output_path: str, zoom: int = 20) -> str:
        url = "https://maps.googleapis.com/maps/api/staticmap"
        params = {
            "center": f"{lat},{lng}",
            "zoom": zoom,
            "size": "640x640",
            "maptype": "satellite",
            "key": self.api_key,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
        Path(output_path).write_bytes(r.content)
        return output_path

    async def get_multi_zoom_satellites(self, lat: float, lng: float, output_dir: str) -> list:
        """Get satellite images at 3 zoom levels for richer context."""
        zooms = [19, 20, 21]
        results = []
        async with httpx.AsyncClient(timeout=30) as client:
            for zoom in zooms:
                path = f"{output_dir}/satellite_z{zoom}.png"
                r = await client.get(
                    "https://maps.googleapis.com/maps/api/staticmap",
                    params={"center": f"{lat},{lng}", "zoom": zoom, "size": "640x640",
                            "maptype": "satellite", "key": self.api_key},
                )
                if r.status_code == 200:
                    Path(path).write_bytes(r.content)
                    results.append({"zoom": zoom, "path": path})
        return results

    async def get_street_views(self, lat: float, lng: float, output_dir: str) -> list:
        """Get street view images from 4 directions using nearest panorama."""
        images = []
        async with httpx.AsyncClient(timeout=30) as client:
            # Get the nearest panorama location from metadata
            meta = await client.get(
                "https://maps.googleapis.com/maps/api/streetview/metadata",
                params={"location": f"{lat},{lng}", "key": self.api_key, "radius": 100},
            )
            meta_data = meta.json()
            if meta_data.get("status") != "OK":
                print(f"  Street View: no panorama found ({meta_data.get('status')})")
                return []

            pano_id = meta_data.get("pano_id")
            sv_lat = meta_data["location"]["lat"]
            sv_lng = meta_data["location"]["lng"]
            print(f"  Street View: using pano {pano_id[:12]}... at ({sv_lat:.5f}, {sv_lng:.5f})")

            for heading in [0, 90, 180, 270]:
                direction = ["N", "E", "S", "W"][[0, 90, 180, 270].index(heading)]
                path = f"{output_dir}/streetview_{heading}.jpg"
                r = await client.get(
                    "https://maps.googleapis.com/maps/api/streetview",
                    params={
                        "size": "640x480",
                        "pano": pano_id,          # use pano_id for precision
                        "heading": heading,
                        "pitch": 10,
                        "fov": 90,
                        "key": self.api_key,
                        "return_error_code": "true",
                    },
                )
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                    Path(path).write_bytes(r.content)
                    images.append({"heading": heading, "path": path, "direction": direction})
        return images

    def image_to_base64(self, path: str) -> str:
        return base64.b64encode(Path(path).read_bytes()).decode()

    def detect_media_type(self, path: str) -> str:
        header = Path(path).read_bytes()[:8]
        if header[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"
        if header[:3] == b'\xff\xd8\xff':
            return "image/jpeg"
        if header[:4] == b'RIFF':
            return "image/webp"
        return "image/jpeg"
