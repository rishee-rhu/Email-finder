"""
UI kit for Cold Email Engine — one stylesheet + small render helpers.

All visual styling lives here so app.py stays about behaviour. To restyle the
app, edit the colour tokens in CSS below (and primaryColor in
.streamlit/config.toml so Streamlit's own widgets match).
"""
import html
import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root{
  --brand:#4F46E5; --brand-dark:#3730A3; --brand-soft:#EEF2FF;
  --ink:#0F172A; --muted:#64748B; --line:#E2E8F0;
  --surface:#FFFFFF; --canvas:#F8FAFC;
  --green:#059669; --green-soft:#ECFDF5;
  --amber:#D97706; --amber-soft:#FFFBEB;
  --red:#DC2626;   --red-soft:#FEF2F2;
  --violet:#7C3AED; --violet-soft:#F5F3FF;
}

html, body, [class*="css"], .stMarkdown, button, input, textarea, select{
  font-family:'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif !important;
}
.block-container{padding-top:3.5rem; padding-bottom:4rem; max-width:1180px;}
h1, h2, h3{letter-spacing:-0.02em; color:var(--ink);}

/* ── Sidebar ─────────────────────────────────────────────────────────── */
section[data-testid="stSidebar"]{background:#0F172A;}
section[data-testid="stSidebar"] *{color:#CBD5E1;}
section[data-testid="stSidebar"] hr{border-color:#1E293B;}
section[data-testid="stSidebar"] [data-testid="stMetricValue"]{color:#F8FAFC; font-size:1.4rem;}
section[data-testid="stSidebar"] [data-testid="stMetricLabel"] p{
  color:#94A3B8; font-size:.72rem; text-transform:uppercase; letter-spacing:.06em;}
section[data-testid="stSidebar"] div[role="radiogroup"]{gap:2px; width:100%; display:flex;
  flex-direction:column; align-items:stretch;}
section[data-testid="stSidebar"] [data-testid="stRadioOption"]{
  padding:9px 12px; border-radius:10px; width:100%; margin:0; transition:background .15s;}
section[data-testid="stSidebar"] [data-testid="stRadioOption"]:hover{background:#1E293B;}
section[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"],
section[data-testid="stSidebar"] [data-testid="stRadioOption"]:has(input:checked){
  background:var(--brand);}
section[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] p,
section[data-testid="stSidebar"] [data-testid="stRadioOption"]:has(input:checked) p{
  color:#fff; font-weight:600;}
section[data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div:not([data-testid="stMarkdownContainer"]){
  display:none;}
section[data-testid="stSidebar"] .stButton button{
  background:#1E293B; border:1px solid #334155; color:#E2E8F0;}
section[data-testid="stSidebar"] .stButton button:hover{border-color:var(--brand); color:#fff;}
.side-brand{display:flex; align-items:center; gap:10px; margin:4px 0 2px;}
.side-logo{width:34px; height:34px; border-radius:9px; background:var(--brand);
  display:flex; align-items:center; justify-content:center; color:#fff !important;
  font-weight:700; font-size:15px;}
.side-name{font-weight:700; color:#F8FAFC !important; font-size:1.02rem; line-height:1.1;}
.side-sub{font-size:.75rem; color:#94A3B8 !important;}
.side-status{display:flex; align-items:center; gap:8px; padding:9px 12px; border-radius:10px;
  background:#1E293B; font-size:.8rem; word-break:break-all;}
.dot{width:8px; height:8px; border-radius:50%; flex:none;}
.dot-on{background:#10B981; box-shadow:0 0 0 3px rgba(16,185,129,.2);}
.dot-off{background:#F59E0B; box-shadow:0 0 0 3px rgba(245,158,11,.2);}

/* ── Page header ─────────────────────────────────────────────────────── */
.page-head{margin-bottom:1.4rem;}
.page-eyebrow{font-size:.75rem; font-weight:600; color:var(--brand);
  text-transform:uppercase; letter-spacing:.08em; margin-bottom:4px;}
.page-title{font-size:1.85rem; font-weight:700; color:var(--ink); letter-spacing:-0.02em;
  margin:0; padding:0; line-height:1.2;}
.page-sub{color:var(--muted); margin-top:6px; font-size:.95rem;}

/* ── Cards ───────────────────────────────────────────────────────────── */
div[data-testid="stVerticalBlockBorderWrapper"]{
  background:var(--surface); border-radius:14px !important; border-color:var(--line) !important;
  box-shadow:0 1px 2px rgba(15,23,42,.04);}
.kpi{background:var(--surface); border:1px solid var(--line); border-radius:14px;
  padding:18px 20px; height:100%; box-shadow:0 1px 2px rgba(15,23,42,.04);}
.kpi-top{display:flex; align-items:center; justify-content:space-between;}
.kpi-label{font-size:.78rem; font-weight:600; color:var(--muted);
  text-transform:uppercase; letter-spacing:.05em;}
.kpi-icon{width:30px; height:30px; border-radius:8px; display:flex; align-items:center;
  justify-content:center; font-size:15px;}
.kpi-value{font-size:2rem; font-weight:700; color:var(--ink); margin-top:8px;
  letter-spacing:-0.02em;}
.kpi-sub{font-size:.8rem; color:var(--muted); margin-top:2px;}
.tone-brand .kpi-icon{background:var(--brand-soft); color:var(--brand);}
.tone-green .kpi-icon{background:var(--green-soft); color:var(--green);}
.tone-amber .kpi-icon{background:var(--amber-soft); color:var(--amber);}
.tone-red .kpi-icon{background:var(--red-soft); color:var(--red);}
.tone-violet .kpi-icon{background:var(--violet-soft); color:var(--violet);}

.section{font-size:.8rem; font-weight:600; color:var(--muted); text-transform:uppercase;
  letter-spacing:.07em; margin:26px 0 10px;}

/* ── Step header inside a card ───────────────────────────────────────── */
.step-head{display:flex; align-items:center; gap:12px; margin-bottom:4px;}
.step-num{width:30px; height:30px; border-radius:50%; background:var(--brand-soft);
  color:var(--brand); font-weight:700; display:flex; align-items:center;
  justify-content:center; font-size:.9rem; flex:none;}
.step-num.done{background:var(--green); color:#fff;}
.step-title{font-size:1.1rem; font-weight:600; color:var(--ink);}
.step-desc{color:var(--muted); font-size:.88rem; margin:0 0 10px 42px;}

/* ── Stepper ─────────────────────────────────────────────────────────── */
.stepper{display:flex; gap:8px; margin:0 0 22px; flex-wrap:wrap;}
.stp{flex:1; min-width:130px; display:flex; align-items:center; gap:10px;
  padding:12px 14px; border-radius:12px; border:1px solid var(--line); background:var(--surface);}
.stp .n{width:26px; height:26px; border-radius:50%; display:flex; align-items:center;
  justify-content:center; font-size:.8rem; font-weight:700; flex:none;
  background:#F1F5F9; color:var(--muted);}
.stp .t{font-size:.86rem; font-weight:600; color:var(--muted); line-height:1.15;}
.stp .c{font-size:.74rem; color:var(--muted); font-weight:400;}
.stp.active{border-color:var(--brand); box-shadow:0 0 0 3px var(--brand-soft);}
.stp.active .n{background:var(--brand); color:#fff;}
.stp.active .t{color:var(--ink);}
.stp.done .n{background:var(--green); color:#fff;}
.stp.done .t{color:var(--ink);}

/* ── Badges ──────────────────────────────────────────────────────────── */
.badge{display:inline-block; padding:2px 10px; border-radius:999px; font-size:.74rem;
  font-weight:600; line-height:1.6;}
.b-brand{background:var(--brand-soft); color:var(--brand-dark);}
.b-green{background:var(--green-soft); color:var(--green);}
.b-amber{background:var(--amber-soft); color:var(--amber);}
.b-red{background:var(--red-soft); color:var(--red);}
.b-grey{background:#F1F5F9; color:var(--muted);}

/* ── Onboarding hero ─────────────────────────────────────────────────── */
.hero{background:linear-gradient(135deg,#4F46E5 0%,#7C3AED 100%); border-radius:18px;
  padding:28px 30px; color:#fff; margin-bottom:22px;}
.hero h2{color:#fff; margin:0 0 6px; font-size:1.5rem;}
.hero p{color:rgba(255,255,255,.88); margin:0; font-size:.95rem;}

/* ── Widgets ─────────────────────────────────────────────────────────── */
.stButton button, .stDownloadButton button, .stFormSubmitButton button{
  border-radius:10px; font-weight:600; padding:.5rem 1.1rem;}
.stTextInput input, .stTextArea textarea, .stNumberInput input{border-radius:10px;}
div[data-testid="stExpander"] details{border-radius:12px; border-color:var(--line);
  background:var(--surface);}
div[data-testid="stDataFrame"]{border-radius:12px; overflow:hidden;}
.stTabs [data-baseweb="tab-list"]{gap:4px;}
.stTabs [data-baseweb="tab"]{padding:8px 16px; border-radius:10px 10px 0 0; font-weight:500;}

@media (max-width: 640px){
  .page-title{font-size:1.45rem;}
  .stp{min-width:100%;}
  .step-desc{margin-left:0;}
}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def _e(x):
    return html.escape(str(x))


def page_header(title, subtitle="", eyebrow=""):
    st.markdown(
        '<div class="page-head">'
        + (f'<div class="page-eyebrow">{_e(eyebrow)}</div>' if eyebrow else "")
        + f'<div class="page-title">{_e(title)}</div>'
        + (f'<div class="page-sub">{_e(subtitle)}</div>' if subtitle else "")
        + "</div>",
        unsafe_allow_html=True)


def kpi(col, label, value, sub="", icon="•", tone="brand"):
    col.markdown(
        f'<div class="kpi tone-{tone}"><div class="kpi-top">'
        f'<span class="kpi-label">{_e(label)}</span>'
        f'<span class="kpi-icon">{icon}</span></div>'
        f'<div class="kpi-value">{_e(value)}</div>'
        + (f'<div class="kpi-sub">{_e(sub)}</div>' if sub else "")
        + "</div>",
        unsafe_allow_html=True)


def section(label):
    st.markdown(f'<div class="section">{_e(label)}</div>', unsafe_allow_html=True)


def step_head(n, title, desc="", done=False):
    st.markdown(
        f'<div class="step-head"><span class="step-num{" done" if done else ""}">'
        f'{"✓" if done else n}</span><span class="step-title">{_e(title)}</span></div>'
        + (f'<p class="step-desc">{_e(desc)}</p>' if desc else ""),
        unsafe_allow_html=True)


def stepper(steps, active):
    """steps: list of (title, caption, done). active: 1-based index."""
    parts = []
    for i, (title, cap, done) in enumerate(steps, start=1):
        cls = "done" if done else ("active" if i == active else "")
        mark = "✓" if done else str(i)
        parts.append(f'<div class="stp {cls}"><span class="n">{mark}</span>'
                     f'<div><div class="t">{_e(title)}</div>'
                     f'<div class="c">{_e(cap)}</div></div></div>')
    st.markdown(f'<div class="stepper">{"".join(parts)}</div>', unsafe_allow_html=True)


def badge(text, tone="grey"):
    return f'<span class="badge b-{tone}">{_e(text)}</span>'


def hero(title, body_html):
    """body_html is trusted, app-authored markup (may contain <b>)."""
    st.markdown(f'<div class="hero"><h2>{_e(title)}</h2><p>{body_html}</p></div>',
                unsafe_allow_html=True)


def sidebar_brand(sender):
    st.markdown(
        '<div class="side-brand"><div class="side-logo">CE</div><div>'
        '<div class="side-name">Cold Email Engine</div>'
        f'<div class="side-sub">{_e(sender) + " · " if sender else ""}Outreach</div>'
        '</div></div>', unsafe_allow_html=True)


def sidebar_status(text, on=True):
    st.markdown(f'<div class="side-status"><span class="dot {"dot-on" if on else "dot-off"}">'
                f'</span>{_e(text)}</div>', unsafe_allow_html=True)
