import streamlit as st
import json
import os
import re
import time
import hashlib
from datetime import datetime

# ── optional deps ─────────────────────────────────────────────
try:
    from scholarly import scholarly
    SCHOLARLY_OK = True
except ImportError:
    SCHOLARLY_OK = False

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
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

st.set_page_config(
    page_title="PaperCluster",
    page_icon="◎",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&display=swap');
html,body,[class*="css"]{font-family:'Inter',sans-serif;}
[data-testid="stSidebar"]{background:#18181c;border-right:1px solid rgba(255,255,255,0.07);}
[data-testid="stSidebar"] *{color:#f0ede8 !important;}
.stApp{background:#0e0e10;color:#f0ede8;}
#MainMenu,footer,header{visibility:hidden;}
.block-container{padding-top:1.5rem;}
.page-title{font-size:1.8rem;font-weight:700;color:#f0ede8;margin-bottom:0.25rem;}
.section-title{font-size:11px;letter-spacing:0.08em;text-transform:uppercase;color:#888885;font-family:'DM Mono',monospace;margin:1.25rem 0 0.6rem;}
.paper-card{background:#18181c;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:0.75rem 1rem;margin-bottom:0.5rem;}
.paper-card h5{color:#f0ede8;margin:0 0 3px;font-size:13px;}
.paper-card .meta{color:#888885;font-size:11px;font-family:'DM Mono',monospace;}
.cluster-chip{display:inline-block;padding:3px 12px;border-radius:100px;font-size:11px;font-family:'DM Mono',monospace;font-weight:500;margin:2px;}
.stat-box{background:#18181c;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:1rem;text-align:center;}
.stat-num{font-size:1.8rem;font-weight:700;color:#c8f07a;}
.stat-label{font-size:11px;color:#888885;font-family:'DM Mono',monospace;text-transform:uppercase;letter-spacing:0.07em;}
</style>
""", unsafe_allow_html=True)

# ── persistence ───────────────────────────────────────────────
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "papercluster_data.json")

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"papers": [], "clusters": {}, "cluster_labels": {}}

def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "papers": st.session_state.papers,
                "clusters": st.session_state.clusters,
                "cluster_labels": st.session_state.cluster_labels,
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.warning(f"Save error: {e}")

# ── session init ──────────────────────────────────────────────
if "loaded" not in st.session_state:
    data = load_data()
    st.session_state.papers = data.get("papers", [])
    st.session_state.clusters = data.get("clusters", {})
    st.session_state.cluster_labels = data.get("cluster_labels", {})
    st.session_state.loaded = True

# ── helpers ───────────────────────────────────────────────────
CLUSTER_COLORS = [
    "#c8f07a","#7eb8f7","#b49ffa","#f5c97a",
    "#ff9f7a","#5dc4a5","#ff6b6b","#e8a0bf",
    "#a0e8d5","#f7d07e","#d0a0f7","#a0c8f7",
]

def paper_id(title):
    return hashlib.md5(title.lower().strip().encode()).hexdigest()[:12]

def fetch_from_crossref(query):
    """Fetch paper metadata from CrossRef API (free, no key needed)"""
    if not REQUESTS_OK:
        return []
    try:
        url = f"https://api.crossref.org/works?query={requests.utils.quote(query)}&rows=10&select=title,author,published,abstract,DOI,container-title"
        r = requests.get(url, timeout=10, headers={"User-Agent": "PaperCluster/1.0 (research tool)"})
        if r.status_code != 200:
            return []
        items = r.json().get("message", {}).get("items", [])
        results = []
        for item in items:
            title_list = item.get("title", [])
            if not title_list:
                continue
            title = title_list[0]
            authors = ""
            if item.get("author"):
                auth_list = [a.get("family", "") for a in item["author"][:3]]
                authors = ", ".join(a for a in auth_list if a)
                if len(item["author"]) > 3:
                    authors += " et al."
            year = ""
            pub = item.get("published", {})
            if pub.get("date-parts"):
                year = str(pub["date-parts"][0][0])
            journal = ""
            ct = item.get("container-title", [])
            if ct:
                journal = ct[0]
            abstract = item.get("abstract", "")
            # strip HTML tags from abstract
            abstract = re.sub(r'<[^>]+>', '', abstract)
            doi = item.get("DOI", "")
            results.append({
                "id": paper_id(title),
                "title": title,
                "authors": authors,
                "year": year,
                "journal": journal,
                "abstract": abstract[:2000],
                "doi": doi,
                "source": "crossref",
            })
        return results
    except Exception:
        return []

def fetch_from_semantic_scholar(query):
    """Fetch from Semantic Scholar API (free, no key needed)"""
    if not REQUESTS_OK:
        return []
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={requests.utils.quote(query)}&limit=10&fields=title,authors,year,abstract,venue,externalIds"
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return []
        items = r.json().get("data", [])
        results = []
        for item in items:
            title = item.get("title", "")
            if not title:
                continue
            authors_raw = item.get("authors", [])
            authors = ", ".join(a.get("name","") for a in authors_raw[:3])
            if len(authors_raw) > 3:
                authors += " et al."
            year = str(item.get("year", "")) if item.get("year") else ""
            journal = item.get("venue", "")
            abstract = item.get("abstract", "") or ""
            doi = item.get("externalIds", {}).get("DOI", "")
            results.append({
                "id": paper_id(title),
                "title": title,
                "authors": authors,
                "year": year,
                "journal": journal,
                "abstract": abstract[:2000],
                "doi": doi,
                "source": "semantic_scholar",
            })
        return results
    except Exception:
        return []

def fetch_by_doi(doi):
    """Fetch single paper by DOI from CrossRef"""
    if not REQUESTS_OK:
        return None
    try:
        doi = doi.strip().replace("https://doi.org/","").replace("http://doi.org/","")
        url = f"https://api.crossref.org/works/{requests.utils.quote(doi)}"
        r = requests.get(url, timeout=10, headers={"User-Agent": "PaperCluster/1.0"})
        if r.status_code != 200:
            return None
        item = r.json().get("message", {})
        title_list = item.get("title", [])
        if not title_list:
            return None
        title = title_list[0]
        authors = ""
        if item.get("author"):
            auth_list = [a.get("family","") for a in item["author"][:3]]
            authors = ", ".join(a for a in auth_list if a)
            if len(item["author"]) > 3:
                authors += " et al."
        year = ""
        pub = item.get("published", {})
        if pub.get("date-parts"):
            year = str(pub["date-parts"][0][0])
        journal = ""
        ct = item.get("container-title", [])
        if ct:
            journal = ct[0]
        abstract = re.sub(r'<[^>]+>', '', item.get("abstract", ""))
        return {
            "id": paper_id(title),
            "title": title,
            "authors": authors,
            "year": year,
            "journal": journal,
            "abstract": abstract[:2000],
            "doi": doi,
            "source": "doi_lookup",
        }
    except Exception:
        return None

def run_clustering(n_clusters=None):
    """Cluster papers using TF-IDF + KMeans on title + abstract"""
    papers = st.session_state.papers
    if len(papers) < 3:
        return False, "Need at least 3 papers to cluster."
    if not SKLEARN_OK:
        return False, "scikit-learn not installed."

    # Build corpus
    corpus = []
    for p in papers:
        text = p.get("title","") + " " + p.get("abstract","") + " " + p.get("journal","")
        corpus.append(text.strip())

    # TF-IDF
    vectorizer = TfidfVectorizer(
        max_features=500,
        stop_words="english",
        ngram_range=(1, 2),
        min_df=1,
    )
    X = vectorizer.fit_transform(corpus)

    # Auto-select n_clusters if not specified
    if n_clusters is None:
        best_k = 2
        best_score = -1
        max_k = min(8, len(papers) - 1)
        if max_k < 2:
            max_k = 2
        for k in range(2, max_k + 1):
            try:
                km = KMeans(n_clusters=k, random_state=42, n_init=10)
                labels = km.fit_predict(X)
                if len(set(labels)) < 2:
                    continue
                score = silhouette_score(X, labels)
                if score > best_score:
                    best_score = score
                    best_k = k
            except Exception:
                pass
        n_clusters = best_k

    # Final clustering
    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = km.fit_predict(X)

    # PCA for 2D visualization
    pca = PCA(n_components=2, random_state=42)
    coords = pca.fit_transform(X.toarray())

    # Extract top keywords per cluster
    feature_names = vectorizer.get_feature_names_out()
    cluster_keywords = {}
    order_centroids = km.cluster_centers_.argsort()[:, ::-1]
    for i in range(n_clusters):
        top = [feature_names[ind] for ind in order_centroids[i, :6]]
        cluster_keywords[str(i)] = top

    # Build cluster assignment
    clusters = {}
    for idx, (paper, label, coord) in enumerate(zip(papers, labels, coords)):
        cid = str(label)
        if cid not in clusters:
            clusters[cid] = []
        clusters[cid].append({
            "id": paper["id"],
            "x": float(coord[0]),
            "y": float(coord[1]),
        })
        # Store coords on paper
        st.session_state.papers[idx]["cluster"] = cid
        st.session_state.papers[idx]["x"] = float(coord[0])
        st.session_state.papers[idx]["y"] = float(coord[1])

    st.session_state.clusters = clusters
    st.session_state.cluster_keywords = cluster_keywords

    # Auto-generate cluster labels from keywords
    existing_labels = st.session_state.cluster_labels
    for cid, kws in cluster_keywords.items():
        if cid not in existing_labels:
            existing_labels[cid] = " · ".join(kws[:3])
    st.session_state.cluster_labels = existing_labels

    save_data()
    return True, f"Clustered into {n_clusters} groups."

# ── sidebar ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ◎ PaperCluster")
    st.markdown('<div style="font-size:11px;color:#c8f07a;font-family:DM Mono,monospace;margin-bottom:4px;">auto-clustering · no API key</div>', unsafe_allow_html=True)
    n = len(st.session_state.papers)
    st.markdown(f'<div style="font-size:10px;color:#888885;font-family:DM Mono,monospace;margin-bottom:8px;">{n} paper{"s" if n!=1 else ""} in library</div>', unsafe_allow_html=True)
    st.markdown("---")
    page = st.radio("page", ["🗺 Cluster Map", "🔍 Search & Add", "📄 Manual Add", "📚 Library", "⚙️ Settings"], label_visibility="collapsed")
    st.markdown("---")
    if n >= 3:
        if st.button("🔄 Re-cluster", use_container_width=True, type="primary"):
            ok, msg = run_clustering()
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
    if n > 0:
        if st.button("🗑 Clear All", use_container_width=True):
            if st.session_state.get("confirm_clear"):
                st.session_state.papers = []
                st.session_state.clusters = {}
                st.session_state.cluster_labels = {}
                save_data()
                st.session_state.confirm_clear = False
                st.rerun()
            else:
                st.session_state.confirm_clear = True
                st.warning("Click again to confirm")

# ── PAGE: CLUSTER MAP ─────────────────────────────────────────
if page == "🗺 Cluster Map":
    st.markdown('<div class="page-title">Cluster Map</div>', unsafe_allow_html=True)

    papers = st.session_state.papers
    clusters = st.session_state.clusters
    cluster_labels = st.session_state.cluster_labels
    cluster_keywords = st.session_state.get("cluster_keywords", {})

    if len(papers) < 3:
        st.info(f"Add at least 3 papers to generate a cluster map. You have {len(papers)} so far.")
        st.markdown('<div style="color:#888885;font-size:13px;">Use **Search & Add** to find papers from CrossRef or Semantic Scholar, or **Manual Add** to enter them directly.</div>', unsafe_allow_html=True)
    elif not clusters:
        st.info("Papers added! Click **Re-cluster** in the sidebar to generate your cluster map.")
    else:
        # Stats row
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f'<div class="stat-box"><div class="stat-num">{len(papers)}</div><div class="stat-label">Papers</div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="stat-box"><div class="stat-num">{len(clusters)}</div><div class="stat-label">Clusters</div></div>', unsafe_allow_html=True)
        with c3:
            covered = sum(1 for p in papers if p.get("abstract","").strip())
            st.markdown(f'<div class="stat-box"><div class="stat-num">{covered}</div><div class="stat-label">With Abstract</div></div>', unsafe_allow_html=True)

        st.markdown('<div class="section-title">Interactive Map</div>', unsafe_allow_html=True)

        # Build data for visualization
        plot_data = []
        for p in papers:
            if "x" in p and "y" in p:
                cid = str(p.get("cluster", "0"))
                color = CLUSTER_COLORS[int(cid) % len(CLUSTER_COLORS)]
                label = cluster_labels.get(cid, f"Cluster {cid}")
                plot_data.append({
                    "id": p["id"],
                    "title": p["title"],
                    "authors": p.get("authors",""),
                    "year": p.get("year",""),
                    "journal": p.get("journal",""),
                    "x": p["x"],
                    "y": p["y"],
                    "cluster": cid,
                    "color": color,
                    "label": label,
                })

        import streamlit.components.v1 as components
        plot_js = json.dumps(plot_data)
        colors_js = json.dumps({str(i): CLUSTER_COLORS[i % len(CLUSTER_COLORS)] for i in range(len(clusters))})
        labels_js = json.dumps(cluster_labels)

        MAP_HTML = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{box-sizing:border-box;margin:0;padding:0;font-family:Inter,sans-serif}
body{background:#0e0e10;overflow:hidden}
#wrap{position:fixed;top:0;left:0;right:0;bottom:0;overflow:hidden}
canvas{position:absolute;top:0;left:0}
#tooltip{position:fixed;background:#1e1e24;border:1px solid rgba(255,255,255,.15);border-radius:10px;padding:10px 14px;font-size:12px;color:#f0ede8;pointer-events:none;display:none;max-width:260px;z-index:100;line-height:1.6}
#tooltip .tt{font-weight:600;color:#f0ede8;margin-bottom:3px;font-size:13px}
#tooltip .tm{font-size:11px;color:#888885;font-family:DM Mono,monospace}
#tooltip .tc{font-size:10px;margin-top:4px;padding:2px 8px;border-radius:100px;display:inline-block}
#legend{position:fixed;bottom:14px;left:14px;background:#18181c;border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:10px 14px;z-index:50}
#legend .li{display:flex;align-items:center;gap:8px;margin-bottom:5px;font-size:11px;color:#ccc8c0;cursor:pointer}
#legend .li:last-child{margin-bottom:0}
#legend .dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
#hint{position:fixed;bottom:14px;right:14px;font-size:10px;color:#444;font-family:DM Mono,monospace}
</style></head>
<body>
<div id="wrap"><canvas id="c"></canvas></div>
<div id="tooltip"><div class="tt" id="tt"></div><div class="tm" id="tm"></div><div class="tc" id="tc"></div></div>
<div id="legend" id="leg"></div>
<div id="hint">scroll=zoom · drag=pan</div>
<script>
var DATA   = DATA_PH;
var COLORS = COLORS_PH;
var LABELS = LABELS_PH;

var canvas = document.getElementById('c');
var ctx    = canvas.getContext('2d');
var W, H;

function resize(){
  W = canvas.width  = window.innerWidth;
  H = canvas.height = window.innerHeight;
  draw();
}
window.addEventListener('resize', resize);

// pan/zoom
var ox=0, oy=0, scale=1;
var dragging=false, lx=0, ly=0;

canvas.addEventListener('wheel', function(e){
  e.preventDefault();
  var f = e.deltaY > 0 ? 0.9 : 1.1;
  var mx = e.clientX, my = e.clientY;
  ox = mx - (mx - ox) * f;
  oy = my - (my - oy) * f;
  scale *= f;
  draw();
},{passive:false});

canvas.addEventListener('mousedown', function(e){dragging=true;lx=e.clientX;ly=e.clientY;});
window.addEventListener('mousemove', function(e){
  if(dragging){ ox+=e.clientX-lx; oy+=e.clientY-ly; lx=e.clientX; ly=e.clientY; draw(); }
  showTooltip(e.clientX, e.clientY);
});
window.addEventListener('mouseup', function(){dragging=false;});

// world → screen
function wx(x){ return ox + x * scale; }
function wy(y){ return oy + y * scale; }

// normalize data coords to canvas
var minX, maxX, minY, maxY;
function initBounds(){
  if(!DATA.length){ minX=minY=-1; maxX=maxY=1; return; }
  minX = Math.min.apply(null, DATA.map(function(d){return d.x;}));
  maxX = Math.max.apply(null, DATA.map(function(d){return d.x;}));
  minY = Math.min.apply(null, DATA.map(function(d){return d.y;}));
  maxY = Math.max.apply(null, DATA.map(function(d){return d.y;}));
}
function initView(){
  initBounds();
  var pad = 80;
  var rw = maxX - minX || 1;
  var rh = maxY - minY || 1;
  scale = Math.min((W-pad*2)/rw, (H-pad*2)/rh) * 0.85;
  ox = W/2 - ((minX+maxX)/2) * scale;
  oy = H/2 - ((minY+maxY)/2) * scale;
}

function draw(){
  ctx.clearRect(0,0,W,H);

  // draw cluster hulls (convex areas)
  var clusterGroups = {};
  DATA.forEach(function(d){
    if(!clusterGroups[d.cluster]) clusterGroups[d.cluster]=[];
    clusterGroups[d.cluster].push(d);
  });

  Object.keys(clusterGroups).forEach(function(cid){
    var pts = clusterGroups[cid];
    var color = COLORS[cid] || '#888';
    // draw soft circle around cluster center
    var cx2 = pts.reduce(function(s,p){return s+p.x;},0)/pts.length;
    var cy2 = pts.reduce(function(s,p){return s+p.y;},0)/pts.length;
    var maxR = 0;
    pts.forEach(function(p){
      var d2 = Math.sqrt((p.x-cx2)*(p.x-cx2)+(p.y-cy2)*(p.y-cy2));
      if(d2>maxR) maxR=d2;
    });
    var r = (maxR * scale + 38);
    var sx = wx(cx2), sy = wy(cy2);
    var grad = ctx.createRadialGradient(sx,sy,0,sx,sy,r);
    grad.addColorStop(0, color.replace(')',',0.10)').replace('rgb','rgba').replace('#','').length>8?color+'22':hexToRgba(color,0.10));
    grad.addColorStop(1, hexToRgba(color,0));
    ctx.beginPath();
    ctx.arc(sx,sy,r,0,Math.PI*2);
    ctx.fillStyle=grad;
    ctx.fill();
  });

  // draw points
  DATA.forEach(function(d){
    var sx=wx(d.x), sy=wy(d.y);
    var r = Math.max(5, Math.min(10, scale*0.15));

    ctx.beginPath();
    ctx.arc(sx,sy,r+2,0,Math.PI*2);
    ctx.fillStyle='rgba(0,0,0,0.4)';
    ctx.fill();

    ctx.beginPath();
    ctx.arc(sx,sy,r,0,Math.PI*2);
    ctx.fillStyle=d.color;
    ctx.fill();

    // label
    if(scale > 60){
      ctx.font = '10px Inter';
      ctx.fillStyle = 'rgba(240,237,232,0.7)';
      ctx.fillText(d.title.substr(0,28)+(d.title.length>28?'...':''), sx+r+4, sy+4);
    }
  });

  // draw cluster labels
  Object.keys(clusterGroups).forEach(function(cid){
    var pts = clusterGroups[cid];
    var color = COLORS[cid] || '#888';
    var cx2 = pts.reduce(function(s,p){return s+p.x;},0)/pts.length;
    var cy2 = pts.reduce(function(s,p){return s+p.y;},0)/pts.length;
    var maxR = 0;
    pts.forEach(function(p){
      var d2=Math.sqrt((p.x-cx2)*(p.x-cx2)+(p.y-cy2)*(p.y-cy2));
      if(d2>maxR) maxR=d2;
    });
    var label = LABELS[cid] || ('Cluster '+cid);
    var sx=wx(cx2), sy=wy(cy2)-(maxR*scale+44);
    ctx.font='bold 11px DM Mono,monospace';
    ctx.fillStyle=color;
    ctx.textAlign='center';
    ctx.fillText(label.substr(0,30), sx, sy);
    ctx.textAlign='left';
  });
}

function hexToRgba(hex,a){
  var r=parseInt(hex.slice(1,3),16),g=parseInt(hex.slice(3,5),16),b=parseInt(hex.slice(5,7),16);
  return 'rgba('+r+','+g+','+b+','+a+')';
}

function showTooltip(mx,my){
  var best=null, bestD=Infinity;
  DATA.forEach(function(d){
    var sx=wx(d.x),sy=wy(d.y);
    var dist=Math.sqrt((mx-sx)*(mx-sx)+(my-sy)*(my-sy));
    if(dist<bestD){bestD=dist;best=d;}
  });
  var tt=document.getElementById('tooltip');
  if(best && bestD < 20){
    document.getElementById('tt').textContent=best.title.substr(0,60)+(best.title.length>60?'...':'');
    document.getElementById('tm').textContent=(best.authors?best.authors.substr(0,40)+' ':'')+(best.year?'· '+best.year:'')+(best.journal?' · '+best.journal.substr(0,30):'');
    document.getElementById('tc').textContent=best.label;
    document.getElementById('tc').style.background=best.color+'33';
    document.getElementById('tc').style.color=best.color;
    tt.style.display='block';
    tt.style.left=(mx+16)+'px';
    tt.style.top=(my-10)+'px';
  } else {
    tt.style.display='none';
  }
}

// build legend
var leg=document.getElementById('leg');
var seen={};
DATA.forEach(function(d){
  if(!seen[d.cluster]){
    seen[d.cluster]=true;
    var li=document.createElement('div');li.className='li';
    var dot=document.createElement('div');dot.className='dot';dot.style.background=d.color;
    var lbl=document.createElement('span');lbl.textContent=(LABELS[d.cluster]||('Cluster '+d.cluster)).substr(0,28);
    li.appendChild(dot);li.appendChild(lbl);
    leg.appendChild(li);
  }
});

resize();
initView();
draw();
</script>
</body></html>"""

        MAP_HTML = MAP_HTML.replace('DATA_PH', plot_js).replace('COLORS_PH', colors_js).replace('LABELS_PH', labels_js)
        components.html(MAP_HTML, height=520, scrolling=False)

        # Cluster summaries below map
        st.markdown('<div class="section-title">Cluster Breakdown</div>', unsafe_allow_html=True)
        for cid, paper_coords in clusters.items():
            color = CLUSTER_COLORS[int(cid) % len(CLUSTER_COLORS)]
            label = cluster_labels.get(cid, f"Cluster {cid}")
            kws = st.session_state.get("cluster_keywords", {}).get(cid, [])
            cluster_papers = [p for p in papers if str(p.get("cluster","")) == cid]

            with st.expander(f"**{label}** — {len(cluster_papers)} papers"):
                # Editable label
                new_label = st.text_input("Rename cluster", value=label, key=f"lbl_{cid}")
                if new_label != label:
                    st.session_state.cluster_labels[cid] = new_label
                    save_data()
                    st.rerun()

                if kws:
                    chips = "".join([f'<span class="cluster-chip" style="background:{color}22;color:{color};">{k}</span>' for k in kws])
                    st.markdown(f'<div style="margin:6px 0">{chips}</div>', unsafe_allow_html=True)

                for p in cluster_papers:
                    meta = " · ".join(x for x in [p.get("authors","")[:35], p.get("year",""), p.get("journal","")[:30]] if x)
                    st.markdown(f'<div class="paper-card"><h5>{p["title"]}</h5><div class="meta">{meta}</div></div>', unsafe_allow_html=True)


# ── PAGE: SEARCH & ADD ────────────────────────────────────────
elif page == "🔍 Search & Add":
    st.markdown('<div class="page-title">Search & Add</div>', unsafe_allow_html=True)
    st.markdown('<div style="color:#888885;font-size:14px;margin-bottom:1.5rem;">Search CrossRef or Semantic Scholar — no API key needed.</div>', unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["🔎 Search by keyword", "🔗 Lookup by DOI"])

    with tab1:
        col1, col2 = st.columns([3,1])
        with col1:
            query = st.text_input("Search query", placeholder="e.g. monetary policy firm discouragement euro area", label_visibility="collapsed")
        with col2:
            source = st.selectbox("Source", ["Semantic Scholar", "CrossRef"], label_visibility="collapsed")

        if st.button("Search", type="primary", use_container_width=False) and query:
            with st.spinner(f"Searching {source}..."):
                if source == "CrossRef":
                    results = fetch_from_crossref(query)
                else:
                    results = fetch_from_semantic_scholar(query)

            if not results:
                st.warning("No results found. Try different keywords or switch source.")
            else:
                st.markdown(f'<div style="font-size:12px;color:#888885;font-family:DM Mono,monospace;margin-bottom:8px;">{len(results)} results</div>', unsafe_allow_html=True)
                existing_ids = {p["id"] for p in st.session_state.papers}

                for r in results:
                    already = r["id"] in existing_ids
                    c1, c2 = st.columns([5,1])
                    with c1:
                        meta = " · ".join(x for x in [r.get("authors","")[:40], r.get("year",""), r.get("journal","")[:35]] if x)
                        abstr = ('<div style="font-size:10px;color:#888">'+r["abstract"][:120]+'...</div>') if r.get("abstract") else ""
                        st.markdown(f'<div class="paper-card"><h5>{r["title"]}</h5><div class="meta">{meta}</div>{abstr}</div>', unsafe_allow_html=True)
                    with c2:
                        if already:
                            st.markdown('<div style="font-size:11px;color:#c8f07a;padding-top:8px;">✓ Added</div>', unsafe_allow_html=True)
                        else:
                            if st.button("+ Add", key=f"add_{r['id']}"):
                                st.session_state.papers.append(r)
                                save_data()
                                st.success(f"Added: {r['title'][:50]}")
                                st.rerun()

    with tab2:
        doi_input = st.text_input("Enter DOI", placeholder="e.g. 10.1016/j.jmoneco.2023.01.001")
        if st.button("Lookup DOI", type="primary") and doi_input:
            with st.spinner("Looking up DOI..."):
                result = fetch_by_doi(doi_input)
            if not result:
                st.error("Could not find paper with that DOI. Check the DOI and try again.")
            else:
                existing_ids = {p["id"] for p in st.session_state.papers}
                st.markdown(f'<div class="paper-card"><h5>{result["title"]}</h5><div class="meta">{result.get("authors","")} · {result.get("year","")} · {result.get("journal","")}</div></div>', unsafe_allow_html=True)
                if result["id"] in existing_ids:
                    st.info("Already in your library.")
                else:
                    if st.button("+ Add this paper"):
                        st.session_state.papers.append(result)
                        save_data()
                        st.success("Added!")
                        st.rerun()


# ── PAGE: MANUAL ADD ──────────────────────────────────────────
elif page == "📄 Manual Add":
    st.markdown('<div class="page-title">Manual Add</div>', unsafe_allow_html=True)
    st.markdown('<div style="color:#888885;font-size:14px;margin-bottom:1.5rem;">Paste paper details directly — the abstract drives clustering quality.</div>', unsafe_allow_html=True)

    with st.form("manual_form"):
        title = st.text_input("Title *")
        c1, c2 = st.columns(2)
        with c1:
            authors = st.text_input("Authors", placeholder="Smith, Jones et al.")
            journal = st.text_input("Journal")
        with c2:
            year = st.text_input("Year")
            doi = st.text_input("DOI (optional)")
        abstract = st.text_area("Abstract *", height=150, placeholder="Paste the abstract here — this is what drives clustering")
        submitted = st.form_submit_button("Add Paper", type="primary")

    if submitted:
        if not title or not abstract:
            st.error("Title and abstract are required.")
        else:
            pid = paper_id(title)
            existing_ids = {p["id"] for p in st.session_state.papers}
            if pid in existing_ids:
                st.warning("This paper is already in your library.")
            else:
                st.session_state.papers.append({
                    "id": pid, "title": title, "authors": authors,
                    "year": year, "journal": journal, "doi": doi,
                    "abstract": abstract, "source": "manual",
                })
                save_data()
                st.success(f"Added: {title[:60]}")
                st.rerun()


# ── PAGE: LIBRARY ─────────────────────────────────────────────
elif page == "📚 Library":
    st.markdown('<div class="page-title">Library</div>', unsafe_allow_html=True)
    papers = st.session_state.papers

    if not papers:
        st.info("No papers yet. Use Search & Add or Manual Add.")
    else:
        search = st.text_input("Filter", placeholder="Search title or author...", label_visibility="collapsed")
        filtered = [p for p in papers if search.lower() in p["title"].lower() or search.lower() in p.get("authors","").lower()] if search else papers

        st.markdown(f'<div style="font-size:12px;color:#888885;font-family:DM Mono,monospace;margin-bottom:12px;">{len(filtered)} of {len(papers)} papers</div>', unsafe_allow_html=True)

        for p in filtered:
            cid = str(p.get("cluster",""))
            color = CLUSTER_COLORS[int(cid) % len(CLUSTER_COLORS)] if cid else "#888885"
            clabel = st.session_state.cluster_labels.get(cid, f"Cluster {cid}") if cid else "Unclustered"
            meta = " · ".join(x for x in [p.get("authors","")[:40], p.get("year",""), p.get("journal","")[:35]] if x)

            c1, c2 = st.columns([5,1])
            with c1:
                doi_chip = ('<span class="cluster-chip" style="background:rgba(126,184,247,0.1);color:#7eb8f7;">' + p.get("doi","")[:25] + '</span>') if p.get("doi") else ""
                st.markdown(f'<div class="paper-card"><h5>{p["title"]}</h5><div class="meta">{meta}</div><div style="margin-top:5px"><span class="cluster-chip" style="background:{color}22;color:{color};">{clabel}</span>{doi_chip}</div></div>', unsafe_allow_html=True)
            with c2:
                if st.button("🗑", key=f"del_{p['id']}", help="Remove"):
                    st.session_state.papers = [x for x in st.session_state.papers if x["id"] != p["id"]]
                    save_data()
                    st.rerun()


# ── PAGE: SETTINGS ────────────────────────────────────────────
elif page == "⚙️ Settings":
    st.markdown('<div class="page-title">Settings</div>', unsafe_allow_html=True)

    st.markdown('<div class="section-title">Clustering</div>', unsafe_allow_html=True)
    n_clusters_manual = st.slider("Number of clusters (0 = auto-detect)", 0, 12, 0)

    if st.button("Run Clustering", type="primary"):
        k = n_clusters_manual if n_clusters_manual > 0 else None
        with st.spinner("Clustering..."):
            ok, msg = run_clustering(k)
        if ok:
            st.success(msg)
            st.rerun()
        else:
            st.error(msg)

    st.markdown('<div class="section-title">Data</div>', unsafe_allow_html=True)
    st.markdown(f'<div style="font-size:13px;color:#888885;">Data file: <span style="font-family:DM Mono,monospace;color:#c8f07a;">{DATA_FILE}</span></div>', unsafe_allow_html=True)

    if st.session_state.papers:
        export = json.dumps({"papers": st.session_state.papers, "clusters": st.session_state.clusters, "cluster_labels": st.session_state.cluster_labels}, indent=2)
        st.download_button("⬇ Export Library (JSON)", export, file_name="papercluster_export.json", mime="application/json")

    st.markdown('<div class="section-title">Dependencies</div>', unsafe_allow_html=True)
    st.markdown(f'- scikit-learn: {"✓" if SKLEARN_OK else "✗ run: pip install scikit-learn"}', unsafe_allow_html=False)
    st.markdown(f'- requests: {"✓" if REQUESTS_OK else "✗ run: pip install requests"}', unsafe_allow_html=False)
    st.markdown(f'- scholarly: {"✓ (optional)" if SCHOLARLY_OK else "○ optional — pip install scholarly"}', unsafe_allow_html=False)
