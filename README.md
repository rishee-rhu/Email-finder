# Cold Email Engine

Finds founder/CEO emails from a dossier, writes a personalised 5-email sequence,
sends them from your Gmail, and auto-runs follow-ups + reply tracking.
Powered by **OpenAI + Apify** only.

---

## Deploy it online (free) — Streamlit Community Cloud

**1. Put this folder on GitHub**
- Create a free account at [github.com](https://github.com) → **New repository** (name it e.g. `cold-email-engine`, keep it Private).
- Upload **all files in this folder** (drag-and-drop works: GitHub → "uploading an existing file").
- Do **not** upload `leads.db`, `gmail_token.json`, or `gmail_credentials.json` if present — the included `.gitignore` already excludes them.

**2. Deploy on Streamlit**
- Go to [share.streamlit.io](https://share.streamlit.io) → sign in with GitHub → **Create app**.
- Repository: your repo · Branch: `main` · **Main file path: `app.py`** → **Deploy**.
- Wait ~2 minutes. You get a public URL like `https://your-app.streamlit.app`.

**3. First-time setup (in the app)**
1. **API Keys** — paste your OpenAI key + Apify key → **Test & Continue**
2. **Dossier** — upload your `.txt`/`.pdf` dossier
3. **Gmail** — connect with a **Gmail App Password** (see below)

Then go to **Campaign → Find**, review, and send.

---

## Gmail on the cloud — use an App Password (not OAuth)

The "Connect via Google account-picker" (OAuth) option **only works when running
locally** — it opens a browser on your own machine. On a hosted app, use the
**App Password**:

1. Turn on **2-Step Verification**: myaccount.google.com/security
2. Create an App Password: myaccount.google.com/apppasswords
3. Paste your Gmail address + the 16-character code in the app.

---

## Important limitations of the free cloud tier (read this)

- **Data resets on reboot.** Streamlit's free tier has a temporary filesystem, so
  `leads.db` (your keys, leads, send history, warmup progress) can be wiped when the
  app sleeps/redeploys. Fine for testing; for permanent storage you'd connect an
  external database (e.g. Supabase/Postgres) later.
- **Follow-ups send while the app is open.** The app checks replies and fires due
  follow-ups on load and on "Sync". For fully automated daily sending when the app is
  closed, you need a scheduler (the included `run_daily.py` + `setup_scheduler.bat`
  are for **local Windows** only).
- **Apify free credit is ~$5/month** (~30–60 runs at current cost). High volume
  needs a paid Apify plan.

---

## Run it locally instead (more persistent)

```bash
pip install -r requirements.txt
streamlit run app.py --server.address localhost
```

Opens at http://localhost:8501. Local runs keep `leads.db` on your disk (no resets),
and you can use the Gmail OAuth option if you add `gmail_credentials.json`.

---

## Work on the look (UI preview)

Double-click **`preview_ui.bat`** (Windows). It opens http://localhost:8502 filled with
fake leads, drafts and replies from `demo.db`, so nothing real is sent and your
`leads.db` is untouched.

- **Colours, fonts, spacing, cards:** edit `ui.py` (colour tokens at the top of `CSS`).
  Also change `primaryColor` in `.streamlit/config.toml` so buttons match.
- **Layout and wording:** edit `app.py`.
- Save the file and the browser reloads on its own.

When you're happy, upload the changed files to GitHub and Streamlit Cloud redeploys.

---

## Files
- `ui.py` — all styling + small UI helpers (header, KPI cards, stepper)
- `demo_data.py` / `preview_ui.bat` — fake data + launcher for UI work
- `app.py` — the Streamlit UI (main file)
- `target_profiler.py` — reads dossier → who to target + search queries
- `lead_finder.py` — discovery + direct page scraping + founder pipeline
- `founder_finder.py` — founder name lookup + email permutations
- `email_verifier.py` — SMTP verification (via Apify) + format/MX checks
- `email_gen.py` — single-call 5-email generator (spam-checked)
- `spam_check.py` — deliverability scan
- `reply_classifier.py` — labels replies positive/negative/neutral
- `scheduler.py` — reply check + due follow-up sender
- `gmail.py` / `gmail_oauth.py` — sending + reply reading
- `db.py` — SQLite storage
