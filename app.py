import subprocess
import sys

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
    "Paste today's race meeting overview URLs below (one per line). "
    "A browser will open once — solve the Cloudflare check if prompted, "
    "then all races across all meetings are scraped automatically."
)

st.divider()

# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

col_input, col_example = st.columns([3, 2])

with col_input:
    urls_input = st.text_area(
        "Meeting URLs",
        placeholder=(
            "https://www.racingandsports.com.au/form-guide/thoroughbred/hong-kong/sha-tin/2026-03-22\n"
            "https://www.racingandsports.com.au/form-guide/thoroughbred/australia/randwick/2026-03-22"
        ),
        height=120,
        key="urls_input",
        label_visibility="collapsed",
    )

with col_example:
    st.markdown("**How it works**")
    st.markdown(
        "- Launch Chrome with the command below\n"
        "- Paste meeting URLs and click Generate\n"
        "- App connects to your real Chrome\n"
        "- **NAP** = biggest points gap\n"
        "- **NB** = second biggest gap\n"
        "- Gap < 4 pts → 2nd rated horse selected"
    )
    with st.expander("Step 1 — Launch Chrome with remote debugging"):
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
                st.success("Chrome launched! Visit racingandsports.com.au, pass the Cloudflare check, then click Generate Tips.")
        else:
            st.markdown("**Run this app locally on Windows** to use the Launch Chrome button.")
            st.markdown("On your Windows machine, run this command manually:")
            st.code(
                r'"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\ChromeDebug"',
                language="bash",
            )
        st.markdown(
            "A Chrome window will open. Visit [racingandsports.com.au](https://www.racingandsports.com.au) "
            "and pass the Cloudflare check once. Then come back here and click **Generate Tips**."
        )

run_btn = st.button("▶  Generate Tips", type="primary")

# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

if run_btn:
    urls = [u.strip() for u in (urls_input or "").splitlines() if u.strip()]
    if not urls:
        st.warning("Please enter at least one meeting URL.")
    else:
        st.session_state.pop("meeting_results", None)
        all_results = {}

        with st.status("Connecting to Chrome...", expanded=True) as status:
            try:
                with sync_playwright() as p:
                    try:
                        # Connect to the user's real Chrome (launched with --remote-debugging-port=9222)
                        browser = p.chromium.connect_over_cdp("http://localhost:9222")
                        context = browser.contexts[0] if browser.contexts else browser.new_context()
                        st.write("Connected to Chrome.")
                    except Exception as e:
                        status.update(
                            label="Could not connect to Chrome. Did you launch it with --remote-debugging-port=9222?",
                            state="error",
                        )
                        st.error(
                            "Chrome not found on port 9222. "
                            "Please close Chrome and relaunch it using the command in 'Step 1' above."
                        )
                        st.stop()

                    for url in urls:
                        track_preview = scraper.extract_track_name(url)
                        st.write(f"**{track_preview}** — loading overview...")
                        try:
                            track, results, nap, nb = scraper.scrape_meeting_with_page(
                                url,
                                context,
                                log_fn=lambda msg: st.write(f"&nbsp;&nbsp;&nbsp;{msg}"),
                            )
                            all_results[track] = (results, nap, nb)
                            st.write(f"**{track}** done — {len(results)} races scraped.")
                        except Exception as e:
                            st.write(f"**{track_preview}** — error: {e}")

                status.update(label="Done!", state="complete", expanded=False)
                st.session_state["meeting_results"] = all_results

            except Exception as e:
                status.update(label=f"Error: {e}", state="error")

# ---------------------------------------------------------------------------
# Results display
# ---------------------------------------------------------------------------

if st.session_state.get("meeting_results"):
    st.divider()

    all_text_lines = []

    for track, (results, nap, nb) in st.session_state["meeting_results"].items():
        st.markdown(f'<div class="meeting-header">🏟 {track}</div>', unsafe_allow_html=True)

        # Column headers
        h1, h2, h3, h4 = st.columns([1, 5, 2, 2])
        h1.markdown("<span style='color:#aaa;font-size:0.8em'>RACE</span>", unsafe_allow_html=True)
        h2.markdown("<span style='color:#aaa;font-size:0.8em'>SELECTION</span>", unsafe_allow_html=True)
        h3.markdown("<span style='color:#aaa;font-size:0.8em'>GAP</span>", unsafe_allow_html=True)
        h4.markdown("<span style='color:#aaa;font-size:0.8em'>TIP</span>", unsafe_allow_html=True)

        all_text_lines.append(track)

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
                all_text_lines.append(f"R{r} {selected['name']}{suffix}")
            else:
                c2.markdown('<span style="color:#ccc">—</span>', unsafe_allow_html=True)
                all_text_lines.append(f"R{r} -")

        all_text_lines.append("")
        st.markdown("<br>", unsafe_allow_html=True)

    # Copy-paste output
    st.divider()
    st.markdown("**Copy-paste version**")
    st.code("\n".join(all_text_lines).strip(), language=None)
