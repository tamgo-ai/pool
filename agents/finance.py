import json
import anthropic


POOL_PROMPT = """You are a pool installation cost estimator for California.

Property info:
- Address: {address}
- Yard size: {yard_size}
- Analysis: {analysis}

Provide a realistic pool installation estimate for this property.
Use current California market rates (2024-2025).

Respond ONLY with valid JSON:
{{
  "pool_size": "description (e.g. 12x24 ft standard)",
  "price_low": 45000,
  "price_high": 75000,
  "price_mid": 58000,
  "monthly_payment_10yr": 580,
  "monthly_payment_15yr": 420,
  "monthly_payment_20yr": 340,
  "interest_rate_assumed": 7.5,
  "includes": ["gunite construction", "plumbing", "electrical", "coping", "plaster finish", "basic decking"],
  "timeline": "8-12 weeks",
  "roi_note": "Pools add 5-8% to California home values",
  "financing_note": "Subject to credit approval. Rates may vary."
}}
"""


class FinanceAgent:
    def __init__(self, anthropic_key: str):
        self.client = anthropic.Anthropic(api_key=anthropic_key)

    def estimate(self, address: str, yard_size: str = "medium", analysis: str = "") -> dict:
        prompt = POOL_PROMPT.format(address=address, yard_size=yard_size, analysis=analysis)
        response = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            return json.loads(text[start:end])
        except Exception:
            return {
                "pool_size": "12x24 ft standard",
                "price_low": 45000,
                "price_high": 75000,
                "price_mid": 58000,
                "monthly_payment_10yr": 580,
                "monthly_payment_15yr": 420,
                "monthly_payment_20yr": 340,
                "interest_rate_assumed": 7.5,
                "includes": ["gunite construction", "plumbing", "electrical", "coping", "plaster finish", "basic decking"],
                "timeline": "8-12 weeks",
                "roi_note": "Pools add 5-8% to California home values",
                "financing_note": "Subject to credit approval. Rates may vary.",
            }
