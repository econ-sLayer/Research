import streamlit as st
import json
import re
import io
from datetime import datetime

try:
    import pypdf
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

st.set_page_config(
    page_title="LitLens — AI Research Assistant",
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
.gap-label { font-family: 'DM Mono', monospace; font-size: 10px; color: #ff6b6b; opacity: 0.7; margin-bottom: 4px; }
.section-title { font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #888885; font-family: 'DM Mono', monospace; margin: 1.25rem 0 0.6rem; }
.page-title { font-family: 'Instrument Serif', serif; font-size: 2rem; letter-spacing: -0.01em; color: #f0ede8; margin-bottom: 0.25rem; }
.summary-block { background: #18181c; border: 1px solid rgba(255,255,255,0.07); border-radius: 12px; padding: 1rem 1.25rem; font-size: 14px; line-height: 1.8; color: #ccc8c0; }
</style>
""", unsafe_allow_html=True)

if "papers" not in st.session_state:
    st.session_state.papers = []
if "selected_id" not in st.session_state:
    st.session_state.selected_id = None
if "api_key" not in st.session_state:
    st.session_state.api_key = ""

def get_model():
    key = st.session_state.api_key.strip()
    if not key or not GENAI_AVAILABLE:
        return None
    try:
        genai.configure(api_key=key)
        return genai.GenerativeModel("gemini-1.5-flash")
    except Exception:
        return None

def call_gemini(prompt: str) -> str:
    model = get_model()
    if not model:
        return ""
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Error: {str(e)}"

def parse_json_response(text: str) -> dict:
    clean = re.sub(r"```json|```", "", text).strip()
    try:
        return json.loads(clean)
    except Exception:
        match = re.search(r'\{.*\}', clean, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return {}

def extract_pdf_text(file_bytes: bytes) -> str:
    if not PDF_SUPPORT:
        return ""
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    text = ""
    for page in reader.pages[:20]:
        text += page.extract_text() or ""
    return text.strip()

def analyze_text(title: str, text: str) -> dict:
    prompt = f"""Analyze this research paper. Return ONLY a JSON object:
{{"summary": "2-3 sentence summary", "findings": ["finding 1", "finding 2", "finding 3"], "themes": ["theme1", "theme2", "theme3"], "gaps": ["gap 1", "gap 2"]}}
Title: {title}
Text: {text[:4000]}
Return ONLY valid JSON, no markdown, no explanation."""
    return parse_json_response(call_gemini(prompt))

def analyze_pdf_content(file_bytes: bytes, filename: str) -> dict:
    text = extract_pdf_text(file_bytes)
    if not text or len(text) < 100:
        return {"error": "No readable text found — this may be a scanned PDF."}
    prompt = f"""Analyze this research paper. Return ONLY a JSON object:
{{"title": "full title", "authors": "authors string", "year": "year", "journal": "venue", "type": "empirical", "abstract": "abstract text", "summary": "2-3 sentence summary", "findings": ["f1","f2","f3"], "themes": ["t1","t2","t3"], "gaps": ["g1","g2"]}}
Type must be one of: empirical, methods, review, theory.
Paper text: {text[:4500]}
Return ONLY valid JSON, no markdown, no explanation."""
    result = parse_json_response(call_gemini(prompt))
    if not result.get("title"):
        result["title"] = filename.replace(".pdf", "")
    return result

def tag_html(paper_type: str) -> str:
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

with st.sidebar:
    st.markdown("## ◎ LitLens")
    st.markdown("---")
    if not GENAI_AVAILABLE:
        st.error("Run: pip install -r requirements.txt")
    else:
        api_key = st.text_input("Google Gemini API Key", value=st.session_state.api_key, type="password", placeholder="AIza...", help="Free at aistudio.google.com — no credit card needed")
        st.session_state.api_key = api_key
        if api_key:
            st.success("API key set ✓", icon="✅")
        else:
            st.info("Get a free key at aistudio.google.com", icon="🔑")
    st.markdown("---")
    st.markdown("**Navigation**")
    page = st.radio("page", ["📚 Library", "📄 Add Paper", "📎 Upload PDF", "🔗 Synthesis", "🔍 Discover"], label_visibility="collapsed")
    st.markdown("---")
    papers = st.session_state.papers
    if papers:
        st.markdown(f"**{len(papers)} paper{'s' if len(papers)!=1 else ''}**")
        search = st.text_input("Search", placeholder="Filter papers...", label_visibility="collapsed")
        filtered = [p for p in papers if search.lower() in p["title"].lower() or search.lower() in p.get("authors","").lower()] if search else papers
        for p in filtered:
            label = f"{'📄 ' if p.get('source')=='pdf' else ''}{p['title'][:45]}{'...' if len(p['title'])>45 else ''}"
            if st.button(label, key=f"sel_{p['id']}", use_container_width=True):
                st.session_state.selected_id = p["id"]
                st.rerun()

ready = bool(st.session_state.api_key.strip()) and GENAI_AVAILABLE

if page == "📚 Library":
    selected = next((p for p in st.session_state.papers if p["id"] == st.session_state.selected_id), None)
    if not selected:
        st.markdown('<div class="page-title">Library</div>', unsafe_allow_html=True)
        st.markdown('<div style="color:#888885; font-size:14px; margin-bottom:2rem;">Select a paper from the sidebar, or add one to get started.</div>', unsafe_allow_html=True)
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
            if st.button("🗑 Remove paper", type="secondary"):
                st.session_state.papers = [x for x in st.session_state.papers if x["id"] != p["id"]]
                st.session_state.selected_id = None
                st.rerun()
        meta_parts = [x for x in [p.get("authors"), p.get("year"), p.get("journal")] if x]
        st.markdown(f'<div style="color:#888885; font-size:13px; font-family:DM Mono,monospace; margin-bottom:1rem;">{" · ".join(meta_parts)}</div>', unsafe_allow_html=True)
        st.markdown(tag_html(p.get("type","empirical")), unsafe_allow_html=True)
        st.markdown('<div class="section-title">Summary</div>', unsafe_allow_html=True)
        if p.get("summary"):
            st.markdown(f'<div class="summary-block">{p["summary"]}</div>', unsafe_allow_html=True)
        else:
            st.info("Not yet analyzed.")
        if p.get("findings"):
            st.markdown('<div class="section-title">Key Findings</div>', unsafe_allow_html=True)
            cols = st.columns(2)
            for i, f in enumerate(p["findings"]):
                with cols[i % 2]:
                    st.markdown(f'<div class="finding"><div class="finding-label">finding {i+1}</div>{f}</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Actions</div>', unsafe_allow_html=True)
        acol1, acol2, acol3, acol4 = st.columns(4)
        with acol1:
            if st.button("✦ Re-analyze", use_container_width=True, disabled=not ready):
                with st.spinner("Analyzing..."):
                    result = analyze_text(p["title"], p.get("abstract",""))
                    p.update({k: result[k] for k in ["summary","findings","themes","gaps"] if k in result})
                    p["analyzed"] = True
                st.rerun()
        with acol2:
            if st.button("Implications", use_container_width=True, disabled=not ready):
                st.session_state[f"action_{p['id']}"] = "implications"
        with acol3:
            if st.button("Methodology", use_container_width=True, disabled=not ready):
                st.session_state[f"action_{p['id']}"] = "methods"
        with acol4:
            if st.button("Critical View", use_container_width=True, disabled=not ready):
                st.session_state[f"action_{p['id']}"] = "critique"
        action_key = f"action_{p['id']}"
        if action_key in st.session_state and ready:
            action = st.session_state[action_key]
            prompts = {
                "implications": f"What are the practical and theoretical implications of this paper?\n\nPaper: {p['title']}\n{p.get('abstract','')}",
                "methods": f"Describe the methodology in detail. Strengths and weaknesses?\n\nPaper: {p['title']}\n{p.get('abstract','')}",
                "critique": f"Provide a critical analysis. Limitations and challenges?\n\nPaper: {p['title']}\n{p.get('abstract','')}",
            }
            label = {"implications":"Implications","methods":"Methodology","critique":"Critical View"}[action]
            st.markdown(f'<div class="section-title">{label}</div>', unsafe_allow_html=True)
            with st.spinner(f"Generating..."):
                result = call_gemini(prompts[action])
            st.markdown(f'<div class="summary-block">{result}</div>', unsafe_allow_html=True)
            del st.session_state[action_key]
        if p.get("abstract"):
            with st.expander("Abstract / Full Text"):
                st.markdown(f'<div style="font-size:13px; color:#888885; line-height:1.8;">{p["abstract"]}</div>', unsafe_allow_html=True)

elif page == "📄 Add Paper":
    st.markdown('<div class="page-title">Add Paper</div>', unsafe_allow_html=True)
    with st.form("add_paper_form"):
        title = st.text_input("Title *", placeholder="Full paper title...")
        col1, col2 = st.columns(2)
        with col1:
            authors = st.text_input("Authors", placeholder="Smith et al., 2023")
            journal = st.text_input("Journal / Venue", placeholder="Nature, NeurIPS, etc.")
        with col2:
            year = st.text_input("Year", placeholder="2024")
            paper_type = st.selectbox("Type", ["empirical", "methods", "review", "theory"])
        abstract = st.text_area("Abstract / Text *", placeholder="Paste the abstract or key excerpts here...", height=150)
        submitted = st.form_submit_button("✦ Analyze & Add", type="primary", disabled=not ready)
    if submitted:
        if not title or not abstract:
            st.error("Title and abstract are required.")
        else:
            with st.spinner("Analyzing paper..."):
                result = analyze_text(title, abstract)
                paper = {"id": str(datetime.now().timestamp()), "title": title, "authors": authors, "year": year, "journal": journal, "type": paper_type, "abstract": abstract, "summary": result.get("summary",""), "findings": result.get("findings",[]), "themes": result.get("themes",[]), "gaps": result.get("gaps",[]), "analyzed": True, "source": "manual"}
                st.session_state.papers.append(paper)
                st.session_state.selected_id = paper["id"]
            st.success(f"✓ '{title}' added and analyzed!")
            st.rerun()

elif page == "📎 Upload PDF":
    st.markdown('<div class="page-title">Upload PDF</div>', unsafe_allow_html=True)
    if not PDF_SUPPORT:
        st.warning("pypdf is not installed. Run: pip install -r requirements.txt", icon="⚠️")
    elif not ready:
        st.warning("Enter your Gemini API key in the sidebar first.", icon="🔑")
    else:
        uploaded = st.file_uploader("Drop PDF files here", type=["pdf"], accept_multiple_files=True, label_visibility="collapsed")
        if uploaded:
            if st.button(f"✦ Analyze {len(uploaded)} PDF{'s' if len(uploaded)>1 else ''}", type="primary"):
                for f in uploaded:
                    with st.spinner(f"Analyzing '{f.name}'..."):
                        try:
                            result = analyze_pdf_content(f.read(), f.name)
                            if "error" in result:
                                st.error(f"'{f.name}': {result['error']}")
                                continue
                            paper = {"id": str(datetime.now().timestamp())+f.name, "title": result.get("title", f.name.replace(".pdf","")), "authors": result.get("authors",""), "year": result.get("year",""), "journal": result.get("journal",""), "type": result.get("type","empirical"), "abstract": result.get("abstract",""), "summary": result.get("summary",""), "findings": result.get("findings",[]), "themes": result.get("themes",[]), "gaps": result.get("gaps",[]), "analyzed": True, "source": "pdf", "filename": f.name}
                            st.session_state.papers.append(paper)
                            st.session_state.selected_id = paper["id"]
                            st.success(f"✓ '{paper['title']}' added!")
                        except Exception as e:
                            st.error(f"Error: {str(e)}")
                st.rerun()

elif page == "🔗 Synthesis":
    st.markdown('<div class="page-title">Synthesis</div>', unsafe_allow_html=True)
    papers = st.session_state.papers
    if len(papers) < 2:
        st.info("Add at least 2 papers to generate a synthesis.")
    else:
        themes = get_all_themes()
        colors = ["#c8f07a","#7eb8f7","#b49ffa","#f5c97a","#ff6b6b","#5dc4a5"]
        st.markdown('<div class="section-title">Cross-cutting Themes</div>', unsafe_allow_html=True)
        if themes:
            tcols = st.columns(min(len(themes), 3))
            for i, (theme, count) in enumerate(themes[:9]):
                with tcols[i % 3]:
                    c = colors[i % len(colors)]
                    st.markdown(f'<div style="background:#18181c;border:1px solid rgba(255,255,255,0.07);border-radius:8px;padding:10px 14px;margin-bottom:8px;"><span style="color:{c};font-weight:600;font-size:14px;">{theme}</span><br><span style="color:#888885;font-size:11px;font-family:DM Mono,monospace;">{count} paper{"s" if count!=1 else ""}</span></div>', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Research Gaps</div>', unsafe_allow_html=True)
        for g in get_all_gaps():
            st.markdown(f'<div class="gap-item"><div class="gap-label">gap</div>{g["gap"]}<br><span style="font-size:11px;color:#888885;font-family:DM Mono,monospace;">from: {g["paper"][:60]}</span></div>', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Generate Literature Review</div>', unsafe_allow_html=True)
        scol1, scol2, scol3, scol4 = st.columns(4)
        synth_type = None
        with scol1:
            if st.button("✦ Full Review", use_container_width=True, disabled=not ready): synth_type = "full"
        with scol2:
            if st.button("Themes", use_container_width=True, disabled=not ready): synth_type = "themes"
        with scol3:
            if st.button("Methods", use_container_width=True, disabled=not ready): synth_type = "methods"
        with scol4:
            if st.button("Gaps", use_container_width=True, disabled=not ready): synth_type = "gaps"
        if synth_type and ready:
            paper_info = "\n\n---\n\n".join([f"Title: {p['title']}\nSummary: {p.get('summary','')}\nThemes: {', '.join(p.get('themes',[]))}\nGaps: {'; '.join(p.get('gaps',[]))}" for p in papers])
            prompts = {"full": f"Write a formal literature review for these {len(papers)} papers with introduction, thematic synthesis, methodology comparison, and research gaps.\n\n{paper_info}", "themes": f"Identify and discuss the major cross-cutting themes across these papers.\n\n{paper_info}", "methods": f"Compare and contrast the research methodologies across these papers.\n\n{paper_info}", "gaps": f"Write a focused section on research gaps and future directions.\n\n{paper_info}"}
            with st.spinner("Generating synthesis..."):
                result = call_gemini(prompts[synth_type])
            st.markdown(f'<div class="summary-block" style="white-space:pre-wrap;">{result}</div>', unsafe_allow_html=True)
            st.download_button("⬇ Download as .txt", result, file_name="litlens-synthesis.txt", mime="text/plain")

elif page == "🔍 Discover":
    st.markdown('<div class="page-title">Discover</div>', unsafe_allow_html=True)
    if not ready:
        st.warning("Enter your Gemini API key in the sidebar first.", icon="🔑")
    else:
        query = st.text_area("Your research topic", placeholder="e.g. I'm studying transformer attention for clinical NLP...", height=100)
        dcol1, dcol2, dcol3, dcol4 = st.columns(4)
        disc_type = None
        with dcol1:
            if st.button("✦ Recommendations", use_container_width=True): disc_type = "general"
        with dcol2:
            if st.button("Seminal Papers", use_container_width=True): disc_type = "seminal"
        with dcol3:
            if st.button("Recent Advances", use_container_width=True): disc_type = "recent"
        with dcol4:
            if st.button("Methods & Tools", use_container_width=True): disc_type = "methods"
        if disc_type and query.strip():
            context = f"\nResearcher has: {', '.join(p['title'] for p in st.session_state.papers)}." if st.session_state.papers else ""
            prompts = {"general": f"Studying: '{query}'{context}\nProvide: 5-8 key papers (with authors/year), 3 databases/tools, and key search terms.", "seminal": f"List the most important seminal papers for: '{query}'{context}\nFor each: title, authors, year, why it matters.", "recent": f"Most important advances (2020-2025) in: '{query}'{context}\nList key papers and trends.", "methods": f"Best methodological approaches for: '{query}'{context}\nRecommend methods, tools, datasets."}
            with st.spinner("Searching..."):
                result = call_gemini(prompts[disc_type])
            st.markdown(f'<div class="summary-block" style="white-space:pre-wrap;">{result}</div>', unsafe_allow_html=True)
        elif disc_type:
            st.warning("Please describe your research topic first.")
