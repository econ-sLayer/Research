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

    st.markdown('<div class="page-title">Board</div>', unsafe_allow_html=True)
    st.markdown('<div style="color:#888885;font-size:13px;margin-bottom:1.2rem;">Drag papers into repositories. Use the panel below to create your own groups.</div>', unsafe_allow_html=True)

    papers     = st.session_state.papers
    repos      = st.session_state.repos
    paper_repos= st.session_state.paper_repos

    if not papers:
        st.info("Add papers first, then come here to organise them into repositories.")
    else:
        # Ensure every paper has a repo assignment
        for p in papers:
            if p["id"] not in paper_repos:
                paper_repos[p["id"]] = "r1"

        # ── Manage repositories ───────────────────────────────
        with st.expander("⚙️  Manage repositories"):
            mc1, mc2, mc3 = st.columns([3, 1, 1])
            with mc1:
                new_name = st.text_input("New repository name", placeholder="e.g. European studies, IV methods…", key="new_repo_name")
            with mc2:
                new_color = st.color_picker("Colour", "#c8f07a", key="new_repo_color")
            with mc3:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                if st.button("＋ Create", use_container_width=True):
                    if new_name.strip():
                        nid = "r_" + str(len(repos)) + "_" + new_name[:10].replace(" ", "")
                        st.session_state.repos.append({"id": nid, "name": new_name.strip(), "color": new_color})
                        save_data()
                        st.rerun()

            deletable = [r for r in st.session_state.repos if r["id"] != "r1"]
            if deletable:
                del_choice = st.selectbox("Delete a repository", ["—"] + [r["name"] for r in deletable], key="del_repo")
                if st.button("🗑  Delete", key="del_repo_btn") and del_choice != "—":
                    del_id = next(r["id"] for r in deletable if r["name"] == del_choice)
                    st.session_state.repos = [r for r in st.session_state.repos if r["id"] != del_id]
                    for pid in list(st.session_state.paper_repos):
                        if st.session_state.paper_repos[pid] == del_id:
                            st.session_state.paper_repos[pid] = "r1"
                    save_data()
                    st.rerun()

        # Re-read after possible changes
        repos       = st.session_state.repos
        paper_repos = st.session_state.paper_repos

        # ── Drag-and-drop board (HTML component) ─────────────
        import json as _json

        cards_data = _json.dumps([{
            "id":      p["id"],
            "title":   p["title"],
            "authors": p.get("authors", ""),
            "year":    p.get("year", ""),
            "type":    p.get("type", "empirical"),
            "source":  p.get("source", "manual"),
            "summary": (p.get("summary", "")[:110] + "…") if p.get("summary") else "",
            "repo":    paper_repos.get(p["id"], "r1"),
        } for p in papers])

        repos_data = _json.dumps(repos)

        board_html = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
*{box-sizing:border-box;margin:0;padding:0;font-family:Inter,sans-serif}
body{background:#0e0e10;color:#f0ede8;padding:6px}
.board{display:flex;gap:12px;overflow-x:auto;padding-bottom:16px;min-height:480px;align-items:flex-start}
.col{min-width:220px;max-width:220px;background:#18181c;border:1px solid rgba(255,255,255,0.07);border-radius:12px;padding:11px;display:flex;flex-direction:column;gap:7px;transition:border-color .15s,background .15s}
.col.over{border-color:rgba(255,255,255,0.35);background:#22222a}
.col-header{font-size:11px;font-weight:600;font-family:'DM Mono',monospace;letter-spacing:.07em;text-transform:uppercase;padding-bottom:8px;border-bottom:1px solid rgba(255,255,255,0.07);display:flex;align-items:center;gap:7px;margin-bottom:2px}
.dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
.cnt{opacity:.4;font-size:10px;margin-left:auto}
.card{background:#0e0e10;border:1px solid rgba(255,255,255,0.09);border-radius:9px;padding:9px 11px;cursor:grab;transition:border-color .12s,transform .1s,opacity .1s;user-select:none}
.card:hover{border-color:rgba(255,255,255,0.22);transform:translateY(-2px)}
.card.dragging{opacity:.35;transform:rotate(2deg) scale(.97)}
.ctitle{font-size:12px;font-weight:500;color:#f0ede8;line-height:1.4;margin-bottom:3px}
.cmeta{font-size:10px;color:#888885;font-family:'DM Mono',monospace;margin-bottom:4px}
.csumm{font-size:11px;color:#77746e;line-height:1.45;margin-bottom:5px}
.tag{display:inline-block;padding:1px 7px;border-radius:100px;font-size:10px;font-family:'DM Mono',monospace;font-weight:500;margin-right:3px}
.tag-empirical{background:rgba(245,201,122,.12);color:#f5c97a}
.tag-methods{background:rgba(126,184,247,.12);color:#7eb8f7}
.tag-review{background:rgba(200,240,122,.12);color:#c8f07a}
.tag-theory{background:rgba(180,159,250,.12);color:#b49ffa}
.tag-pdf{background:rgba(126,184,247,.12);color:#7eb8f7}
.empty{border:1.5px dashed rgba(255,255,255,0.1);border-radius:9px;height:56px;display:flex;align-items:center;justify-content:center;font-size:10px;color:#444;font-family:'DM Mono',monospace}
#savebar{position:fixed;bottom:14px;right:14px;display:flex;gap:8px;align-items:center;z-index:99}
#savebtn{background:#c8f07a;color:#0e0e10;border:none;border-radius:8px;padding:8px 18px;font-size:13px;font-weight:600;cursor:pointer;display:none}
#savebtn.on{display:block}
#savedmsg{background:#18181c;color:#c8f07a;border:1px solid rgba(200,240,122,.3);border-radius:8px;padding:8px 16px;font-size:12px;font-family:'DM Mono',monospace;display:none}
#savedmsg.on{display:block}
</style>
</head>
<body>
<div class="board" id="board"></div>
<div id="savebar">
  <div id="savedmsg">✓ Saved!</div>
  <button id="savebtn" onclick="doSave()">💾 Save</button>
</div>
<script>
var papers=PAPERS_DATA;
var repos=REPOS_DATA;
var assign={};
papers.forEach(function(p){assign[p.id]=p.repo});
var dragging=null,dirty=false;

function build(){
  var board=document.getElementById('board');
  board.innerHTML='';
  repos.forEach(function(repo){
    var col=document.createElement('div');
    col.className='col';
    col.dataset.rid=repo.id;
    var rp=papers.filter(function(p){return assign[p.id]===repo.id});
    col.innerHTML='<div class="col-header"><div class="dot" style="background:'+repo.color+'"></div>'+repo.name+'<span class="cnt">'+rp.length+'</span></div>';
    if(rp.length===0){
      var em=document.createElement('div');
      em.className='empty';
      em.textContent='drop here';
      col.appendChild(em);
    }
    rp.forEach(function(p){
      var c=document.createElement('div');
      c.className='card';
      c.draggable=true;
      c.dataset.pid=p.id;
      var meta=(p.authors?p.authors.substring(0,28):'')+(p.year?' · '+p.year:'');
      var pdfTag=p.source==='pdf'?'<span class="tag tag-pdf">PDF</span>':'';
      c.innerHTML='<div class="ctitle">'+p.title+'</div>'
        +(meta?'<div class="cmeta">'+meta+'</div>':'')
        +(p.summary?'<div class="csumm">'+p.summary+'</div>':'')
        +'<span class="tag tag-'+p.type+'">'+p.type+'</span>'+pdfTag;
      c.addEventListener('dragstart',function(e){
        dragging=p.id;
        setTimeout(function(){c.classList.add('dragging')},0);
        e.dataTransfer.effectAllowed='move';
      });
      c.addEventListener('dragend',function(){
        c.classList.remove('dragging');
        dragging=null;
        document.querySelectorAll('.col').forEach(function(x){x.classList.remove('over')});
      });
      col.appendChild(c);
    });
    col.addEventListener('dragover',function(e){e.preventDefault();col.classList.add('over')});
    col.addEventListener('dragleave',function(){col.classList.remove('over')});
    col.addEventListener('drop',function(e){
      e.preventDefault();col.classList.remove('over');
      if(dragging && assign[dragging]!==repo.id){
        assign[dragging]=repo.id;
        dirty=true;
        document.getElementById('savebtn').classList.add('on');
        build();
      }
    });
    board.appendChild(col);
  });
}

function doSave(){
  window.parent.postMessage({type:'litlens_assign',data:JSON.stringify(assign)},'*');
  document.getElementById('savebtn').classList.remove('on');
  document.getElementById('savedmsg').classList.add('on');
  setTimeout(function(){document.getElementById('savedmsg').classList.remove('on')},2000);
  dirty=false;
}

build();
</script>
</body>
</html>"""

        board_html = board_html.replace("PAPERS_DATA", cards_data).replace("REPOS_DATA", repos_data)
        components.html(board_html, height=580, scrolling=True)

        # ── Fallback assignment (selectboxes, always visible) ─
        st.markdown('<div class="section-title" style="margin-top:1.5rem;">Assign papers to repositories</div>', unsafe_allow_html=True)
        st.markdown('<div style="font-size:12px;color:#888885;margin-bottom:10px;line-height:1.6;">Use the drag-and-drop board above, or assign directly here. Changes save instantly.</div>', unsafe_allow_html=True)

        repo_opts   = {r["id"]: r["name"] for r in repos}
        repo_keys   = list(repo_opts.keys())
        changed     = False
        cols2 = st.columns(2)
        for i, p in enumerate(papers):
            with cols2[i % 2]:
                cur = paper_repos.get(p["id"], "r1")
                cur_idx = repo_keys.index(cur) if cur in repo_keys else 0
                choice = st.selectbox(
                    (p["title"][:48] + "…") if len(p["title"]) > 48 else p["title"],
                    options=repo_keys,
                    format_func=lambda x: repo_opts[x],
                    index=cur_idx,
                    key="ra_" + p["id"],
                )
                if choice != cur:
                    st.session_state.paper_repos[p["id"]] = choice
                    changed = True

        if changed:
            save_data()
            st.rerun()


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
