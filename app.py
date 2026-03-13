import streamlit as st
import json
import re
import io
import hashlib
import os
from datetime import datetime

try:
    import pypdf
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

st.set_page_config(
    page_title="LitLens — Research Assistant",
    page_icon="◎",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=DM+Mono:wght@400;500&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
[data-testid="stSidebar"] { background: #18181c; border-right: 1px solid rgba(255,255,255,0.07); }
[data-testid="stSidebar"] * { color: #f0ede8 !important; }
.stApp { background: #0e0e10; color: #f0ede8; }
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 1.5rem; }
.paper-card { background: #18181c; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 1rem 1.25rem; margin-bottom: 0.75rem; }
.paper-card h4 { color: #f0ede8; margin: 0 0 4px; font-size: 15px; }
.paper-card .meta { color: #888885; font-size: 12px; font-family: 'DM Mono', monospace; }
.finding { background: #18181c; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 10px 14px; margin-bottom: 6px; font-size: 14px; color: #ccc8c0; line-height: 1.7; }
.finding-label { font-family: 'DM Mono', monospace; font-size: 10px; color: #c8f07a; margin-bottom: 4px; }
.tag { display: inline-block; padding: 2px 10px; border-radius: 100px; font-size: 11px; font-family: 'DM Mono', monospace; font-weight: 500; margin-right: 4px; }
.tag-empirical { background: rgba(245,201,122,0.1); color: #f5c97a; }
.tag-methods { background: rgba(126,184,247,0.1); color: #7eb8f7; }
.tag-review { background: rgba(200,240,122,0.1); color: #c8f07a; }
.tag-theory { background: rgba(180,159,250,0.1); color: #b49ffa; }
.tag-pdf { background: rgba(126,184,247,0.1); color: #7eb8f7; }
.gap-item { background: rgba(255,107,107,0.07); border: 1px solid rgba(255,107,107,0.15); border-radius: 8px; padding: 10px 14px; margin-bottom: 6px; font-size: 13px; color: #e8c5c5; line-height: 1.6; }
.section-title { font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #888885; font-family: 'DM Mono', monospace; margin: 1.25rem 0 0.6rem; }
.page-title { font-family: 'Instrument Serif', serif; font-size: 2rem; letter-spacing: -0.01em; color: #f0ede8; margin-bottom: 0.25rem; }
.summary-block { background: #18181c; border: 1px solid rgba(255,255,255,0.07); border-radius: 12px; padding: 1rem 1.25rem; font-size: 14px; line-height: 1.8; color: #ccc8c0; }
.theme-chip { display:inline-block; background:#18181c; border:1px solid rgba(255,255,255,0.1); border-radius:100px; padding:4px 12px; font-size:12px; color:#c8f07a; margin:3px; }
</style>
""", unsafe_allow_html=True)

# ── Persistent storage ────────────────────────────────────────
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "litlens_data.json")

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"papers": [], "notes": {}, "selected_id": None,
            "repos": [], "paper_repos": {}, "board_state": {}}

def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "papers": st.session_state.papers,
                "notes": st.session_state.notes,
                "selected_id": st.session_state.selected_id,
                "repos": st.session_state.get("repos", []),
                "paper_repos": st.session_state.get("paper_repos", {}),
                "board_state": st.session_state.get("board_state", {}),
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.warning(f"Could not save: {e}")

# ── Session state init ────────────────────────────────────────
if "loaded" not in st.session_state:
    data = load_data()
    st.session_state.papers = data.get("papers", [])
    st.session_state.notes = data.get("notes", {})
    st.session_state.selected_id = data.get("selected_id", None)
    st.session_state.repos = data.get("repos", [])
    st.session_state.paper_repos = data.get("paper_repos", {})
    st.session_state.board_state = data.get("board_state", {})
    st.session_state.loaded = True

if "selected_id" not in st.session_state:
    st.session_state.selected_id = None

# ── Board save via query param ────────────────────────────────
_qs = st.query_params
if "_bs" in _qs:
    try:
        _new_bs = json.loads(_qs["_bs"])
        st.session_state.board_state = _new_bs
        save_data()
    except Exception:
        pass
    st.query_params.clear()

# ── Analysis helpers ──────────────────────────────────────────
def extract_pdf_text(file_bytes):
    if not PDF_SUPPORT:
        return ""
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    text = ""
    for page in reader.pages[:25]:
        text += page.extract_text() or ""
    return text.strip()

def extract_abstract(text):
    tl = text.lower()
    for marker in ["abstract", "summary", "introduction"]:
        idx = tl.find(marker)
        if idx != -1:
            return text[idx:idx+1500].strip()
    return text[:1000]

def extract_title_from_text(text, filename):
    lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 20]
    return lines[0][:120] if lines else filename.replace(".pdf", "")

def extract_structured_themes(text):
    tl = text.lower()
    geo_keywords = {
        "united states": "USA", "u.s.": "USA", "american": "USA",
        "china": "China", "chinese": "China",
        "european union": "EU", "europe": "Europe", "european": "Europe",
        "united kingdom": "UK", "britain": "UK", "british": "UK",
        "germany": "Germany", "france": "France", "italy": "Italy",
        "japan": "Japan", "india": "India", "russia": "Russia",
        "brazil": "Brazil", "latin america": "Latin America",
        "africa": "Africa", "middle east": "Middle East",
        "asia": "Asia", "developing countries": "Developing Countries",
        "emerging markets": "Emerging Markets", "oecd": "OECD countries",
        "brics": "BRICS", "global": "Global", "international": "International",
        "cross-country": "Cross-country", "multinational": "Multinational",
    }
    geo_found = list(dict.fromkeys([v for k, v in geo_keywords.items() if k in tl]))[:4]

    period_found = []
    ranges = re.findall(r'((?:19|20)\d{2})\s*[-\u2013]\s*((?:19|20)\d{2})', text)
    for start, end in ranges[:3]:
        period_found.append(f"{start}\u2013{end}")
    if not period_found:
        decades = re.findall(r'((?:19|20)\d{2}s)', tl)
        period_found = list(dict.fromkeys(decades))[:3]
    period_kw = {
        "longitudinal": "Longitudinal", "panel data": "Panel data",
        "time series": "Time series", "cross-sectional": "Cross-sectional",
        "annual": "Annual data", "monthly": "Monthly data",
        "quarterly": "Quarterly data", "covid": "COVID-19 period",
        "financial crisis": "Financial crisis period",
    }
    for k, v in period_kw.items():
        if k in tl and v not in period_found:
            period_found.append(v)
    period_found = period_found[:4]

    technique_keywords = {
        "regression": "Regression", "ols": "OLS", "fixed effects": "Fixed effects",
        "random effects": "Random effects", "instrumental variable": "IV / 2SLS",
        "difference-in-difference": "Diff-in-diff", "did ": "Diff-in-diff",
        "propensity score": "Propensity score matching",
        "regression discontinuity": "Regression discontinuity",
        "synthetic control": "Synthetic control", "var model": "VAR model",
        "granger": "Granger causality", "cointegration": "Cointegration",
        "meta-analysis": "Meta-analysis", "systematic review": "Systematic review",
        "machine learning": "Machine learning", "deep learning": "Deep learning",
        "neural network": "Neural network", "random forest": "Random forest",
        "logistic regression": "Logistic regression", "probit": "Probit model",
        "event study": "Event study", "bayesian": "Bayesian analysis",
        "gmm": "GMM", "survey": "Survey analysis", "case study": "Case study",
    }
    tech_found = list(dict.fromkeys([v for k, v in technique_keywords.items() if k in tl]))[:5]

    dataset_keywords = {
        "world bank": "World Bank data", "imf": "IMF data",
        "compustat": "Compustat", "crsp": "CRSP", "bloomberg": "Bloomberg",
        "eurostat": "Eurostat", "census": "Census data",
        "firm-level": "Firm-level data", "country-level": "Country-level data",
        "twitter": "Twitter/X data", "patent": "Patent data",
        "annual report": "Annual reports", "proprietary": "Proprietary dataset",
        "hand-collected": "Hand-collected data",
    }
    data_found = list(dict.fromkeys([v for k, v in dataset_keywords.items() if k in tl]))[:4]

    variable_keywords = {
        "gdp": "GDP", "economic growth": "Economic growth",
        "inflation": "Inflation", "unemployment": "Unemployment",
        "interest rate": "Interest rate", "exchange rate": "Exchange rate",
        "stock return": "Stock returns", "firm performance": "Firm performance",
        "profitability": "Profitability", "leverage": "Leverage",
        "investment": "Investment", "innovation": "Innovation",
        "productivity": "Productivity", "foreign direct investment": "FDI",
        "fdi": "FDI", "esg": "ESG scores", "sustainability": "Sustainability",
        "corporate governance": "Corporate governance",
        "ownership": "Ownership structure", "dividend": "Dividends",
        "liquidity": "Liquidity", "volatility": "Volatility",
        "income inequality": "Income inequality", "poverty": "Poverty",
        "co2": "CO2 emissions", "carbon": "Carbon emissions",
    }
    var_found = list(dict.fromkeys([v for k, v in variable_keywords.items() if k in tl]))[:5]

    return {
        "geopolitical": geo_found, "period": period_found,
        "techniques": tech_found, "datasets": data_found, "variables": var_found,
    }

def auto_extract_keywords(text):
    s = extract_structured_themes(text)
    flat = s["techniques"] + s["variables"] + s["geopolitical"]
    return flat[:6] if flat else ["research", "analysis"]

def simple_summarize(text, title):
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if 40 < len(s.strip()) < 300]
    keywords = ["propose", "present", "show", "demonstrate", "find", "result",
                "achieve", "improve", "introduce", "novel", "contribute", "significant"]
    scored = sorted([(sum(1 for k in keywords if k in s.lower()), s) for s in sentences[:50]], reverse=True)
    top = [s for _, s in scored[:3]]
    return " ".join(top) if top else (sentences[0] if sentences else f"Paper: {title}")

def simple_findings(text):
    sentences = re.split(r'(?<=[.!?])\s+', text)
    markers = ["we show", "we find", "we demonstrate", "we propose", "we present",
               "results show", "results indicate", "our method", "achieves",
               "outperforms", "improves", "significantly", "we conclude", "this paper"]
    findings = [s.strip() for s in sentences if 40 < len(s.strip()) < 250 and any(m in s.lower() for m in markers)]
    return findings[:4] if findings else ["See abstract for key contributions."]

def simple_gaps(text):
    sentences = re.split(r'(?<=[.!?])\s+', text)
    markers = ["limitation", "future work", "future research", "however",
               "drawback", "challenge", "remain", "not address", "beyond the scope",
               "one limitation", "further research"]
    gaps = [s.strip() for s in sentences if 30 < len(s.strip()) < 250 and any(m in s.lower() for m in markers)]
    return gaps[:2] if gaps else ["Limitations not explicitly stated in available text."]

def analyze_locally(title, text):
    return {
        "summary": simple_summarize(text, title),
        "findings": simple_findings(text),
        "themes": auto_extract_keywords(text),
        "gaps": simple_gaps(text),
    }

def tag_html(paper_type):
    return f'<span class="tag tag-{paper_type}">{paper_type}</span>'

def get_all_gaps():
    return [{"gap": g, "paper": p["title"]} for p in st.session_state.papers for g in p.get("gaps", [])]

# ── SIDEBAR ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ◎ LitLens")
    st.markdown('<div style="font-size:11px; color:#c8f07a; font-family:DM Mono,monospace; margin-bottom:2px;">no API key needed</div>', unsafe_allow_html=True)
    data_exists = os.path.exists(DATA_FILE)
    st.markdown(f'<div style="font-size:10px; color:#888885; font-family:DM Mono,monospace; margin-bottom:8px;">💾 {"data saved" if data_exists else "no saved data yet"}</div>', unsafe_allow_html=True)
    st.markdown("---")
    st.markdown("**Navigation**")
    page = st.radio("page", ["📚 Library", "🗂 Board", "📄 Add Paper", "📎 Upload PDF", "🔗 Synthesis", "📝 Notes"], label_visibility="collapsed")
    st.markdown("---")
    papers = st.session_state.papers
    if papers:
        st.markdown(f"**{len(papers)} paper{'s' if len(papers)!=1 else ''}**")
        search = st.text_input("Search", placeholder="Filter...", label_visibility="collapsed")
        filtered = [p for p in papers if search.lower() in p["title"].lower() or search.lower() in p.get("authors","").lower()] if search else papers
        for p in filtered:
            label = f"{'📄 ' if p.get('source')=='pdf' else ''}{p['title'][:42]}{'...' if len(p['title'])>42 else ''}"
            if st.button(label, key=f"sel_{p['id']}", use_container_width=True):
                st.session_state.selected_id = p["id"]
                save_data()
                st.rerun()
    else:
        st.markdown('<div style="font-size:12px; color:#888885; line-height:1.7;">No papers yet.<br>Add one to get started.</div>', unsafe_allow_html=True)

# ── PAGE: LIBRARY ─────────────────────────────────────────────
if page == "📚 Library":
    selected = next((p for p in st.session_state.papers if p["id"] == st.session_state.selected_id), None)

    if not selected:
        st.markdown('<div class="page-title">Library</div>', unsafe_allow_html=True)
        st.markdown('<div style="color:#888885;font-size:14px;margin-bottom:2rem;">Select a paper from the sidebar, or add one to get started.</div>', unsafe_allow_html=True)
        if st.session_state.papers:
            cols = st.columns(2)
            for i, p in enumerate(st.session_state.papers):
                with cols[i % 2]:
                    st.markdown(f'<div class="paper-card"><h4>{p["title"]}</h4><div class="meta">{p.get("authors","—")} {("· "+p["year"]) if p.get("year") else ""}</div><div style="margin-top:8px">{tag_html(p.get("type","empirical"))}{"<span class=tag tag-pdf>PDF</span>" if p.get("source")=="pdf" else ""}</div></div>', unsafe_allow_html=True)
        else:
            st.info("No papers yet. Use **Add Paper** or **Upload PDF** to begin.")
    else:
        p = selected
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f'<div class="page-title">{p["title"]}</div>', unsafe_allow_html=True)
        with col2:
            if st.button("🗑 Remove", type="secondary"):
                st.session_state.papers = [x for x in st.session_state.papers if x["id"] != p["id"]]
                st.session_state.selected_id = None
                save_data()
                st.rerun()

        meta_parts = [x for x in [p.get("authors"), p.get("year"), p.get("journal")] if x]
        st.markdown(f'<div style="color:#888885;font-size:13px;font-family:DM Mono,monospace;margin-bottom:1rem;">{" · ".join(meta_parts)}</div>', unsafe_allow_html=True)
        st.markdown(tag_html(p.get("type","empirical")) + ('&nbsp;<span class="tag tag-pdf">PDF</span>' if p.get("source")=="pdf" else ""), unsafe_allow_html=True)

        st.markdown('<div class="section-title">Summary</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="summary-block">{p.get("summary","No summary yet.")}</div>', unsafe_allow_html=True)

        if p.get("findings"):
            st.markdown('<div class="section-title">Key Findings</div>', unsafe_allow_html=True)
            cols = st.columns(2)
            for i, f in enumerate(p["findings"]):
                with cols[i % 2]:
                    st.markdown(f'<div class="finding"><div class="finding-label">finding {i+1}</div>{f}</div>', unsafe_allow_html=True)

        if p.get("themes"):
            st.markdown('<div class="section-title">Themes</div>', unsafe_allow_html=True)
            st.markdown("".join([f'<span class="theme-chip">{t}</span>' for t in p["themes"]]), unsafe_allow_html=True)

        if p.get("gaps"):
            st.markdown('<div class="section-title">Research Gaps</div>', unsafe_allow_html=True)
            for g in p["gaps"]:
                st.markdown(f'<div class="gap-item">{g}</div>', unsafe_allow_html=True)

        st.markdown('<div class="section-title">Actions</div>', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Re-analyze", use_container_width=True):
                with st.spinner("Analyzing..."):
                    text = p.get("abstract","") + " " + p.get("full_text","")
                    result = analyze_locally(p["title"], text)
                    p.update(result)
                    save_data()
                st.rerun()
        with col2:
            if st.button("✏️ Edit Metadata", use_container_width=True):
                st.session_state[f"editing_{p['id']}"] = True

        if st.session_state.get(f"editing_{p['id']}"):
            with st.form(f"edit_{p['id']}"):
                new_title   = st.text_input("Title", value=p["title"])
                new_authors = st.text_input("Authors", value=p.get("authors",""))
                new_year    = st.text_input("Year", value=p.get("year",""))
                new_journal = st.text_input("Journal", value=p.get("journal",""))
                new_type    = st.selectbox("Type", ["empirical","methods","review","theory"],
                                           index=["empirical","methods","review","theory"].index(p.get("type","empirical")))
                if st.form_submit_button("Save"):
                    p.update({"title": new_title, "authors": new_authors,
                              "year": new_year, "journal": new_journal, "type": new_type})
                    save_data()
                    del st.session_state[f"editing_{p['id']}"]
                    st.rerun()

        if p.get("abstract"):
            with st.expander("Abstract / Full Text"):
                st.markdown(f'<div style="font-size:13px;color:#888885;line-height:1.8;">{p["abstract"][:3000]}</div>', unsafe_allow_html=True)


# ── PAGE: BOARD ───────────────────────────────────────────────
elif page == "🗂 Board":
    import streamlit.components.v1 as components
    import json as _json

    papers = st.session_state.papers

    if "board_state" not in st.session_state or not st.session_state.board_state:
        raw = load_data()
        st.session_state.board_state = raw.get("board_state", {
            "subjects": [], "arrows": [], "pool_pos": {"x": 20, "y": 60}
        })

    papers_js = _json.dumps([{
        "id": p["id"], "title": p["title"],
        "authors": p.get("authors", ""), "year": p.get("year", ""),
        "type": p.get("type", "empirical"), "source": p.get("source", "manual"),
    } for p in papers])
    state_js = _json.dumps(st.session_state.board_state)

    BOARD_HTML = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0;padding:0;font-family:Inter,sans-serif;-webkit-user-select:none;user-select:none}
body{background:#0e0e10;overflow:hidden}
#wrap{position:fixed;top:0;left:0;right:0;bottom:0;overflow:hidden;cursor:default}
#cv{position:absolute;top:0;left:0;width:5000px;height:4000px;transform-origin:0 0}
#sv{position:absolute;top:0;left:0;width:5000px;height:4000px;pointer-events:none;z-index:1}
#sv.am{pointer-events:all;cursor:crosshair}
.node{position:absolute;background:#18181c;border:2px solid rgba(255,255,255,.1);border-radius:14px;min-width:220px;max-width:255px;z-index:10;box-shadow:0 6px 28px rgba(0,0,0,.6)}
.node.am-hi{border-color:#c8f07a !important;background:#1e1e24}
.node-head{padding:9px 12px 7px;cursor:move;display:flex;align-items:center;gap:7px;border-radius:12px 12px 0 0}
.ndot{width:10px;height:10px;border-radius:50%;flex-shrink:0;pointer-events:none}
.ntitle{font-size:13px;font-weight:600;color:#f0ede8;flex:1;outline:none;border:none;background:none;cursor:text}
.ntitle:focus{background:rgba(255,255,255,.06);border-radius:4px;padding:2px 5px}
.nbtns{display:flex;gap:3px;opacity:0;transition:opacity .15s}
.node:hover .nbtns{opacity:1}
.nbtns button,.sfbtn{background:none;border:none;color:#777;cursor:pointer;font-size:12px;padding:2px 5px;border-radius:4px}
.nbtns button:hover,.sfbtn:hover{background:rgba(255,255,255,.08);color:#f0ede8}
.nbody{padding:0 8px 8px}
.sf{background:#0e0e10;border:1px solid rgba(255,255,255,.06);border-radius:9px;margin-bottom:5px}
.sf.dz-over{border-color:#c8f07a;background:#141418}
.sfh{padding:5px 8px;display:flex;align-items:center;gap:5px;cursor:pointer}
.sfdot{width:7px;height:7px;border-radius:50%;flex-shrink:0;pointer-events:none}
.sfname{font-size:11px;font-weight:500;color:#ccc8c0;flex:1;outline:none;border:none;background:none;cursor:text}
.sfname:focus{background:rgba(255,255,255,.05);border-radius:3px;padding:1px 4px}
.sftog{font-size:10px;color:#555;padding:0 3px;flex-shrink:0}
.sfpapers{padding:0 6px 6px;display:flex;flex-direction:column;gap:4px}
.sfpapers.closed{display:none}
.dz{border:1.5px dashed rgba(255,255,255,.08);border-radius:7px;padding:6px;font-size:10px;color:#444;text-align:center;font-family:DM Mono,monospace;min-height:28px;display:flex;align-items:center;justify-content:center;transition:border-color .15s,background .15s,color .15s}
.dz.over{border-color:#c8f07a;background:rgba(200,240,122,.06);color:#c8f07a}
.pc{background:#18181c;border:1px solid rgba(255,255,255,.08);border-radius:7px;padding:7px 9px;cursor:grab;line-height:1.4;position:relative;transition:border-color .12s,opacity .15s,transform .1s}
.pc:hover{border-color:rgba(255,255,255,.22);transform:translateY(-1px)}
.pc.dragging{opacity:.3;cursor:grabbing}
.pc .pt{font-size:12px;font-weight:500;color:#f0ede8;margin-bottom:2px;padding-right:16px}
.pc .pm{font-size:10px;color:#666;font-family:DM Mono,monospace}
.pc .pk{font-size:10px;color:#888;font-family:DM Mono,monospace}
.pc .prm{position:absolute;top:4px;right:4px;background:none;border:none;color:#555;cursor:pointer;font-size:11px;padding:1px 4px;border-radius:3px;opacity:0;transition:opacity .15s;line-height:1}
.pc:hover .prm{opacity:1}
#pool{position:absolute;z-index:15;background:#111215;border:1px solid rgba(255,255,255,.08);border-radius:13px;padding:10px;min-width:210px;max-width:240px}
#ph{font-size:11px;font-weight:600;color:#888885;font-family:DM Mono,monospace;text-transform:uppercase;letter-spacing:.07em;margin-bottom:7px;cursor:move;display:flex;align-items:center;gap:6px}
#pcnt{font-size:10px;color:#f5c97a;font-family:DM Mono,monospace;margin-left:auto}
#pcards{display:flex;flex-direction:column;gap:5px;max-height:400px;overflow-y:auto}
#pcards::-webkit-scrollbar{width:4px}
#pcards::-webkit-scrollbar-thumb{background:#333;border-radius:2px}
#ctrlbar{position:absolute;top:12px;left:12px;z-index:50;display:flex;gap:6px;align-items:center}
#ctrlbar button{background:#18181c;color:#f0ede8;border:1px solid rgba(255,255,255,.15);border-radius:7px;padding:5px 11px;font-size:12px;cursor:pointer}
#ctrlbar button:hover{background:#222}
#ctrlbar button.on{background:#c8f07a;color:#0e0e10;border-color:#c8f07a}
.addsf{width:100%;background:none;border:1.5px dashed rgba(255,255,255,.1);border-radius:7px;color:#555;font-size:11px;cursor:pointer;padding:5px;margin-top:2px}
.addsf:hover{border-color:rgba(255,255,255,.28);color:#f0ede8}
.arr{stroke:rgba(255,255,255,.2);stroke-width:1.5;fill:none;marker-end:url(#ah);cursor:pointer;pointer-events:stroke}
.arr:hover{stroke:#7eb8f7}
.arr.sel{stroke:#c8f07a;stroke-width:2.5;marker-end:url(#ahs)}
#toast{position:fixed;bottom:14px;right:14px;background:#18181c;color:#c8f07a;border:1px solid rgba(200,240,122,.3);border-radius:8px;padding:7px 14px;font-size:12px;font-family:DM Mono,monospace;display:none;z-index:400}
#toast.on{display:block}
</style></head>
<body>
<div id="wrap">
  <div id="cv">
    <svg id="sv"><defs>
      <marker id="ah" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0,8 3,0 6" fill="rgba(255,255,255,.3)"/></marker>
      <marker id="ahs" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0,8 3,0 6" fill="#c8f07a"/></marker>
    </defs></svg>
    <div id="ctrlbar">
      <button onclick="addSubject()">+ Subject</button>
      <button id="bam" onclick="toggleAM()">Connect</button>
      <button id="bda" style="display:none" onclick="delArrow()">Del Arrow</button>
      <button onclick="resetView()">Fit</button>
    </div>
    <div id="pool">
      <div id="ph">Unassigned <span id="pcnt"></span></div>
      <div id="pcards"></div>
    </div>
  </div>
</div>
<div id="toast">Saved!</div>
<script>
var PAPERS = PAPERS_PH;
var ST = STATE_PH;
if(!ST.subjects) ST.subjects=[];
if(!ST.arrows)   ST.arrows=[];
if(!ST.pool_pos) ST.pool_pos={x:20,y:56};

// Restore from sessionStorage if it has a newer timestamp
(function(){
  try{
    var ss=sessionStorage.getItem('litlens_board');
    if(ss){
      var parsed=JSON.parse(ss);
      if(parsed && parsed._ts && (!ST._ts || parsed._ts > ST._ts)){
        ST=parsed;
        if(!ST.subjects) ST.subjects=[];
        if(!ST.arrows)   ST.arrows=[];
        if(!ST.pool_pos) ST.pool_pos={x:20,y:56};
      }
    }
  }catch(e){}
})();

var PM={};
PAPERS.forEach(function(p){ PM[p.id]=p; });
var COLS=["#c8f07a","#7eb8f7","#b49ffa","#f5c97a","#ff9f7a","#5dc4a5","#ff6b6b"];
var ci=0;
function nc(){ return COLS[(ci++)%COLS.length]; }
function uid(){ return 'x'+Math.random().toString(36).substr(2,9); }
function esc(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

// pan/zoom
var px=0,py=0,sc=1,panning=false,psx=0,psy=0;
var CV=document.getElementById('cv'),WR=document.getElementById('wrap');
function applyT(){ CV.style.transform='translate('+px+'px,'+py+'px) scale('+sc+')'; }
function resetView(){ px=0;py=0;sc=1;applyT(); }
WR.addEventListener('wheel',function(e){ e.preventDefault(); sc=Math.min(2.5,Math.max(0.2,sc*(e.deltaY>0?0.9:1.1))); applyT(); },{passive:false});
WR.addEventListener('mousedown',function(e){ if(e.target!==WR&&e.target!==CV&&e.target.id!=='sv') return; panning=true;psx=e.clientX-px;psy=e.clientY-py;WR.style.cursor='grabbing'; });
document.addEventListener('mousemove',function(e){ if(!panning) return; px=e.clientX-psx;py=e.clientY-psy;applyT(); });
document.addEventListener('mouseup',function(){ panning=false;WR.style.cursor=''; });

// drag state
var dragPid=null,dragFrom={sid:null,sfid:null};

// save
var saveTimer=null;
function md(){ clearTimeout(saveTimer); saveTimer=setTimeout(doSave,800); }
function doSave(){
  ST._ts=Date.now();
  var json=JSON.stringify(ST);
  try{ sessionStorage.setItem('litlens_board',json); }catch(e){}
  // Tell parent Streamlit to save via URL param
  try{
    var base=window.parent.location.href.split('?')[0];
    window.parent.history.replaceState(null,'',base+'?_bs='+encodeURIComponent(json));
  }catch(e){}
  var t=document.getElementById('toast');
  t.textContent='Saved!'; t.classList.add('on');
  setTimeout(function(){t.classList.remove('on');},1200);
}

function render(){
  document.querySelectorAll('.node').forEach(function(e){e.remove();});
  ST.subjects.forEach(buildNode);
  buildPool();
  drawArrows();
}

function assignedSet(){
  var s={};
  ST.subjects.forEach(function(sub){ sub.subfields.forEach(function(sf){ sf.papers.forEach(function(id){s[id]=1;}); }); });
  return s;
}

function buildPool(){
  var pool=document.getElementById('pool');
  pool.style.left=ST.pool_pos.x+'px'; pool.style.top=ST.pool_pos.y+'px';
  var as=assignedSet();
  var ua=PAPERS.filter(function(p){return !as[p.id];});
  document.getElementById('pcnt').textContent=ua.length?'('+ua.length+')':'(0)';
  var cont=document.getElementById('pcards');
  cont.innerHTML='';
  if(!ua.length){ cont.innerHTML='<div style="font-size:10px;color:#444;font-family:DM Mono,monospace;text-align:center;padding:8px">all assigned</div>'; }
  else { ua.forEach(function(p){ cont.appendChild(makeCard(p,null,null)); }); }
  makeDraggable(document.getElementById('ph'),function(x,y){ ST.pool_pos={x:x,y:y}; pool.style.left=x+'px'; pool.style.top=y+'px'; },{nodeEl:pool});
}

function makeCard(p,sid,sfid){
  var d=document.createElement('div'); d.className='pc'; d.dataset.pid=p.id;
  var meta=(p.authors?p.authors.substr(0,24):'')+(p.year?' · '+p.year:'');
  d.innerHTML='<div class="pt">'+esc(p.title.substr(0,52))+(p.title.length>52?'...':'')+'</div>'+(meta?'<div class="pm">'+esc(meta)+'</div>':'')+'<div class="pk">'+esc(p.type)+(p.source==='pdf'?' PDF':'')+'</div>';
  d.addEventListener('mousedown',function(e){e.stopPropagation();});
  d.setAttribute('draggable','true');
  d.addEventListener('dragstart',function(e){ dragPid=p.id; dragFrom={sid:sid,sfid:sfid}; d.classList.add('dragging'); e.dataTransfer.effectAllowed='move'; e.dataTransfer.setData('text/plain',p.id); });
  d.addEventListener('dragend',function(){ d.classList.remove('dragging'); dragPid=null; dragFrom={sid:null,sfid:null}; document.querySelectorAll('.dz').forEach(function(z){z.classList.remove('over');}); document.querySelectorAll('.sf').forEach(function(s){s.classList.remove('dz-over');}); });
  if(sid&&sfid){
    var rb=document.createElement('button'); rb.className='prm'; rb.textContent='x'; rb.title='Remove from subfield';
    rb.addEventListener('mousedown',function(e){e.stopPropagation();e.preventDefault();});
    rb.addEventListener('click',function(e){
      e.stopPropagation();
      var subj=ST.subjects.find(function(x){return x.id===sid;});
      if(subj){ var sf2=subj.subfields.find(function(x){return x.id===sfid;}); if(sf2) sf2.papers=sf2.papers.filter(function(x){return x!==p.id;}); }
      md(); render();
    });
    d.appendChild(rb);
  }
  return d;
}

function mkbtn(label,fn){ var b=document.createElement('button'); b.textContent=label; b.addEventListener('click',fn); return b; }

function buildNode(s){
  var el=document.createElement('div'); el.className='node'; el.id='n_'+s.id;
  el.style.left=s.x+'px'; el.style.top=s.y+'px';
  if(s.color) el.style.borderColor=s.color;

  var head=document.createElement('div'); head.className='node-head';
  var dot=document.createElement('div'); dot.className='ndot'; dot.style.background=s.color||'#888';
  var title=document.createElement('div'); title.className='ntitle'; title.contentEditable='true'; title.textContent=s.name;
  title.addEventListener('mousedown',function(e){e.stopPropagation();});
  title.addEventListener('blur',function(){s.name=title.textContent.trim()||'Subject';md();});
  title.addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();title.blur();}});
  var btns=document.createElement('div'); btns.className='nbtns';
  btns.appendChild(mkbtn('*',function(e){e.stopPropagation();s.color=nc();el.style.borderColor=s.color;dot.style.background=s.color;md();}));
  btns.appendChild(mkbtn('X',function(e){
    e.stopPropagation();
    if(!confirm('Delete "'+s.name+'"?')) return;
    ST.subjects=ST.subjects.filter(function(x){return x.id!==s.id;});
    ST.arrows=ST.arrows.filter(function(a){return a.from!==s.id&&a.to!==s.id;});
    md();render();
  }));
  head.appendChild(dot); head.appendChild(title); head.appendChild(btns); el.appendChild(head);

  var body=document.createElement('div'); body.className='nbody';
  s.subfields.forEach(function(sf){body.appendChild(buildSF(s,sf));});
  var addSF=document.createElement('button'); addSF.className='addsf'; addSF.textContent='+ Add subfield';
  addSF.addEventListener('mousedown',function(e){e.stopPropagation();});
  addSF.addEventListener('click',function(e){e.stopPropagation();s.subfields.push({id:uid(),name:'New subfield',color:nc(),papers:[],open:true});md();render();});
  body.appendChild(addSF); el.appendChild(body);

  makeDraggable(head,function(x,y){s.x=x;s.y=y;drawArrows();},{nodeEl:el,exclude:'button,[contenteditable]'});
  el.addEventListener('click',function(e){if(AM&&!e.target.closest('button')&&!e.target.closest('[contenteditable]'))handleAC(s.id);});
  el.addEventListener('dragover',function(e){e.preventDefault();});
  document.getElementById('cv').appendChild(el);
}

function buildSF(s,sf){
  var wrap=document.createElement('div'); wrap.className='sf';
  var hdr=document.createElement('div'); hdr.className='sfh';
  var dot=document.createElement('div'); dot.className='sfdot'; dot.style.background=sf.color||'#888';
  var nm=document.createElement('div'); nm.className='sfname'; nm.contentEditable='true'; nm.textContent=sf.name;
  nm.addEventListener('mousedown',function(e){e.stopPropagation();});
  nm.addEventListener('blur',function(){sf.name=nm.textContent.trim()||'Subfield';md();});
  nm.addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();nm.blur();}});
  var tog=document.createElement('span'); tog.className='sftog'; tog.textContent=sf.open!==false?'v':'^';
  var cb=mkbtn('*',function(e){e.stopPropagation();sf.color=nc();dot.style.background=sf.color;md();}); cb.className='sfbtn';
  var db=mkbtn('X',function(e){e.stopPropagation();s.subfields=s.subfields.filter(function(x){return x.id!==sf.id;});md();render();}); db.className='sfbtn';
  hdr.appendChild(dot); hdr.appendChild(nm); hdr.appendChild(tog); hdr.appendChild(cb); hdr.appendChild(db);
  wrap.appendChild(hdr);

  var pfld=document.createElement('div');
  pfld.className='sfpapers'+(sf.open===false?' closed':'');
  hdr.addEventListener('click',function(e){
    if(e.target.contentEditable==='true'||e.target.tagName==='BUTTON') return;
    sf.open=sf.open===false?true:false;
    pfld.classList.toggle('closed',sf.open===false);
    tog.textContent=sf.open!==false?'v':'^';
  });

  sf.papers.forEach(function(pid){ var p=PM[pid]; if(p) pfld.appendChild(makeCard(p,s.id,sf.id)); });

  var dz=document.createElement('div'); dz.className='dz'; dz.textContent='drop paper here';
  dz.addEventListener('dragover',function(e){e.preventDefault();e.stopPropagation();dz.classList.add('over');wrap.classList.add('dz-over');});
  dz.addEventListener('dragleave',function(){dz.classList.remove('over');wrap.classList.remove('dz-over');});
  dz.addEventListener('drop',function(e){
    e.preventDefault(); e.stopPropagation();
    dz.classList.remove('over'); wrap.classList.remove('dz-over');
    var pid=e.dataTransfer.getData('text/plain')||dragPid;
    if(!pid) return;
    if(dragFrom.sid&&dragFrom.sfid){
      var src=ST.subjects.find(function(x){return x.id===dragFrom.sid;});
      if(src){ var ssf=src.subfields.find(function(x){return x.id===dragFrom.sfid;}); if(ssf) ssf.papers=ssf.papers.filter(function(x){return x!==pid;}); }
    }
    if(sf.papers.indexOf(pid)===-1) sf.papers.push(pid);
    md(); render();
  });
  pfld.appendChild(dz); wrap.appendChild(pfld);
  return wrap;
}

var AM=false,AS=null,selArr=null;
function nodeCenter(id){ var el=document.getElementById('n_'+id); if(!el) return null; return{x:parseInt(el.style.left)+el.offsetWidth/2,y:parseInt(el.style.top)+el.offsetHeight/2}; }
function drawArrows(){
  var svg=document.getElementById('sv');
  svg.querySelectorAll('.arr').forEach(function(e){e.remove();});
  ST.arrows.forEach(function(a){
    var c1=nodeCenter(a.from),c2=nodeCenter(a.to); if(!c1||!c2) return;
    var dx=c2.x-c1.x,dy=c2.y-c1.y;
    var path=document.createElementNS('http://www.w3.org/2000/svg','path');
    path.setAttribute('d','M '+c1.x+' '+c1.y+' C '+(c1.x+dx*.45)+' '+c1.y+','+(c2.x-dx*.45)+' '+c2.y+','+c2.x+' '+c2.y);
    path.setAttribute('class','arr'+(selArr===a.id?' sel':''));
    path.setAttribute('marker-end',selArr===a.id?'url(#ahs)':'url(#ah)');
    path.dataset.aid=a.id;
    path.addEventListener('click',function(e){e.stopPropagation();selArr=selArr===a.id?null:a.id;document.getElementById('bda').style.display=selArr?'block':'none';drawArrows();});
    svg.appendChild(path);
  });
}
function toggleAM(){
  AM=!AM; AS=null;
  var b=document.getElementById('bam');
  document.getElementById('sv').classList.toggle('am',AM);
  b.classList.toggle('on',AM);
  b.textContent=AM?'Connecting...':'Connect';
}
function handleAC(id){
  if(!AM) return;
  if(!AS){ AS=id; var el=document.getElementById('n_'+id); if(el) el.classList.add('am-hi'); }
  else{
    if(AS!==id){ var exists=ST.arrows.some(function(a){return a.from===AS&&a.to===id;}); if(!exists){ST.arrows.push({id:uid(),from:AS,to:id});md();} }
    var el2=document.getElementById('n_'+AS); if(el2) el2.classList.remove('am-hi');
    AS=null; toggleAM(); render();
  }
}
function delArrow(){
  if(!selArr) return;
  ST.arrows=ST.arrows.filter(function(a){return a.id!==selArr;});
  selArr=null; document.getElementById('bda').style.display='none';
  md(); drawArrows();
}

function makeDraggable(handle,onMove,opts){
  opts=opts||{}; var nodeEl=opts.nodeEl||handle; var sx,sy,sl,st2,active=false;
  handle.addEventListener('mousedown',function(e){
    if(opts.exclude&&e.target.closest(opts.exclude)) return;
    if(e.button!==0) return;
    active=true; sx=e.clientX; sy=e.clientY; sl=parseInt(nodeEl.style.left)||0; st2=parseInt(nodeEl.style.top)||0;
    e.preventDefault(); e.stopPropagation();
  });
  document.addEventListener('mousemove',function(e){
    if(!active) return;
    var dx=(e.clientX-sx)/sc,dy=(e.clientY-sy)/sc;
    nodeEl.style.left=Math.max(0,sl+dx)+'px'; nodeEl.style.top=Math.max(0,st2+dy)+'px';
    onMove(Math.max(0,sl+dx),Math.max(0,st2+dy));
  });
  document.addEventListener('mouseup',function(){if(active){active=false;md();}});
}

function addSubject(){
  ST.subjects.push({id:uid(),name:'New Subject',color:nc(),x:(-px/sc)+80,y:(-py/sc)+70,subfields:[{id:uid(),name:'General',color:'#888885',papers:[],open:true}]});
  md(); render();
}

render();
</script>
</body></html>"""

    BOARD_HTML = BOARD_HTML.replace('PAPERS_PH', papers_js).replace('STATE_PH', state_js)
    components.html(BOARD_HTML, height=740, scrolling=False)
    st.caption("+ Subject · Connect two subjects · drag pool cards into subfield zones · hover card = x to unassign · scroll=zoom · drag canvas to pan · auto-saves on every change")


# ── PAGE: ADD PAPER ───────────────────────────────────────────
elif page == "📄 Add Paper":
    st.markdown('<div class="page-title">Add Paper</div>', unsafe_allow_html=True)
    st.markdown('<div style="color:#888885;font-size:14px;margin-bottom:1.5rem;">Paste the title and abstract — analysis runs locally, no API needed.</div>', unsafe_allow_html=True)

    with st.form("add_paper_form"):
        title = st.text_input("Title *", placeholder="Full paper title...")
        col1, col2 = st.columns(2)
        with col1:
            authors = st.text_input("Authors", placeholder="Smith et al., 2023")
            journal = st.text_input("Journal / Venue", placeholder="Nature, NeurIPS...")
        with col2:
            year = st.text_input("Year", placeholder="2024")
            paper_type = st.selectbox("Type", ["empirical","methods","review","theory"])
        abstract = st.text_area("Abstract / Text *", placeholder="Paste the abstract or key excerpts...", height=160)
        submitted = st.form_submit_button("Analyze & Add", type="primary")

    if submitted:
        if not title or not abstract:
            st.error("Title and abstract are required.")
        else:
            with st.spinner("Analyzing..."):
                result = analyze_locally(title, abstract)
                paper = {
                    "id": hashlib.md5((title+str(datetime.now())).encode()).hexdigest(),
                    "title": title, "authors": authors, "year": year,
                    "journal": journal, "type": paper_type, "abstract": abstract,
                    "summary": result["summary"], "findings": result["findings"],
                    "themes": result["themes"], "gaps": result["gaps"],
                    "analyzed": True, "source": "manual",
                }
                st.session_state.papers.append(paper)
                st.session_state.selected_id = paper["id"]
                save_data()
            st.success(f"Added: {title}")
            st.rerun()


# ── PAGE: UPLOAD PDF ──────────────────────────────────────────
elif page == "📎 Upload PDF":
    st.markdown('<div class="page-title">Upload PDF</div>', unsafe_allow_html=True)
    st.markdown('<div style="color:#888885;font-size:14px;margin-bottom:1.5rem;">Upload PDFs — text is extracted and analyzed locally, no API needed.</div>', unsafe_allow_html=True)

    if not PDF_SUPPORT:
        st.warning("pypdf not installed. Run: pip install pypdf", icon="⚠️")
    else:
        uploaded = st.file_uploader("Drop PDF files here", type=["pdf"], accept_multiple_files=True, label_visibility="collapsed")
        if uploaded:
            if st.button(f"Process {len(uploaded)} PDF{'s' if len(uploaded)>1 else ''}", type="primary"):
                for f in uploaded:
                    with st.spinner(f"Reading {f.name}..."):
                        try:
                            file_bytes = f.read()
                            text = extract_pdf_text(file_bytes)
                            if not text or len(text) < 80:
                                st.error(f"{f.name}: No readable text (may be scanned).")
                                continue
                            title = extract_title_from_text(text, f.name)
                            abstract = extract_abstract(text)
                            result = analyze_locally(title, text)
                            paper = {
                                "id": hashlib.md5((f.name+str(datetime.now())).encode()).hexdigest(),
                                "title": title, "authors": "", "year": "", "journal": "",
                                "type": "empirical", "abstract": abstract, "full_text": text[:5000],
                                "summary": result["summary"], "findings": result["findings"],
                                "themes": result["themes"], "gaps": result["gaps"],
                                "analyzed": True, "source": "pdf", "filename": f.name,
                            }
                            st.session_state.papers.append(paper)
                            st.session_state.selected_id = paper["id"]
                            save_data()
                            st.success(f"Added: {title[:60]}")
                        except Exception as e:
                            st.error(f"Error processing {f.name}: {str(e)}")
                st.rerun()


# ── PAGE: SYNTHESIS ───────────────────────────────────────────
elif page == "🔗 Synthesis":
    st.markdown('<div class="page-title">Synthesis</div>', unsafe_allow_html=True)
    papers = st.session_state.papers

    if len(papers) < 2:
        st.info("Add at least 2 papers to see the synthesis.")
    else:
        st.markdown(f'<div style="color:#888885;font-size:14px;margin-bottom:1rem;">{len(papers)} papers in your library</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Cross-cutting Themes</div>', unsafe_allow_html=True)

        from collections import defaultdict
        agg = {k: defaultdict(list) for k in ["geopolitical","period","techniques","datasets","variables"]}
        for p in papers:
            text = (p.get("abstract","") + " " + p.get("full_text","") + " " + p.get("summary","")).lower()
            for cat, items in extract_structured_themes(text).items():
                for item in items:
                    agg[cat][item].append(p["title"])

        cat_config = [
            ("geopolitical", "Geopolitical Focus", "#7eb8f7"),
            ("period",       "Period of Data",     "#f5c97a"),
            ("techniques",   "Analysis Techniques","#c8f07a"),
            ("datasets",     "Datasets Used",      "#b49ffa"),
            ("variables",    "Key Variables",      "#ff9f7a"),
        ]
        for cat_key, cat_label, color in cat_config:
            items = agg[cat_key]
            if not items:
                continue
            st.markdown(f'<div style="font-size:12px;font-weight:500;color:{color};font-family:DM Mono,monospace;text-transform:uppercase;letter-spacing:0.07em;margin:1rem 0 0.4rem;">{cat_label}</div>', unsafe_allow_html=True)
            chips = ""
            for item, paper_list in sorted(items.items(), key=lambda x: -len(x[1])):
                tip = ", ".join(pp[:40] for pp in paper_list[:3])
                chips += f'<span title="{tip}" style="display:inline-block;background:#18181c;border:1px solid rgba(255,255,255,0.1);border-radius:100px;padding:4px 12px;font-size:12px;color:{color};margin:3px;">{item} <span style="opacity:0.5;font-size:10px;">x{len(paper_list)}</span></span>'
            st.markdown(f'<div>{chips}</div>', unsafe_allow_html=True)

        st.markdown('<div class="section-title">Research Gaps</div>', unsafe_allow_html=True)
        for g in get_all_gaps():
            st.markdown(f'<div class="gap-item">{g["gap"]}<br><span style="font-size:11px;color:#888885;font-family:DM Mono,monospace;">from: {g["paper"][:55]}</span></div>', unsafe_allow_html=True)

        st.markdown('<div class="section-title">All Summaries</div>', unsafe_allow_html=True)
        synthesis_text = ""
        for p in papers:
            st.markdown(f'<div style="background:#18181c;border:1px solid rgba(255,255,255,0.07);border-radius:10px;padding:12px 16px;margin-bottom:10px;"><div style="font-size:14px;font-weight:500;color:#f0ede8;margin-bottom:6px;">{p["title"]}</div><div style="font-size:13px;color:#ccc8c0;line-height:1.7;">{p.get("summary","")}</div></div>', unsafe_allow_html=True)
            synthesis_text += f"## {p['title']}\n{p.get('summary','')}\n\nFindings:\n" + "\n".join(f"- {f}" for f in p.get("findings",[])) + "\n\n"

        st.download_button("Download All Summaries (.txt)", synthesis_text, file_name="litlens-synthesis.txt", mime="text/plain")


# ── PAGE: NOTES ───────────────────────────────────────────────
elif page == "📝 Notes":
    st.markdown('<div class="page-title">Notes</div>', unsafe_allow_html=True)

    if not st.session_state.papers:
        st.info("Add papers first to attach notes to them.")
    else:
        paper_titles = {p["id"]: p["title"] for p in st.session_state.papers}
        paper_ids = list(paper_titles.keys())
        default_idx = 0
        if st.session_state.selected_id in paper_ids:
            default_idx = paper_ids.index(st.session_state.selected_id)
        selected_for_note = st.selectbox("Select paper", options=paper_ids, index=default_idx,
                                          format_func=lambda x: paper_titles[x])
        st.session_state.selected_id = selected_for_note

        existing = st.session_state.notes.get(selected_for_note, "")
        new_note = st.text_area("Your notes", value=existing, height=200,
                                 placeholder="Write your thoughts, critiques, connections to other work...")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Save Note", type="primary", use_container_width=True):
                st.session_state.notes[selected_for_note] = new_note
                save_data()
                st.success("Saved!")
        with col2:
            if st.button("Clear Note", use_container_width=True):
                st.session_state.notes[selected_for_note] = ""
                st.rerun()

        if any(v for v in st.session_state.notes.values()):
            st.markdown('<div class="section-title">All Notes</div>', unsafe_allow_html=True)
            all_notes_text = ""
            for pid, note in st.session_state.notes.items():
                if note and pid in paper_titles:
                    st.markdown(f'<div style="background:#18181c;border:1px solid rgba(255,255,255,0.07);border-radius:10px;padding:12px 16px;margin-bottom:10px;"><div style="font-size:13px;font-weight:500;color:#c8f07a;margin-bottom:6px;">{paper_titles[pid]}</div><div style="font-size:13px;color:#ccc8c0;line-height:1.7;white-space:pre-wrap;">{note}</div></div>', unsafe_allow_html=True)
                    all_notes_text += f"## {paper_titles[pid]}\n{note}\n\n"
            if all_notes_text:
                st.download_button("Download All Notes", all_notes_text, file_name="litlens-notes.txt", mime="text/plain")
