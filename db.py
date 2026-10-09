import os
import sqlite3
import json
from datetime import datetime, timedelta

# CEE_DB lets preview_ui.bat point the app at a throwaway demo database.
DB = os.environ.get("CEE_DB", "leads.db")

def init():
    conn = sqlite3.connect(DB)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT
    );

    CREATE TABLE IF NOT EXISTS leads (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        brand_name   TEXT,
        contact_name TEXT DEFAULT '',
        email        TEXT UNIQUE,
        website      TEXT DEFAULT '',
        instagram    TEXT DEFAULT '',
        category     TEXT DEFAULT 'D2C',
        market       TEXT DEFAULT 'India',
        source       TEXT DEFAULT '',
        status       TEXT DEFAULT 'pool',
        step         INTEGER DEFAULT 0,
        emails_json  TEXT DEFAULT '{}',
        last_sent    TEXT,
        replied      INTEGER DEFAULT 0,
        added_at     TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS sent_log (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id  INTEGER,
        step     INTEGER,
        subject  TEXT,
        body     TEXT,
        sent_at  TEXT,
        FOREIGN KEY (lead_id) REFERENCES leads(id)
    );

    CREATE TABLE IF NOT EXISTS drafts (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id      INTEGER,
        brand_name   TEXT,
        email        TEXT,
        category     TEXT,
        market       TEXT,
        emails_json  TEXT DEFAULT '{}',
        status       TEXT DEFAULT 'draft',
        created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (lead_id) REFERENCES leads(id)
    );
    """)
    conn.commit()

    # Migrations — add columns for existing DBs that predate later versions
    for migration in [
        "ALTER TABLE leads ADD COLUMN market TEXT DEFAULT 'India'",
        "ALTER TABLE leads ADD COLUMN source TEXT DEFAULT ''",
        "ALTER TABLE leads ADD COLUMN reply_sentiment TEXT DEFAULT ''",
        "ALTER TABLE leads ADD COLUMN reply_label TEXT DEFAULT ''",
        "ALTER TABLE leads ADD COLUMN reply_snippet TEXT DEFAULT ''",
        "ALTER TABLE leads ADD COLUMN reply_at TEXT DEFAULT ''",
    ]:
        try:
            conn.execute(migration)
            conn.commit()
        except Exception:
            pass  # column already exists

    conn.close()

def get(key, default=None):
    conn = sqlite3.connect(DB)
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return r[0] if r else default

def put(key, value):
    conn = sqlite3.connect(DB)
    conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()

def upsert_lead(brand_name, email, contact_name="", website="", instagram="",
                category="D2C", emails_json="{}", market="India", source=""):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""INSERT OR IGNORE INTO leads
        (brand_name, contact_name, email, website, instagram, category, emails_json, market, source)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (brand_name, contact_name, email, website, instagram, category, emails_json, market, source))
    conn.commit()
    lead_id = c.lastrowid
    conn.close()
    return lead_id

def all_leads(status=None):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    if status:
        rows = conn.execute(
            "SELECT * FROM leads WHERE status=? ORDER BY added_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM leads ORDER BY added_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_lead(lead_id):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    conn.close()
    return dict(r) if r else None

def mark_sent(lead_id, step, subject, body=""):
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE leads SET step=?, last_sent=?, status='active' WHERE id=?",
                 (step, now, lead_id))
    conn.execute("INSERT INTO sent_log (lead_id, step, subject, body, sent_at) VALUES (?,?,?,?,?)",
                 (lead_id, step, subject, body, now))
    conn.commit()
    conn.close()

def mark_replied(lead_id, sentiment="", label="", snippet=""):
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB)
    conn.execute(
        """UPDATE leads SET replied=1, status='replied',
           reply_sentiment=?, reply_label=?, reply_snippet=?, reply_at=?
           WHERE id=?""",
        (sentiment, label, snippet[:1500], now, lead_id))
    conn.commit()
    conn.close()


def reply_breakdown():
    """
    Counts of replies by sentiment and by label, for the dashboard.
    Returns {"sentiment": {pos,neg,neu}, "label": {interested,...}, "total": n}.
    """
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT reply_sentiment AS s, reply_label AS l
           FROM leads WHERE replied=1""").fetchall()
    conn.close()
    sentiment, label = {}, {}
    for r in rows:
        s = (r["s"] or "unclassified")
        l = (r["l"] or "unclassified")
        sentiment[s] = sentiment.get(s, 0) + 1
        label[l] = label.get(l, 0) + 1
    return {"sentiment": sentiment, "label": label, "total": len(rows)}


def replies_detailed():
    """All replied/converted leads with their reply info, newest first."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT * FROM leads WHERE replied=1
           ORDER BY reply_at DESC, last_sent DESC""").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def mark_converted(lead_id):
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE leads SET status='converted' WHERE id=?", (lead_id,))
    conn.commit()
    conn.close()

# Days to wait after each step before the NEXT email is due.
# Email 1 Day 0 → E2 +3 (Day 3) → E3 +4 (Day 7) → E4 +5 (Day 12) → E5 +4 (Day 16).
# Keep in sync with email_gen.SEQUENCE_DELAYS.
FOLLOWUP_DELAYS = {1: 3, 2: 4, 3: 5, 4: 4}


def due_followups():
    """Return leads where next follow-up is due based on delay schedule."""
    delays = FOLLOWUP_DELAYS
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    due = []
    for step, days in delays.items():
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = conn.execute(
            """SELECT * FROM leads WHERE step=? AND status='active'
               AND replied=0 AND last_sent<?""",
            (step, cutoff)
        ).fetchall()
        due.extend([dict(r) for r in rows])
    conn.close()
    return due

def pull_from_pool(count=100):
    """Return up to `count` leads from the pool (status='pool'), oldest first."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM leads WHERE status='pool' ORDER BY added_at ASC LIMIT ?",
        (count,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def pool_size():
    conn = sqlite3.connect(DB)
    r = conn.execute("SELECT COUNT(*) FROM leads WHERE status='pool'").fetchone()
    conn.close()
    return r[0] if r else 0

def stats():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    r = conn.execute("""SELECT
        COUNT(*) as total,
        SUM(CASE WHEN status='pool'      THEN 1 ELSE 0 END) as pool,
        SUM(CASE WHEN status='active'    THEN 1 ELSE 0 END) as active,
        SUM(CASE WHEN status='replied'   THEN 1 ELSE 0 END) as replied,
        SUM(CASE WHEN status='converted' THEN 1 ELSE 0 END) as converted
    FROM leads""").fetchone()
    conn.close()
    if not r:
        return {}
    return {k: (v or 0) for k, v in dict(r).items()}

def today_stats():
    """Emails sent today split by new (step 1) vs follow-up (step 2-5)."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn  = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    r = conn.execute("""
        SELECT
            COUNT(*)                                       AS total,
            SUM(CASE WHEN step=1 THEN 1 ELSE 0 END)       AS new_sends,
            SUM(CASE WHEN step>1 THEN 1 ELSE 0 END)       AS followups,
            SUM(CASE WHEN step=2 THEN 1 ELSE 0 END)       AS step2,
            SUM(CASE WHEN step=3 THEN 1 ELSE 0 END)       AS step3,
            SUM(CASE WHEN step=4 THEN 1 ELSE 0 END)       AS step4,
            SUM(CASE WHEN step=5 THEN 1 ELSE 0 END)       AS step5
        FROM sent_log WHERE sent_at LIKE ?
    """, (f"{today}%",)).fetchone()
    conn.close()
    if not r:
        return {"total":0,"new_sends":0,"followups":0,"step2":0,"step3":0,"step4":0,"step5":0}
    d = dict(r)
    return {k: (v or 0) for k, v in d.items()}

def last_n_days_sends(n=7):
    """
    Returns list of dicts [{date, new_sends, followups}, ...] for last N days.
    """
    conn = sqlite3.connect(DB)
    rows = conn.execute("""
        SELECT
            DATE(sent_at)                                   AS day,
            SUM(CASE WHEN step=1 THEN 1 ELSE 0 END)        AS new_sends,
            SUM(CASE WHEN step>1 THEN 1 ELSE 0 END)        AS followups
        FROM sent_log
        WHERE sent_at >= DATE('now', ?)
        GROUP BY day
        ORDER BY day ASC
    """, (f"-{n} days",)).fetchall()
    conn.close()
    return [{"date": r[0], "new_sends": r[1], "followups": r[2]} for r in rows]

def reply_rate_by_step():
    """
    For each email step 1-5: how many leads are at that step vs how many replied.
    Returns list of dicts [{step, sent, replied, rate}].
    """
    conn = sqlite3.connect(DB)
    rows = conn.execute("""
        SELECT
            sl.step,
            COUNT(DISTINCT sl.lead_id)                          AS sent,
            COUNT(DISTINCT CASE WHEN l.replied=1 THEN l.id END) AS replied
        FROM sent_log sl
        JOIN leads l ON sl.lead_id = l.id
        GROUP BY sl.step
        ORDER BY sl.step
    """).fetchall()
    conn.close()
    result = []
    for r in rows:
        sent    = r[1] or 1
        replied = r[2] or 0
        result.append({
            "step":    f"Email {r[0]}",
            "sent":    r[1],
            "replied": replied,
            "rate":    round(replied / sent * 100, 1),
        })
    return result

def category_stats():
    """Reply counts and rates per D2C category."""
    conn = sqlite3.connect(DB)
    rows = conn.execute("""
        SELECT
            category,
            COUNT(*)                                    AS total,
            SUM(CASE WHEN replied=1   THEN 1 ELSE 0 END) AS replied,
            SUM(CASE WHEN status='pool' THEN 1 ELSE 0 END) AS in_pool
        FROM leads
        WHERE status != 'pool'
        GROUP BY category
        ORDER BY replied DESC
    """).fetchall()
    conn.close()
    return [
        {"category": r[0], "total": r[1], "replied": r[2],
         "rate": round((r[2] or 0) / max(r[1], 1) * 100, 1)}
        for r in rows
    ]

def recent_replies(n=5):
    """Most recent N leads that replied."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT * FROM leads
        WHERE status IN ('replied','converted')
        ORDER BY last_sent DESC
        LIMIT ?
    """, (n,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def due_today():
    """Follow-ups due today or overdue."""
    delays = FOLLOWUP_DELAYS
    conn   = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    due = []
    for step, days in delays.items():
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = conn.execute("""
            SELECT *, ? + 1 AS next_step FROM leads
            WHERE step=? AND status='active' AND replied=0 AND last_sent<?
        """, (step, step, cutoff)).fetchall()
        due.extend([dict(r) for r in rows])
    conn.close()
    return due

def week_stats():
    """Emails sent in the last 7 days."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    r = conn.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN step=1 THEN 1 ELSE 0 END) AS new_sends,
               SUM(CASE WHEN step>1 THEN 1 ELSE 0 END) AS followups
        FROM sent_log
        WHERE sent_at >= DATE('now', '-7 days')
    """).fetchone()
    conn.close()
    if not r:
        return {"total": 0, "new_sends": 0, "followups": 0}
    return {k: (v or 0) for k, v in dict(r).items()}

def save_drafts(draft_list):
    """Save a list of {lead_id, brand_name, email, category, market, emails_json} dicts."""
    conn = sqlite3.connect(DB)
    conn.execute("DELETE FROM drafts WHERE status='draft'")  # clear old unsent drafts
    for d in draft_list:
        conn.execute("""INSERT INTO drafts (lead_id, brand_name, email, category, market, emails_json, status)
            VALUES (?,?,?,?,?,?,?)""",
            (d.get("lead_id"), d.get("brand_name"), d.get("email"),
             d.get("category"), d.get("market"), d.get("emails_json","{}"), "draft"))
    conn.commit()
    conn.close()

def get_drafts():
    """Return all pending drafts."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM drafts WHERE status='draft' ORDER BY created_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_draft(draft_id):
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE drafts SET status='sent' WHERE id=?", (draft_id,))
    conn.commit()
    conn.close()

def market_stats():
    """Lead counts broken down by market."""
    conn = sqlite3.connect(DB)
    rows = conn.execute("""
        SELECT market, COUNT(*) as total,
               SUM(CASE WHEN status='pool'      THEN 1 ELSE 0 END) as pool,
               SUM(CASE WHEN status='active'    THEN 1 ELSE 0 END) as active,
               SUM(CASE WHEN replied=1          THEN 1 ELSE 0 END) as replied
        FROM leads
        GROUP BY market
        ORDER BY total DESC
    """).fetchall()
    conn.close()
    return [{"market": r[0], "total": r[1], "pool": r[2],
             "active": r[3], "replied": r[4]} for r in rows]

def warmup_daily_limit():
    """
    Returns today's send limit based on Gmail warmup schedule.
    Starts at 20/day, adds 20 each week, caps at 100.
    """
    start = get("warmup_start")
    if not start:
        put("warmup_start", datetime.now().strftime("%Y-%m-%d"))
        return 20
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d")
        days = (datetime.now() - start_date).days
        if days < 7:   return 20
        if days < 14:  return 40
        if days < 21:  return 60
        if days < 28:  return 80
        return 100
    except Exception:
        return 100

def save_campaign(state):
    """Persist the in-progress campaign (verified leads, audits, drafts) to disk
    so switching pages or restarting never loses paid-for API work."""
    put("campaign_state", json.dumps(state))


def load_campaign():
    raw = get("campaign_state")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def clear_campaign():
    put("campaign_state", "")


def range_stats(start, end):
    """Sent counts between two 'YYYY-MM-DD' dates (inclusive)."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    r = conn.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN step=1 THEN 1 ELSE 0 END) AS new_sends,
               SUM(CASE WHEN step>1 THEN 1 ELSE 0 END) AS followups
        FROM sent_log WHERE DATE(sent_at) BETWEEN ? AND ?
    """, (start, end)).fetchone()
    conn.close()
    d = dict(r) if r else {}
    return {k: (v or 0) for k, v in d.items()} if d else \
           {"total": 0, "new_sends": 0, "followups": 0}


def range_reply_count(start, end):
    """Replies received between two 'YYYY-MM-DD' dates (inclusive)."""
    conn = sqlite3.connect(DB)
    r = conn.execute(
        "SELECT COUNT(*) FROM leads WHERE replied=1 AND DATE(reply_at) BETWEEN ? AND ?",
        (start, end)).fetchone()
    conn.close()
    return r[0] if r else 0


def funnel_counts():
    """Count leads at each stage for funnel visualization."""
    conn = sqlite3.connect(DB)
    rows = conn.execute("""
        SELECT step, COUNT(*) as cnt
        FROM leads
        WHERE status='active'
        GROUP BY step
        ORDER BY step
    """).fetchall()
    s = stats()
    conn.close()
    funnel = {f"Email {r[0]} sent": r[1] for r in rows}
    funnel["Replied"]   = s.get("replied",   0)
    funnel["Converted"] = s.get("converted", 0)
    return funnel
