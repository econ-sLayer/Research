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
html,body{width:100%;height:100%;overflow:hidden;background:#0e0e10}
canvas{position:fixed;top:0;left:0;cursor:grab}
canvas.dragging{cursor:grabbing}
#tip{position:fixed;background:#1a1a20;border:1px solid rgba(255,255,255,.18);border-radius:11px;
  padding:11px 15px;font-size:12px;color:#f0ede8;pointer-events:none;display:none;
  max-width:280px;z-index:99;line-height:1.65;box-shadow:0 6px 28px rgba(0,0,0,.7)}
#tip b{font-size:13px;display:block;margin-bottom:3px;color:#fff}
#tip small{color:#777;font-family:DM Mono,monospace;font-size:10px}
#tip .cl{display:inline-block;margin-top:6px;padding:2px 10px;border-radius:100px;
  font-size:10px;font-family:DM Mono,monospace;font-weight:500}
#leg{position:fixed;top:14px;right:14px;background:#18181c;
  border:1px solid rgba(255,255,255,.08);border-radius:11px;padding:10px 14px;z-index:50;max-width:200px}
#leg .li{display:flex;align-items:center;gap:8px;margin-bottom:5px;font-size:11px;color:#ccc8c0}
#leg .li:last-child{margin-bottom:0}
.dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
#hint{position:fixed;bottom:12px;right:14px;font-size:10px;color:#333;font-family:DM Mono,monospace}
#resetbtn{position:fixed;bottom:12px;left:14px;background:#18181c;
  border:1px solid rgba(255,255,255,.1);border-radius:7px;padding:5px 12px;
  font-size:11px;color:#888;cursor:pointer;font-family:DM Mono,monospace;z-index:50}
#resetbtn:hover{color:#f0ede8;border-color:rgba(255,255,255,.3)}
</style></head><body>
<canvas id="c"></canvas>
<div id="tip"><b id="tt"></b><small id="tm"></small><br><span id="tcl" class="cl"></span></div>
<div id="leg"></div>
<div id="hint">scroll = zoom · drag = pan</div>
<button id="resetbtn" onclick="resetView()">⊡ Reset view</button>
<script>
var D    = DATA_PH;
var COLS = COLORS_PH;
var LBLS = LABELS_PH;

var cv  = document.getElementById('c');
var ctx = cv.getContext('2d');
var W, H;

// pan / zoom state
var ox = 0, oy = 0, sc = 1;
var dragging = false, lx = 0, ly = 0;

function resize(){
  W = cv.width  = window.innerWidth;
  H = cv.height = window.innerHeight;
  draw();
}
window.addEventListener('resize', resize);

// ── input ──────────────────────────────────────────────────
cv.addEventListener('wheel', function(e){
  e.preventDefault();
  var f  = e.deltaY > 0 ? 0.88 : 1.14;
  ox = e.clientX - (e.clientX - ox) * f;
  oy = e.clientY - (e.clientY - oy) * f;
  sc *= f;
  sc  = Math.max(0.15, Math.min(4, sc));
  draw();
}, {passive:false});

cv.addEventListener('mousedown', function(e){
  dragging = true; lx = e.clientX; ly = e.clientY;
  cv.classList.add('dragging');
});
window.addEventListener('mousemove', function(e){
  if(dragging){
    ox += e.clientX - lx;
    oy += e.clientY - ly;
    lx  = e.clientX; ly = e.clientY;
    draw();
  }
  tooltip(e.clientX, e.clientY);
});
window.addEventListener('mouseup', function(){ dragging = false; cv.classList.remove('dragging'); });

// world → screen
function wx(x){ return ox + x * sc; }
function wy(y){ return oy + y * sc; }

// ── build tree layout ──────────────────────────────────────
// Group papers by cluster
var groups = {};
D.forEach(function(p){
  var c = p.cluster;
  if(!groups[c]) groups[c] = [];
  groups[c].push(p);
});
var clusterIds = Object.keys(groups);
var numC = clusterIds.length;

// Tree positions (computed once, stored on each paper + cluster centers)
var clusterCenters = {}; // cid -> {x,y}
var nodePos = {};        // paper title -> {x,y}

function buildTree(){
  // Root at origin
  var ROOT = {x: 0, y: 0};

  // Place cluster centers in a circle around root
  var cRadius = 380;
  clusterIds.forEach(function(cid, ci){
    var angle = (2 * Math.PI * ci / numC) - Math.PI/2;
    var cx = ROOT.x + Math.cos(angle) * cRadius;
    var cy = ROOT.y + Math.sin(angle) * cRadius;
    clusterCenters[cid] = {x: cx, y: cy, angle: angle};

    // Place papers in a circle/fan around their cluster center
    var papers = groups[cid];
    var n = papers.length;
    var pRadius = 90 + n * 12;  // grow radius with more papers
    // fan around the outward direction
    var spreadAngle = Math.min(Math.PI * 0.9, n * 0.38);
    var startAngle  = angle - spreadAngle/2;
    papers.forEach(function(p, pi){
      var a = n > 1 ? startAngle + (spreadAngle * pi / (n-1)) : angle;
      nodePos[p.title] = {
        x: cx + Math.cos(a) * pRadius,
        y: cy + Math.sin(a) * pRadius,
        angle: a,
      };
      p._tx = nodePos[p.title].x;
      p._ty = nodePos[p.title].y;
    });
  });
}
buildTree();

// ── initial view: fit everything ──────────────────────────
function resetView(){
  var allX = D.map(function(p){return p._tx;});
  var allY = D.map(function(p){return p._ty;});
  allX.push(0); allY.push(0);
  var mnx = Math.min.apply(null,allX), mxx = Math.max.apply(null,allX);
  var mny = Math.min.apply(null,allY), mxy = Math.max.apply(null,allY);
  var rw = mxx - mnx || 1, rh = mxy - mny || 1;
  var pad = 120;
  sc = Math.min((W - pad*2)/rw, (H - pad*2)/rh) * 0.88;
  sc = Math.max(0.15, Math.min(4, sc));
  ox = W/2 - ((mnx+mxx)/2) * sc;
  oy = H/2 - ((mny+mxy)/2) * sc;
  draw();
}

// ── hex helper ─────────────────────────────────────────────
function hex2rgba(h, a){
  var r=parseInt(h.slice(1,3),16), g=parseInt(h.slice(3,5),16), b=parseInt(h.slice(5,7),16);
  return 'rgba('+r+','+g+','+b+','+a+')';
}

// ── draw ───────────────────────────────────────────────────
function draw(){
  ctx.clearRect(0, 0, W, H);

  var ROOT_SX = wx(0), ROOT_SY = wy(0);

  // ── root node ──
  ctx.beginPath();
  ctx.arc(ROOT_SX, ROOT_SY, 14, 0, Math.PI*2);
  ctx.fillStyle = '#2a2a32';
  ctx.strokeStyle = 'rgba(255,255,255,0.15)';
  ctx.lineWidth = 1.5;
  ctx.fill(); ctx.stroke();
  ctx.font = 'bold 10px DM Mono,monospace';
  ctx.fillStyle = '#888885';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('◎', ROOT_SX, ROOT_SY);
  ctx.textAlign = 'left';
  ctx.textBaseline = 'alphabetic';

  clusterIds.forEach(function(cid){
    var cc     = clusterCenters[cid];
    var color  = COLS[parseInt(cid) % COLS.length];
    var label  = LBLS[cid] || ('Cluster ' + cid);
    var papers = groups[cid];
    var csx    = wx(cc.x), csy = wy(cc.y);

    // ── root → cluster branch ──
    ctx.beginPath();
    ctx.moveTo(ROOT_SX, ROOT_SY);
    // bezier control points
    var mx = (ROOT_SX + csx)/2, my = (ROOT_SY + csy)/2;
    ctx.quadraticCurveTo(mx, my, csx, csy);
    ctx.strokeStyle = hex2rgba(color, 0.25);
    ctx.lineWidth   = Math.max(1, 2 * sc * 0.4);
    ctx.stroke();

    // ── cluster → paper branches ──
    papers.forEach(function(p){
      var psx = wx(p._tx), psy = wy(p._ty);
      ctx.beginPath();
      ctx.moveTo(csx, csy);
      var cpx = (csx + psx)/2 + (psy - csy)*0.15;
      var cpy = (csy + psy)/2 - (psx - csx)*0.15;
      ctx.quadraticCurveTo(cpx, cpy, psx, psy);
      ctx.strokeStyle = hex2rgba(color, 0.18);
      ctx.lineWidth   = Math.max(0.5, 1.2 * sc * 0.4);
      ctx.stroke();
    });

    // ── cluster glow ──
    var gr = Math.max(40, 90 * sc * 0.5);
    var grd = ctx.createRadialGradient(csx, csy, 0, csx, csy, gr);
    grd.addColorStop(0, hex2rgba(color, 0.18));
    grd.addColorStop(1, hex2rgba(color, 0));
    ctx.beginPath();
    ctx.arc(csx, csy, gr, 0, Math.PI*2);
    ctx.fillStyle = grd;
    ctx.fill();

    // ── cluster node ──
    var cr = Math.max(10, 18 * Math.min(sc, 1));
    ctx.beginPath();
    ctx.arc(csx, csy, cr + 3, 0, Math.PI*2);
    ctx.fillStyle = 'rgba(0,0,0,0.5)';
    ctx.fill();
    ctx.beginPath();
    ctx.arc(csx, csy, cr, 0, Math.PI*2);
    ctx.fillStyle = hex2rgba(color, 0.22);
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.fill(); ctx.stroke();

    // ── cluster label ──
    var fs = Math.max(9, Math.min(13, 11 * sc * 0.7 + 5));
    ctx.font = 'bold ' + fs + 'px Inter';
    ctx.fillStyle = color;
    ctx.textAlign = 'center';
    // place label on the outward side
    var lx2 = csx + Math.cos(cc.angle) * (cr + 14 + fs);
    var ly2 = csy + Math.sin(cc.angle) * (cr + 14 + fs);
    // background pill
    var tw = ctx.measureText(label.length > 28 ? label.substr(0,26)+'...' : label).width;
    ctx.fillStyle = 'rgba(14,14,16,0.75)';
    ctx.beginPath();
    ctx.rect(lx2 - tw/2 - 5, ly2 - fs/2 - 3, tw + 10, fs + 7);
    ctx.fill();
    ctx.fillStyle = color;
    ctx.fillText(label.length > 28 ? label.substr(0,26)+'...' : label, lx2, ly2 + fs*0.35);
    ctx.textAlign = 'left';

    // ── paper dots ──
    papers.forEach(function(p){
      var psx = wx(p._tx), psy = wy(p._ty);
      var pr  = Math.max(4, Math.min(8, 6 * sc * 0.5 + 3));

      ctx.beginPath();
      ctx.arc(psx, psy, pr + 2, 0, Math.PI*2);
      ctx.fillStyle = 'rgba(0,0,0,0.5)';
      ctx.fill();

      ctx.beginPath();
      ctx.arc(psx, psy, pr, 0, Math.PI*2);
      ctx.fillStyle = color;
      ctx.fill();

      // paper title label at higher zoom
      if(sc > 0.7){
        var tfs = Math.max(8, Math.min(11, 9 * sc * 0.6 + 4));
        ctx.font = tfs + 'px Inter';
        ctx.fillStyle = 'rgba(200,197,190,0.7)';
        var short = p.title.length > 30 ? p.title.substr(0,28)+'...' : p.title;
        // offset label away from cluster center
        var dx = psx - csx, dy = psy - csy;
        var dist = Math.sqrt(dx*dx+dy*dy) || 1;
        var lox = (dx/dist) * (pr + 5);
        var loy = (dy/dist) * (pr + 5);
        ctx.fillText(short, psx + lox, psy + loy + tfs*0.35);
      }
    });
  });
}

// ── tooltip ────────────────────────────────────────────────
function tooltip(mx, my){
  var best = null, bd = 9999;
  D.forEach(function(p){
    var psx = wx(p._tx), psy = wy(p._ty);
    var dist = Math.sqrt(Math.pow(mx-psx,2) + Math.pow(my-psy,2));
    if(dist < bd){ bd = dist; best = p; }
  });
  var tip = document.getElementById('tip');
  if(best && bd < 18){
    document.getElementById('tt').textContent = best.title.substr(0,70) + (best.title.length>70?'...':'');
    var m = [best.authors?best.authors.substr(0,38):'', best.year, best.journal?best.journal.substr(0,32):''].filter(Boolean).join(' · ');
    document.getElementById('tm').textContent = m;
    var tcl = document.getElementById('tcl');
    tcl.textContent = best.label || ('Cluster '+best.cluster);
    tcl.style.background = (COLS[parseInt(best.cluster)%COLS.length]) + '28';
    tcl.style.color       = COLS[parseInt(best.cluster)%COLS.length];
    tip.style.display = 'block';
    tip.style.left = (mx + 18) + 'px';
    tip.style.top  = Math.min(my - 10, window.innerHeight - 140) + 'px';
  } else {
    tip.style.display = 'none';
  }
}

// ── legend ─────────────────────────────────────────────────
var leg = document.getElementById('leg'), seen = {};
D.forEach(function(d){
  if(!seen[d.cluster]){
    seen[d.cluster] = true;
    var li   = document.createElement('div'); li.className = 'li';
    var dot  = document.createElement('div'); dot.className = 'dot';
    dot.style.background = COLS[parseInt(d.cluster) % COLS.length];
    var span = document.createElement('span');
    span.textContent = (LBLS[d.cluster]||('Cluster '+d.cluster)).substr(0,24);
    li.appendChild(dot); li.appendChild(span); leg.appendChild(li);
  }
});

// ── init ───────────────────────────────────────────────────
resize();
resetView();
</script></body></html>"""
        colors_list = [COLS[int(cid) % len(COLS)] for cid in range(max(int(c) for c in cluster_ids)+1)] if cluster_ids else COLS
        MAP = MAP.replace('DATA_PH',   json.dumps(plot_data))
        MAP = MAP.replace('COLORS_PH', json.dumps(colors_list))
        MAP = MAP.replace('LABELS_PH', json.dumps(cl))
        components.html(MAP, height=780, scrolling=False)

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
