
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
from io import BytesIO
import json

# Optional deps for Google Sheets (we guard-import them)
try:
    import gspread
    from google.oauth2.service_account import Credentials
    HAS_GSHEETS = True
except Exception:
    HAS_GSHEETS = False

st.set_page_config(page_title="Sprint Planner (All-in-One)", page_icon="🏃", layout="wide")
st.title("🏃 Sprint Planner — All-in-One")

# ---------------- Core schedule logic ---------------- #
DEFAULT_PHASES = [
    ("Phase 1 - General Prep", "Build foundation: sprint drills, general strength"),
    ("Phase 2 - Specific Prep", "Acceleration, max velocity, introduce 150m runs"),
    ("Phase 3 - Pre-Competition (Indoor)", "Sharpening, block starts, race sim (60/200)"),
    ("Phase 4 - Taper & Peak 1", "Taper into indoor peak"),
    ("Phase 5 - Transition/Recovery", "Active recovery, variation"),
    ("Phase 6 - Outdoor Build", "100/200m base, special endurance, bends"),
    ("Phase 7 - Pre-Competition Outdoor", "Race-specific prep (100/200)"),
    ("Phase 8 - Taper & Peak 2", "Taper into outdoor peak"),
    ("Phase 9 - Post-season Reset", "Active recovery & reset")
]

ROTATIONS = {
    "Mon": [
        "Warm-up + drills; Starts/accelerations; Core",
        "Warm-up + drills; Accel 30–40m; Relaxed 60m; Core",
        "Warm-up + drills; Accel 30m x8; Med ball; Core",
        "Warm-up + drills; Blocks; Accel; Short 50–60m; Core"
    ],
    "Tue": [
        "Drills; Flying 20–30m; Light plyo",
        "Drills; Relaxed strides; Bounding; Core",
        "Drills; Accel 30m; Hurdle hops; Med ball",
        "Drills; Flying 20–30m; Plyo circuit"
    ],
    "Wed": [
        "Bodyweight circuit (legs + push + core)",
        "Bands (rows, pull-aparts) + glutes + core",
        "Single-leg / balance strength + core",
        "Split squats + pull-aparts + stability core"
    ],
    "Thu": [
        "Key session: special endurance / race sim",
        "Key session: bend runs / race rhythm",
        "Key session: 150–200m @90–95% + starts",
        "Key session: race pace mix (100/200)"
    ],
    "Fri": [
        "Flying 20–30m; Blocks; Explosive circuit",
        "Accel 20–40m; Jump squats; Core",
        "Accel 20–30m; Bounding; Med ball",
        "Relaxed 40–60m; Blocks; Explosive lunges; Core"
    ],
    "Sat": [
        "Optional sprint (if fresh) or active recovery",
        "Optional: relaxed 150–200m + stretch",
        "Optional: accel + light plyo",
        "Optional: short race sim; or rest"
    ],
    "Sun": [
        "Rest / Competition",
        "Rest / Mobility",
        "Rest / Easy bike",
        "Rest"
    ]
}

def build_schedule(cfg):
    start = datetime.strptime(cfg["season_start"], "%Y-%m-%d")
    end = datetime.strptime(cfg["season_end"], "%Y-%m-%d")
    weeks = pd.date_range(start=start, end=end, freq="W-MON")

    peak1 = datetime.strptime(cfg["peaks"]["indoor_peak_dates"][0], "%Y-%m-%d")
    peak2 = datetime.strptime(cfg["peaks"]["outdoor_peak_date"], "%Y-%m-%d")

    phases_cfg = [
        ("Phase 1 - General Prep", start, peak1 - timedelta(days=84)),
        ("Phase 2 - Specific Prep", peak1 - timedelta(days=83), peak1 - timedelta(days=35)),
        ("Phase 3 - Pre-Competition (Indoor)", peak1 - timedelta(days=34), peak1 - timedelta(days=7)),
        ("Phase 4 - Taper & Peak 1", peak1 - timedelta(days=6), peak1),
        ("Phase 5 - Transition/Recovery", peak1 + timedelta(days=1), peak1 + timedelta(days=14)),
        ("Phase 6 - Outdoor Build", peak1 + timedelta(days=15), peak2 - timedelta(days=49)),
        ("Phase 7 - Pre-Competition Outdoor", peak2 - timedelta(days=48), peak2 - timedelta(days=14)),
        ("Phase 8 - Taper & Peak 2", peak2 - timedelta(days=13), peak2),
        ("Phase 9 - Post-season Reset", peak2 + timedelta(days=1), end)
    ]

    def phase_for(date):
        for name, s, e in phases_cfg:
            if s <= date <= e:
                return name
        return ""

    bike_km_per_day = cfg.get("bike_km_per_day", 0)
    commute_factor = 0.9 if bike_km_per_day >= 30 else 1.0
    age = cfg.get("age", 15)
    age_factor = 1.0 if age >= 16 else 0.95

    schedule_cfg = cfg.get("schedule", {})
    schedule_mode = schedule_cfg.get("mode", "none")
    sessions_per_week = schedule_cfg.get("sessions_per_week", 5)
    include_time_prefix = schedule_cfg.get("include_time_prefix", True)
    manual_slots = schedule_cfg.get("slots", {})

    def _time_prefix_manual(slots):
        parts = []
        for s in slots:
            t = f'{s.get("start","")}-{s.get("end","")} @ {s.get("location","")}'
            parts.append(t)
        return " + ".join(parts)

    def _time_prefix_auto(day, sessions_per_week):
        templates = {
            5: {
                "Mon": {"location": "Statina/Club", "minutes": 75},
                "Tue": {"location": "Track", "minutes": 60},
                "Wed": {"location": "Home (core)", "minutes": 60},
                "Thu": {"location": "Papendal/Track", "minutes": 105},
                "Fri": {"location": "Track", "minutes": 60}
            },
            4: {
                "Mon": {"location": "Club/Track", "minutes": 75},
                "Wed": {"location": "Home (core)", "minutes": 45},
                "Thu": {"location": "Track", "minutes": 90},
                "Fri": {"location": "Track", "minutes": 60}
            },
            6: {
                "Mon": {"location": "Track", "minutes": 75},
                "Tue": {"location": "Track", "minutes": 60},
                "Wed": {"location": "Home (core)", "minutes": 60},
                "Thu": {"location": "Track", "minutes": 105},
                "Fri": {"location": "Track", "minutes": 60},
                "Sat": {"location": "Track (optional)", "minutes": 90}
            }
        }
        t = templates.get(sessions_per_week, templates[5]).get(day, None)
        if not t or t["minutes"] == 0:
            return ""
        return f'(@ {t["location"]}, ~{t["minutes"]} min) — '

    rows = []
    for i, w in enumerate(weeks):
        phase = phase_for(w)
        if not phase:
            continue
        rot_idx = i % 4
        focus = next((d for n,d in DEFAULT_PHASES if n == phase), "")
        vol_mod = round(commute_factor * age_factor, 2)
        if "Taper" in phase:
            vol_mod = 0.5
        if "Transition" in phase or "Post-season" in phase:
            vol_mod = 0.4

        day_cells = {}
        for day in ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]:
            base_text = ROTATIONS[day][rot_idx]
            prefix = ""
            if include_time_prefix:
                if schedule_mode == "manual":
                    slots = manual_slots.get(day, [])
                    if slots:
                        prefix = f"{_time_prefix_manual(slots)} — "
                elif schedule_mode == "auto":
                    prefix = _time_prefix_auto(day, sessions_per_week)
            day_cells[day] = f"{prefix}{base_text}" if prefix else base_text

        rows.append({
            "Week of": w.strftime("%Y-%m-%d"),
            "Phase": phase,
            "Focus": focus,
            "Mon": day_cells["Mon"],
            "Tue": day_cells["Tue"],
            "Wed": day_cells["Wed"],
            "Thu": day_cells["Thu"],
            "Fri": day_cells["Fri"],
            "Sat": day_cells["Sat"],
            "Sun": day_cells["Sun"],
            "Volume modifier": vol_mod
        })

    return pd.DataFrame(rows)

def df_to_excel_download(df, filename="plan.xlsx"):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    st.download_button("Download Excel", data=output.getvalue(), file_name=filename,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

def json_download_button(cfg, filename="config.json"):
    js = json.dumps(cfg, indent=2, ensure_ascii=False)
    st.download_button("Download Config JSON", data=js.encode("utf-8"),
                       file_name=filename, mime="application/json")

# ---------------- Race calendar helpers ---------------- #
def taper_protocol(priority, peak_type):
    if priority == "A":
        return {
            "Volume change": "-40% to -60%",
            "Intensity": "High (short & sharp)",
            "Key sessions": "Mon: starts/accel; Tue: flying 20–30m; Thu: race-pace touches; Fri: micro-priming",
            "Strength": "Explosive only (bodyweight/bands)",
            "Rest days": "≥1 full rest day before race",
            "Notes": f"A-peak ({peak_type}): keep CNS fresh; no fatigue-dense work last 72h"
        }
    if priority == "B":
        return {
            "Volume change": "-20% to -30%",
            "Intensity": "Moderate-high",
            "Key sessions": "Short starts + 1 race-pace rep",
            "Strength": "Light explosive set",
            "Rest days": "Optional rest day before race",
            "Notes": "Rehearsal race; do not over-taper"
        }
    return {
        "Volume change": "No change or -10%",
        "Intensity": "Normal training",
        "Key sessions": "Keep routine; short starts",
        "Strength": "Normal",
        "Rest days": "None required",
        "Notes": "Training race; prioritize learning"
    }

def calendar_to_excel(df_cal):
    # Expand with taper columns
    rows = []
    for _, r in df_cal.iterrows():
        p = taper_protocol(r["Priority (A/B/C)"], r.get("Peak type",""))
        rows.append({
            "Date": r["Date"],
            "Meet": r["Meet"],
            "Priority (A/B/C)": r["Priority (A/B/C)"],
            "Events": r["Events"],
            "Taper: Volume": p["Volume change"],
            "Taper: Intensity": p["Intensity"],
            "Taper: Key sessions": p["Key sessions"],
            "Taper: Strength": p["Strength"],
            "Taper: Rest days": p["Rest days"],
            "Notes": p["Notes"]
        })
    out = pd.DataFrame(rows)
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as w:
        out.to_excel(w, index=False, sheet_name="Race Calendar")
    return bio.getvalue()

# ---------------- Google Sheets helpers ---------------- #
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

@st.cache_resource(show_spinner=False)
def get_gspread_client_from_secrets():
    if not HAS_GSHEETS:
        return None, "gspread/google-auth niet geïnstalleerd"
    if "gcp_service_account" not in st.secrets:
        return None, "st.secrets['gcp_service_account'] ontbreekt"
    try:
        info = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        client = gspread.authorize(creds)
        return client, None
    except Exception as e:
        return None, f"Fout bij secrets-auth: {e}"

def get_gspread_client_from_upload(uploaded_json_file):
    if not HAS_GSHEETS:
        return None, "gspread/google-auth niet geïnstalleerd", None
    try:
        info = json.loads(uploaded_json_file.getvalue().decode("utf-8"))
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        client = gspread.authorize(creds)
        return client, None, info.get("client_email", None)
    except Exception as e:
        return None, f"Fout bij JSON-upload-auth: {e}", None

def open_sheet(client, sheet_id_or_url, worksheet_name):
    try:
        if sheet_id_or_url.startswith("http"):
            sh = client.open_by_url(sheet_id_or_url)
        else:
            sh = client.open_by_key(sheet_id_or_url)
        try:
            ws = sh.worksheet(worksheet_name)
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title=worksheet_name, rows=1000, cols=20)
            ws.append_row(["Date","Athlete","Session","RPE","Fatigue","Notes"])
        return sh, ws, None
    except Exception as e:
        return None, None, f"Kon sheet niet openen: {e}"

# ---------------- UI Tabs ---------------- #
tab1, tab2, tab3 = st.tabs(["Plan Generator", "Race Calendar", "Athlete Log"])

with tab1:
    st.subheader("Plan Generator (manual/auto schedule)")
    col1, col2, col3 = st.columns(3)
    with col1:
        athlete_name = st.text_input("Athlete name", "Kylie")
        age = st.number_input("Age", min_value=10, max_value=30, value=15)
        sex = st.selectbox("Sex", ["F","M","Other"], index=0)
    with col2:
        season_start = st.date_input("Season start", datetime(2025,9,1))
        season_end = st.date_input("Season end", datetime(2026,7,1))
        bike_km = st.number_input("Bike km/day", min_value=0, max_value=100, value=32)
    with col3:
        pb60 = st.number_input("PB 60m (s)", min_value=6.0, max_value=12.0, value=8.58, step=0.01)
        pb100 = st.number_input("PB 100m (s)", min_value=10.0, max_value=20.0, value=13.48, step=0.01)
        pb200 = st.number_input("PB 200m (s)", min_value=20.0, max_value=40.0, value=29.09, step=0.01)

    st.markdown("### Peaks")
    p1c1, p1c2, p1c3 = st.columns(3)
    with p1c1:
        indoor_peak_1 = st.date_input("Indoor peak date", datetime(2026,2,21))
    with p1c2:
        indoor_peak_2 = st.date_input("Indoor peak date (day 2)", datetime(2026,2,22))
    with p1c3:
        outdoor_peak = st.date_input("Outdoor peak date", datetime(2026,6,28))

    st.markdown("### Schedule mode")
    schedule_mode = st.radio("Choose", ["manual","auto"], horizontal=True, index=0)
    include_prefix = st.checkbox("Include time/location prefix in cells", value=True)

    manual_slots = {}
    sessions_per_week = 5
    if schedule_mode == "manual":
        st.markdown("**Manual schedule — set per day**")
        grid = st.columns(7)
        days = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
        loc_defaults = {
            "Mon":"Statina", "Tue":"Track", "Wed":"Home (online)",
            "Thu":"Papendal", "Fri":"Track", "Sat":"Track (optional)", "Sun":""
        }
        time_defaults = {
            "Mon":(time(20,0), time(21,15)),
            "Tue":(time(19,0), time(20,0)),
            "Wed":(time(17,0), time(18,0)),
            "Thu":(time(16,30), time(18,15)),
            "Fri":(time(19,30), time(20,30)),
            "Sat":(time(9,30), time(11,30)),
            "Sun":(None, None)
        }
        for i, d in enumerate(days):
            with grid[i]:
                st.write(f"**{d}**")
                loc = st.text_input(f"Location {d}", loc_defaults[d], key=f"loc_{d}")
                start_default, end_default = time_defaults[d]
                if start_default and end_default:
                    t1 = st.time_input(f"Start {d}", start_default, key=f"start_{d}")
                    t2 = st.time_input(f"End {d}", end_default, key=f"end_{d}")
                    add = st.checkbox(f"Use {d}", True if d in ["Mon","Tue","Wed","Thu","Fri"] else False, key=f"use_{d}")
                    if add:
                        manual_slots[d] = [ {"start": t1.strftime("%H:%M"), "end": t2.strftime("%H:%M"), "location": loc} ]
                else:
                    st.info("No default time")
                    add = st.checkbox(f"Use {d}", False, key=f"use_{d}")
                    if add:
                        manual_slots[d] = []
    else:
        st.markdown("**Auto schedule — sessions/week**")
        sessions_per_week = st.slider("Sessions per week", 3, 6, 5, 1)

    if st.button("Generate plan"):
        cfg = {
            "season_start": season_start.strftime("%Y-%m-%d"),
            "season_end": season_end.strftime("%Y-%m-%d"),
            "athlete_name": athlete_name,
            "age": age,
            "sex": sex,
            "pbs": {"60m": pb60, "100m": pb100, "200m": pb200},
            "bike_km_per_day": bike_km,
            "peaks": {
                "indoor_peak_dates": [indoor_peak_1.strftime("%Y-%m-%d"), indoor_peak_2.strftime("%Y-%m-%d")],
                "outdoor_peak_date": outdoor_peak.strftime("%Y-%m-%d")
            },
            "events": ["60m","100m","200m"],
            "schedule": {
                "mode": schedule_mode,
                "include_time_prefix": include_prefix,
                "sessions_per_week": sessions_per_week,
                "slots": manual_slots
            }
        }
        df = build_schedule(cfg)
        st.success(f"Plan generated for {athlete_name}. Weeks: {len(df)}")
        st.dataframe(df, use_container_width=True)
        df_to_excel_download(df, filename=f"{athlete_name.replace(' ','_')}_SprintPlan.xlsx")
        json_download_button(cfg, filename=f"{athlete_name.replace(' ','_')}_config.json")

with tab2:
    st.subheader("Race Calendar + Taper")
    st.caption("Vul hier je wedstrijden in en krijg automatisch taper-adviezen per A/B/C prioriteit.")
    default_rows = [
        {"Date":"2026-01-31","Meet":"Indoor Open #1","Events":"60m,200m","Priority (A/B/C)":"B","Peak type":"Indoor 60/200"},
        {"Date":"2026-02-07","Meet":"Indoor Open #2","Events":"60m","Priority (A/B/C)":"B","Peak type":"Indoor 60/200"},
        {"Date":"2026-02-14","Meet":"Indoor Open #3","Events":"60m,200m","Priority (A/B/C)":"B","Peak type":"Indoor 60/200"},
        {"Date":"2026-02-21","Meet":"Indoor Peak Day 1","Events":"60m,200m","Priority (A/B/C)":"A","Peak type":"Indoor 60/200"},
        {"Date":"2026-02-22","Meet":"Indoor Peak Day 2","Events":"60m,200m","Priority (A/B/C)":"A","Peak type":"Indoor 60/200"},
        {"Date":"2026-05-10","Meet":"Outdoor Open #1","Events":"100m,200m","Priority (A/B/C)":"B","Peak type":"Outdoor 100/200"},
        {"Date":"2026-05-24","Meet":"Outdoor Open #2","Events":"100m","Priority (A/B/C)":"B","Peak type":"Outdoor 100/200"},
        {"Date":"2026-06-07","Meet":"Outdoor Open #3","Events":"100m,200m","Priority (A/B/C)":"B","Peak type":"Outdoor 100/200"},
        {"Date":"2026-06-14","Meet":"Outdoor Open #4","Events":"100m","Priority (A/B/C)":"B","Peak type":"Outdoor 100/200"},
        {"Date":"2026-06-28","Meet":"Outdoor Peak","Events":"100m,200m","Priority (A/B/C)":"A","Peak type":"Outdoor 100/200"}
    ]
    df_cal = st.data_editor(pd.DataFrame(default_rows), num_rows="dynamic", use_container_width=True)
    st.info("Tip: sorteer op datum en pas prioriteiten aan. A = hoofdwedstrijden; B = voorbereiding; C = trainingswedstrijden.")

    if st.button("Download Race Calendar (Excel)"):
        data = calendar_to_excel(df_cal)
        st.download_button("Download Excel", data=data, file_name="Race_Calendar_Taper.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tab3:
    st.subheader("Athlete Log → Google Sheets")
    if not HAS_GSHEETS:
        st.warning("gspread/google-auth niet geïnstalleerd. Voeg ze toe aan requirements en redeploy.")
    auth_mode = st.radio("Authenticatie", ["st.secrets (aanbevolen)", "JSON upload"], horizontal=True, index=0)
    sheet_id_or_url = st.text_input("Spreadsheet URL of ID", placeholder="https://docs.google.com/spreadsheets/d/.......")
    worksheet_name = st.text_input("Worksheet naam", value="AthleteLogs")

    client = None
    service_account_email = None
    if auth_mode == "st.secrets (aanbevolen)":
        if HAS_GSHEETS:
            client, err = get_gspread_client_from_secrets()
            if err:
                st.error(err)
            else:
                st.success("Verbonden via st.secrets")
    else:
        if HAS_GSHEETS:
            uploaded = st.file_uploader("Upload service account JSON", type=["json"])
            if uploaded:
                client, err, service_account_email = get_gspread_client_from_upload(uploaded)
                if err:
                    st.error(err)
                else:
                    st.success("Verbonden via JSON upload")
                    if service_account_email:
                        st.info(f"Deel je Google Sheet met: **{service_account_email}** (Editor)")

    st.markdown("---")
    st.markdown("### Athlete Log formulier")
    with st.form("log_form"):
        date = st.date_input("Date", datetime.today())
        athlete = st.text_input("Athlete name")
        session = st.selectbox("Session day", ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"])
        rpe = st.slider("Session RPE (1–10)", 1, 10, 6)
        fatigue = st.slider("Fatigue (1–10)", 1, 10, 5)
        notes = st.text_area("Notes")
        submitted = st.form_submit_button("Submit")

    if submitted:
        if not client:
            st.error("Niet verbonden met Google Sheets. Stel je authenticatie in.")
        elif not sheet_id_or_url or not worksheet_name:
            st.error("Vul de Spreadsheet URL/ID en Worksheet naam in.")
        else:
            _, ws, err = open_sheet(client, sheet_id_or_url, worksheet_name)
            if err:
                st.error(err)
            else:
                try:
                    ws.append_row([date.strftime("%Y-%m-%d"), athlete, session, rpe, fatigue, notes])
                    st.success("Inzending opgeslagen in Google Sheets ✅")
                except Exception as e:
                    st.error(f"Kon niet schrijven naar sheet: {e}")

    st.markdown("---")
    st.markdown("### Recent entries")
    if HAS_GSHEETS and client and sheet_id_or_url and worksheet_name:
        _, ws, err = open_sheet(client, sheet_id_or_url, worksheet_name)
        if not err:
            try:
                records = ws.get_all_records()
                df = pd.DataFrame(records)
                if not df.empty:
                    c1, c2 = st.columns(2)
                    with c1:
                        who = st.text_input("Filter op atleet (optioneel)")
                    with c2:
                        last_n = st.number_input("Toon laatste N", min_value=5, max_value=500, value=50, step=5)
                    if who:
                        df = df[df["Athlete"].str.contains(who, case=False, na=False)]
                    st.dataframe(df.tail(int(last_n)), use_container_width=True)
                else:
                    st.info("Nog geen data in het werkblad.")
            except Exception as e:
                st.error(f"Kon records niet lezen: {e}")

# Footer
st.caption("© Sprint Planner — All-in-One | Streamlit app for coaches & athletes")
