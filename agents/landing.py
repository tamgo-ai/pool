import uuid
import json
from pathlib import Path


LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Your Dream Pool — {address_short}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #0a0f1e; color: #fff; }}
  .hero {{ position: relative; width: 100%; height: 100vh; min-height: 600px; overflow: hidden; }}
  .hero video, .hero img.hero-img {{ width: 100%; height: 100%; object-fit: cover; }}
  .hero-overlay {{ position: absolute; inset: 0; background: linear-gradient(to bottom, rgba(0,0,0,0.2) 0%, rgba(0,20,60,0.85) 100%); }}
  .hero-content {{ position: absolute; bottom: 0; left: 0; right: 0; padding: 40px 24px 50px; text-align: center; }}
  .badge {{ display: inline-block; background: rgba(0,180,255,0.2); border: 1px solid rgba(0,180,255,0.5); color: #00b4ff; padding: 6px 16px; border-radius: 20px; font-size: 13px; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 16px; }}
  h1 {{ font-size: clamp(28px, 5vw, 52px); font-weight: 800; line-height: 1.1; margin-bottom: 12px; }}
  h1 span {{ color: #00b4ff; }}
  .address {{ font-size: 16px; color: rgba(255,255,255,0.7); margin-bottom: 32px; }}
  .cta-btn {{ display: inline-block; background: linear-gradient(135deg, #00b4ff, #0066ff); color: #fff; font-size: 18px; font-weight: 700; padding: 18px 48px; border-radius: 50px; text-decoration: none; cursor: pointer; border: none; transition: transform 0.2s, box-shadow 0.2s; box-shadow: 0 8px 32px rgba(0,100,255,0.4); }}
  .cta-btn:hover {{ transform: translateY(-2px); box-shadow: 0 12px 40px rgba(0,100,255,0.6); }}

  .section {{ max-width: 900px; margin: 0 auto; padding: 60px 24px; }}
  .section-title {{ font-size: 32px; font-weight: 800; text-align: center; margin-bottom: 8px; }}
  .section-sub {{ color: rgba(255,255,255,0.6); text-align: center; margin-bottom: 40px; font-size: 16px; }}

  .price-cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; margin-bottom: 16px; }}
  .price-card {{ background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 28px 20px; text-align: center; }}
  .price-card.featured {{ background: linear-gradient(135deg, rgba(0,100,255,0.2), rgba(0,180,255,0.1)); border-color: #00b4ff; }}
  .price-label {{ font-size: 13px; color: rgba(255,255,255,0.5); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }}
  .price-amount {{ font-size: 36px; font-weight: 800; color: #00b4ff; }}
  .price-period {{ font-size: 13px; color: rgba(255,255,255,0.5); margin-top: 4px; }}
  .price-range {{ text-align: center; color: rgba(255,255,255,0.5); font-size: 14px; margin-bottom: 12px; }}
  .includes {{ background: rgba(255,255,255,0.03); border-radius: 12px; padding: 20px 24px; margin-top: 20px; }}
  .includes h4 {{ font-size: 14px; color: rgba(255,255,255,0.5); margin-bottom: 12px; text-transform: uppercase; letter-spacing: 1px; }}
  .includes ul {{ list-style: none; display: flex; flex-wrap: wrap; gap: 8px; }}
  .includes li {{ background: rgba(0,180,255,0.1); border: 1px solid rgba(0,180,255,0.2); color: #cce8ff; padding: 4px 12px; border-radius: 20px; font-size: 13px; }}
  .disclaimer {{ font-size: 12px; color: rgba(255,255,255,0.35); text-align: center; margin-top: 12px; }}

  .form-section {{ background: rgba(255,255,255,0.03); border-radius: 24px; border: 1px solid rgba(255,255,255,0.08); padding: 48px 32px; }}
  .form-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  @media (max-width: 600px) {{ .form-grid {{ grid-template-columns: 1fr; }} }}
  .form-group {{ display: flex; flex-direction: column; gap: 6px; }}
  .form-group.full {{ grid-column: 1 / -1; }}
  label {{ font-size: 13px; color: rgba(255,255,255,0.6); letter-spacing: 0.5px; }}
  input, select, textarea {{ background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.15); border-radius: 10px; color: #fff; padding: 14px 16px; font-size: 15px; width: 100%; transition: border-color 0.2s; }}
  input:focus, select:focus, textarea:focus {{ outline: none; border-color: #00b4ff; background: rgba(0,180,255,0.08); }}
  select option {{ background: #1a2040; }}
  .submit-btn {{ width: 100%; background: linear-gradient(135deg, #00b4ff, #0066ff); color: #fff; font-size: 18px; font-weight: 700; padding: 18px; border: none; border-radius: 50px; cursor: pointer; margin-top: 8px; transition: opacity 0.2s; }}
  .submit-btn:hover {{ opacity: 0.9; }}
  .success-msg {{ display: none; text-align: center; padding: 24px; color: #00ff9d; font-size: 18px; font-weight: 600; }}

  .render-section {{ text-align: center; }}
  .render-img {{ width: 100%; max-width: 700px; border-radius: 20px; box-shadow: 0 24px 80px rgba(0,100,255,0.3); }}

  footer {{ text-align: center; padding: 40px 24px; color: rgba(255,255,255,0.3); font-size: 13px; border-top: 1px solid rgba(255,255,255,0.06); }}
</style>
</head>
<body>

<!-- HERO: Video or fallback image -->
<div class="hero">
  {hero_content}
  <div class="hero-overlay"></div>
  <div class="hero-content">
    <div class="badge">Personalized for your home</div>
    <h1>Your Backyard.<br><span>Your Dream Pool.</span></h1>
    <p class="address">📍 {address}</p>
    <button class="cta-btn" onclick="document.getElementById('contact').scrollIntoView({{behavior:'smooth'}})">
      Get My Free Quote →
    </button>
  </div>
</div>

<!-- RENDER -->
<div class="section render-section">
  <div class="badge" style="margin-bottom:16px">AI Visualization</div>
  <h2 class="section-title">See It Before You Build It</h2>
  <p class="section-sub">This is your actual property with a pool — generated just for you.</p>
  <img src="/output/{job_id}/render.jpg" alt="Pool render for {address_short}" class="render-img">
</div>

<!-- PRICING -->
<div class="section">
  <div class="badge" style="margin-bottom:16px">Investment</div>
  <h2 class="section-title">Pool Investment Estimate</h2>
  <p class="section-sub">Based on your property size and current California market rates.</p>

  <div class="price-cards">
    <div class="price-card">
      <div class="price-label">Starting from</div>
      <div class="price-amount">${price_low:,}</div>
      <div class="price-period">installed</div>
    </div>
    <div class="price-card featured">
      <div class="price-label">As low as</div>
      <div class="price-amount">${monthly_15yr}/mo</div>
      <div class="price-period">15-year financing</div>
    </div>
    <div class="price-card">
      <div class="price-label">Property value add</div>
      <div class="price-amount">+5-8%</div>
      <div class="price-period">California avg.</div>
    </div>
  </div>
  <p class="price-range">Estimated range: ${price_low:,} – ${price_high:,} · {pool_size} · {timeline}</p>

  <div class="includes">
    <h4>What's included</h4>
    <ul>
      {includes_html}
    </ul>
  </div>
  <p class="disclaimer">{financing_note} This is an estimate only. Final pricing requires on-site assessment.</p>
</div>

<!-- CONTACT FORM -->
<div class="section" id="contact">
  <div class="badge" style="margin-bottom:16px">Get Started</div>
  <h2 class="section-title">Claim Your Free Quote</h2>
  <p class="section-sub">A pool specialist will contact you within 24 hours.</p>

  <div class="form-section">
    <form id="leadForm" onsubmit="submitForm(event)">
      <input type="hidden" name="job_id" value="{job_id}">
      <input type="hidden" name="address" value="{address}">
      <div class="form-grid">
        <div class="form-group">
          <label>First Name *</label>
          <input type="text" name="first_name" required placeholder="John">
        </div>
        <div class="form-group">
          <label>Last Name *</label>
          <input type="text" name="last_name" required placeholder="Smith">
        </div>
        <div class="form-group">
          <label>Phone *</label>
          <input type="tel" name="phone" required placeholder="(555) 123-4567">
        </div>
        <div class="form-group">
          <label>Email *</label>
          <input type="email" name="email" required placeholder="john@email.com">
        </div>
        <div class="form-group">
          <label>Best time to call</label>
          <select name="call_time">
            <option>Morning (8am-12pm)</option>
            <option>Afternoon (12pm-5pm)</option>
            <option selected>Evening (5pm-8pm)</option>
            <option>Anytime</option>
          </select>
        </div>
        <div class="form-group">
          <label>Budget range</label>
          <select name="budget">
            <option>Under $50,000</option>
            <option selected>$50,000 – $75,000</option>
            <option>$75,000 – $100,000</option>
            <option>$100,000+</option>
          </select>
        </div>
        <div class="form-group full">
          <label>Any questions or notes?</label>
          <textarea name="notes" rows="3" placeholder="Tell us anything about your backyard or pool vision..."></textarea>
        </div>
      </div>
      <button type="submit" class="submit-btn">Yes, I Want My Free Quote →</button>
      <div class="success-msg" id="successMsg">🎉 Amazing! We'll call you within 24 hours.</div>
    </form>
  </div>
</div>

<footer>
  <p>© 2025 Pool AI · This page was created exclusively for {address_short} · Powered by TAMGO AI</p>
</footer>

<script>
async function submitForm(e) {{
  e.preventDefault();
  const form = e.target;
  const data = Object.fromEntries(new FormData(form));
  try {{
    await fetch('/api/lead', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(data)
    }});
  }} catch(_) {{}}
  form.querySelector('.submit-btn').style.display = 'none';
  document.getElementById('successMsg').style.display = 'block';
}}
</script>
</body>
</html>
"""


class LandingAgent:
    def __init__(self, base_url: str, output_base: str):
        self.base_url = base_url.rstrip("/")
        self.output_base = output_base

    def generate(self, job_id: str, address: str, finance: dict, has_video: bool) -> str:
        address_short = address.split(",")[0]
        includes_html = "".join(f"<li>{item}</li>" for item in finance.get("includes", []))

        if has_video:
            hero_content = f'<video autoplay muted loop playsinline class="hero-img"><source src="/output/{job_id}/video.mp4" type="video/mp4"></video>'
        else:
            hero_content = f'<img src="/output/{job_id}/render.jpg" alt="Pool visualization" class="hero-img">'

        html = LANDING_HTML.format(
            job_id=job_id,
            address=address,
            address_short=address_short,
            hero_content=hero_content,
            price_low=finance.get("price_low", 45000),
            price_high=finance.get("price_high", 75000),
            price_mid=finance.get("price_mid", 58000),
            monthly_15yr=finance.get("monthly_payment_15yr", 420),
            pool_size=finance.get("pool_size", "standard"),
            timeline=finance.get("timeline", "8-12 weeks"),
            includes_html=includes_html,
            financing_note=finance.get("financing_note", "Subject to credit approval."),
        )
        path = f"{self.output_base}/{job_id}/landing.html"
        Path(path).write_text(html, encoding="utf-8")
        return f"{self.base_url}/p/{job_id}"
