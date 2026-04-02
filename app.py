import asyncio
import datetime
import os
import smtplib
import subprocess
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Fix for Windows: Streamlit switches asyncio to SelectorEventLoop which breaks
# Playwright's subprocess. Force ProactorEventLoop before anything else.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import streamlit as st
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

import scraper


# ---------------------------------------------------------------------------
# Install Playwright Chromium on first run (required on Streamlit Cloud)
# ---------------------------------------------------------------------------

@st.cache_resource
def ensure_playwright_browser():
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        st.warning(f"Playwright install warning: {result.stderr[:300]}")
    return True

ensure_playwright_browser()

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="RAS Tips Generator",
    page_icon="🏇",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    .nap-badge {
        background: #FFD700;
        color: #000;
        padding: 3px 12px;
        border-radius: 12px;
        font-weight: 700;
        font-size: 0.8em;
        letter-spacing: 0.05em;
    }
    .nb-badge {
        background: #A8A8A8;
        color: #fff;
        padding: 3px 12px;
        border-radius: 12px;
        font-weight: 700;
        font-size: 0.8em;
        letter-spacing: 0.05em;
    }
    .horse-name {
        font-weight: 600;
        font-size: 1.05em;
    }
    .race-label {
        color: #888;
        font-size: 0.9em;
        font-weight: 600;
    }
    .gap-label {
        color: #aaa;
        font-size: 0.85em;
    }
    .meeting-header {
        font-size: 1.4em;
        font-weight: 700;
        letter-spacing: 0.08em;
        margin-bottom: 0.2em;
    }
    div[data-testid="stHorizontalBlock"] {
        align-items: center;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("🏇 Racing & Sports Tips Generator")
st.caption(
    "Automatically finds today's thoroughbred meetings for your selected countries, "
    "scrapes every race, and generates NAP & NB selections."
)

st.divider()

# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

col_left, col_right = st.columns([3, 2])

with col_left:
    with st.expander("Step 1 — Launch Chrome with remote debugging", expanded=False):
        if sys.platform == "win32":
            st.markdown("Click the button below to launch Chrome with remote debugging:")
            if st.button("🚀 Launch Chrome"):
                subprocess.Popen(
                    [
                        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                        "--remote-debugging-port=9222",
                        r"--user-data-dir=C:\ChromeDebug",
                    ],
                    close_fds=True,
                )
                st.success("Chrome launched! If racingandsports.com.au shows a security check, complete it — then click Generate Tips.")
        else:
            st.markdown("On your Windows machine, run this command manually:")
            st.code(
                r'"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\ChromeDebug"',
                language="bash",
            )
        st.markdown(
            "A Chrome window will open. Visit [racingandsports.com.au](https://www.racingandsports.com.au) "
            "and pass the Cloudflare check once. Then come back here and click **Generate Tips**."
        )

with col_right:
    st.markdown("**Countries monitored**")
    st.markdown(
        "🇿🇦 South Africa &nbsp;·&nbsp; 🇮🇪 Ireland\n\n"
        "🇲🇾 Malaysia &nbsp;·&nbsp; 🇭🇰 Hong Kong\n\n"
        "🇲🇺 Mauritius &nbsp;·&nbsp; 🇫🇷 France\n\n"
        "🇯🇵 Japan &nbsp;·&nbsp; 🇦🇪 UAE &nbsp;·&nbsp; 🇸🇬 Singapore"
    )
    st.caption("All thoroughbred meetings for these countries are scraped automatically.")

st.divider()

# ---------------------------------------------------------------------------
# Mode selector
# ---------------------------------------------------------------------------

mode = st.radio(
    "Select mode",
    options=["Today's Tips", "Select Countries", "Add Racecard URLs"],
    horizontal=True,
    help="Today's Tips scrapes all countries. Select Countries lets you pick which ones. Add Racecard URLs lets you paste meeting links for a future date.",
)

COUNTRY_OPTIONS = {
    "South Africa": "south-africa",
    "Ireland": "ireland",
    "Malaysia": "malaysia",
    "Hong Kong": "hong-kong",
    "Mauritius": "mauritius",
    "France": "france",
    "Japan": "japan",
    "UAE": "united-arab-emirates",
    "Singapore": "singapore",
}

selected_countries = []
manual_urls = []

if mode == "Select Countries":
    st.markdown("Choose one or more countries to scrape today's meetings from:")
    chosen = st.multiselect(
        "Countries",
        options=list(COUNTRY_OPTIONS.keys()),
        default=list(COUNTRY_OPTIONS.keys()),
        label_visibility="collapsed",
    )
    selected_countries = [COUNTRY_OPTIONS[c] for c in chosen]

elif mode == "Add Racecard URLs":
    st.markdown(
        "Paste race meeting URLs below, one per line. "
        "Use this to generate tips for a future date (e.g. Sunday's card on a Friday)."
    )
    urls_input = st.text_area(
        "Meeting URLs",
        placeholder=(
            "https://www.racingandsports.com.au/form-guide/thoroughbred/ireland/leopardstown/2026-04-06\n"
            "https://www.racingandsports.com.au/form-guide/thoroughbred/hong-kong/sha-tin/2026-04-06"
        ),
        height=130,
        label_visibility="collapsed",
    )
    manual_urls = [u.strip() for u in (urls_input or "").splitlines() if u.strip()]

run_btn = st.button("▶  Generate Tips", type="primary")

# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

if run_btn:
    st.session_state.pop("meeting_results", None)
    all_results = {}
    _ok = True

    with st.status("Connecting to Chrome...", expanded=True) as status:
        try:
            with sync_playwright() as p:

                # ── Connect to Chrome ────────────────────────────────────────
                try:
                    browser = p.chromium.connect_over_cdp("http://localhost:9222")
                    context = browser.contexts[0] if browser.contexts else browser.new_context()
                    st.write("✅ Connected to Chrome.")
                except Exception as e:
                    status.update(label="Could not connect to Chrome.", state="error")
                    st.error(
                        "**Chrome not found on port 9222.**\n\n"
                        "Please use the **Launch Chrome** button in Step 1 above, "
                        "then visit racingandsports.com.au and pass the security check "
                        "before clicking Generate Tips.\n\n"
                        f"Detail: {e}"
                    )
                    _ok = False

                # ── Find meetings (auto or manual) ───────────────────────────
                if _ok:
                    if mode in ("Today's Tips", "Select Countries"):
                        if mode == "Select Countries" and not selected_countries:
                            status.update(label="No countries selected.", state="error")
                            st.error("Please select at least one country.")
                            _ok = False
                        else:
                            status.update(label="Finding today's meetings...")
                            countries_arg = selected_countries if mode == "Select Countries" else None
                            meetings = scraper.get_todays_race_urls(
                                context,
                                log_fn=lambda msg: st.write(msg),
                                countries=countries_arg,
                            )
                            if not meetings:
                                status.update(label="No meetings found for your countries today.", state="error")
                                st.warning("No thoroughbred meetings found today for the selected countries.")
                                _ok = False
                    else:
                        # Manual URL mode — validate input then build meeting list
                        if not manual_urls:
                            status.update(label="No URLs entered.", state="error")
                            st.error("Please paste at least one meeting URL in the box above.")
                            _ok = False
                        else:
                            meetings = [
                                (scraper.extract_track_name(u), [u])
                                for u in manual_urls
                            ]
                            st.write(f"Using {len(meetings)} manually entered meeting(s).")

                # ── Scrape each meeting ──────────────────────────────────────
                if _ok:
                    status.update(label=f"Scraping {len(meetings)} meeting(s)...")
                    for track_preview, race_urls in meetings:
                        st.write(f"**{track_preview}** — scraping...")
                        try:
                            if mode in ("Today's Tips", "Select Countries"):
                                # Race URLs already known — scrape directly
                                track, results, nap, nb = scraper.scrape_races_from_urls(
                                    track_preview,
                                    race_urls,
                                    context,
                                    log_fn=lambda msg: st.write(f"&nbsp;&nbsp;&nbsp;{msg}"),
                                )
                            else:
                                # Meeting URL provided — detect races then scrape
                                track, results, nap, nb = scraper.scrape_meeting_with_page(
                                    race_urls[0],
                                    context,
                                    log_fn=lambda msg: st.write(f"&nbsp;&nbsp;&nbsp;{msg}"),
                                )
                            all_results[track] = (results, nap, nb)
                            st.write(f"**{track}** done — {len(results)} races scraped.")
                        except Exception as e:
                            st.write(f"**{track_preview}** — error: {e}")

            if _ok:
                status.update(label="Done!", state="complete", expanded=False)
                st.session_state["meeting_results"] = all_results

        except Exception as e:
            status.update(label=f"Error: {e}", state="error")
            st.error(str(e))

# ---------------------------------------------------------------------------
# Results display
# ---------------------------------------------------------------------------

if st.session_state.get("meeting_results"):
    st.divider()

    wordpress_lines = []   # clean — for copy-pasting into WordPress
    file_lines      = []   # with (NAP)/(NB) — for the saved text file
    email_lines     = []   # HTML bold — for the email

    for track, (results, nap, nb) in st.session_state["meeting_results"].items():
        st.markdown(f'<div class="meeting-header">🏟 {track}</div>', unsafe_allow_html=True)

        # Column headers
        h1, h2, h3, h4 = st.columns([1, 5, 2, 2])
        h1.markdown("<span style='color:#aaa;font-size:0.8em'>RACE</span>", unsafe_allow_html=True)
        h2.markdown("<span style='color:#aaa;font-size:0.8em'>SELECTION</span>", unsafe_allow_html=True)
        h3.markdown("<span style='color:#aaa;font-size:0.8em'>GAP</span>", unsafe_allow_html=True)
        h4.markdown("<span style='color:#aaa;font-size:0.8em'>TIP</span>", unsafe_allow_html=True)

        wordpress_lines.append(f"**{track}**")
        file_lines.append(f"**{track}**")
        email_lines.append(f"<b>{track}</b>")

        for r, selected, gap in results:
            c1, c2, c3, c4 = st.columns([1, 5, 2, 2])

            c1.markdown(
                f'<span class="race-label">R{r}</span>',
                unsafe_allow_html=True,
            )

            if selected:
                c2.markdown(
                    f'<span class="horse-name">{selected["name"]}</span>',
                    unsafe_allow_html=True,
                )
                c3.markdown(
                    f'<span class="gap-label">{gap} pts</span>',
                    unsafe_allow_html=True,
                )
                if r == nap:
                    c4.markdown('<span class="nap-badge">NAP</span>', unsafe_allow_html=True)
                elif r == nb:
                    c4.markdown('<span class="nb-badge">NB</span>', unsafe_allow_html=True)

                suffix = " (NAP)" if r == nap else " (NB)" if r == nb else ""
                if r == nap or r == nb:
                    wordpress_lines.append(f"**R{r} {selected['name']}**")
                    file_lines.append(f"**R{r} {selected['name']}{suffix}**")
                    email_lines.append(f"<b>R{r} {selected['name']}{suffix}</b>")
                else:
                    wordpress_lines.append(f"R{r} {selected['name']}")
                    file_lines.append(f"R{r} {selected['name']}{suffix}")
                    email_lines.append(f"R{r} {selected['name']}{suffix}")
            else:
                c2.markdown('<span style="color:#ccc">—</span>', unsafe_allow_html=True)
                wordpress_lines.append(f"R{r} -")
                file_lines.append(f"R{r} -")
                email_lines.append(f"R{r} -")

        wordpress_lines.append("")
        file_lines.append("")
        email_lines.append("")
        st.markdown("<br>", unsafe_allow_html=True)

    # Copy-paste output (clean, for WordPress)
    st.divider()
    st.markdown("**Copy-paste version**")
    output_text = "\n".join(wordpress_lines).strip()
    st.code(output_text, language=None)

    # Auto-save to a dated text file (with NAP/NB labels)
    today = datetime.date.today().strftime("%Y-%m-%d")
    file_text = "\n".join(file_lines).strip()
    save_path = os.path.join(os.path.dirname(__file__), f"tips_{today}.txt")
    try:
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(f"RAS Tips — {today}\n")
            f.write("=" * 40 + "\n\n")
            f.write(file_text)
        st.success(f"Tips saved to: tips_{today}.txt")
    except Exception as e:
        st.warning(f"Could not save tips file: {e}")

    # Auto-email the tips
    try:
        app_password = st.secrets.get("GMAIL_APP_PASSWORD", "")
        email_from   = st.secrets.get("EMAIL_FROM", "")
        email_to     = st.secrets.get("EMAIL_TO", "")

        if app_password and app_password != "your-app-password-here" and email_from and email_to:
            email_text = "\n".join(email_lines).strip()
            email_html = f"<html><body><h3>RAS Tips — {today}</h3>{'<br>'.join(email_lines).strip()}</body></html>"

            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"RAS Tips — {today}"
            msg["From"]    = email_from
            msg["To"]      = email_to
            msg.attach(MIMEText(email_text, "plain"))
            msg.attach(MIMEText(email_html, "html"))

            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(email_from, app_password)
                server.sendmail(email_from, email_to.split(","), msg.as_string())

            st.success(f"Tips emailed to {email_to} ✉️")
    except Exception as e:
        st.warning(f"Could not send email: {e}")
