import httpx
import base64
from pathlib import Path


LOB_BASE = "https://api.lob.com/v1"


class MailerAgent:
    def __init__(self, lob_api_key: str):
        self.auth = (lob_api_key, "")

    async def send_postcard(
        self,
        front_path: str,
        back_path: str,
        to_address: dict,
        from_address: dict,
        description: str = "Pool AI Postcard",
    ) -> dict:
        """
        to_address / from_address: {name, address_line1, city, state, zip}
        """
        front_b64 = base64.b64encode(Path(front_path).read_bytes()).decode()
        back_b64 = base64.b64encode(Path(back_path).read_bytes()).decode()

        payload = {
            "description": description,
            "to": {
                "name": to_address.get("name", "Homeowner"),
                "address_line1": to_address["address_line1"],
                "address_city": to_address["city"],
                "address_state": to_address["state"],
                "address_zip": to_address["zip"],
                "address_country": "US",
            },
            "from": {
                "name": from_address.get("name", "Pool AI"),
                "address_line1": from_address["address_line1"],
                "address_city": from_address["city"],
                "address_state": from_address["state"],
                "address_zip": from_address["zip"],
                "address_country": "US",
            },
            "front": f"data:image/jpeg;base64,{front_b64}",
            "back": f"data:image/jpeg;base64,{back_b64}",
            "size": "6x4",
        }

        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{LOB_BASE}/postcards",
                json=payload,
                auth=self.auth,
            )
            r.raise_for_status()
            return r.json()

    def parse_address(self, formatted_address: str) -> dict:
        """Best-effort parse of a formatted address string."""
        parts = [p.strip() for p in formatted_address.split(",")]
        result = {"address_line1": parts[0], "city": "", "state": "", "zip": ""}
        if len(parts) >= 3:
            result["city"] = parts[1]
            state_zip = parts[2].strip().split()
            if len(state_zip) >= 2:
                result["state"] = state_zip[0]
                result["zip"] = state_zip[1]
            elif len(state_zip) == 1:
                result["state"] = state_zip[0]
        return result
