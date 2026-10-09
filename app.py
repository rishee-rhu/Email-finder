"""
Cold Email Engine
Dossier-driven cold outreach: keys -> dossier -> Gmail -> target -> find ->
verify -> research -> review -> send. Powered by OpenAI + Apify only.
"""
import json
import time
import pandas as pd
import streamlit as st
from datetime import datetime
from pathlib import Path

import db
import gmail
import gmail_oauth
import email_gen
import lead_finder
import scheduler
import key_tester
import target_profiler
import email_verifier
import spam_check
import local_finder
import ui

db.init()

PROVIDER = "openai"   # this build is OpenAI + Apify only


# ════════════════════════════════════════════════════════════════════════════
# helpers
# ════════════════════════════════════════════════════════════════════════════

def _read_dossier_file(uploaded):
    if uploaded.name.endswith(".txt"):
        return uploaded.read().decode("utf-8", errors="ignore")
    if uploaded.name.endswith(".pdf"):
        try:
            import PyPDF2, io
            reader = PyPDF2.PdfReader(io.BytesIO(uploaded.read()))
            return "\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception:
            st.warning("Could not read PDF — paste the text instead.")
    return ""


def _send_email(to, subject, body):
    """Send via OAuth if connected, else App Password."""
    if gmail_oauth.is_connected():
        gmail_oauth.send(to, subject, body)
    else:
        gmail.send(db.get("gmail_address", ""), db.get("gmail_password", ""),
                   to, subject, body)


def _gmail_ready():
    return gmail_oauth.is_connected() or bool(db.get("gmail_address"))


# ════════════════════════════════════════════════════════════════════════════
# ONBOARDING  (Step 1 keys -> Step 2 dossier -> Step 3 Gmail)
# ════════════════════════════════════════════════════════════════════════════

def _run_onboarding():
    st.set_page_config(page_title="Cold Email Engine — Setup", page_icon="✉️",
                       layout="centered")
    ui.inject_css()

    # What's actually complete (drives green pills + which screen to resume on)
    keys_ok    = bool(db.get("ai_key") and db.get("apify_key"))
    dossier_ok = bool((db.get("dossier") or "").strip()) or \
                 bool(st.session_state.get("ob_dossier", "").strip())
    gmail_ok   = _gmail_ready()
    done = {1: keys_ok, 2: dossier_ok, 3: gmail_ok}

    # Resume at the first unfinished step (don't re-show screens already done)
    if "onboarding_step" not in st.session_state:
        st.session_state.onboarding_step = 1 if not keys_ok else (2 if not dossier_ok else 3)
    step = st.session_state.onboarding_step

    ui.page_header("Set up your outreach", "Three quick steps, then you're ready to send.",
                   eyebrow="Cold Email Engine")
    ui.stepper([("API keys", "OpenAI + Apify", done[1]),
                ("Your dossier", "Who you are, what you sell", done[2]),
                ("Connect Gmail", "Send from your address", done[3])], step)

    # ── STEP 1: KEYS ─────────────────────────────────────────────────────────
    if step == 1:
        ui.hero("Welcome", "Two keys power everything: <b>OpenAI</b> writes and researches "
                "the emails, <b>Apify</b> finds the brands and their addresses.")
        with st.form("ob_keys"):
            ai_key = st.text_input("OpenAI API Key", value=db.get("ai_key", ""),
                                   type="password",
                                   help="platform.openai.com → API keys")
            apify_key = st.text_input("Apify API Key", value=db.get("apify_key", ""),
                                      type="password",
                                      help="apify.com → Settings → API tokens")
            go = st.form_submit_button("Test & Continue", type="primary",
                                       use_container_width=True)
        if go:
            if not ai_key or not apify_key:
                st.error("Both keys are required for this build.")
            else:
                db.put("ai_provider", PROVIDER)
                db.put("ai_key", ai_key)
                db.put("apify_key", apify_key)
                with st.spinner("Testing keys…"):
                    r_ai    = key_tester.test_openai(ai_key)
                    r_apify = key_tester.test_apify(apify_key)
                for name, r in (("OpenAI", r_ai), ("Apify", r_apify)):
                    (st.success if r["ok"] else st.error)(f"{name}: {r['message']}")
                if r_ai["ok"] and r_apify["ok"]:
                    st.success("Both keys verified.")
                    st.session_state.onboarding_step = 2
                    time.sleep(1.0)
                    st.rerun()
                else:
                    st.error("Fix the failing key above and try again.")

    # ── STEP 2: DOSSIER ──────────────────────────────────────────────────────
    elif step == 2:
        ui.hero("Your dossier", "Upload the document that describes who you are and what you "
                "offer. The AI reads it to decide <b>who to email</b> and to <b>write</b> each message.")

        uploaded = st.file_uploader("Upload your dossier (.txt or .pdf)", type=["txt", "pdf"])
        if uploaded:
            txt = _read_dossier_file(uploaded)
            if txt.strip():
                st.session_state.ob_dossier = txt
                st.success(f"Loaded: {uploaded.name} ({len(txt):,} characters). You're set.")
            else:
                st.error("Couldn't read text from that file — try a .txt, or paste below.")

        with st.expander("No file? Paste your dossier text instead"):
            pasted = st.text_area("Paste dossier", value="", height=200,
                                  placeholder="Paste your offer / background here…")
            if pasted.strip():
                st.session_state.ob_dossier = pasted

        sender_name = st.text_input("Your name (email sign-off)",
                                    value=db.get("sender_name", "") or "")

        has_dossier = bool(st.session_state.get("ob_dossier", "").strip())
        if has_dossier:
            st.caption("Dossier ready — it won't be shown back to you. Click continue.")
        if st.button("Save & Continue", type="primary", use_container_width=True,
                     disabled=not has_dossier):
            if len(st.session_state.get("ob_dossier", "").strip()) < 50:
                st.error("Dossier is too short — add more about your offer.")
            elif not sender_name.strip():
                st.error("Enter your name for the email sign-off.")
            else:
                db.put("dossier", st.session_state.ob_dossier)
                db.put("sender_name", sender_name)
                st.session_state.pop("ob_dossier", None)
                st.session_state.onboarding_step = 3
                st.rerun()

    # ── STEP 3: GMAIL ────────────────────────────────────────────────────────
    elif step == 3:
        ui.hero("Connect Gmail", "Link Gmail so the app can send from your address.")

        if _gmail_ready():
            who = gmail_oauth.connected_email() if gmail_oauth.is_connected() \
                  else db.get("gmail_address")
            st.success(f"Gmail connected: {who}")
            if st.button("Finish Setup — Open the App", type="primary",
                         use_container_width=True):
                db.put("onboarding_complete", "1")
                if gmail_oauth.is_connected():
                    db.put("gmail_address", gmail_oauth.connected_email() or "")
                del st.session_state["onboarding_step"]
                st.rerun()
        else:
            st.markdown("""
**Connect with an App Password — no files, no Google Cloud.**

An App Password is a **16-character code Google gives you** — it is *different from your
normal Gmail password* and is made specifically for apps like this.

1. Turn on **2-Step Verification**: [myaccount.google.com/security](https://myaccount.google.com/security)
2. Open **App Passwords**: [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Type a name (e.g. "Cold Email Engine") → **Create** → copy the 16-character code
4. Paste your Gmail address and that code below
""")
            with st.form("ob_pw"):
                gaddr = st.text_input("Your Gmail address", value=db.get("gmail_address", ""))
                gpass = st.text_input("16-character App Password", type="password",
                                      help="NOT your normal Gmail password — the code from step 3 above")
                if st.form_submit_button("Connect Gmail", type="primary",
                                         use_container_width=True):
                    if gmail.test_credentials(gaddr, gpass):
                        db.put("gmail_address", gaddr)
                        db.put("gmail_password", gpass)
                        st.success("Gmail connected.")
                        st.rerun()
                    else:
                        st.error("Login failed. Make sure 2-Step Verification is ON and you "
                                 "pasted the 16-character App Password (not your normal password).")

            with st.expander("Advanced: use Google's account-picker (one-time file setup)"):
                creds_exists = (Path(__file__).parent / "gmail_credentials.json").exists()
                st.caption("This gives the 'pick your Google account' screen, but needs a "
                           "one-time gmail_credentials.json from Google Cloud Console.")
                if creds_exists:
                    st.success("gmail_credentials.json found.")
                    if st.button("Connect via Google account-picker", use_container_width=True):
                        with st.spinner("Opening browser for Google…"):
                            addr, err = gmail_oauth.run_oauth_flow()
                        st.error(f"Auth failed: {err}") if err else st.success(f"Connected as {addr}")
                        if not err:
                            st.rerun()
                else:
                    st.info("Drop gmail_credentials.json in the app folder to enable this.")

    st.stop()


if not db.get("onboarding_complete"):
    _run_onboarding()


# ════════════════════════════════════════════════════════════════════════════
# MAIN APP
# ════════════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="Cold Email Engine", page_icon="✉️", layout="wide",
                   initial_sidebar_state="expanded")
ui.inject_css()

# Auto-sync replies/follow-ups once per session
if "synced_on_load" not in st.session_state:
    st.session_state.synced_on_load = True
    if _gmail_ready():
        try:
            log = []
            scheduler.run(log=lambda m: log.append(m))
            st.session_state.last_sync_time = datetime.now().strftime("%H:%M:%S")
        except Exception:
            pass

NAV = {"Campaign": "✉️  Campaign", "Dashboard": "📊  Dashboard",
       "All Leads": "👥  All leads", "Replies": "💬  Replies", "Settings": "⚙️  Settings"}

with st.sidebar:
    ui.sidebar_brand(db.get("sender_name", ""))
    st.divider()
    page = st.radio("Go to", list(NAV), format_func=NAV.get,
                    label_visibility="collapsed")
    st.divider()
    s = db.stats()
    m1, m2 = st.columns(2)
    m1.metric("Sent today", db.today_stats().get("total", 0))
    m2.metric("Replies", s.get("replied", 0))
    st.metric("Active sequences", s.get("active", 0))
    if gmail_oauth.is_connected():
        ui.sidebar_status(gmail_oauth.connected_email() or "Gmail connected", on=True)
    elif db.get("gmail_address"):
        ui.sidebar_status(db.get("gmail_address"), on=True)
    else:
        ui.sidebar_status("Gmail not connected", on=False)
    st.write("")
    if st.button("↻  Sync replies & follow-ups", use_container_width=True):
        with st.spinner("Syncing…"):
            r = scheduler.run()
        st.success(f"{len(r['replies'])} replies, {len(r['sent'])} follow-ups sent")
    if st.session_state.get("last_sync_time"):
        st.caption(f"Last synced {st.session_state.last_sync_time}")


# ════════════════════════════════════════════════════════════════════════════
# CAMPAIGN  — the 6-step linear flow
# ════════════════════════════════════════════════════════════════════════════

if page == "Campaign":

    ai_key    = db.get("ai_key", "")
    apify_key = db.get("apify_key", "")
    dossier   = db.get("dossier", email_gen.DEFAULT_DOSSIER)
    sender    = db.get("sender_name", "")

    # ── Restore saved campaign whenever the session has no live data.
    #    Runs on every Campaign visit, so progress reappears after a page switch
    #    OR a server restart — paid-for API work is never lost. ─────────────────
    if "camp_verified" not in st.session_state:
        saved = db.load_campaign()
        if saved:
            st.session_state.camp_verified = saved.get("verified", [])
            st.session_state.camp_audits = saved.get("audits", {})
            drafts = saved.get("drafts", [])
            for d in drafts:                      # JSON turns int keys to str — fix
                if isinstance(d.get("_seq"), dict):
                    d["_seq"] = {int(k): v for k, v in d["_seq"].items()}
            st.session_state.camp_drafts = drafts
            st.session_state.camp_profile = saved.get("profile")
            st.session_state.camp_verify_results = saved.get("verify_results", {})
            st.session_state.camp_found_count = saved.get("found_count", 0)

    def _persist_campaign():
        db.save_campaign({
            "verified": st.session_state.get("camp_verified", []),
            "audits": st.session_state.get("camp_audits", {}),
            "drafts": st.session_state.get("camp_drafts", []),
            "profile": st.session_state.get("camp_profile"),
            "verify_results": st.session_state.get("camp_verify_results", {}),
            "found_count": st.session_state.get("camp_found_count", 0),
        })

    _v = st.session_state.get("camp_verified", [])
    _d = st.session_state.get("camp_drafts", [])
    _a = [d for d in _d if d["_approved"] and not d["_skip"]]
    hc1, hc2 = st.columns([3, 1])
    with hc1:
        ui.page_header("New campaign", "Find small businesses, write the sequence, review, send.",
                       eyebrow="Outreach")
    _active = 4 if _a else (3 if _d else (2 if _v else 1))
    ui.stepper([("Find", f"{len(_v)} leads" if _v else "Small businesses", bool(_v)),
                ("Write", f"{len(_d)} sequences" if _d else "AI drafts", bool(_d)),
                ("Review", f"{len(_a)} approved" if _d else "Edit & approve", bool(_a)),
                ("Send", f"limit {db.warmup_daily_limit()}/day", False)], _active)
    if _v:
        if hc2.button("Start new campaign", use_container_width=True,
                      help="Clears saved progress for this campaign"):
            for k in ("camp_verified", "camp_audits", "camp_drafts",
                      "camp_verify_results", "camp_found_count"):
                st.session_state.pop(k, None)
            db.clear_campaign()
            st.rerun()

    # Silently build (or reuse) the target profile from the dossier — no button.
    def _get_profile():
        prof = st.session_state.get("camp_profile")
        if prof:
            return prof
        if db.get("icp_json"):
            try:
                prof = json.loads(db.get("icp_json"))
                st.session_state.camp_profile = prof
                return prof
            except Exception:
                pass
        prof = target_profiler.build_profile(dossier, PROVIDER, ai_key)
        st.session_state.camp_profile = prof
        db.put("icp_json", json.dumps(prof))
        return prof

    with st.container(border=True):
        ui.step_head(1, "Find leads",
                     "Reads your dossier, works out who to target, and finds small "
                     "businesses with a real email.", done=bool(_v))
        SRC_MAPS, SRC_WEB, SRC_BOTH = ("Local small businesses (Google Maps)",
                                       "Online brands (web search, founders only)", "Both")
        source = st.radio("Where to look", [SRC_MAPS, SRC_WEB, SRC_BOTH], horizontal=True,
                          help="Maps finds owner-run local businesses a new freelancer can "
                               "actually win. Web search finds online brands and their founders.")
        target_n = st.number_input("How many leads to find", min_value=1,
                                   max_value=500, value=20, step=5)
        target_n = int(target_n)

        use_maps = source in (SRC_MAPS, SRC_BOTH)
        if use_maps:
            _cached = st.session_state.get("camp_profile") or {}
            mc1, mc2, mc3 = st.columns([3, 1, 1])
            cities_txt = mc1.text_input(
                "Cities (separate with ;)",
                value="; ".join(_cached.get("cities") or ["Mumbai, India"]),
                help="Your own city first. Each city is one Google Maps run.")
            max_reviews = mc2.number_input(
                "Max Google reviews", min_value=10, max_value=5000, value=300, step=50,
                help="Lower = smaller businesses. Big chains have thousands.")
            per_query = mc3.number_input("Places per search", min_value=5, max_value=100,
                                         value=20, step=5)
            cities = [c.strip() for c in cities_txt.split(";") if c.strip()]
            n_terms = len(_cached.get("maps_queries") or []) or 5
            est = len(cities) * n_terms * int(per_query) * local_finder.COST_PER_PLACE
            st.caption(f"Google Maps cost: about ${est:.2f} in Apify credit "
                       f"({len(cities)} cities × {n_terms} searches × {int(per_query)} places).")

        if st.button(f"Find {target_n} emails", type="primary"):
            if not apify_key:
                st.error("Apify key missing — add it in Settings.")
            else:
                with st.spinner("Analysing your dossier to work out who to target…"):
                    profile = _get_profile()
                region = profile.get("ideal_customer", {}).get("region", "India")
                rl = region.lower()
                market = "USA" if ("usa" in rl or "united states" in rl) else \
                         ("UK" if ("uk" in rl or "united kingdom" in rl) else "India")

                prog = st.progress(0)
                status = st.empty()
                runlog = []

                def on_prog(msg, n):
                    status.info(msg)
                    runlog.append(msg)
                    if target_n:
                        prog.progress(min(int((n or 0) / target_n * 100), 99))

                # Over-fetch so that AFTER verification we still have target_n good ones
                oversample = int(target_n * 1.6) + 5
                found = []
                with st.spinner("Finding businesses and emails…"):
                    if use_maps:
                        if not profile.get("maps_queries"):      # profile built by an older version
                            db.put("icp_json", "")
                            st.session_state.pop("camp_profile", None)
                            profile = _get_profile()
                        found += local_finder.find_local_leads(
                            apify_key, ai_key, profile, cities or ["Mumbai, India"],
                            target=oversample, per_query=int(per_query),
                            max_reviews=int(max_reviews), market=market,
                            on_progress=on_prog)
                    if source in (SRC_WEB, SRC_BOTH):
                        # Web discovery from the dossier's queries, then strict founder validation
                        brand_candidates = lead_finder.find_domains_via_google(
                            apify_key, profile.get("search_queries", []),
                            max_domains=min(oversample * 6, 150))
                        runlog.append(f"Discovery: {len(brand_candidates)} company domains from search.")
                        found += lead_finder.find_founder_leads(
                            apify_key=apify_key,
                            candidates=brand_candidates,
                            target=oversample,
                            market=market,
                            on_progress=on_prog,
                        )
                    _seen = set()
                    found = [l for l in found
                             if l["email"] not in _seen and not _seen.add(l["email"])]
                st.session_state.camp_runlog = runlog

                # Verify internally, automatically — only genuine emails move forward
                verified_all, results = [], {}
                if found:
                    status.info("Verifying emails (format + domain mail server)…")
                    emails = [l["email"] for l in found]
                    valid, results = email_verifier.verify_batch(emails)
                    valid_set = set(valid)
                    verified_all = [l for l in found if l["email"] in valid_set]
                verified = verified_all[:target_n]      # exactly what you asked for
                prog.progress(100)

                st.session_state.camp_found_count = len(found)
                st.session_state.camp_verified = verified
                st.session_state.camp_verify_results = results
                for k in ("camp_audits", "camp_drafts"):
                    st.session_state.pop(k, None)
                _persist_campaign()

                if len(verified) >= target_n:
                    st.success(f"Got your {target_n} verified emails "
                               f"(checked {len(found)} brands, kept the {target_n} that passed).")
                elif verified:
                    st.warning(f"Only {len(verified)} verified emails available right now "
                               f"(you asked for {target_n}; checked {len(found)} brands). "
                               "Run Find again or raise the count to gather more.")
                else:
                    st.error("No leads found this run.")
                    with st.expander("Run details (what happened at each stage)", expanded=True):
                        for line in runlog:
                            st.text(line)
                        st.caption("Reading this: if 'company domains' is 0 → search/Apify "
                                   "issue. If domains found but 0 founders → LinkedIn lookup "
                                   "didn't match. If founders found but 0 verified → the SMTP "
                                   "verifier actor or published emails came up empty.")

        # Make the profile available to later steps (e.g. the audit) if already built
        profile = st.session_state.get("camp_profile")
        if not profile and db.get("icp_json"):
            try:
                profile = json.loads(db.get("icp_json"))
                st.session_state.camp_profile = profile
            except Exception:
                profile = None

        verified = st.session_state.get("camp_verified", [])
        if verified:
            QUALITY = {"founder_real": "Founder, published", "founder_verified": "Founder, verified guess",
                       "owner": "Owner, published", "owner_gmail": "Owner Gmail, published",
                       "business_inbox": "Business inbox, published"}
            n_pub = sum(1 for l in verified if l.get("email_quality") != "founder_verified")
            st.caption(f"{len(verified)} leads ready · {n_pub} emails published on their own "
                       f"site, {len(verified) - n_pub} verified guesses.")
            st.dataframe(pd.DataFrame([{
                "Business": l["brand_name"],
                "Contact": l.get("contact_name") or "—",
                "Email": l["email"],
                "Email type": QUALITY.get(l.get("email_quality"), l.get("email_quality", "")),
                "Reviews": l.get("reviews", "—"),
                "City": (l.get("city") or "—").split(",")[0],
                "Phone": l.get("phone") or "—",
                "Why it fits": l.get("fit_reason") or "—",
                "Website": l.get("website", ""),
            } for l in verified]), use_container_width=True, hide_index=True,
                column_config={"Website": st.column_config.LinkColumn("Website")})

            # show what got dropped, for transparency
            results = st.session_state.get("camp_verify_results", {})
            bad = [(e, r) for e, r in results.items() if not r["valid"]]
            if bad:
                with st.expander(f"{len(bad)} addresses dropped during verification"):
                    for e, r in bad[:60]:
                        st.text(f"{e} — {r['reason']}")

    with st.container(border=True):
        ui.step_head(2, "Write emails",
                     "One personalised 5-email sequence per founder, spam-checked.",
                     done=bool(_d))

        st.caption("Tip: each email is saved the moment it's written, so even if you "
                   "navigate away mid-run, finished ones are kept.")
        if st.button("Write emails", type="primary", disabled=not verified):
            prog = st.progress(0)
            status = st.empty()
            # Write into session_state directly + persist after EACH brand, so partial
            # progress survives a page switch / interruption.
            st.session_state.camp_drafts = []
            for i, lead in enumerate(verified):
                status.info(f"Writing {lead['brand_name']} ({i+1}/{len(verified)})…")
                try:
                    seq = email_gen.generate_sequence(
                        lead, dossier, PROVIDER, ai_key, sender,
                        signals=lead.get("signals", {}))
                    st.session_state.camp_drafts.append(
                        {"_lead": lead, "_seq": seq, "_approved": False, "_skip": False})
                    _persist_campaign()          # save after every single brand
                except Exception as e:
                    st.warning(f"Skipped {lead['brand_name']}: {e}")
                prog.progress(int((i + 1) / len(verified) * 100))
            prog.progress(100)
            status.success(f"Wrote {len(st.session_state.camp_drafts)} email sequences.")
            _persist_campaign()

    with st.container(border=True):
        ui.step_head(3, "Review drafts",
                     "Edit, approve or skip each sequence before anything is sent.")
        drafts = st.session_state.get("camp_drafts", [])
        if not drafts:
            st.info("Drafts will appear here after step 2 (Write emails).")
        else:
            # bulk approve
            bc1, bc2 = st.columns([1, 3])
            if bc1.button("Approve all"):
                for d in st.session_state.camp_drafts:
                    if not d["_skip"]:
                        d["_approved"] = True
                _persist_campaign()
                st.rerun()

            for idx, d in enumerate(drafts):
                lead = d["_lead"]
                e1 = d["_seq"].get(1, {})
                score = e1.get("spam_score", 10)
                badge = (":green[● Approved]" if d["_approved"] else
                         (":red[○ Skipped]" if d["_skip"] else ":orange[○ Draft]"))
                with st.expander(
                    f"{badge}  **{lead['brand_name']}** · {lead['email']} · "
                    f"{lead.get('category','')} · spam-safety {score}/10",
                    expanded=False,
                ):
                    sig = d["_lead"].get("signals", {})
                    if sig.get("social"):
                        st.caption("Personalised from: " + ", ".join(sig["social"].keys()) +
                                   (" · has blog" if sig.get("hasBlog") else ""))
                    new_subj = st.text_input("Subject", e1.get("subject", ""), key=f"s_{idx}")
                    new_body = st.text_area("Email 1 body", e1.get("body", ""),
                                            height=260, key=f"b_{idx}")
                    st.session_state.camp_drafts[idx]["_seq"][1]["subject"] = new_subj
                    st.session_state.camp_drafts[idx]["_seq"][1]["body"] = new_body

                    if e1.get("spam_issues"):
                        st.warning("Spam flags: " +
                                   ", ".join(i["found"] for i in e1["spam_issues"][:6]))

                    st.caption("Follow-ups (Emails 2–5)")
                    for step, tab in zip(range(2, 6), st.tabs([f"Email {n}" for n in range(2, 6)])):
                        em = d["_seq"].get(step, {})
                        tab.markdown(f"**{em.get('subject','')}**")
                        tab.text(em.get("body", ""))

                    a1, a2 = st.columns(2)
                    if a1.button("Approve", key=f"ap_{idx}"):
                        st.session_state.camp_drafts[idx]["_approved"] = True
                        st.session_state.camp_drafts[idx]["_skip"] = False
                        _persist_campaign()
                        st.rerun()
                    if a2.button("Skip", key=f"sk_{idx}"):
                        st.session_state.camp_drafts[idx]["_skip"] = True
                        st.session_state.camp_drafts[idx]["_approved"] = False
                        _persist_campaign()
                        st.rerun()

            approved = [d for d in drafts if d["_approved"] and not d["_skip"]]
            st.progress(len(approved) / max(len(drafts), 1),
                        text=f"{len(approved)} of {len(drafts)} approved")

    with st.container(border=True):
        ui.step_head(4, "Send",
                     "Email 1 goes out now; follow-ups 2–5 schedule themselves.")
        ready = [d for d in st.session_state.get("camp_drafts", [])
                 if d["_approved"] and not d["_skip"]]
        delay = st.slider("Delay between sends (seconds)", 3, 30, 6,
                          help="Spacing out sends protects Gmail deliverability")
        limit = db.warmup_daily_limit()
        if len(ready) > limit:
            st.warning(f"Gmail warmup limit today is {limit}/day. Only the first {limit} "
                       f"approved emails will send; the rest stay as drafts.")

        if st.button(f"Send {min(len(ready), limit)} emails now", type="primary",
                     disabled=not ready or not _gmail_ready()):
            if not _gmail_ready():
                st.error("Connect Gmail first (Settings).")
            else:
                prog = st.progress(0)
                status = st.empty()
                sent, errors = 0, []
                batch = ready[:limit]
                for i, d in enumerate(batch):
                    lead = d["_lead"]
                    seq  = d["_seq"]
                    e1   = seq.get(1, {})
                    try:
                        lead_id = db.upsert_lead(
                            brand_name=lead.get("brand_name", "Unknown"),
                            email=lead["email"], website=lead.get("website", ""),
                            category=lead.get("category", "D2C"),
                            emails_json=json.dumps({str(k): v for k, v in seq.items()}),
                            market=lead.get("market", "India"), source=lead.get("source", ""))
                        if lead_id:
                            _send_email(lead["email"], e1["subject"], e1["body"])
                            db.mark_sent(lead_id, 1, e1["subject"], e1["body"])
                            sent += 1
                    except Exception as e:
                        errors.append(f"{lead.get('brand_name')}: {e}")
                    prog.progress(int((i + 1) / len(batch) * 100))
                    status.info(f"Sent {sent}/{len(batch)}…")
                    time.sleep(delay)
                prog.progress(100)
                status.success(f"Sent {sent} emails. Follow-ups 2–5 are now scheduled automatically.")
                if errors:
                    with st.expander(f"{len(errors)} errors"):
                        for e in errors:
                            st.text(e)
                for k in ("camp_found", "camp_verified", "camp_audits", "camp_drafts",
                          "camp_verify_results", "camp_found_count"):
                    st.session_state.pop(k, None)
                db.clear_campaign()



# ════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ════════════════════════════════════════════════════════════════════════════

elif page == "Dashboard":
    ui.page_header("Dashboard", "How your outreach is performing.", eyebrow="Overview")

    from datetime import date, timedelta as _td

    s = db.stats()
    limit = db.warmup_daily_limit()

    # ── Timeframe selector ────────────────────────────────────────────────────
    tcol1, tcol2 = st.columns([2, 3])
    with tcol1:
        preset = st.selectbox("Timeframe",
                              ["Today", "Yesterday", "Last 7 days", "Last 30 days", "Custom"])
    today_d = date.today()
    if preset == "Today":
        start_d = end_d = today_d
    elif preset == "Yesterday":
        start_d = end_d = today_d - _td(days=1)
    elif preset == "Last 7 days":
        start_d, end_d = today_d - _td(days=6), today_d
    elif preset == "Last 30 days":
        start_d, end_d = today_d - _td(days=29), today_d
    else:  # Custom
        with tcol2:
            rng = st.date_input("Pick a date range",
                                value=(today_d - _td(days=7), today_d))
            if isinstance(rng, (list, tuple)) and len(rng) == 2:
                start_d, end_d = rng
            else:
                start_d = end_d = rng if not isinstance(rng, (list, tuple)) else rng[0]

    start_s, end_s = start_d.isoformat(), end_d.isoformat()
    rs = db.range_stats(start_s, end_s)
    rr = db.range_reply_count(start_s, end_s)
    sent_in_range = rs.get("total", 0)
    rate = round(rr / max(sent_in_range, 1) * 100, 1)
    label = preset if preset != "Custom" else f"{start_s} → {end_s}"

    ui.section(label)
    c1, c2, c3, c4 = st.columns(4)
    ui.kpi(c1, "Emails sent", sent_in_range,
           f'{rs.get("new_sends",0)} new · {rs.get("followups",0)} follow-ups', "✉", "brand")
    ui.kpi(c2, "Replies", rr, "in this period", "💬", "green")
    ui.kpi(c3, "Reply rate", f"{rate}%", "replies ÷ sent", "↗", "amber")
    ui.kpi(c4, "Active sequences", s.get("active", 0), f"limit {limit}/day", "⟳", "violet")

    if limit < 100:
        st.info(f"Gmail warmup active — sending up to {limit}/day today (auto-increases weekly to 100).")
    st.caption("Follow-ups (Emails 2–5) send automatically while the app is open. "
               "For sending even when it's closed, set up the daily scheduler (Settings).")

    st.write("")
    cl, cr = st.columns([3, 2])
    with cl:
        ui.section("Sent · last 7 days")
        trend = db.last_n_days_sends(7)
        if trend:
            dft = pd.DataFrame(trend).set_index("date")
            dft.columns = ["New (Email 1)", "Follow-ups"]
            st.bar_chart(dft, color=["#4F46E5", "#10B981"], height=220)
        else:
            st.info("No sends yet.")
    with cr:
        ui.section("Sequence funnel")
        funnel = db.funnel_counts()
        if funnel:
            st.bar_chart(pd.DataFrame(list(funnel.items()),
                         columns=["Stage", "Count"]).set_index("Stage"),
                         color="#7C3AED", height=220)
        else:
            st.info("No active sequences yet.")

    # ── Reply breakdown (positive / negative / neutral + labels) ─────────────
    rb = db.reply_breakdown()
    ui.section("Replies by type")
    if rb["total"]:
        sen = rb["sentiment"]
        rc1, rc2, rc3 = st.columns(3)
        ui.kpi(rc1, "Positive", sen.get("positive", 0), icon="●", tone="green")
        ui.kpi(rc2, "Neutral", sen.get("neutral", 0), icon="●", tone="amber")
        ui.kpi(rc3, "Negative", sen.get("negative", 0), icon="●", tone="red")
        st.write("")
        labels = rb["label"]
        if labels:
            st.bar_chart(pd.DataFrame(
                [{"Type": k.replace("_", " ").title(), "Count": v} for k, v in labels.items()]
            ).set_index("Type"), color="#4F46E5", height=200)
    else:
        st.info("No replies classified yet — they'll be auto-labelled as they arrive.")

    due = db.due_today()
    ui.section(f"Follow-ups due now ({len(due)})")
    if due:
        st.write(", ".join(f"{l['brand_name']} (Email {l['step']+1})" for l in due[:12]))
        if st.button("Send all due follow-ups", type="primary"):
            with st.spinner("Sending…"):
                r = scheduler.run()
            st.success(f"Sent {len(r['sent'])} follow-ups.")
            st.rerun()
    else:
        st.success("All caught up.")


# ════════════════════════════════════════════════════════════════════════════
# ALL LEADS
# ════════════════════════════════════════════════════════════════════════════

elif page == "All Leads":
    ui.page_header("All leads", "Everyone you've found or emailed.", eyebrow="Pipeline")
    f1, f2 = st.columns([1, 3])
    fs = f1.selectbox("Status", ["All", "pool", "active", "replied", "converted"])
    leads = db.all_leads() if fs == "All" else db.all_leads(fs)
    if leads:
        cols = ["brand_name", "email", "category", "market", "status", "step",
                "last_sent", "replied"]
        avail = [c for c in cols if c in leads[0]]
        df = pd.DataFrame(leads)[avail]
        df.columns = [c.replace("_", " ").title() for c in avail]
        if "Replied" in df.columns:
            df["Replied"] = df["Replied"].map({0: "No", 1: "Yes"})
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button("⬇  Download CSV", df.to_csv(index=False), "leads.csv", "text/csv")

        ui.section("View generated emails")
        opts = {f"{l['brand_name']} ({l['email']})": l for l in leads}
        sel = st.selectbox("Lead", list(opts.keys()))
        if sel:
            ej = json.loads(opts[sel].get("emails_json") or "{}")
            if ej:
                step = st.selectbox("Email step", [1, 2, 3, 4, 5])
                e = ej.get(str(step), {})
                if e:
                    st.markdown(f"**Subject:** {e.get('subject','')}")
                    st.text_area("Body", e.get("body", ""), height=240)
                else:
                    st.info("No email for this step.")
            else:
                st.info("No pre-generated emails for this lead.")
    else:
        st.info("No leads yet. Run a campaign to find your first founders.")


# ════════════════════════════════════════════════════════════════════════════
# REPLIES
# ════════════════════════════════════════════════════════════════════════════

elif page == "Replies":
    ui.page_header("Replies", "Auto-labelled as they arrive. Mark wins as converted.",
                   eyebrow="Inbox")
    detailed = db.replies_detailed()
    converted = db.all_leads(status="converted")

    if not detailed and not converted:
        st.info("No replies yet — the app checks automatically on load and on Sync.")
    else:
        # filter by sentiment
        flt = st.radio("Show", ["All", "Positive", "Neutral", "Negative"],
                       horizontal=True, label_visibility="collapsed")
        sentiment_badge = {"positive": ":green[● Positive]", "negative": ":red[● Negative]",
                           "neutral": ":orange[● Neutral]", "": ":gray[○ Unclassified]"}
        shown = [l for l in detailed
                 if flt == "All" or (l.get("reply_sentiment", "") == flt.lower())]

        ui.section(f"{len(shown)} repl{'y' if len(shown)==1 else 'ies'}")
        for l in shown:
            sent = l.get("reply_sentiment", "") or ""
            label = (l.get("reply_label", "") or "reply").replace("_", " ")
            badge = sentiment_badge.get(sent, ":gray[○ Unclassified]")
            with st.expander(f"{badge}  **{l['brand_name']}** · {label} · {l['email']}"):
                st.markdown(f"**Category:** {l['category']} · **Replied after:** Email {l['step']}")
                if l.get("reply_snippet"):
                    st.markdown("**What they said:**")
                    st.text(l["reply_snippet"][:800])
                if l["status"] != "converted":
                    if st.button("Mark as converted", key=f"cv_{l['id']}"):
                        db.mark_converted(l["id"])
                        st.rerun()
                else:
                    st.success("Converted")

        if converted:
            ui.section(f"{len(converted)} converted")
            for l in converted:
                st.markdown(f"- **{l['brand_name']}** ({l['email']})")


# ════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ════════════════════════════════════════════════════════════════════════════

elif page == "Settings":
    ui.page_header("Settings", "Keys, dossier, Gmail and sending limits.", eyebrow="Account")
    t_keys, t_dossier, t_gmail, t_warm = st.tabs(["API keys", "Dossier", "Gmail", "Warmup"])

    with t_keys:
        with st.form("settings"):
            st.markdown("**Keys** (OpenAI + Apify)")
            ai_key = st.text_input("OpenAI API Key", value=db.get("ai_key", ""), type="password")
            apify_key = st.text_input("Apify API Key", value=db.get("apify_key", ""), type="password")

            st.markdown("**Your profile**")
            sender_name = st.text_input("Your name (sign-off)", value=db.get("sender_name", ""))

            if st.form_submit_button("Save Settings", type="primary"):
                db.put("ai_provider", PROVIDER)
                db.put("ai_key", ai_key)
                db.put("apify_key", apify_key)
                db.put("sender_name", sender_name)
                st.success("Settings saved.")

    with t_dossier:
        _cur = db.get("dossier", "") or ""
        if _cur.strip():
            st.success(f"Current dossier loaded ({len(_cur):,} characters).")
            with st.expander("View current dossier"):
                st.text(_cur[:6000])
        else:
            st.warning("No dossier set yet.")

        new_file = st.file_uploader("Replace dossier (.txt or .pdf)", type=["txt", "pdf"],
                                    key="settings_dossier_upload")
        if new_file is not None:
            new_txt = _read_dossier_file(new_file)
            if new_txt.strip():
                st.caption(f"New file read: {new_file.name} ({len(new_txt):,} characters).")
                if st.button("Replace dossier", type="primary"):
                    db.put("dossier", new_txt)
                    db.put("icp_json", "")                       # rebuild targeting from new dossier
                    st.session_state.pop("camp_profile", None)
                    st.success("Dossier replaced. Targeting refreshes on your next Find.")
            else:
                st.error("Couldn't read text from that file — try a .txt or a text-based PDF.")

    with t_keys:
        if st.button("Test keys"):
            for name, r in (("OpenAI", key_tester.test_openai(db.get("ai_key", ""))),
                            ("Apify", key_tester.test_apify(db.get("apify_key", "")))):
                (st.success if r["ok"] else st.error)(f"{name}: {r['message']}")

    with t_gmail:
        if gmail_oauth.is_connected():
            st.success(f"Connected via Google: {gmail_oauth.connected_email()}")
            if st.button("Disconnect Gmail"):
                gmail_oauth.disconnect()
                st.rerun()
        elif db.get("gmail_address"):
            st.success(f"Connected with App Password: {db.get('gmail_address')}")
        else:
            st.warning("Gmail not connected.")

        with st.form("gmail_pw"):
            st.markdown("**App Password** (works locally and on the cloud)")
            gaddr = st.text_input("Gmail address", value=db.get("gmail_address", ""))
            gpass = st.text_input("16-character App Password", type="password",
                                  help="myaccount.google.com/apppasswords")
            if st.form_submit_button("Save & test", type="primary"):
                if gmail.test_credentials(gaddr, gpass):
                    db.put("gmail_address", gaddr)
                    db.put("gmail_password", gpass)
                    st.success("Gmail connected.")
                else:
                    st.error("Login failed. Check 2-Step Verification is ON and use the "
                             "App Password, not your normal password.")

        if not gmail_oauth.is_connected():
            with st.expander("Advanced: connect via Google account-picker (local only)"):
                if st.button("Connect Gmail via Google"):
                    addr, err = gmail_oauth.run_oauth_flow()
                    st.error(err) if err else st.success(f"Connected as {addr}")
                    if not err:
                        st.rerun()

    with t_warm:
        limit = db.warmup_daily_limit()
        st.progress(min(limit / 100, 1.0), text=f"Today's send limit: {limit}/day")
        st.caption("New Gmail senders ramp up slowly so Google doesn't flag you: "
                   "20 → 40 → 60 → 80 → 100 per day over 4 weeks. It rises automatically.")
