"""
E-Waste Passport & Circularity Platform  |  Tamil Nadu
-------------------------------------------------------
Run:   streamlit run app.py
Deps:  pip install streamlit qrcode[pil] pillow pandas numpy folium streamlit-folium

Optional libraries (qrcode, folium, streamlit-folium) have fallbacks, so the
app still runs if they are missing. All hubs, rates and the AI image analysis
are illustrative mock data, ready to be swapped for real services.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from datetime import date, datetime, time, timedelta, timezone

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw

try:
    import qrcode
    HAS_QR = True
except Exception:  # pragma: no cover
    HAS_QR = False

try:
    import folium
    HAS_FOLIUM = True
except Exception:  # pragma: no cover
    HAS_FOLIUM = False

try:
    from streamlit_folium import st_folium
    HAS_ST_FOLIUM = True
except Exception:  # pragma: no cover
    HAS_ST_FOLIUM = False

st.set_page_config(page_title="E-Waste Passport | Tamil Nadu", page_icon="♻️", layout="wide")

IST = timezone(timedelta(hours=5, minutes=30))
INK, TEAL, AMBER, RED = "#14352A", "#0F766E", "#B45309", "#B91C1C"

# ----------------------------------------------------------------------------
# Reference data (mock)
# ----------------------------------------------------------------------------
# district: (lat, lon, tier)
DISTRICTS = {
    "Chennai": (13.0827, 80.2707, "Urban"),
    "Coimbatore": (11.0168, 76.9558, "Urban"),
    "Madurai": (9.9252, 78.1198, "Urban"),
    "Salem": (11.6643, 78.1460, "Urban"),
    "Trichy": (10.7905, 78.7047, "Urban"),
    "Tirunelveli": (8.7139, 77.7567, "Semi-urban"),
    "Vellore": (12.9165, 79.1325, "Semi-urban"),
    "Erode": (11.3410, 77.7172, "Semi-urban"),
    "Thanjavur": (10.7870, 79.1378, "Semi-urban"),
    "Thoothukudi": (8.7642, 78.1348, "Semi-urban"),
    "Kanyakumari": (8.0883, 77.5385, "Semi-urban"),
    "Dharmapuri": (12.1211, 78.1582, "Rural"),
    "Nilgiris": (11.4064, 76.6932, "Rural"),
    "Ramanathapuram": (9.3639, 78.8395, "Rural"),
    "Ariyalur": (11.1401, 79.0786, "Rural"),
}
# tier: (drop-off label, pickup min h, pickup max h)
TIER_SLA = {
    "Urban": ("Instant", 4, 8),
    "Semi-urban": ("Instant (district hub)", 12, 24),
    "Rural": ("Same day (nearest taluk point)", 24, 48),
}
TIER_COLOR = {"Urban": "green", "Semi-urban": "orange", "Rural": "red"}
DEVICES = ["Smartphone", "Laptop", "Tablet", "Charger", "Household Appliance"]
STATUSES = ["Powers on", "Partially working", "Dead"]


def build_hubs() -> pd.DataFrame:
    rows = []
    extra = {"Chennai": ["Guindy", "Tambaram"], "Coimbatore": ["Peelamedu"], "Madurai": ["Anna Nagar"]}
    for d, (lat, lon, tier) in DISTRICTS.items():
        rows.append(dict(Hub=f"{d} Central E-Waste Hub", District=d, Tier=tier, Type="Primary processing hub",
                         lat=lat, lon=lon, Accepts="All categories"))
        for i, area in enumerate(extra.get(d, [])):
            rows.append(dict(Hub=f"{d} {area} Collection Point", District=d, Tier=tier, Type="Collection point",
                             lat=lat + 0.03 * (i + 1), lon=lon - 0.035 * (i + 1),
                             Accepts="Phones, laptops, tablets, chargers"))
    return pd.DataFrame(rows)


HUBS = build_hubs()

# Typical grams recovered per unit (illustrative averages)
MATERIALS = {
    "Smartphone": dict(weight=170, Copper=15, Gold=0.03, Aluminum=25, Plastics=30),
    "Laptop": dict(weight=2200, Copper=120, Gold=0.20, Aluminum=350, Plastics=600),
    "Tablet": dict(weight=480, Copper=35, Gold=0.08, Aluminum=120, Plastics=120),
    "Charger": dict(weight=120, Copper=25, Gold=0.00, Aluminum=5, Plastics=60),
    "Household Appliance": dict(weight=8000, Copper=400, Gold=0.05, Aluminum=600, Plastics=1500),
}
SCRAP_RATE_INR_PER_G = {"Copper": 0.80, "Gold": 6500.0, "Aluminum": 0.22, "Plastics": 0.03}  # mock rates
BASE_RESALE_INR = {"Smartphone": 6000, "Laptop": 15000, "Tablet": 7000, "Charger": 300, "Household Appliance": 2500}
STATUS_MULT = {"Powers on": 1.0, "Partially working": 0.4, "Dead": 0.05}
RECOVERY_FACTOR = {"Direct Reuse / Refurbishment": 1.0, "Component Harvesting": 0.80, "Certified Recycling": 0.92}
STREAM_COLOR = {"Direct Reuse / Refurbishment": TEAL, "Component Harvesting": AMBER, "Certified Recycling": INK}

# ----------------------------------------------------------------------------
# Styling
# ----------------------------------------------------------------------------
st.markdown(
    f"""
<style>
.block-container {{ padding-top: 2rem; max-width: 1200px; }}
.hero {{ background: {INK}; color: #fff; padding: 1.6rem 1.8rem; border-radius: 10px; margin-bottom: 1.2rem; }}
.hero h1 {{ color: #fff; margin: 0 0 .3rem 0; font-size: 1.9rem; }}
.hero p {{ margin: 0; color: #cfe3da; font-size: 1rem; }}
.card {{ border: 1px solid rgba(128,128,128,.3); border-left: 5px solid {TEAL}; border-radius: 8px;
         padding: 1rem 1.2rem; margin: .5rem 0 1rem 0; background: rgba(128,128,128,.07); }}
.card h4 {{ margin: 0 0 .35rem 0; }}
.card p {{ margin: .2rem 0; }}
.pid {{ font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 1.7rem; font-weight: 700; color: {TEAL}; }}
.pill {{ display:inline-block; padding: .1rem .6rem; border-radius: 999px; font-size: .8rem;
         border: 1px solid rgba(128,128,128,.5); margin-right: .3rem; }}
</style>
""",
    unsafe_allow_html=True,
)


def card(title: str, body: str, color: str = TEAL) -> None:
    st.markdown(f'<div class="card" style="border-left-color:{color}"><h4>{title}</h4>{body}</div>',
                unsafe_allow_html=True)


def hero(title: str, subtitle: str) -> None:
    st.markdown(f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def now() -> datetime:
    return datetime.now(IST)


def init_state() -> None:
    st.session_state.setdefault("passport", None)
    st.session_state.setdefault("registry", [])
    st.session_state.setdefault("schedule", None)
    st.session_state.setdefault("assessment", None)
    st.session_state.setdefault("data_security", None)
    st.session_state.setdefault("routing", None)
    st.session_state.setdefault("audit", None)


def add_event(stage: str, detail: str) -> None:
    p = st.session_state.passport
    if p is not None:
        p["events"].append({"stage": stage, "detail": detail, "timestamp": now().strftime("%Y-%m-%d %H:%M:%S IST")})


def new_passport_id(name: str, district: str, device: str) -> str:
    seed = f"{name}|{district}|{device}|{now().isoformat()}|{len(st.session_state.registry)}"
    code = hashlib.sha256(seed.encode()).hexdigest()[:4].upper()
    return f"EW-{now().year}-{code}"


def make_qr(payload: str) -> Image.Image:
    """Real QR via `qrcode`; falls back to a hash-derived placeholder pattern."""
    if HAS_QR:
        qr = qrcode.QRCode(box_size=8, border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(payload)
        qr.make(fit=True)
        return qr.make_image(fill_color=INK, back_color="white").convert("RGB")
    n, cell = 25, 8
    bits = hashlib.sha256(payload.encode()).digest() * 8
    img = Image.new("RGB", (n * cell, n * cell), "white")
    d = ImageDraw.Draw(img)
    for i in range(n * n):
        if (bits[i % len(bits)] >> (i % 8)) & 1:
            x, y = (i % n) * cell, (i // n) * cell
            d.rectangle([x, y, x + cell - 1, y + cell - 1], fill=INK)
    for ox, oy in [(0, 0), (n - 7, 0), (0, n - 7)]:
        d.rectangle([ox * cell, oy * cell, (ox + 7) * cell, (oy + 7) * cell], fill="white", outline=INK, width=cell)
        d.rectangle([(ox + 2) * cell, (oy + 2) * cell, (ox + 5) * cell, (oy + 5) * cell], fill=INK)
    return img


def img_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_hub(district: str) -> tuple[pd.Series, float]:
    lat, lon, _ = DISTRICTS[district]
    d = HUBS.apply(lambda r: haversine_km(lat, lon, r.lat, r.lon), axis=1)
    i = int(d.idxmin())
    return HUBS.loc[i], float(d.loc[i])


def eta_for(district: str, mode: str) -> tuple[str, str]:
    """Return (headline, detail) for the estimated collection time."""
    tier = DISTRICTS[district][2]
    drop, lo, hi = TIER_SLA[tier]
    if mode == "Drop at hub":
        return drop, f"{tier} district: walk-in drop-off, no waiting time."
    return f"{lo}-{hi} hours", f"{tier} district: scheduled doorstep pickup, ~{lo}-{hi} h after confirmation."


def analyze_image(file_bytes: bytes) -> dict:
    """SIMULATED AI exterior-damage analysis. Replace with a real vision model
    (e.g. a Claude vision call or an on-device CNN) returning the same dict shape."""
    rng = np.random.default_rng(int(hashlib.sha256(file_bytes).hexdigest()[:8], 16))
    pool = ["Screen crack", "Frame dent", "Back-panel scratches", "Port corrosion", "Liquid-damage indicator",
            "Casing swelling", "Missing buttons"]
    k = int(rng.integers(0, 4))
    findings = list(rng.choice(pool, size=k, replace=False)) if k else []
    score = int(min(100, (rng.integers(5, 25) if not findings else rng.integers(20, 55)) + 12 * len(findings)))
    return {"damage_score": score, "findings": [str(f) for f in findings], "confidence": float(round(rng.uniform(.78, .96), 2))}


def decide_route(device: str, a: dict) -> tuple[str, list[str]]:
    reasons = []
    if a["swelling"]:
        reasons.append("Battery swelling is a fire/chemical hazard, so the item needs certified hazardous handling.")
        return "Certified Recycling", reasons
    if a["powers_on"] and a["screen_ok"] and a["damage"] < 35:
        reasons.append("Device powers on, screen is intact and exterior damage is low.")
        return "Direct Reuse / Refurbishment", reasons
    if device == "Charger" and a["powers_on"] and a["damage"] < 40:
        reasons.append("Charger is functional with limited damage.")
        return "Direct Reuse / Refurbishment", reasons
    if a["powers_on"] or a["status"] == "Partially working" or (a["screen_ok"] and a["damage"] < 50):
        reasons.append("Device is not fit for reuse as a whole, but boards, displays or batteries can be salvaged.")
        return "Component Harvesting", reasons
    reasons.append("Device is dead and heavily damaged, so material recovery is the best outcome.")
    return "Certified Recycling", reasons


def material_breakdown(device: str, stream: str) -> pd.DataFrame:
    m, f = MATERIALS[device], RECOVERY_FACTOR[stream]
    rows = []
    for mat in ["Copper", "Gold", "Aluminum", "Plastics"]:
        grams = m[mat] * f
        value = 0.0 if stream.startswith("Direct") else grams * SCRAP_RATE_INR_PER_G[mat]
        rows.append({"Material": mat, "Per device (g)": m[mat], "Recovered / retained (g)": round(grams, 3),
                     "Scrap value (INR)": round(value, 2)})
    return pd.DataFrame(rows)


def monetary_value(device: str, status: str, stream: str, condition: int, data_secure: bool,
                   mat_df: pd.DataFrame) -> dict:
    base = BASE_RESALE_INR[device] * STATUS_MULT[status] * condition / 100
    if stream.startswith("Direct"):
        resale, bonus = base, 20
    elif stream == "Component Harvesting":
        resale, bonus = base * 0.30, 10
    else:
        resale, bonus = 0.0, 0
    scrap = float(mat_df["Scrap value (INR)"].sum())
    kg = MATERIALS[device]["weight"] / 1000
    credits = round(kg * 40 + bonus + (15 if data_secure else 0))
    return {"resale": round(resale), "scrap": round(scrap), "credits": credits, "total": round(resale + scrap + credits)}


def ledger_frame() -> pd.DataFrame:
    """Hash-chained event log: each record commits to the previous one."""
    p = st.session_state.passport
    rows, prev = [], "0" * 64
    for i, e in enumerate(p["events"]):
        body = json.dumps({"id": p["id"], "n": i, **e}, sort_keys=True)
        h = hashlib.sha256((prev + body).encode()).hexdigest()
        rows.append({"Block": i, "Stage": e["stage"], "Detail": e["detail"], "Timestamp": e["timestamp"],
                     "Prev hash": prev[:10] + "…", "Hash": h[:10] + "…", "_full": h})
        prev = h
    return pd.DataFrame(rows)


def need_passport() -> bool:
    if st.session_state.passport is None:
        st.warning("No passport yet. Register a device on the Home & Registration page first.")
        return False
    return True


# ----------------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------------
def page_home() -> None:
    hero("E-Waste Passport & Circularity Platform",
         "Give every discarded device a verifiable identity, from your doorstep to certified recovery.")

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("Register your device")
        with st.form("register"):
            name = st.text_input("Your name", placeholder="e.g. Priya Raman")
            c1, c2 = st.columns(2)
            district = c1.selectbox("District", list(DISTRICTS), index=0)
            device = c2.selectbox("Device type", DEVICES)
            status = st.radio("Operational status", STATUSES, horizontal=True)
            submitted = st.form_submit_button("Create E-Waste Passport")
        if submitted:
            if not name.strip():
                st.error("Enter your name to create a passport.")
            else:
                pid = new_passport_id(name, district, device)
                st.session_state.passport = {"id": pid, "name": name.strip(), "district": district, "device": device,
                                             "status": status, "created": now().strftime("%d %b %Y, %H:%M IST"),
                                             "events": []}
                for k in ("schedule", "assessment", "data_security", "routing", "audit"):
                    st.session_state[k] = None
                add_event("Registration", f"{device} ({status}) registered in {district}")
                st.session_state.registry.append({"Passport ID": pid, "Owner": name.strip(), "District": district,
                                                  "Device": device, "Status": status})
                st.success(f"Passport {pid} created.")

    p = st.session_state.passport
    with right:
        st.subheader("Your passport")
        if p:
            card(p["device"] + " passport",
                 f'<div class="pid">{p["id"]}</div><p>{p["name"]} · {p["district"]}</p>'
                 f'<p><span class="pill">{p["status"]}</span><span class="pill">Issued {p["created"]}</span></p>')
            qr = make_qr(f'EWP|{p["id"]}|{p["district"]}|{p["device"]}')
            st.image(qr, caption="Scan at the hub to verify this passport", width=220)
            st.download_button("Download QR (PNG)", img_bytes(qr), file_name=f'{p["id"]}.png', mime="image/png")
            if not HAS_QR:
                st.caption("`qrcode` is not installed, so this is a placeholder pattern. Run `pip install qrcode[pil]`.")
        else:
            st.info("Fill in the form to generate your Passport ID and QR code.")

    st.divider()
    st.subheader("Collection time")
    if not p:
        st.caption("Register a device to schedule collection.")
    else:
        c1, c2, c3 = st.columns(3)
        mode = c1.radio("How will you hand over?", ["Drop at hub", "Doorstep pickup"])
        day = c2.date_input("Preferred date", value=date.today() + timedelta(days=1), min_value=date.today())
        slot = c3.selectbox("Time slot", ["09:00-12:00", "12:00-15:00", "15:00-18:00"])
        headline, detail = eta_for(p["district"], mode)
        hub, km = nearest_hub(p["district"])
        m1, m2, m3 = st.columns(3)
        m1.metric("Estimated collection time", headline)
        m2.metric("Nearest hub", hub["Hub"])
        m3.metric("Approx. distance", f"{km:.1f} km")
        st.caption(detail)
        if st.button("Confirm collection slot"):
            st.session_state.schedule = {"mode": mode, "date": day.strftime("%d %b %Y"), "slot": slot,
                                         "hub": hub["Hub"], "eta": headline}
            add_event("Collection scheduled", f"{mode}, {day:%d %b %Y} {slot}, hub: {hub['Hub']}")
            st.success(f"Booked: {mode.lower()} on {day:%d %b %Y}, {slot}.")
        if st.session_state.schedule:
            s = st.session_state.schedule
            st.markdown(f"**Current booking:** {s['mode']} · {s['date']} · {s['slot']} · {s['hub']}")

    if st.session_state.registry:
        st.divider()
        st.subheader("Registered passports this session")
        st.dataframe(pd.DataFrame(st.session_state.registry), hide_index=True)


def page_map() -> None:
    hero("Tamil Nadu Collection Network",
         "Authorised hubs across 15 districts, with pickup times based on how far you are from a processing centre.")
    p = st.session_state.passport
    default = list(DISTRICTS).index(p["district"]) if p else 0
    c1, c2 = st.columns([2, 1])
    district = c1.selectbox("Your district", list(DISTRICTS), index=default)
    mode = c2.radio("Hand-over", ["Drop at hub", "Doorstep pickup"], horizontal=True, key="map_mode")
    tier = DISTRICTS[district][2]
    headline, detail = eta_for(district, mode)
    hub, km = nearest_hub(district)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("District type", tier)
    m2.metric("Estimated time", headline)
    m3.metric("Nearest hub", hub["Hub"].replace(" E-Waste Hub", "").replace(" Collection Point", " CP"))
    m4.metric("Distance", f"{km:.1f} km")
    st.caption(detail)

    lat, lon, _ = DISTRICTS[district]
    if HAS_FOLIUM:
        m = folium.Map(location=[10.9, 78.4], zoom_start=7, tiles="OpenStreetMap")
        for _, r in HUBS.iterrows():
            drop, lo, hi = TIER_SLA[r.Tier]
            folium.Marker(
                [r.lat, r.lon], tooltip=r.Hub,
                popup=folium.Popup(f"<b>{r.Hub}</b><br>{r.Type}<br>Accepts: {r.Accepts}<br>"
                                   f"Drop-off: {drop}<br>Pickup: {lo}-{hi} h", max_width=260),
                icon=folium.Icon(color=TIER_COLOR[r.Tier], icon="recycle", prefix="fa"),
            ).add_to(m)
        folium.CircleMarker([lat, lon], radius=14, color=INK, fill=True, fill_opacity=.15,
                            tooltip=f"You: {district}").add_to(m)
        if HAS_ST_FOLIUM:
            try:
                st_folium(m, height=520, use_container_width=True, returned_objects=[])
            except TypeError:
                st_folium(m, height=520, returned_objects=[])
        else:
            components.html(m._repr_html_(), height=540)
    else:
        st.map(HUBS[["lat", "lon"]], zoom=6)
        st.caption("`folium` is not installed, showing the basic map. Run `pip install folium streamlit-folium`.")
    st.caption("Marker colour: green = urban, orange = semi-urban, red = rural. Hub locations are illustrative.")

    st.subheader("Service levels by district type")
    sla = pd.DataFrame([{"District type": t, "Drop-off": v[0], "Doorstep pickup": f"{v[1]}-{v[2]} hours",
                         "Districts": ", ".join(k for k, d in DISTRICTS.items() if d[2] == t)}
                        for t, v in TIER_SLA.items()])
    st.dataframe(sla, hide_index=True)
    with st.expander("All authorised hubs"):
        st.dataframe(HUBS[["Hub", "District", "Tier", "Type", "Accepts"]], hide_index=True)


def page_assessment() -> None:
    hero("Device Condition & Data Security",
         "Check the device, then protect your personal data before handing it over.")
    if not need_passport():
        return
    p = st.session_state.passport
    st.markdown(f"Assessing **{p['device']}** · `{p['id']}`")

    tab1, tab2 = st.tabs(["Condition assessment", "Data recovery gateway"])
    with tab1:
        c1, c2 = st.columns(2, gap="large")
        with c1:
            st.markdown("##### Manual checks")
            screen_ok = st.checkbox("Screen intact?", value=True)
            swelling = st.checkbox("Battery swelling or bulging case?")
            powers_on = st.checkbox("Powers on?", value=p["status"] != "Dead")
            casing_ok = st.checkbox("Casing free of major dents or cracks?", value=True)
        with c2:
            st.markdown("##### AI exterior scan")
            up = st.file_uploader("Upload a photo of the device", type=["jpg", "jpeg", "png"])
            ai = None
            if up is not None:
                data = up.getvalue()
                try:
                    st.image(Image.open(io.BytesIO(data)), width=260)
                except Exception:
                    st.error("That file could not be read as an image. Try a JPG or PNG.")
                if st.button("Run AI damage analysis"):
                    with st.spinner("Analysing exterior..."):
                        st.session_state["ai_result"] = analyze_image(data)
                ai = st.session_state.get("ai_result")
            else:
                st.session_state.pop("ai_result", None)
                st.caption("No photo yet. The score will use manual checks only.")
            if ai:
                a, b = st.columns(2)
                a.metric("Damage score", f"{ai['damage_score']}/100")
                b.metric("Model confidence", f"{ai['confidence']:.0%}")
                st.write("Detected: " + (", ".join(ai["findings"]) if ai["findings"] else "no visible damage"))
            st.caption("Simulated analysis. `analyze_image()` is the hook for a real vision model.")

        damage = ai["damage_score"] if ai else (0 if casing_ok else 30)
        condition = int(max(0, min(100, 100 - (0 if screen_ok else 20) - (35 if swelling else 0)
                                   - (0 if powers_on else 25) - (0 if casing_ok else 10) - 0.3 * damage)))
        st.divider()
        m1, m2, m3 = st.columns(3)
        m1.metric("Condition score", f"{condition}/100")
        m2.metric("Exterior damage", f"{damage}/100")
        m3.metric("Hazard flag", "Battery hazard" if swelling else "None")
        if swelling:
            st.error("Swollen batteries can ignite. Do not charge or puncture the device, and keep it in a cool, dry place.")
        eff_status = p["status"]
        if not powers_on and eff_status == "Powers on":
            eff_status = "Dead"
        elif powers_on and eff_status == "Dead":
            eff_status = "Partially working"
        if st.button("Save assessment"):
            st.session_state.assessment = dict(screen_ok=screen_ok, swelling=swelling, powers_on=powers_on,
                                               casing_ok=casing_ok, damage=damage, condition=condition,
                                               status=eff_status,
                                               findings=ai["findings"] if ai else [])
            add_event("Assessment", f"Condition {condition}/100, damage {damage}/100, swelling={swelling}")
            st.success("Assessment saved. Continue to Circular Routing.")

    with tab2:
        st.markdown("##### Protect your data before hand-over")
        if p["device"] in ("Charger", "Household Appliance"):
            st.info("This device type does not normally store personal data, so no wipe is needed.")
            if st.button("Mark data security as not applicable"):
                st.session_state.data_security = {"method": "Not applicable", "done": True}
                add_event("Data security", "Not applicable for device type")
        else:
            want = st.toggle("I need help securing my data", value=False)
            if want:
                method = st.radio("Choose a protocol",
                                  ["Secure remote data-wipe checklist", "Local data-recovery assistance"])
                dead = p["status"] == "Dead" or not powers_on
                if method.startswith("Secure"):
                    steps = ["Back up photos, contacts and documents to your cloud or another device",
                             "Sign out of Google / Apple / Microsoft accounts and remove the device from your account",
                             "Disable Find My Device and activation lock",
                             "Remove SIM and memory cards",
                             "Run factory reset with encryption enabled (encrypt first, then reset)",
                             "Confirm the device boots to the setup screen"]
                    if dead:
                        st.warning("A device that will not power on cannot be reset. Choose local assistance so the "
                                   "storage can be removed and destroyed with a certificate.")
                else:
                    steps = ["Technician at the hub attempts data recovery from storage (with your consent)",
                             "Recovered files are copied to media you supply, then verified with you",
                             "Storage is cryptographically erased (NIST 800-88) or physically shredded",
                             "You receive a signed destruction certificate linked to your passport"]
                done = [st.checkbox(s, key=f"ds_{i}_{method}") for i, s in enumerate(steps)]
                st.progress(sum(done) / len(done), text=f"{sum(done)} of {len(done)} steps done")
                if st.button("Confirm data security"):
                    if all(done):
                        st.session_state.data_security = {"method": method, "done": True}
                        add_event("Data security", method + " completed")
                        st.success("Data security recorded on your passport.")
                    else:
                        st.error("Complete every step before confirming.")
            else:
                st.caption("If you skip this, the hub will treat your device as containing personal data and "
                           "securely erase its storage on arrival.")
        ds = st.session_state.data_security
        if ds and ds["done"]:
            st.success(f"Data security status: {ds['method']}")


def page_routing() -> None:
    hero("Circular Routing & Material Value",
         "Where your device goes next, what it is made of, and what it is worth.")
    if not need_passport():
        return
    p, a = st.session_state.passport, st.session_state.assessment
    if a is None:
        st.warning("Save a condition assessment first. Showing an estimate based on your registration status.")
        a = dict(screen_ok=p["status"] == "Powers on", swelling=False, powers_on=p["status"] != "Dead",
                 casing_ok=True, damage=20, condition={"Powers on": 80, "Partially working": 50, "Dead": 25}[p["status"]],
                 status=p["status"], findings=[])
    device = p["device"]
    stream, reasons = decide_route(device, a)
    ds_done = bool(st.session_state.data_security and st.session_state.data_security["done"])
    mat = material_breakdown(device, stream)
    val = monetary_value(device, a["status"], stream, a["condition"], ds_done, mat)

    if st.button("Lock routing decision to passport"):
        st.session_state.routing = {"stream": stream, **val}
        add_event("Routing", f"{stream}; est. value INR {val['total']}; credits {val['credits']}")
        st.success("Routing recorded.")

    t1, t2, t3 = st.tabs(["Routing decision", "Material recovery", "Monetary value"])
    with t1:
        card(stream, "<p>" + "</p><p>".join(reasons) + "</p>", STREAM_COLOR[stream])
        c1, c2, c3 = st.columns(3)
        c1.metric("Condition score", f"{a['condition']}/100")
        c2.metric("Data secured", "Yes" if ds_done else "Not yet")
        c3.metric("Device weight", f"{MATERIALS[device]['weight'] / 1000:.2f} kg")
        st.markdown("**The three streams**")
        s1, s2, s3 = st.columns(3)
        for col, (name, text) in zip((s1, s2, s3), [
            ("Direct Reuse / Refurbishment", "Tested, cleaned and resold or donated. Highest value, lowest footprint."),
            ("Component Harvesting", "Boards, displays, batteries and cameras are removed and reused as spares."),
            ("Certified Recycling", "Shredded and refined by an authorised recycler for metals and plastics.")]):
            with col:
                card(("✔ " if name == stream else "") + name, f"<p>{text}</p>", STREAM_COLOR[name])
    with t2:
        label = "retained in service" if stream.startswith("Direct") else "recovered"
        st.markdown(f"Estimated material **{label}** for a {device.lower()} via {stream.lower()}.")
        cols = st.columns(4)
        for col, (_, r) in zip(cols, mat.iterrows()):
            unit = f"{r['Recovered / retained (g)']:.2f} g" if r["Material"] == "Gold" else f"{r['Recovered / retained (g)']:.1f} g"
            col.metric(r["Material"], unit)
        st.bar_chart(mat.set_index("Material")["Recovered / retained (g)"].drop("Gold"))
        st.caption("Gold is shown in the metrics only because its mass is too small to chart beside bulk metals.")
        st.dataframe(mat, hide_index=True)
        st.caption(f"Recovery factor for this stream: {RECOVERY_FACTOR[stream]:.0%}. Averages are illustrative.")
    with t3:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Residual market value", f"₹{val['resale']:,}")
        c2.metric("Scrap material value", f"₹{val['scrap']:,}")
        c3.metric("Eco-incentive credits", f"{val['credits']} GRT")
        c4.metric("Total estimated benefit", f"₹{val['total']:,}")
        st.bar_chart(pd.DataFrame({"INR": [val["resale"], val["scrap"], val["credits"]]},
                                  index=["Residual value", "Scrap value", "Eco credits"]))
        st.caption("Credits are issued at 1 GRT = ₹1 for this demo. They include a bonus for secured data and for reuse. "
                   "Market rates are mock values, not live prices.")


def page_workflow() -> None:
    hero("End-to-End Workflow & Unique Technology",
         "Six stages, one tamper-evident record.")
    p = st.session_state.passport

    st.graphviz_chart(f"""
    digraph G {{
      rankdir=LR; bgcolor="transparent";
      node [shape=box, style="rounded,filled", fillcolor="{INK}", fontcolor="white", color="{INK}", fontname="Helvetica", margin="0.2,0.12"];
      edge [color="{TEAL}", penwidth=1.6];
      R [label="Registration\\nPassport ID + QR"]; M [label="TN Map Routing\\nNearest hub + ETA"];
      A [label="Assessment\\nManual + AI scan"]; D [label="Data Security\\nWipe / recovery"];
      V [label="Material Recovery\\nReuse / Harvest / Recycle"]; F [label="Final Audit\\nSigned + tokens minted"];
      R -> M -> A -> D -> V -> F;
    }}""")

    done = {
        "Registration": p is not None,
        "TN Map Routing": bool(st.session_state.schedule),
        "Assessment": bool(st.session_state.assessment),
        "Data Security": bool(st.session_state.data_security),
        "Material Recovery": bool(st.session_state.routing),
        "Final Audit": bool(st.session_state.audit),
    }
    cols = st.columns(6)
    for col, (k, v) in zip(cols, done.items()):
        col.metric(k, "Done" if v else "Pending")
    st.progress(sum(done.values()) / 6, text=f"{sum(done.values())} of 6 stages complete")

    with st.expander("What happens at each stage"):
        st.markdown("""
- **Registration:** the owner creates a passport with a unique ID and QR code.
- **TN map routing:** the nearest authorised hub is matched and a collection time is estimated from the district type.
- **Assessment:** manual checks and an AI photo scan produce a condition score and flag battery hazards.
- **Data security:** the owner completes a wipe checklist or gets hub-assisted recovery and certified destruction.
- **Material recovery:** the item is routed to reuse, harvesting or recycling and the recovered material is estimated.
- **Final audit:** the hub weighs the output, signs the record and mints eco credits.
""")

    st.divider()
    st.subheader("Cryptographic Material Passports & Green Tokenomics")
    c1, c2 = st.columns(2, gap="large")
    with c1:
        card("Cryptographic Material Passport",
             "<p>Every step above is written to a hash-chained record. Each entry contains the hash of the one before it, "
             "so editing any past step breaks every later hash. Hubs and recyclers sign their entries, and the QR code "
             "on the device opens the full chain.</p>")
    with c2:
        card("Green Tokenomics",
             "<p><b>Mint:</b> GRT credits are issued only after a signed final audit.<br>"
             "<b>Earn:</b> owners, collectors and recyclers are rewarded per verified kilogram.<br>"
             "<b>Spend:</b> redeem for bus passes, utility bill rebates or refurbished devices.<br>"
             "<b>Stake:</b> recyclers lock tokens that are slashed if audits find mismatched mass.</p>", AMBER)

    st.markdown("##### Live demo: this passport's chain")
    if not p:
        st.info("Register a device to see its chain.")
        return
    df = ledger_frame()
    st.dataframe(df.drop(columns="_full"), hide_index=True)
    st.caption("Demo only: hashes are computed locally with SHA-256. A production system would anchor the final hash "
               "on a permissioned ledger and use digital signatures per actor.")

    r = st.session_state.routing
    if st.session_state.audit:
        au = st.session_state.audit
        st.success(f"Final audit complete. {au['tokens']} GRT minted. Passport root hash: {au['root']}")
    elif r is None:
        st.info("Lock a routing decision on the Circular Routing page to enable the final audit.")
    else:
        if st.button("Run final audit and mint tokens"):
            add_event("Final audit", f"Hub verified output for {r['stream']}; {r['credits']} GRT minted")
            root = ledger_frame().iloc[-1]["_full"]
            st.session_state.audit = {"tokens": r["credits"], "root": root[:24] + "…"}
            st.rerun()


# ----------------------------------------------------------------------------
# Navigation
# ----------------------------------------------------------------------------
def main() -> None:
    init_state()
    pages = {
        "Home & Registration": page_home,
        "TN Collection Map": page_map,
        "Condition & Data Security": page_assessment,
        "Circular Routing & Value": page_routing,
        "Workflow & Technology": page_workflow,
    }
    with st.sidebar:
        st.markdown("### ♻️ E-Waste Passport")
        choice = st.radio("Go to", list(pages), label_visibility="collapsed")
        st.divider()
        p = st.session_state.passport
        if p:
            st.markdown(f"**Active passport**  \n`{p['id']}`  \n{p['device']} · {p['district']}")
            if st.session_state.audit:
                st.success("Audit complete")
        else:
            st.caption("No active passport")
    pages[choice]()


main()
