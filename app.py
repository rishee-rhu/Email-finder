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
    st.set_page_config(page_title="Cold Email Engine — Setup", layout="centered")
    st.markdown("""
    <style>
    .setup-card{background:linear-gradient(135deg,#1B4F72,#2874A6);border-radius:16px;
        padding:28px;color:white;margin-bottom:20px;}
    .step-pill{display:inline-block;padding:4px 14px;border-radius:20px;font-size:0.8rem;
        font-weight:700;margin-bottom:12px;}
    .step-active{background:#2874A6;color:white;}
    .step-pending{background:rgba(120,120,120,0.25);}
    .step-done{background:#27AE60;color:white;}
    </style>""", unsafe_allow_html=True)

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

    c1, c2, c3 = st.columns(3)
    for col, n, label in [(c1, 1, "API Keys"), (c2, 2, "Your Dossier"), (c3, 3, "Connect Gmail")]:
        if done[n]:
            tag, mark = "step-done", "✓"
        elif step == n:
            tag, mark = "step-active", str(n)
        else:
            tag, mark = "step-pending", str(n)
        col.markdown(f'<span class="step-pill {tag}">{mark} · {label}</span>',
                     unsafe_allow_html=True)
    st.markdown("---")

    # ── STEP 1: KEYS ─────────────────────────────────────────────────────────
    if step == 1:
        st.markdown('<div class="setup-card"><h2>Welcome</h2>'
                    '<p>Two keys power everything: <b>OpenAI</b> writes and researches the '
                    'emails, <b>Apify</b> finds the brands and their addresses.</p></div>',
                    unsafe_allow_html=True)
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
                st.write(("OK " if r_ai["ok"] else "FAIL ") + f"OpenAI — {r_ai['message']}")
                st.write(("OK " if r_apify["ok"] else "FAIL ") + f"Apify — {r_apify['message']}")
                if r_ai["ok"] and r_apify["ok"]:
                    st.success("Both keys verified.")
                    st.session_state.onboarding_step = 2
                    time.sleep(1.0)
                    st.rerun()
                else:
                    st.error("Fix the failing key above and try again.")

    # ── STEP 2: DOSSIER ──────────────────────────────────────────────────────
    elif step == 2:
        st.markdown('<div class="setup-card"><h2>Your Dossier</h2>'
                    '<p>Upload the document that describes who you are and what you offer. '
                    'The AI reads it to decide <b>who to email</b> and to <b>write</b> each message.</p></div>',
                    unsafe_allow_html=True)

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
        st.markdown('<div class="setup-card"><h2>Connect Gmail</h2>'
                    '<p>Link Gmail so the app can send from your address.</p></div>',
                    unsafe_allow_html=True)

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

st.set_page_config(page_title="Cold Email Engine", layout="wide",
                   initial_sidebar_state="expanded")

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

with st.sidebar:
    st.title("Cold Email Engine")
    st.caption(db.get("sender_name", "") + " — Cold Outreach")
    st.divider()
    page = st.radio("Go to", ["Campaign", "Dashboard", "All Leads", "Replies", "Settings"],
                    label_visibility="collapsed")
    st.divider()
    s = db.stats()
    st.metric("Sent today", db.today_stats().get("total", 0))
    st.metric("Active sequences", s.get("active", 0))
    st.metric("Replies", s.get("replied", 0))
    if gmail_oauth.is_connected():
        st.success(gmail_oauth.connected_email())
    elif db.get("gmail_address"):
        st.info(f"{db.get('gmail_address')} (App Password)")
    else:
        st.warning("Gmail not connected")
    if st.button("Sync replies & follow-ups", use_container_width=True):
        with st.spinner("Syncing…"):
            r = scheduler.run()
        st.success(f"{len(r['replies'])} replies, {len(r['sent'])} follow-ups sent")


# ════════════════════════════════════════════════════════════════════════════
# CAMPAIGN  — the 6-step linear flow
# ════════════════════════════════════════════════════════════════════════════

if page == "Campaign":
    st.title("New Campaign")

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
    if _v:
        if st.button("Start a new campaign (clears saved progress)"):
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

    # ── STEP 1: FIND ─────────────────────────────────────────────────────────
    st.markdown("### 1 · Find emails")
    st.caption("Reads your dossier, works out who to target, and finds founder emails — one click.")
    target_n = st.number_input("How many founder emails to find", min_value=1,
                               max_value=500, value=20, step=5)
    target_n = int(target_n)

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
            with st.spinner("Finding companies & founders, verifying emails via Apify…"):
                # Generic discovery: use THIS student's dossier queries (works for any
                # field), then keep the strict founder-validation that ensures accuracy.
                brand_candidates = lead_finder.find_domains_via_google(
                    apify_key, profile.get("search_queries", []),
                    max_domains=min(oversample * 6, 150))
                runlog.append(f"Discovery: {len(brand_candidates)} company domains from search.")
                found = lead_finder.find_founder_leads(
                    apify_key=apify_key,
                    candidates=brand_candidates,
                    target=oversample,
                    market=market,
                    on_progress=on_prog,
                )
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
                st.error("No founder emails found this run.")
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
        n_real = sum(1 for l in verified if l.get("email_quality") == "founder_real")
        st.caption(f"{len(verified)} founder/CEO emails ready · {n_real} published (real), "
                   f"{len(verified) - n_real} verified-guess. Brands with no findable "
                   "founder email were skipped — no business addresses included.")
        st.dataframe(pd.DataFrame([{
            "Brand": l["brand_name"],
            "Founder": l.get("contact_name") or "—",
            "Role": l.get("contact_role") or "—",
            "Email": l["email"],
            "Source": "Published" if l.get("email_quality") == "founder_real" else "Verified guess",
            "Category": l.get("category"),
        } for l in verified]), use_container_width=True, hide_index=True)

        # show what got dropped, for transparency
        results = st.session_state.get("camp_verify_results", {})
        bad = [(e, r) for e, r in results.items() if not r["valid"]]
        if bad:
            with st.expander(f"{len(bad)} addresses dropped during verification"):
                for e, r in bad[:60]:
                    st.text(f"{e} — {r['reason']}")

    st.divider()

    # ── STEP 2: RESEARCH + WRITE (audit folded in — one AI call per brand) ────
    st.markdown("### 2 · Write emails")

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

    st.divider()

    # ── STEP 3: REVIEW ───────────────────────────────────────────────────────
    st.markdown("### 3 · Review drafts")
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
            badge = "approved" if d["_approved"] else ("skipped" if d["_skip"] else "draft")
            with st.expander(
                f"[{badge}] {lead['brand_name']} <{lead['email']}> · "
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

                with st.expander("Preview follow-ups (Emails 2–5)"):
                    for step in range(2, 6):
                        em = d["_seq"].get(step, {})
                        st.markdown(f"**Email {step} — {em.get('subject','')}**")
                        st.text(em.get("body", ""))

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
        st.info(f"{len(approved)} of {len(drafts)} approved.")

    st.divider()

    # ── STEP 4: SEND ─────────────────────────────────────────────────────────
    st.markdown("### 4 · Send")
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
    st.markdown("""
    <style>
    .card{background:linear-gradient(135deg,#1B4F72,#2874A6);border-radius:14px;
        padding:20px;color:white;text-align:center;height:108px;display:flex;
        flex-direction:column;justify-content:center;}
    .card-green{background:linear-gradient(135deg,#1E8449,#27AE60);}
    .card-orange{background:linear-gradient(135deg,#BA4A00,#E67E22);}
    .card-purple{background:linear-gradient(135deg,#6C3483,#9B59B6);}
    .card-num{font-size:2.1rem;font-weight:700;}
    .card-lbl{font-size:0.74rem;opacity:0.85;margin-top:4px;text-transform:uppercase;}
    .card-sub{font-size:0.7rem;opacity:0.7;margin-top:6px;}
    .section-title{font-size:1.05rem;font-weight:600;margin:18px 0 8px;color:#1B4F72;}
    </style>""", unsafe_allow_html=True)

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

    st.markdown(f'<p class="section-title">{label.upper()}</p>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f'<div class="card"><div class="card-num">{sent_in_range}</div>'
                f'<div class="card-lbl">Emails sent</div>'
                f'<div class="card-sub">{rs.get("new_sends",0)} new · {rs.get("followups",0)} follow-ups</div></div>',
                unsafe_allow_html=True)
    c2.markdown(f'<div class="card card-green"><div class="card-num">{rr}</div>'
                f'<div class="card-lbl">Replies</div>'
                f'<div class="card-sub">in this period</div></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="card card-orange"><div class="card-num">{rate}%</div>'
                f'<div class="card-lbl">Reply rate</div>'
                f'<div class="card-sub">replies ÷ sent</div></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="card card-purple"><div class="card-num">{s.get("active",0)}</div>'
                f'<div class="card-lbl">Active sequences</div>'
                f'<div class="card-sub">limit {limit}/day</div></div>', unsafe_allow_html=True)

    if limit < 100:
        st.info(f"Gmail warmup active — sending up to {limit}/day today (auto-increases weekly to 100).")
    st.caption("Follow-ups (Emails 2–5) send automatically while the app is open. "
               "For sending even when it's closed, set up the daily scheduler (Settings).")

    st.markdown("<br>", unsafe_allow_html=True)
    cl, cr = st.columns([3, 2])
    with cl:
        st.markdown('<p class="section-title">SENT — LAST 7 DAYS</p>', unsafe_allow_html=True)
        trend = db.last_n_days_sends(7)
        if trend:
            dft = pd.DataFrame(trend).set_index("date")
            dft.columns = ["New (Email 1)", "Follow-ups"]
            st.bar_chart(dft, color=["#2874A6", "#27AE60"], height=220)
        else:
            st.info("No sends yet.")
    with cr:
        st.markdown('<p class="section-title">SEQUENCE FUNNEL</p>', unsafe_allow_html=True)
        funnel = db.funnel_counts()
        if funnel:
            st.bar_chart(pd.DataFrame(list(funnel.items()),
                         columns=["Stage", "Count"]).set_index("Stage"),
                         color="#9B59B6", height=220)
        else:
            st.info("No active sequences yet.")

    # ── Reply breakdown (positive / negative / neutral + labels) ─────────────
    st.markdown("<br>", unsafe_allow_html=True)
    rb = db.reply_breakdown()
    st.markdown('<p class="section-title">REPLIES BY TYPE</p>', unsafe_allow_html=True)
    if rb["total"]:
        sen = rb["sentiment"]
        rc1, rc2, rc3 = st.columns(3)
        rc1.markdown(f'<div class="card card-green"><div class="card-num">{sen.get("positive",0)}</div>'
                     f'<div class="card-lbl">Positive</div></div>', unsafe_allow_html=True)
        rc2.markdown(f'<div class="card card-orange"><div class="card-num">{sen.get("neutral",0)}</div>'
                     f'<div class="card-lbl">Neutral</div></div>', unsafe_allow_html=True)
        rc3.markdown(f'<div class="card" style="background:linear-gradient(135deg,#922B21,#E74C3C)">'
                     f'<div class="card-num">{sen.get("negative",0)}</div>'
                     f'<div class="card-lbl">Negative</div></div>', unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        labels = rb["label"]
        if labels:
            st.bar_chart(pd.DataFrame(
                [{"Type": k.replace("_", " ").title(), "Count": v} for k, v in labels.items()]
            ).set_index("Type"), color="#2874A6", height=200)
    else:
        st.info("No replies classified yet — they'll be auto-labelled as they arrive.")

    due = db.due_today()
    st.markdown(f'<p class="section-title">FOLLOW-UPS DUE NOW ({len(due)})</p>',
                unsafe_allow_html=True)
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
    st.title("All Leads")
    f1, f2 = st.columns(2)
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
        st.dataframe(df, use_container_width=True)
        st.download_button("Download CSV", df.to_csv(index=False), "leads.csv", "text/csv")

        st.divider()
        st.subheader("View generated emails")
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
        st.info("No leads yet — run a Campaign.")


# ════════════════════════════════════════════════════════════════════════════
# REPLIES
# ════════════════════════════════════════════════════════════════════════════

elif page == "Replies":
    st.title("Replies")
    detailed = db.replies_detailed()
    converted = db.all_leads(status="converted")

    if not detailed and not converted:
        st.info("No replies yet — the app checks automatically on load and on Sync.")
    else:
        # filter by sentiment
        flt = st.radio("Show", ["All", "Positive", "Neutral", "Negative"],
                       horizontal=True, label_visibility="collapsed")
        sentiment_badge = {"positive": "🟢 Positive", "negative": "🔴 Negative",
                           "neutral": "🟡 Neutral", "": "⚪ Unclassified"}
        shown = [l for l in detailed
                 if flt == "All" or (l.get("reply_sentiment", "") == flt.lower())]

        st.subheader(f"{len(shown)} repl{'y' if len(shown)==1 else 'ies'}")
        for l in shown:
            sent = l.get("reply_sentiment", "") or ""
            label = (l.get("reply_label", "") or "reply").replace("_", " ")
            badge = sentiment_badge.get(sent, "⚪ Unclassified")
            with st.expander(f"{badge} · {l['brand_name']} — {label} ({l['email']})"):
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
            st.divider()
            st.subheader(f"{len(converted)} converted")
            for l in converted:
                st.markdown(f"- **{l['brand_name']}** ({l['email']})")


# ════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ════════════════════════════════════════════════════════════════════════════

elif page == "Settings":
    st.title("Settings")

    with st.form("settings"):
        st.subheader("Keys (OpenAI + Apify)")
        ai_key = st.text_input("OpenAI API Key", value=db.get("ai_key", ""), type="password")
        apify_key = st.text_input("Apify API Key", value=db.get("apify_key", ""), type="password")

        st.subheader("Your profile")
        sender_name = st.text_input("Your name (sign-off)", value=db.get("sender_name", ""))

        if st.form_submit_button("Save Settings", type="primary"):
            db.put("ai_provider", PROVIDER)
            db.put("ai_key", ai_key)
            db.put("apify_key", apify_key)
            db.put("sender_name", sender_name)
            st.success("Settings saved.")

    st.divider()
    st.subheader("Dossier")
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

    st.divider()
    st.subheader("Connections")
    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown("**Keys**")
        if st.button("Test keys"):
            st.write(key_tester.test_openai(db.get("ai_key", "")))
            st.write(key_tester.test_apify(db.get("apify_key", "")))
    with cc2:
        st.markdown("**Gmail**")
        if gmail_oauth.is_connected():
            st.success(gmail_oauth.connected_email())
            if st.button("Disconnect Gmail"):
                gmail_oauth.disconnect()
                st.rerun()
        else:
            st.warning("Not connected via OAuth.")
            if st.button("Connect Gmail via Google"):
                addr, err = gmail_oauth.run_oauth_flow()
                st.error(err) if err else st.success(f"Connected as {addr}")
                if not err:
                    st.rerun()

    st.divider()
    st.subheader("Gmail warmup")
    limit = db.warmup_daily_limit()
    st.markdown(f"Today's send limit: **{limit}/day** (20 → 40 → 60 → 80 → 100 over 4 weeks).")
