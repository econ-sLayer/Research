import streamlit as st
import json
import os
import re
import hashlib
import time

try:
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    from sklearn.metrics import silhouette_score
    SKLEARN_OK = True
except ImportError:
    SKLEARN_OK = False

try:
    from scholarly import scholarly, ProxyGenerator
    SCHOLARLY_OK = True
except ImportError:
    SCHOLARLY_OK = False

try:
    import pypdf, io
    PDF_OK = True
except ImportError:
    PDF_OK = False

st.set_page_config(page_title="PaperCluster", page_icon="◎", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&display=swap');
html,body,[class*="css"]{font-family:'Inter',sans-serif;}
[data-testid="stSidebar"]{background:#18181c;border-right:1px solid rgba(255,255,255,0.07);}
[data-testid="stSidebar"] *{color:#f0ede8 !important;}
.stApp{background:#0e0e10;color:#f0ede8;}
#MainMenu,footer,header{visibility:hidden;}
.block-container{padding-top:1.5rem;}
.ptitle{font-size:1.8rem;font-weight:700;color:#f0ede8;margin-bottom:0.2rem;}
.sec{font-size:10px;letter-spacing:0.09em;text-transform:uppercase;color:#666;font-family:'DM Mono',monospace;margin:1.2rem 0 0.5rem;}
.card{background:#18181c;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:0.7rem 1rem;margin-bottom:0.45rem;}
.card h5{color:#f0ede8;margin:0 0 2px;font-size:13px;line-height:1.4;}
.card .m{color:#666;font-size:11px;font-family:'DM Mono',monospace;}
.chip{display:inline-block;padding:2px 10px;border-radius:100px;font-size:10px;font-family:'DM Mono',monospace;margin:2px;}
</style>
""", unsafe_allow_html=True)

# ── persistence ───────────────────────────────────────────────
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pc_data.json")

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"papers": [], "cluster_labels": {}, "cluster_keywords": {}}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "papers": st.session_state.papers,
            "cluster_labels": st.session_state.cluster_labels,
            "cluster_keywords": st.session_state.cluster_keywords,
        }, f, ensure_ascii=False, indent=2)

if "loaded" not in st.session_state:
    d = load_data()
    st.session_state.papers         = d.get("papers", [])
    st.session_state.cluster_labels  = d.get("cluster_labels", {})
    st.session_state.cluster_keywords = d.get("cluster_keywords", {})
    st.session_state.loaded = True

# ── helpers ───────────────────────────────────────────────────
COLS = ["#c8f07a","#7eb8f7","#b49ffa","#f5c97a","#ff9f7a","#5dc4a5","#ff6b6b","#e8a0bf","#a0e8d5","#f7d07e"]

def pid(title):
    return hashlib.md5(title.lower().strip().encode()).hexdigest()[:12]

def already_added(paper_id):
    return any(p["id"] == paper_id for p in st.session_state.papers)

def add_paper(p):
    if not already_added(p["id"]):
        st.session_state.papers.append(p)
        save_data()
        return True
    return False

# ── clustering ────────────────────────────────────────────────
def run_clustering(n_clusters=None):
    papers = st.session_state.papers
    if len(papers) < 3:
        return False, "Need at least 3 papers."
    if not SKLEARN_OK:
        return False, "Run: pip install scikit-learn"

    corpus = [
        (p.get("title","") + " " + p.get("abstract","") + " " + p.get("journal","")).strip()
        for p in papers
    ]

    vec = TfidfVectorizer(max_features=600, stop_words="english", ngram_range=(1,2), min_df=1)
    X = vec.fit_transform(corpus)

    # auto k
    if n_clusters is None:
        best_k, best_s = 2, -1
        for k in range(2, min(9, len(papers))):
            try:
                lbl = KMeans(n_clusters=k, random_state=42, n_init=10).fit_predict(X)
                if len(set(lbl)) < 2: continue
                s = silhouette_score(X, lbl)
                if s > best_s: best_k, best_s = k, s
            except Exception:
                pass
        n_clusters = best_k

    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = km.fit_predict(X)

    # 2-D coords via PCA
    coords = PCA(n_components=2, random_state=42).fit_transform(X.toarray())

    # top keywords per cluster
    fn = vec.get_feature_names_out()
    kws = {}
    for i in range(n_clusters):
        top = [fn[j] for j in km.cluster_centers_[i].argsort()[::-1][:6]]
        kws[str(i)] = top

    # assign
    for idx, (p, lbl, c) in enumerate(zip(papers, labels, coords)):
        st.session_state.papers[idx]["cluster"] = str(lbl)
        st.session_state.papers[idx]["x"] = float(c[0])
        st.session_state.papers[idx]["y"] = float(c[1])

    st.session_state.cluster_keywords = kws

    # auto-labels (only for new cluster ids)
    for cid, words in kws.items():
        if cid not in st.session_state.cluster_labels:
            st.session_state.cluster_labels[cid] = " · ".join(words[:3])

    save_data()
    return True, f"Done — {n_clusters} clusters."

# ── sidebar ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ◎ PaperCluster")
    n = len(st.session_state.papers)
    st.markdown(f'<div style="font-size:10px;color:#c8f07a;font-family:DM Mono,monospace;margin-bottom:6px;">{n} paper{"s" if n!=1 else ""}</div>', unsafe_allow_html=True)
    st.markdown("---")
    page = st.radio("", ["🗺 Map", "🎓 Google Scholar", "💻 From PC", "✏️ Manual"], label_visibility="collapsed")
    st.markdown("---")
    if n >= 3:
        if st.button("🔄 Cluster & Map", use_container_width=True, type="primary"):
            with st.spinner("Clustering..."):
                ok, msg = run_clustering()
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
        k_manual = st.number_input("Force # clusters (0=auto)", min_value=0, max_value=12, value=0)
        if k_manual > 0:
            if st.button("Run with fixed k", use_container_width=True):
                with st.spinner("Clustering..."):
                    ok, msg = run_clustering(k_manual)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

# ── PAGE: MAP ─────────────────────────────────────────────────
if page == "🗺 Map":
    st.markdown('<div class="ptitle">Cluster Map</div>', unsafe_allow_html=True)

    papers  = st.session_state.papers
    cl      = st.session_state.cluster_labels
    kws     = st.session_state.cluster_keywords

    if len(papers) < 3:
        st.info(f"Add at least 3 papers to cluster. You have {n} so far.")
    elif not any("x" in p for p in papers):
        st.info("Papers added. Click **Cluster & Map** in the sidebar.")
    else:
        # collect unique clusters
        cluster_ids = sorted(set(p.get("cluster","0") for p in papers if "x" in p))

        # Editable cluster names inline
        st.markdown('<div class="sec">Cluster labels — click to rename</div>', unsafe_allow_html=True)
        cols = st.columns(min(len(cluster_ids), 4))
        for i, cid in enumerate(cluster_ids):
            color = COLS[int(cid) % len(COLS)]
            with cols[i % len(cols)]:
                new = st.text_input(f"Cluster {cid}", value=cl.get(cid, f"Cluster {cid}"), key=f"lbl_{cid}", label_visibility="collapsed")
                if new != cl.get(cid):
                    st.session_state.cluster_labels[cid] = new
                    cl[cid] = new
                    save_data()
                st.markdown(f'<div style="font-size:10px;color:{color};font-family:DM Mono,monospace;margin-top:-8px;margin-bottom:6px;">{" · ".join(kws.get(cid,[])[:4])}</div>', unsafe_allow_html=True)

        # Build JS data
        plot_data = []
        for p in papers:
            if "x" not in p: continue
            cid = p.get("cluster","0")
            color = COLS[int(cid) % len(COLS)]
            plot_data.append({
                "title":   p["title"],
                "authors": p.get("authors",""),
                "year":    p.get("year",""),
                "journal": p.get("journal",""),
                "cluster": cid,
                "label":   cl.get(cid, f"Cluster {cid}"),
                "color":   color,
                "x": p["x"], "y": p["y"],
            })

        import streamlit.components.v1 as components
        MAP = r"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0;padding:0;font-family:Inter,sans-serif}
body{background:#0e0e10;overflow:hidden}
canvas{display:block}
#tip{position:fixed;background:#1e1e24;border:1px solid rgba(255,255,255,.15);border-radius:10px;
  padding:10px 14px;font-size:12px;color:#f0ede8;pointer-events:none;display:none;
  max-width:270px;z-index:99;line-height:1.6;box-shadow:0 4px 20px rgba(0,0,0,.5)}
#tip b{font-size:13px;display:block;margin-bottom:3px}
#tip small{color:#888;font-family:DM Mono,monospace;font-size:10px}
#tip .cl{display:inline-block;margin-top:5px;padding:2px 9px;border-radius:100px;font-size:10px;font-family:DM Mono,monospace}
#leg{position:fixed;bottom:12px;left:12px;background:#18181c;border:1px solid rgba(255,255,255,.08);
  border-radius:10px;padding:8px 12px;z-index:50;max-width:220px}
#leg .li{display:flex;align-items:center;gap:7px;margin-bottom:4px;font-size:11px;color:#ccc8c0}
#leg .li:last-child{margin-bottom:0}
.dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
#hint{position:fixed;bottom:12px;right:12px;font-size:10px;color:#333;font-family:DM Mono,monospace}
</style></head><body>
<canvas id="c"></canvas>
<div id="tip"><b id="tt"></b><small id="tm"></small><span id="tcl" class="cl"></span></div>
<div id="leg"></div>
<div id="hint">scroll = zoom · drag = pan</div>
<script>
var D=DATA_PH;
var cv=document.getElementById('c'),ctx=cv.getContext('2d');
var W,H,ox=0,oy=0,sc=1,drag=false,lx=0,ly=0;

function resize(){W=cv.width=window.innerWidth;H=cv.height=window.innerHeight;draw();}
window.addEventListener('resize',resize);

cv.addEventListener('wheel',function(e){
  e.preventDefault();
  var f=e.deltaY>0?0.88:1.14,mx=e.clientX,my=e.clientY;
  ox=mx-(mx-ox)*f; oy=my-(my-oy)*f; sc*=f; draw();
},{passive:false});
cv.addEventListener('mousedown',function(e){drag=true;lx=e.clientX;ly=e.clientY;});
window.addEventListener('mousemove',function(e){
  if(drag){ox+=e.clientX-lx;oy+=e.clientY-ly;lx=e.clientX;ly=e.clientY;draw();}
  tooltip(e.clientX,e.clientY);
});
window.addEventListener('mouseup',function(){drag=false;});

function wx(x){return ox+x*sc;}
function wy(y){return oy+y*sc;}

function initView(){
  if(!D.length)return;
  var xs=D.map(function(d){return d.x;}),ys=D.map(function(d){return d.y;});
  var mnx=Math.min.apply(null,xs),mxx=Math.max.apply(null,xs);
  var mny=Math.min.apply(null,ys),mxy=Math.max.apply(null,ys);
  var rw=mxx-mnx||1,rh=mxy-mny||1,pad=90;
  sc=Math.min((W-pad*2)/rw,(H-pad*2)/rh)*0.82;
  ox=W/2-((mnx+mxx)/2)*sc;
  oy=H/2-((mny+mxy)/2)*sc;
}

function hex2rgba(h,a){
  var r=parseInt(h.slice(1,3),16),g=parseInt(h.slice(3,5),16),b=parseInt(h.slice(5,7),16);
  return 'rgba('+r+','+g+','+b+','+a+')';
}

function draw(){
  ctx.clearRect(0,0,W,H);

  // group by cluster
  var grp={};
  D.forEach(function(d){if(!grp[d.cluster])grp[d.cluster]=[];grp[d.cluster].push(d);});

  // soft glow per cluster
  Object.keys(grp).forEach(function(cid){
    var pts=grp[cid];
    var cx=pts.reduce(function(s,p){return s+p.x;},0)/pts.length;
    var cy=pts.reduce(function(s,p){return s+p.y;},0)/pts.length;
    var maxR=0;
    pts.forEach(function(p){var d=Math.sqrt(Math.pow(p.x-cx,2)+Math.pow(p.y-cy,2));if(d>maxR)maxR=d;});
    var r=maxR*sc+50,sx=wx(cx),sy=wy(cy);
    var g=ctx.createRadialGradient(sx,sy,0,sx,sy,r);
    var col=pts[0].color;
    g.addColorStop(0,hex2rgba(col,0.12));
    g.addColorStop(1,hex2rgba(col,0));
    ctx.beginPath();ctx.arc(sx,sy,r,0,Math.PI*2);
    ctx.fillStyle=g;ctx.fill();

    // cluster label
    var label=pts[0].label||('Cluster '+cid);
    ctx.font='bold 11px DM Mono,monospace';
    ctx.fillStyle=col;
    ctx.textAlign='center';
    ctx.fillText(label.length>32?label.substr(0,30)+'...':label, sx, sy-(maxR*sc+34));
    ctx.textAlign='left';
  });

  // dots
  D.forEach(function(d){
    var sx=wx(d.x),sy=wy(d.y);
    var r=Math.max(5,Math.min(9,sc*0.12));
    ctx.beginPath();ctx.arc(sx,sy,r+2,0,Math.PI*2);
    ctx.fillStyle='rgba(0,0,0,0.5)';ctx.fill();
    ctx.beginPath();ctx.arc(sx,sy,r,0,Math.PI*2);
    ctx.fillStyle=d.color;ctx.fill();
    if(sc>55){
      ctx.font='9px Inter';
      ctx.fillStyle='rgba(240,237,232,0.55)';
      ctx.fillText(d.title.substr(0,26)+(d.title.length>26?'...':''),sx+r+4,sy+3);
    }
  });
}

function tooltip(mx,my){
  var best=null,bd=9999;
  D.forEach(function(d){
    var dist=Math.sqrt(Math.pow(mx-wx(d.x),2)+Math.pow(my-wy(d.y),2));
    if(dist<bd){bd=dist;best=d;}
  });
  var tip=document.getElementById('tip');
  if(best&&bd<18){
    document.getElementById('tt').textContent=best.title.substr(0,65)+(best.title.length>65?'...':'');
    var m=[best.authors?best.authors.substr(0,35):'',best.year,best.journal?best.journal.substr(0,28):''].filter(Boolean).join(' · ');
    document.getElementById('tm').textContent=m;
    var tcl=document.getElementById('tcl');
    tcl.textContent=best.label;
    tcl.style.background=best.color+'28';
    tcl.style.color=best.color;
    tip.style.display='block';
    tip.style.left=(mx+16)+'px';
    tip.style.top=Math.min(my-10,window.innerHeight-120)+'px';
  } else {
    tip.style.display='none';
  }
}

// legend
var leg=document.getElementById('leg'),seen={};
D.forEach(function(d){
  if(!seen[d.cluster]){
    seen[d.cluster]=true;
    var li=document.createElement('div');li.className='li';
    var dot=document.createElement('div');dot.className='dot';dot.style.background=d.color;
    var span=document.createElement('span');
    span.textContent=(d.label||('Cluster '+d.cluster)).substr(0,26);
    li.appendChild(dot);li.appendChild(span);leg.appendChild(li);
  }
});

resize();initView();draw();
</script></body></html>"""

        MAP = MAP.replace('DATA_PH', json.dumps(plot_data))
        components.html(MAP, height=560, scrolling=False)

        # Paper list by cluster
        st.markdown('<div class="sec">Papers by cluster</div>', unsafe_allow_html=True)
        for cid in cluster_ids:
            color  = COLS[int(cid) % len(COLS)]
            label  = cl.get(cid, f"Cluster {cid}")
            cpapers = [p for p in papers if p.get("cluster") == cid]
            with st.expander(f"{label}  —  {len(cpapers)} papers", expanded=False):
                for p in cpapers:
                    meta = " · ".join(x for x in [p.get("authors","")[:38], p.get("year",""), p.get("journal","")[:32]] if x)
                    st.markdown(f'<div class="card"><h5>{p["title"]}</h5><div class="m">{meta}</div></div>', unsafe_allow_html=True)


# ── PAGE: GOOGLE SCHOLAR ──────────────────────────────────────
elif page == "🎓 Google Scholar":
    st.markdown('<div class="ptitle">Google Scholar Search</div>', unsafe_allow_html=True)

    if not SCHOLARLY_OK:
        st.error("scholarly not installed. Run: `pip install scholarly` then restart.")
        st.code("pip install scholarly")
        st.stop()

    st.markdown('<div style="color:#888885;font-size:13px;margin-bottom:1.2rem;">Searches Google Scholar just like the real site — by keywords. Results include title, authors, year, abstract.</div>', unsafe_allow_html=True)

    query = st.text_input("Search Google Scholar", placeholder="e.g. monetary policy firm discouragement euro area SME")
    n_results = st.slider("Number of results to fetch", 5, 30, 10)

    if st.button("🔍 Search Scholar", type="primary") and query:
        results = []
        errors  = []
        progress = st.progress(0, text="Connecting to Google Scholar...")

        try:
            search_query = scholarly.search_pubs(query)
            for i in range(n_results):
                progress.progress(int((i+1)/n_results*100), text=f"Fetching result {i+1}/{n_results}...")
                try:
                    pub = next(search_query)
                    bib = pub.get("bib", {})
                    title = bib.get("title", "")
                    if not title:
                        continue
                    authors_list = bib.get("author", [])
                    if isinstance(authors_list, list):
                        authors = ", ".join(authors_list[:3])
                        if len(authors_list) > 3: authors += " et al."
                    else:
                        authors = str(authors_list)
                    year    = str(bib.get("pub_year", ""))
                    journal = bib.get("venue", "") or bib.get("journal", "") or bib.get("booktitle","")
                    abstract = bib.get("abstract","")
                    results.append({
                        "id":       pid(title),
                        "title":    title,
                        "authors":  authors,
                        "year":     year,
                        "journal":  journal,
                        "abstract": abstract[:2500],
                        "source":   "scholar",
                    })
                    time.sleep(0.3)  # be polite to Scholar
                except StopIteration:
                    break
                except Exception as e:
                    errors.append(str(e))
                    continue
        except Exception as e:
            st.error(f"Scholar search failed: {e}. Google Scholar may be blocking requests — try again in a few minutes.")
            st.stop()

        progress.empty()

        if not results:
            st.warning("No results returned. Google Scholar may be rate-limiting. Wait a minute and try again.")
        else:
            st.markdown(f'<div style="font-size:12px;color:#888885;font-family:DM Mono,monospace;margin-bottom:10px;">{len(results)} results found</div>', unsafe_allow_html=True)
            st.session_state["scholar_results"] = results

    # Show results
    results = st.session_state.get("scholar_results", [])
    if results:
        add_all = st.button("＋ Add all results", use_container_width=False)
        if add_all:
            added = sum(1 for r in results if add_paper(r))
            st.success(f"Added {added} new papers.")
            st.rerun()

        for r in results:
            exists = already_added(r["id"])
            c1, c2 = st.columns([5,1])
            with c1:
                abstr = r.get("abstract","")
                abstr_preview = f'<div style="font-size:10px;color:#555;margin-top:3px;">{abstr[:130]}{"..." if len(abstr)>130 else ""}</div>' if abstr else ""
                meta = " · ".join(x for x in [r.get("authors","")[:40], r.get("year",""), r.get("journal","")[:35]] if x)
                st.markdown(f'<div class="card"><h5>{r["title"]}</h5><div class="m">{meta}</div>{abstr_preview}</div>', unsafe_allow_html=True)
            with c2:
                if exists:
                    st.markdown('<div style="font-size:11px;color:#c8f07a;padding-top:10px;font-family:DM Mono,monospace;">✓ added</div>', unsafe_allow_html=True)
                else:
                    if st.button("＋ Add", key=f"sch_{r['id']}"):
                        add_paper(r)
                        st.rerun()


# ── PAGE: FROM PC ─────────────────────────────────────────────
elif page == "💻 From PC":
    st.markdown('<div class="ptitle">Add from PC</div>', unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["📄 Upload PDF", "📋 Paste BibTeX / RIS"])

    with tab1:
        if not PDF_OK:
            st.warning("pypdf not installed. Run: `pip install pypdf`")
        else:
            st.markdown('<div style="color:#888885;font-size:13px;margin-bottom:1rem;">Upload one or more PDF papers. Title and abstract are extracted automatically.</div>', unsafe_allow_html=True)
            files = st.file_uploader("Drop PDFs here", type=["pdf"], accept_multiple_files=True, label_visibility="collapsed")
            if files and st.button("Process PDFs", type="primary"):
                for f in files:
                    with st.spinner(f"Reading {f.name}..."):
                        try:
                            reader = pypdf.PdfReader(io.BytesIO(f.read()))
                            text = "".join(page.extract_text() or "" for page in reader.pages[:20])
                            if len(text) < 80:
                                st.error(f"{f.name}: no readable text (scanned PDF?)")
                                continue
                            # extract title from first meaningful line
                            lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 15]
                            title = lines[0][:120] if lines else f.name.replace(".pdf","")
                            # extract abstract
                            tl = text.lower()
                            abstract = ""
                            for marker in ["abstract", "summary"]:
                                idx = tl.find(marker)
                                if idx != -1:
                                    abstract = text[idx:idx+1500].strip()
                                    break
                            if not abstract:
                                abstract = text[:1000]
                            paper = {
                                "id": pid(title), "title": title,
                                "authors": "", "year": "", "journal": "",
                                "abstract": abstract[:2500], "source": "pdf",
                            }
                            if add_paper(paper):
                                st.success(f"Added: {title[:60]}")
                            else:
                                st.info(f"Already in library: {title[:50]}")
                        except Exception as e:
                            st.error(f"Error: {f.name} — {e}")
                st.rerun()

    with tab2:
        st.markdown('<div style="color:#888885;font-size:13px;margin-bottom:1rem;">Paste BibTeX entries exported from Zotero, Mendeley, or any reference manager.</div>', unsafe_allow_html=True)
        bibtex_text = st.text_area("Paste BibTeX here", height=250, placeholder='@article{smith2023,\n  title={...},\n  author={Smith, John},\n  year={2023},\n  journal={...},\n  abstract={...}\n}')

        if st.button("Parse & Add", type="primary") and bibtex_text.strip():
            # simple BibTeX parser (no external lib needed)
            entries = re.split(r'@\w+\s*\{', bibtex_text)
            added_count = 0
            for entry in entries[1:]:  # skip first empty
                def get_field(field, text):
                    m = re.search(field + r'\s*=\s*[\{"](.*?)[\}"](?:\s*[,\}])', text, re.IGNORECASE | re.DOTALL)
                    return m.group(1).strip() if m else ""

                title    = get_field("title", entry)
                authors  = get_field("author", entry)
                year     = get_field("year", entry)
                journal  = get_field("journal", entry) or get_field("booktitle", entry)
                abstract = get_field("abstract", entry)

                if not title:
                    continue

                # clean up LaTeX
                title    = re.sub(r'[{}]', '', title)
                abstract = re.sub(r'[{}]', '', abstract)
                authors  = re.sub(r'[{}]', '', authors)

                paper = {
                    "id": pid(title), "title": title,
                    "authors": authors[:120], "year": year,
                    "journal": journal[:100], "abstract": abstract[:2500],
                    "source": "bibtex",
                }
                if add_paper(paper):
                    added_count += 1

            if added_count:
                st.success(f"Added {added_count} papers.")
                st.rerun()
            else:
                st.warning("No new papers found in BibTeX. Check format or they may already be in the library.")


# ── PAGE: MANUAL ──────────────────────────────────────────────
elif page == "✏️ Manual":
    st.markdown('<div class="ptitle">Add Manually</div>', unsafe_allow_html=True)
    st.markdown('<div style="color:#888885;font-size:13px;margin-bottom:1.2rem;">The abstract is what drives clustering — the more complete, the better.</div>', unsafe_allow_html=True)

    with st.form("mf"):
        title    = st.text_input("Title *")
        c1, c2   = st.columns(2)
        with c1:
            authors = st.text_input("Authors")
            journal = st.text_input("Journal / Venue")
        with c2:
            year    = st.text_input("Year")
        abstract = st.text_area("Abstract *", height=160)
        sub = st.form_submit_button("Add Paper", type="primary")

    if sub:
        if not title or not abstract:
            st.error("Title and abstract are required.")
        else:
            paper = {
                "id": pid(title), "title": title,
                "authors": authors, "year": year,
                "journal": journal, "abstract": abstract[:2500],
                "source": "manual",
            }
            if add_paper(paper):
                st.success(f"Added: {title[:60]}")
                st.rerun()
            else:
                st.warning("Already in library.")
