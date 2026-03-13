import streamlit as st
import json
import re
import io
import hashlib
from datetime import datetime

try:
    import pypdf
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

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

# ── Persistent storage (local JSON file) ─────────────────────
import os
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "litlens_data.json")

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"papers": [], "notes": {}, "repos": [{"id":"r1","name":"Unassigned","color":"#888885"}], "paper_repos": {}}

def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"papers": st.session_state.papers, "notes": st.session_state.notes, "selected_id": st.session_state.selected_id, "repos": st.session_state.repos, "paper_repos": st.session_state.paper_repos}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.warning(f"Could not save data: {e}")

# ── Session state ─────────────────────────────────────────────
if "loaded" not in st.session_state:
    data = load_data()
    st.session_state.papers = data.get("papers", [])
    st.session_state.notes = data.get("notes", {})
    st.session_state.selected_id = data.get("selected_id", None)
    st.session_state.repos = data.get("repos", [{"id":"r1","name":"Unassigned","color":"#888885"}])
    st.session_state.paper_repos = data.get("paper_repos", {})
    st.session_state.loaded = True
if "selected_id" not in st.session_state:
    st.session_state.selected_id = None

# ── Helpers ───────────────────────────────────────────────────
def extract_pdf_text(file_bytes):
    if not PDF_SUPPORT:
        return ""
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    text = ""
    for page in reader.pages[:25]:
        text += page.extract_text() or ""
    return text.strip()

def extract_abstract(text):
    """Try to find abstract in text"""
    text_lower = text.lower()
    for marker in ["abstract", "summary", "introduction"]:
        idx = text_lower.find(marker)
        if idx != -1:
            chunk = text[idx:idx+1500].strip()
            return chunk
    return text[:1000]

def extract_title_from_text(text, filename):
    """Guess title from first lines of PDF text"""
    lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 20]
    if lines:
        return lines[0][:120]
    return filename.replace(".pdf", "")

def extract_structured_themes(text):
    """Extract structured research themes across 5 categories"""
    tl = text.lower()

    # 1. GEOPOLITICAL FACTORS — countries, regions, blocs
    geo_keywords = {
        "united states": "USA", "u.s.": "USA", "american": "USA",
        "china": "China", "chinese": "China",
        "european union": "EU", "europe": "Europe", "european": "Europe",
        "united kingdom": "UK", "britain": "UK", "british": "UK",
        "germany": "Germany", "france": "France", "italy": "Italy",
        "japan": "Japan", "japanese": "Japan",
        "india": "India", "indian": "India",
        "russia": "Russia", "russian": "Russia",
        "brazil": "Brazil", "latin america": "Latin America",
        "africa": "Africa", "african": "Africa",
        "middle east": "Middle East", "asia": "Asia", "asian": "Asia",
        "developing countries": "Developing Countries",
        "emerging markets": "Emerging Markets",
        "oecd": "OECD countries", "brics": "BRICS",
        "global": "Global", "cross-country": "Cross-country",
        "multinational": "Multinational", "international": "International",
    }
    geo_found = list(dict.fromkeys([v for k, v in geo_keywords.items() if k in tl]))[:4]

    # 2. PERIOD OF DATA — years, decades, time ranges
    import re as _re
    period_found = []
    # explicit year ranges like 2000-2020, 1990–2015
    ranges = _re.findall(r'((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2})', text)
    for start, end in ranges[:3]:
        period_found.append(f"{start}–{end}")
    # single years mentioned as study period
    if not period_found:
        decades = _re.findall(r'((?:19|20)\d{2}s)', tl)
        period_found = list(dict.fromkeys(decades))[:3]
    # keywords
    period_kw = {
        "longitudinal": "Longitudinal", "panel data": "Panel data",
        "time series": "Time series", "cross-sectional": "Cross-sectional",
        "annual": "Annual data", "monthly": "Monthly data",
        "quarterly": "Quarterly data", "daily": "Daily data",
        "pre-pandemic": "Pre-pandemic", "post-pandemic": "Post-pandemic",
        "covid": "COVID-19 period", "financial crisis": "Financial crisis period",
    }
    for k, v in period_kw.items():
        if k in tl and v not in period_found:
            period_found.append(v)
    period_found = period_found[:4]

    # 3. TECHNIQUES OF ANALYSIS
    technique_keywords = {
        "regression": "Regression", "ols": "OLS", "fixed effects": "Fixed effects",
        "random effects": "Random effects", "instrumental variable": "IV / 2SLS",
        "difference-in-difference": "Diff-in-diff", "difference in difference": "Diff-in-diff",
        "did ": "Diff-in-diff", "propensity score": "Propensity score matching",
        "regression discontinuity": "Regression discontinuity",
        "synthetic control": "Synthetic control",
        "var model": "VAR model", "vector autoregression": "VAR model",
        "granger": "Granger causality", "cointegration": "Cointegration",
        "meta-analysis": "Meta-analysis", "systematic review": "Systematic review",
        "machine learning": "Machine learning", "deep learning": "Deep learning",
        "neural network": "Neural network", "random forest": "Random forest",
        "support vector": "SVM", "logistic regression": "Logistic regression",
        "probit": "Probit model", "tobit": "Tobit model",
        "event study": "Event study", "structural equation": "SEM",
        "bayesian": "Bayesian analysis", "gmm": "GMM",
        "survey": "Survey analysis", "interview": "Qualitative interviews",
        "case study": "Case study", "content analysis": "Content analysis",
        "natural experiment": "Natural experiment",
    }
    tech_found = list(dict.fromkeys([v for k, v in technique_keywords.items() if k in tl]))[:5]

    # 4. DATASETS
    dataset_keywords = {
        "world bank": "World Bank data", "imf": "IMF data",
        "worldscope": "Worldscope", "compustat": "Compustat",
        "crsp": "CRSP", "bloomberg": "Bloomberg",
        "eurostat": "Eurostat", "oecd data": "OECD data",
        "census": "Census data", "survey data": "Survey data",
        "panel data": "Panel dataset", "administrative data": "Administrative data",
        "firm-level": "Firm-level data", "country-level": "Country-level data",
        "micro-level": "Micro-level data", "macro-level": "Macro-level data",
        "twitter": "Twitter/X data", "social media": "Social media data",
        "patent": "Patent data", "annual report": "Annual reports",
        "financial statement": "Financial statements",
        "proprietary": "Proprietary dataset", "hand-collected": "Hand-collected data",
    }
    data_found = list(dict.fromkeys([v for k, v in dataset_keywords.items() if k in tl]))[:4]

    # 5. VARIABLES
    variable_keywords = {
        "gdp": "GDP", "economic growth": "Economic growth",
        "inflation": "Inflation", "unemployment": "Unemployment",
        "interest rate": "Interest rate", "exchange rate": "Exchange rate",
        "stock return": "Stock returns", "firm performance": "Firm performance",
        "profitability": "Profitability", "leverage": "Leverage",
        "investment": "Investment", "innovation": "Innovation",
        "productivity": "Productivity", "trade": "Trade",
        "foreign direct investment": "FDI", "fdi": "FDI",
        "esg": "ESG scores", "sustainability": "Sustainability",
        "corporate governance": "Corporate governance",
        "board": "Board characteristics", "ceo": "CEO characteristics",
        "ownership": "Ownership structure", "dividend": "Dividends",
        "liquidity": "Liquidity", "volatility": "Volatility",
        "credit": "Credit", "debt": "Debt",
        "income inequality": "Income inequality", "poverty": "Poverty",
        "education": "Education", "health": "Health outcomes",
        "co2": "CO2 emissions", "carbon": "Carbon emissions",
        "temperature": "Temperature", "price": "Prices",
    }
    var_found = list(dict.fromkeys([v for k, v in variable_keywords.items() if k in tl]))[:5]

    return {
        "geopolitical": geo_found,
        "period": period_found,
        "techniques": tech_found,
        "datasets": data_found,
        "variables": var_found,
    }

def auto_extract_keywords(text):
    """Legacy: flat list of themes for per-paper display"""
    themes_struct = extract_structured_themes(text)
    flat = (themes_struct["techniques"] + themes_struct["variables"] + themes_struct["geopolitical"])
    return flat[:6] if flat else ["research", "analysis"]

def simple_summarize(text, title):
    """Create a basic extractive summary without AI"""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 40 and len(s.strip()) < 300]
    
    keywords = ["propose", "present", "show", "demonstrate", "find", "result", 
                "achieve", "improve", "outperform", "introduce", "novel", "new method",
                "contribute", "first", "state-of-the-art", "significant"]
    
    scored = []
    for s in sentences[:50]:
        score = sum(1 for k in keywords if k in s.lower())
        scored.append((score, s))
    
    scored.sort(reverse=True)
    top = [s for _, s in scored[:3]]
    
    if top:
        return " ".join(top)
    return sentences[0] if sentences else f"Paper: {title}"

def simple_findings(text):
    """Extract likely findings sentences"""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    markers = ["we show", "we find", "we demonstrate", "we propose", "we present",
               "results show", "results indicate", "our method", "our approach",
               "achieves", "outperforms", "improves", "significantly", "accuracy of",
               "we conclude", "this paper", "this work"]
    findings = []
    for s in sentences:
        s = s.strip()
        if 40 < len(s) < 250:
            if any(m in s.lower() for m in markers):
                findings.append(s)
        if len(findings) >= 4:
            break
    return findings if findings else ["See abstract for key contributions."]

def simple_gaps(text):
    """Extract likely limitation/gap sentences"""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    markers = ["limitation", "future work", "future research", "however", 
               "drawback", "challenge", "remain", "not address", "beyond the scope",
               "left for future", "one limitation", "further research"]
    gaps = []
    for s in sentences:
        s = s.strip()
        if 30 < len(s) < 250:
            if any(m in s.lower() for m in markers):
                gaps.append(s)
        if len(gaps) >= 2:
            break
    return gaps if gaps else ["Limitations not explicitly stated in available text."]

def analyze_locally(title, text):
    """Full local analysis - no API needed"""
    return {
        "summary": simple_summarize(text, title),
        "findings": simple_findings(text),
        "themes": auto_extract_keywords(text),
        "gaps": simple_gaps(text),
    }

def tag_html(paper_type):
    return f'<span class="tag tag-{paper_type}">{paper_type}</span>'

def get_all_themes():
    themes = {}
    for p in st.session_state.papers:
        for t in p.get("themes", []):
            k = t.lower().strip()
            themes[k] = themes.get(k, 0) + 1
    return sorted(themes.items(), key=lambda x: -x[1])

def get_all_gaps():
    return [{"gap": g, "paper": p["title"]} for p in st.session_state.papers for g in p.get("gaps", [])]

# ── SIDEBAR ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ◎ LitLens")
    st.markdown('<div style="font-size:11px; color:#c8f07a; font-family:DM Mono,monospace; margin-bottom:2px;">no API key needed</div>', unsafe_allow_html=True)
    import os
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
            themes_html = "".join([f'<span class="theme-chip">{t}</span>' for t in p["themes"]])
            st.markdown(f'<div>{themes_html}</div>', unsafe_allow_html=True)

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
            # Edit metadata
            if st.button("✏️ Edit Metadata", use_container_width=True):
                st.session_state[f"editing_{p['id']}"] = True

        if st.session_state.get(f"editing_{p['id']}"):
            with st.form(f"edit_{p['id']}"):
                new_title = st.text_input("Title", value=p["title"])
                new_authors = st.text_input("Authors", value=p.get("authors",""))
                new_year = st.text_input("Year", value=p.get("year",""))
                new_journal = st.text_input("Journal", value=p.get("journal",""))
                new_type = st.selectbox("Type", ["empirical","methods","review","theory"], index=["empirical","methods","review","theory"].index(p.get("type","empirical")))
                if st.form_submit_button("Save"):
                    p.update({"title": new_title, "authors": new_authors, "year": new_year, "journal": new_journal, "type": new_type})
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

    if "board_state" not in st.session_state:
        raw = load_data()
        st.session_state.board_state = raw.get("board_state", {
            "subjects": [], "arrows": [], "pool_pos": {"x": 20, "y": 20}
        })

    papers_for_js    = _json.dumps([{"id":p["id"],"title":p["title"],"authors":p.get("authors",""),"year":p.get("year",""),"type":p.get("type","empirical"),"source":p.get("source","manual")} for p in papers])
    board_state_js   = _json.dumps(st.session_state.board_state)

    qs = st.query_params
    if "bsave" in qs:
        try:
            new_bs = _json.loads(qs["bsave"])
            st.session_state.board_state = new_bs
            raw = load_data()
            raw["board_state"] = new_bs
            import os as _os
            with open(DATA_FILE,"w",encoding="utf-8") as _f:
                _json.dump(raw, _f, ensure_ascii=False, indent=2)
            st.query_params.clear()
            st.success("Board saved!")
            st.rerun()
        except Exception as e:
            st.error(f"Save error: {e}")
            st.query_params.clear()

    HTML = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0;padding:0;font-family:Inter,sans-serif}
body{background:#0e0e10;overflow:hidden;user-select:none}
#toolbar{position:fixed;top:0;left:0;right:0;height:46px;background:#18181c;border-bottom:1px solid rgba(255,255,255,0.08);display:flex;align-items:center;gap:6px;padding:0 12px;z-index:200}
#toolbar button{background:#0e0e10;color:#f0ede8;border:1px solid rgba(255,255,255,0.12);border-radius:7px;padding:5px 12px;font-size:12px;cursor:pointer}
#toolbar button:hover{background:#222228}
#toolbar button.active{background:#c8f07a;color:#0e0e10;border-color:#c8f07a}
.sep{width:1px;height:22px;background:rgba(255,255,255,0.08);margin:0 4px}
#hint{font-size:11px;color:#444;font-family:DM Mono,monospace;margin-left:auto}
#cw{position:fixed;top:46px;left:0;right:0;bottom:0;overflow:hidden}
#cv{position:absolute;top:0;left:0;width:4000px;height:3000px}
svg#sv{position:absolute;top:0;left:0;width:4000px;height:3000px;pointer-events:none;z-index:1}
svg#sv.am{pointer-events:all;cursor:crosshair}
.subj{position:absolute;background:#18181c;border:2px solid rgba(255,255,255,0.1);border-radius:14px;min-width:230px;max-width:260px;z-index:10;box-shadow:0 4px 20px rgba(0,0,0,.5)}
.subj.sel{border-color:#c8f07a !important}
.sh{padding:10px 12px 8px;cursor:move;display:flex;align-items:center;gap:7px}
.sdot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.stitle{font-size:13px;font-weight:600;color:#f0ede8;flex:1;outline:none;background:none;border:none}
.stitle:focus{background:rgba(255,255,255,0.06);border-radius:4px;padding:2px 5px}
.sact{display:flex;gap:3px;opacity:0;transition:opacity .15s}
.subj:hover .sact{opacity:1}
.sact button,.sf-btn{background:none;border:none;color:#888885;cursor:pointer;font-size:12px;padding:2px 5px;border-radius:4px}
.sact button:hover,.sf-btn:hover{background:rgba(255,255,255,0.08);color:#f0ede8}
.sbody{padding:0 8px 8px}
.sf{background:#0e0e10;border:1px solid rgba(255,255,255,0.06);border-radius:9px;margin-bottom:5px;overflow:hidden}
.sfh{padding:5px 8px;display:flex;align-items:center;gap:5px;cursor:pointer}
.sfdot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.sfname{font-size:11px;font-weight:500;color:#ccc8c0;flex:1;outline:none;background:none;border:none}
.sfname:focus{background:rgba(255,255,255,0.05);border-radius:3px;padding:1px 4px}
.sftog{font-size:10px;color:#555}
.sfp{padding:0 6px 6px;display:flex;flex-direction:column;gap:4px}
.sfp.clp{display:none}
.pc{background:#18181c;border:1px solid rgba(255,255,255,0.07);border-radius:7px;padding:6px 8px;cursor:grab;font-size:11px;color:#ccc8c0;line-height:1.4}
.pc:hover{border-color:rgba(255,255,255,0.2)}
.pc .pm{font-size:10px;color:#666;font-family:DM Mono,monospace}
.pc .pt{font-size:10px;color:#777;font-family:DM Mono,monospace}
.dz{border:1.5px dashed rgba(255,255,255,0.07);border-radius:7px;padding:5px;font-size:10px;color:#444;text-align:center;font-family:DM Mono,monospace;min-height:28px;display:flex;align-items:center;justify-content:center}
.dz.ov{border-color:#c8f07a;background:rgba(200,240,122,0.05);color:#c8f07a}
.addsf{width:100%;background:none;border:1px dashed rgba(255,255,255,0.1);border-radius:7px;color:#555;font-size:11px;cursor:pointer;padding:5px;margin-top:3px}
.addsf:hover{border-color:rgba(255,255,255,0.25);color:#f0ede8}
.port{width:12px;height:12px;background:#c8f07a;border-radius:50%;border:none;cursor:crosshair;position:absolute;right:-7px;top:calc(50% - 6px);z-index:20;opacity:0}
.subj:hover .port{opacity:1}
#pool{position:absolute;background:#111114;border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:10px;min-width:200px;z-index:10}
#ph{font-size:11px;color:#888885;font-family:DM Mono,monospace;text-transform:uppercase;letter-spacing:.07em;margin-bottom:7px;cursor:move}
#pc{display:flex;flex-direction:column;gap:4px;min-height:28px}
.al{stroke:rgba(255,255,255,0.2);stroke-width:1.5;fill:none;marker-end:url(#ah);cursor:pointer}
.al:hover{stroke:#7eb8f7}
.al.sal{stroke:#c8f07a;stroke-width:2.5;marker-end:url(#ahs)}
#sb{position:fixed;bottom:12px;right:12px;z-index:300;display:flex;gap:8px;align-items:center}
#svbtn{background:#c8f07a;color:#0e0e10;border:none;border-radius:8px;padding:8px 18px;font-size:13px;font-weight:600;cursor:pointer;display:none}
#svbtn.on{display:block}
#svmsg{background:#18181c;color:#c8f07a;border:1px solid rgba(200,240,122,.3);border-radius:8px;padding:7px 14px;font-size:12px;font-family:DM Mono,monospace;display:none}
#svmsg.on{display:block}
</style></head><body>
<div id="toolbar">
  <span style="font-size:12px;color:#888885;font-family:DM Mono,monospace">◎ Board</span>
  <div class="sep"></div>
  <button onclick="addSubject()">＋ Subject</button>
  <button id="bam" onclick="toggleAM()">↗ Connect</button>
  <button id="bda" onclick="delSelArrow()" style="display:none">🗑 Arrow</button>
  <div class="sep"></div>
  <button onclick="resetView()">⊡ Fit</button>
  <span id="hint">pan: drag canvas &nbsp;|&nbsp; zoom: scroll &nbsp;|&nbsp; connect: click ↗ then two subjects</span>
</div>
<div id="cw"><div id="cv">
  <svg id="sv"><defs>
    <marker id="ah" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0,8 3,0 6" fill="rgba(255,255,255,0.35)"/></marker>
    <marker id="ahs" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0,8 3,0 6" fill="#c8f07a"/></marker>
  </defs></svg>
  <div id="pool"><div id="ph">📥 Unassigned</div><div id="pc"></div></div>
</div></div>
<div id="sb"><div id="svmsg">✓ Saved!</div><button id="svbtn" onclick="doSave()">💾 Save board</button></div>
<script>
var AP=__PAPERS__;
var ST=__STATE__;
if(!ST.subjects)ST.subjects=[];
if(!ST.arrows)ST.arrows=[];
if(!ST.pool_pos)ST.pool_pos={x:20,y:20};
var PM={};AP.forEach(function(p){PM[p.id]=p;});
var dirty=false,AM=false,AS=null,selArrow=null;
var px=0,py=0,sc=1,panning=false,psx=0,psy=0;
var COLS=["#c8f07a","#7eb8f7","#b49ffa","#f5c97a","#ff9f7a","#5dc4a5","#ff6b6b"];
var ci=0;
function nc(){return COLS[(ci++)%COLS.length];}
function uid(){return'x'+Math.random().toString(36).substr(2,9);}

function assignedIds(){
  var a={};
  ST.subjects.forEach(function(s){s.subfields.forEach(function(sf){sf.papers.forEach(function(id){a[id]=1;});});});
  return a;
}
function unassigned(){var a=assignedIds();return AP.filter(function(p){return!a[p.id];});}

function render(){
  document.querySelectorAll('.subj').forEach(function(e){e.remove();});
  ST.subjects.forEach(buildSubject);
  buildPool();
  drawArrows();
}

function buildPool(){
  var pool=document.getElementById('pool');
  pool.style.left=ST.pool_pos.x+'px';pool.style.top=ST.pool_pos.y+'px';
  var c=document.getElementById('pc');c.innerHTML='';
  var ua=unassigned();
  if(!ua.length){c.innerHTML='<div style="font-size:10px;color:#444;font-family:DM Mono,monospace;padding:4px;text-align:center">all assigned</div>';return;}
  ua.forEach(function(p){c.appendChild(makeCard(p,null,null));});
  dragNode(pool,function(x,y){ST.pool_pos={x:x,y:y};});
}

function makeCard(p,sid,sfid){
  var d=document.createElement('div');d.className='pc';d.draggable=true;
  d.dataset.pid=p.id;d.dataset.fsid=sid||'';d.dataset.fsfid=sfid||'';
  var m=(p.authors?p.authors.substr(0,22):'')+(p.year?' · '+p.year:'');
  d.innerHTML='<div style="font-weight:500;margin-bottom:2px">'+p.title.substr(0,52)+(p.title.length>52?'…':'')+'</div>'
    +(m?'<div class="pm">'+m+'</div>':'')+'<div class="pt">'+p.type+(p.source==='pdf'?' · PDF':'')+'</div>';
  d.addEventListener('dragstart',function(e){
    e.dataTransfer.setData('pid',p.id);
    e.dataTransfer.setData('fsid',sid||'');
    e.dataTransfer.setData('fsfid',sfid||'');
    e.dataTransfer.effectAllowed='move';
  });
  return d;
}

function buildSubject(s){
  var el=document.createElement('div');
  el.className='subj';el.id='s_'+s.id;
  el.style.left=s.x+'px';el.style.top=s.y+'px';
  if(s.color)el.style.borderColor=s.color;

  // Port
  var port=document.createElement('button');port.className='port';port.title='Connect';
  port.addEventListener('click',function(e){e.stopPropagation();handleAC(s.id);});
  el.appendChild(port);

  // Header
  var sh=document.createElement('div');sh.className='sh';
  var dot=document.createElement('div');dot.className='sdot';dot.style.background=s.color||'#888';
  var tit=document.createElement('div');tit.className='stitle';tit.contentEditable='true';tit.textContent=s.name;
  tit.addEventListener('blur',function(){s.name=tit.textContent.trim()||'Subject';md();});
  tit.addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();tit.blur();}});
  var act=document.createElement('div');act.className='sact';
  var cb=document.createElement('button');cb.textContent='🎨';cb.onclick=function(e){e.stopPropagation();s.color=nc();md();render();};
  var db=document.createElement('button');db.textContent='✕';db.onclick=function(e){
    e.stopPropagation();
    if(!confirm('Delete "'+s.name+'"?'))return;
    ST.subjects=ST.subjects.filter(function(x){return x.id!==s.id;});
    ST.arrows=ST.arrows.filter(function(a){return a.from!==s.id&&a.to!==s.id;});
    md();render();
  };
  act.appendChild(cb);act.appendChild(db);
  sh.appendChild(dot);sh.appendChild(tit);sh.appendChild(act);
  el.appendChild(sh);

  // Body
  var body=document.createElement('div');body.className='sbody';
  s.subfields.forEach(function(sf){body.appendChild(buildSF(s,sf));});
  var addsf=document.createElement('button');addsf.className='addsf';addsf.textContent='+ Add subfield';
  addsf.onclick=function(e){e.stopPropagation();s.subfields.push({id:uid(),name:'New subfield',color:nc(),papers:[],open:true});md();render();};
  body.appendChild(addsf);
  el.appendChild(body);

  dragNode(el,function(x,y){s.x=x;s.y=y;drawArrows();},{handle:sh,exclude:'button,[contenteditable]'});
  el.addEventListener('click',function(e){if(AM&&!e.target.closest('button')&&!e.target.closest('[contenteditable]'))handleAC(s.id);});
  document.getElementById('cv').appendChild(el);
}

function buildSF(s,sf){
  var wrap=document.createElement('div');wrap.className='sf';
  var hdr=document.createElement('div');hdr.className='sfh';
  var dot=document.createElement('div');dot.className='sfdot';dot.style.background=sf.color||'#888';
  var nm=document.createElement('div');nm.className='sfname';nm.contentEditable='true';nm.textContent=sf.name;
  nm.addEventListener('blur',function(){sf.name=nm.textContent.trim()||'Subfield';md();});
  nm.addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();nm.blur();}});
  var tog=document.createElement('span');tog.className='sftog';tog.textContent=sf.open!==false?'▾':'▸';
  var cb2=document.createElement('button');cb2.className='sf-btn';cb2.textContent='🎨';
  cb2.onclick=function(e){e.stopPropagation();sf.color=nc();md();render();};
  var db2=document.createElement('button');db2.className='sf-btn';db2.textContent='✕';
  db2.onclick=function(e){e.stopPropagation();s.subfields=s.subfields.filter(function(x){return x.id!==sf.id;});md();render();};
  hdr.appendChild(dot);hdr.appendChild(nm);hdr.appendChild(tog);hdr.appendChild(cb2);hdr.appendChild(db2);
  wrap.appendChild(hdr);

  var pd=document.createElement('div');pd.className='sfp'+(sf.open===false?' clp':'');
  hdr.addEventListener('click',function(e){
    if(e.target.contentEditable==='true'||e.target.tagName==='BUTTON')return;
    sf.open=sf.open===false?true:false;
    pd.classList.toggle('clp',sf.open===false);
    tog.textContent=sf.open!==false?'▾':'▸';
  });

  sf.papers.forEach(function(pid){var p=PM[pid];if(p)pd.appendChild(makeCard(p,s.id,sf.id));});

  var dz=document.createElement('div');dz.className='dz';dz.textContent='drop paper here';
  dz.addEventListener('dragover',function(e){e.preventDefault();dz.classList.add('ov');});
  dz.addEventListener('dragleave',function(){dz.classList.remove('ov');});
  dz.addEventListener('drop',function(e){
    e.preventDefault();dz.classList.remove('ov');
    var pid=e.dataTransfer.getData('pid');
    var fsid=e.dataTransfer.getData('fsid');
    var fsfid=e.dataTransfer.getData('fsfid');
    if(!pid)return;
    if(fsid&&fsfid){
      var src=ST.subjects.find(function(x){return x.id===fsid;});
      if(src){var ssf=src.subfields.find(function(x){return x.id===fsfid;});if(ssf)ssf.papers=ssf.papers.filter(function(x){return x!==pid;});}
    }
    if(sf.papers.indexOf(pid)===-1)sf.papers.push(pid);
    md();render();
  });
  pd.appendChild(dz);
  wrap.appendChild(pd);
  return wrap;
}

function subjectCenter(id){
  var el=document.getElementById('s_'+id);
  if(!el)return null;
  return{x:parseInt(el.style.left)+el.offsetWidth/2,y:parseInt(el.style.top)+el.offsetHeight/2};
}

function drawArrows(){
  var svg=document.getElementById('sv');
  svg.querySelectorAll('.al').forEach(function(e){e.remove();});
  ST.arrows.forEach(function(a){
    var c1=subjectCenter(a.from),c2=subjectCenter(a.to);
    if(!c1||!c2)return;
    var dx=c2.x-c1.x,dy=c2.y-c1.y;
    var d='M '+c1.x+' '+c1.y+' C '+(c1.x+dx*0.45)+' '+c1.y+', '+(c2.x-dx*0.45)+' '+c2.y+', '+c2.x+' '+c2.y;
    var path=document.createElementNS('http://www.w3.org/2000/svg','path');
    path.setAttribute('d',d);
    path.setAttribute('class','al'+(selArrow===a.id?' sal':''));
    path.setAttribute('marker-end',selArrow===a.id?'url(#ahs)':'url(#ah)');
    path.style.pointerEvents='stroke';
    path.dataset.aid=a.id;
    path.addEventListener('click',function(e){
      e.stopPropagation();
      selArrow=selArrow===a.id?null:a.id;
      document.getElementById('bda').style.display=selArrow?'block':'none';
      drawArrows();
    });
    svg.appendChild(path);
  });
}

function toggleAM(){
  AM=!AM;AS=null;
  var btn=document.getElementById('bam');
  document.getElementById('sv').classList.toggle('am',AM);
  if(AM){btn.classList.add('active');btn.textContent='↗ Connecting…';document.getElementById('hint').textContent='Click first subject → then second subject to draw arrow';}
  else{btn.classList.remove('active');btn.textContent='↗ Connect';document.getElementById('hint').textContent='pan: drag canvas | zoom: scroll | connect: click ↗ then two subjects';}
}

function handleAC(id){
  if(!AM)return;
  if(!AS){
    AS=id;
    var el=document.getElementById('s_'+id);if(el)el.classList.add('sel');
    document.getElementById('hint').textContent='Now click destination subject…';
  } else {
    if(AS!==id){
      var exists=ST.arrows.some(function(a){return a.from===AS&&a.to===id;});
      if(!exists){ST.arrows.push({id:uid(),from:AS,to:id});md();}
    }
    var el2=document.getElementById('s_'+AS);if(el2)el2.classList.remove('sel');
    AS=null;toggleAM();render();
  }
}

function delSelArrow(){
  if(!selArrow)return;
  ST.arrows=ST.arrows.filter(function(a){return a.id!==selArrow;});
  selArrow=null;document.getElementById('bda').style.display='none';
  md();drawArrows();
}

function dragNode(el,onMove,opts){
  opts=opts||{};
  var handle=opts.handle||el;
  var sx,sy,sl,st,dragging=false;
  handle.addEventListener('mousedown',function(e){
    if(opts.exclude&&e.target.closest(opts.exclude))return;
    dragging=true;sx=e.clientX;sy=e.clientY;
    sl=parseInt(el.style.left)||0;st=parseInt(el.style.top)||0;
    e.preventDefault();e.stopPropagation();
  });
  document.addEventListener('mousemove',function(e){
    if(!dragging)return;
    var dx=(e.clientX-sx)/sc,dy=(e.clientY-sy)/sc;
    var nx=Math.max(0,sl+dx),ny=Math.max(0,st+dy);
    el.style.left=nx+'px';el.style.top=ny+'px';
    onMove(nx,ny);
  });
  document.addEventListener('mouseup',function(){if(dragging){dragging=false;md();}});
}

var cw=document.getElementById('cw'),cv=document.getElementById('cv');
cw.addEventListener('mousedown',function(e){
  if(e.target!==cw&&e.target!==cv&&e.target.id!=='sv')return;
  panning=true;psx=e.clientX-px;psy=e.clientY-py;cw.style.cursor='grabbing';
});
document.addEventListener('mousemove',function(e){if(!panning)return;px=e.clientX-psx;py=e.clientY-psy;applyT();});
document.addEventListener('mouseup',function(){panning=false;cw.style.cursor='';});
cw.addEventListener('wheel',function(e){
  e.preventDefault();
  sc=Math.min(2,Math.max(0.25,sc*(e.deltaY>0?0.9:1.1)));applyT();
},{passive:false});
function applyT(){cv.style.transform='translate('+px+'px,'+py+'px) scale('+sc+')';cv.style.transformOrigin='0 0';}
function resetView(){px=0;py=0;sc=1;applyT();}

function addSubject(){
  ST.subjects.push({id:uid(),name:'New Subject',color:nc(),x:(-px/sc)+80,y:(-py/sc)+80,subfields:[{id:uid(),name:'General',color:'#888885',papers:[],open:true}]});
  md();render();
}

function md(){dirty=true;document.getElementById('svbtn').classList.add('on');}

function doSave(){
  var enc=encodeURIComponent(JSON.stringify(ST));
  window.parent.location.href=window.parent.location.href.split('?')[0]+'?bsave='+enc;
}

render();
</script></body></html>"""

    HTML = HTML.replace('__PAPERS__', papers_for_js).replace('__STATE__', board_state_js)
    components.html(HTML, height=700, scrolling=False)
    st.caption("💡 ＋ Subject to add a node · drag header to move · ↗ Connect then click two subjects for arrows · click arrow to select then 🗑 to delete · drag paper cards into subfield drop zones · 💾 Save board to persist")


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
        submitted = st.form_submit_button("✦ Analyze & Add", type="primary")

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
            st.success(f"✓ '{title}' added!")
            st.rerun()

# ── PAGE: UPLOAD PDF ──────────────────────────────────────────
elif page == "📎 Upload PDF":
    st.markdown('<div class="page-title">Upload PDF</div>', unsafe_allow_html=True)
    st.markdown('<div style="color:#888885;font-size:14px;margin-bottom:1.5rem;">Upload PDFs — text is extracted and analyzed locally, no API needed.</div>', unsafe_allow_html=True)

    if not PDF_SUPPORT:
        st.warning("pypdf not installed. Run: `pip install pypdf`", icon="⚠️")
    else:
        uploaded = st.file_uploader("Drop PDF files here", type=["pdf"], accept_multiple_files=True, label_visibility="collapsed")
        if uploaded:
            if st.button(f"✦ Process {len(uploaded)} PDF{'s' if len(uploaded)>1 else ''}", type="primary"):
                for f in uploaded:
                    with st.spinner(f"Reading '{f.name}'..."):
                        try:
                            file_bytes = f.read()
                            text = extract_pdf_text(file_bytes)
                            if not text or len(text) < 80:
                                st.error(f"'{f.name}': No readable text — may be a scanned PDF.")
                                continue
                            title = extract_title_from_text(text, f.name)
                            abstract = extract_abstract(text)
                            result = analyze_locally(title, text)
                            paper = {
                                "id": hashlib.md5((f.name+str(datetime.now())).encode()).hexdigest(),
                                "title": title, "authors": "", "year": "", "journal": "",
                                "type": "empirical", "abstract": abstract,
                                "full_text": text[:5000],
                                "summary": result["summary"], "findings": result["findings"],
                                "themes": result["themes"], "gaps": result["gaps"],
                                "analyzed": True, "source": "pdf", "filename": f.name,
                            }
                            st.session_state.papers.append(paper)
                            st.session_state.selected_id = paper["id"]
                            save_data()
                            st.success(f"✓ '{title[:60]}' added! Check Library to edit the title/authors.")
                        except Exception as e:
                            st.error(f"Error processing '{f.name}': {str(e)}")
                st.rerun()

# ── PAGE: SYNTHESIS ───────────────────────────────────────────
elif page == "🔗 Synthesis":
    st.markdown('<div class="page-title">Synthesis</div>', unsafe_allow_html=True)
    papers = st.session_state.papers

    if len(papers) < 2:
        st.info("Add at least 2 papers to see the synthesis.")
    else:
        st.markdown(f'<div style="color:#888885;font-size:14px;margin-bottom:1rem;">{len(papers)} papers in your library</div>', unsafe_allow_html=True)

        # Structured cross-cutting themes
        st.markdown('<div class="section-title">Cross-cutting Themes</div>', unsafe_allow_html=True)

        # Aggregate structured themes across all papers
        from collections import defaultdict
        agg = {"geopolitical": defaultdict(list), "period": defaultdict(list),
               "techniques": defaultdict(list), "datasets": defaultdict(list), "variables": defaultdict(list)}

        for p in papers:
            text = (p.get("abstract","") + " " + p.get("full_text","") + " " + p.get("summary","")).lower()
            structured = extract_structured_themes(text)
            for cat, items in structured.items():
                for item in items:
                    agg[cat][item].append(p["title"])

        cat_config = [
            ("geopolitical", "🌍 Geopolitical Focus", "#7eb8f7"),
            ("period",       "📅 Period of Data",     "#f5c97a"),
            ("techniques",   "🔬 Analysis Techniques","#c8f07a"),
            ("datasets",     "🗄 Datasets Used",      "#b49ffa"),
            ("variables",    "📊 Key Variables",      "#ff9f7a"),
        ]

        for cat_key, cat_label, color in cat_config:
            items = agg[cat_key]
            if not items:
                continue
            st.markdown(f'<div style="font-size:12px;font-weight:500;color:{color};font-family:DM Mono,monospace;text-transform:uppercase;letter-spacing:0.07em;margin:1rem 0 0.4rem;">{cat_label}</div>', unsafe_allow_html=True)
            chips = ""
            for item, paper_list in sorted(items.items(), key=lambda x: -len(x[1])):
                count = len(paper_list)
                tip = ", ".join(p[:40] for p in paper_list[:3])
                chips += f'<span title="{tip}" style="display:inline-block;background:#18181c;border:1px solid rgba(255,255,255,0.1);border-radius:100px;padding:4px 12px;font-size:12px;color:{color};margin:3px;cursor:default;">{item} <span style="opacity:0.5;font-size:10px;">×{count}</span></span>'
            st.markdown(f'<div style="margin-bottom:4px;">{chips}</div>', unsafe_allow_html=True)

        # Gaps
        st.markdown('<div class="section-title">Research Gaps Identified</div>', unsafe_allow_html=True)
        for g in get_all_gaps():
            st.markdown(f'<div class="gap-item">{g["gap"]}<br><span style="font-size:11px;color:#888885;font-family:DM Mono,monospace;">from: {g["paper"][:55]}</span></div>', unsafe_allow_html=True)

        # Paper summaries
        st.markdown('<div class="section-title">All Summaries</div>', unsafe_allow_html=True)
        synthesis_text = ""
        for p in papers:
            st.markdown(f'<div style="background:#18181c;border:1px solid rgba(255,255,255,0.07);border-radius:10px;padding:12px 16px;margin-bottom:10px;"><div style="font-size:14px;font-weight:500;color:#f0ede8;margin-bottom:6px;">{p["title"]}</div><div style="font-size:13px;color:#ccc8c0;line-height:1.7;">{p.get("summary","—")}</div></div>', unsafe_allow_html=True)
            synthesis_text += f"## {p['title']}\n{p.get('summary','')}\n\nFindings:\n" + "\n".join(f"- {f}" for f in p.get("findings",[])) + "\n\n"

        st.markdown('<div class="section-title">Export</div>', unsafe_allow_html=True)
        st.download_button("⬇ Download All Summaries (.txt)", synthesis_text, file_name="litlens-synthesis.txt", mime="text/plain")

# ── PAGE: NOTES ───────────────────────────────────────────────
elif page == "📝 Notes":
    st.markdown('<div class="page-title">Notes</div>', unsafe_allow_html=True)
    st.markdown('<div style="color:#888885;font-size:14px;margin-bottom:1.5rem;">Your personal research notes, saved in this session.</div>', unsafe_allow_html=True)

    if not st.session_state.papers:
        st.info("Add papers first to attach notes to them.")
    else:
        paper_titles = {p["id"]: p["title"] for p in st.session_state.papers}
        paper_ids = list(paper_titles.keys())
        # default to currently selected paper if available
        default_idx = 0
        if st.session_state.selected_id in paper_ids:
            default_idx = paper_ids.index(st.session_state.selected_id)
        selected_for_note = st.selectbox("Select paper", options=paper_ids, index=default_idx, format_func=lambda x: paper_titles[x])
        st.session_state.selected_id = selected_for_note

        existing = st.session_state.notes.get(selected_for_note, "")
        new_note = st.text_area("Your notes", value=existing, height=200, placeholder="Write your thoughts, critiques, connections to other work...")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 Save Note", type="primary", use_container_width=True):
                st.session_state.notes[selected_for_note] = new_note
                save_data()
                st.success("Saved!")
        with col2:
            if st.button("🗑 Clear Note", use_container_width=True):
                st.session_state.notes[selected_for_note] = ""
                st.rerun()

        # Show all notes
        if any(v for v in st.session_state.notes.values()):
            st.markdown('<div class="section-title">All Notes</div>', unsafe_allow_html=True)
            all_notes_text = ""
            for pid, note in st.session_state.notes.items():
                if note and pid in paper_titles:
                    st.markdown(f'<div style="background:#18181c;border:1px solid rgba(255,255,255,0.07);border-radius:10px;padding:12px 16px;margin-bottom:10px;"><div style="font-size:13px;font-weight:500;color:#c8f07a;margin-bottom:6px;">{paper_titles[pid]}</div><div style="font-size:13px;color:#ccc8c0;line-height:1.7;white-space:pre-wrap;">{note}</div></div>', unsafe_allow_html=True)
                    all_notes_text += f"## {paper_titles[pid]}\n{note}\n\n"
            if all_notes_text:
                st.download_button("⬇ Download All Notes", all_notes_text, file_name="litlens-notes.txt", mime="text/plain")
