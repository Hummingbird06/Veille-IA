#!/usr/bin/env python3
"""Veille IA : récupère les flux RSS/Atom de la liste SOURCES et génère index.html.

Aucune dépendance à installer (bibliothèque standard de Python uniquement).
Pour ajouter ou retirer une source, modifie simplement la liste SOURCES ci-dessous.
"""
import html
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

# (nom, adresse du flux, langue, catégorie)   catégories : labs, news, analyse, fr
SOURCES = [
    ("OpenAI", "https://openai.com/news/rss.xml", "EN", "labs"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml", "EN", "labs"),
    ("Google AI", "https://blog.google/technology/ai/rss/", "EN", "labs"),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml", "EN", "labs"),
    ("NVIDIA", "https://blogs.nvidia.com/blog/category/generative-ai/feed/", "EN", "labs"),
    ("Anthropic (flux non officiel)", "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml", "EN", "labs"),
    ("TechCrunch", "https://techcrunch.com/category/artificial-intelligence/feed/", "EN", "news"),
    ("The Verge", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "EN", "news"),
    ("MIT Technology Review", "https://www.technologyreview.com/topic/artificial-intelligence/feed", "EN", "news"),
    ("Ars Technica", "https://arstechnica.com/ai/feed/", "EN", "news"),
    ("Simon Willison", "https://simonwillison.net/atom/everything/", "EN", "analyse"),
    ("Import AI", "https://importai.substack.com/feed", "EN", "analyse"),
    ("Latent Space", "https://www.latent.space/feed", "EN", "analyse"),
    ("Actu IA", "https://www.actuia.com/feed/", "FR", "fr"),
    ("Numerama", "https://www.numerama.com/tag/intelligence-artificielle/feed/", "FR", "fr"),
    ("Le Monde", "https://www.lemonde.fr/intelligence-artificielle/rss_full.xml", "FR", "fr"),
]

CATS = [("tous", "Tout"), ("labs", "Labos et modèles"), ("news", "Actualité"), ("analyse", "Analyses"), ("fr", "En français")]
MAX_THIS_WEEK = 5      # articles max par source sur les 7 derniers jours
MAX_PREVIOUS = 2       # articles max par source sur les 7 jours d'avant
UA = "Mozilla/5.0 (compatible; veille-ia/1.0)"
OUT = Path(__file__).resolve().parent / "index.html"

JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
JOURS_L = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS_L = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(4_000_000)


def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def child_text(el, *names):
    for c in el:
        if local(c.tag) in names:
            txt = "".join(c.itertext()).strip()
            if txt:
                return txt
    return ""


def parse_date(s):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def clean(s, n=230):
    s = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > n:
        s = s[:n].rsplit(" ", 1)[0].rstrip(",;:.") + "…"
    return s


def parse_feed(data):
    root = ET.fromstring(data)
    out = []
    for el in root.iter():
        t = local(el.tag)
        if t not in ("item", "entry"):
            continue
        title = clean(child_text(el, "title"), 200)
        link = ""
        for c in el:
            if local(c.tag) == "link":
                link = c.attrib.get("href") or (c.text or "").strip()
                if link and (c.attrib.get("rel") in (None, "alternate")):
                    break
        date = parse_date(child_text(el, "pubDate", "published", "updated", "date"))
        summary = clean(child_text(el, "description", "summary", "encoded", "content"))
        if title and link.startswith("http") and date:
            out.append({"title": title, "link": link, "date": date, "summary": summary})
    return out


def collect(now):
    items, failed, seen = [], [], set()
    for name, url, lang, cat in SOURCES:
        try:
            entries = parse_feed(fetch(url))
        except Exception as e:  # une source en panne ne doit pas bloquer les autres
            print(f"[échec] {name}: {e}", file=sys.stderr)
            failed.append(name)
            continue
        entries.sort(key=lambda x: x["date"], reverse=True)
        n_week = n_prev = 0
        for e in entries:
            age = now - e["date"]
            if age < timedelta(0):
                age = timedelta(0)
            if e["link"] in seen:
                continue
            if age <= timedelta(days=7) and n_week < MAX_THIS_WEEK:
                n_week += 1
                period = "week"
            elif timedelta(days=7) < age <= timedelta(days=14) and n_prev < MAX_PREVIOUS:
                n_prev += 1
                period = "prev"
            else:
                continue
            seen.add(e["link"])
            items.append({**e, "src": name, "lang": lang, "cat": cat, "period": period})
    items.sort(key=lambda x: x["date"], reverse=True)
    return items, failed


def paris(d):
    try:
        from zoneinfo import ZoneInfo
        return d.astimezone(ZoneInfo("Europe/Paris"))
    except Exception:
        return d


def card(it, feat=False, n=0):
    d = paris(it["date"])
    e = html.escape
    label = f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"
    summ = f'<p>{e(it["summary"])}</p>' if it["summary"] else ""
    cls = f"it feat g{n % 3}" if feat else "it"
    return (
        f'<article class="{cls}" data-cat="{it["cat"]}" data-text="{e((it["title"] + " " + it["src"]).lower(), quote=True)}">'
        f'<div class="meta"><span class="src">{e(it["src"])}</span><span class="lang">{it["lang"]}</span>'
        f'<time datetime="{it["date"].strftime("%Y-%m-%d")}">{label}</time></div>'
        f'<h3><a href="{e(it["link"], quote=True)}" target="_blank" rel="noopener noreferrer">{e(it["title"])}</a></h3>{summ}</article>'
    )


def pick_featured(week):
    """Les 3 plus récents, de sources différentes si possible."""
    feat, used = [], set()
    for i in week:
        if i["src"] not in used and len(feat) < 3:
            feat.append(i)
            used.add(i["src"])
    return feat


def render(items, failed, now):
    d = paris(now)
    stamp = f"{JOURS_L[d.weekday()]} {d.day} {MOIS_L[d.month - 1]} {d.year}"
    week = [i for i in items if i["period"] == "week"]
    prev = [i for i in items if i["period"] == "prev"]
    feat = pick_featured(week)
    rest = [i for i in week if i not in feat]
    body = ""
    if feat:
        body += '<section class="grp"><h2>À la une</h2><div class="featgrid">' + "".join(card(i, True, n) for n, i in enumerate(feat)) + "</div></section>"
    if rest:
        body += '<section class="grp"><h2>Cette semaine</h2><div class="list">' + "".join(card(i) for i in rest) + "</div></section>"
    if prev:
        body += '<section class="grp"><h2>La semaine précédente</h2><div class="list">' + "".join(card(i) for i in prev) + "</div></section>"
    if not body:
        body = '<p class="empty">Aucun article récupéré cette fois-ci. La prochaine mise à jour réessaiera.</p>'
    filters = "".join(
        f'<button type="button" class="f" data-f="{k}" aria-pressed="{"true" if k == "tous" else "false"}">{v}</button>' for k, v in CATS
    )
    foot = f"{len(SOURCES) - len(failed)} sources sur {len(SOURCES)} interrogées"
    if failed:
        foot += " · indisponibles cette fois : " + html.escape(", ".join(failed))
    page = TEMPLATE
    for k, v in {"%%ICON%%": ICON, "%%STAMP%%": stamp, "%%FILTERS%%": filters, "%%COUNT%%": str(len(items)), "%%FOOT%%": foot, "%%BODY%%": body}.items():
        page = page.replace(k, v)
    return page


ICON = "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"

TEMPLATE = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Veille IA"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#000000">
<link rel="apple-touch-icon" href="data:image/png;base64,%%ICON%%"><link rel="icon" href="data:image/png;base64,%%ICON%%">
<title>Veille IA</title>
<style>
:root{--bg:#f5f5f7;--surface:#fff;--fg:#1d1d1f;--dim:#6e6e73;--line:rgba(0,0,0,.1);--accent:#0071e3;--glass:rgba(245,245,247,.72);--pill:rgba(0,0,0,.06);
--g0:#0a84ff;--g1:#bf5af2;--g2:#ff9f0a;--t1:#0071e3;--t2:#a550e0;--t3:#ff2d55;
--font:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","Helvetica Neue",system-ui,"Segoe UI",sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#000;--surface:#1c1c1e;--fg:#f5f5f7;--dim:#a1a1a6;--line:rgba(255,255,255,.14);--accent:#2997ff;--glass:rgba(0,0,0,.72);--pill:rgba(255,255,255,.12);--t1:#2997ff;--t2:#bf5af2;--t3:#ff375f;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#000;--surface:#1c1c1e;--fg:#f5f5f7;--dim:#a1a1a6;--line:rgba(255,255,255,.14);--accent:#2997ff;--glass:rgba(0,0,0,.72);--pill:rgba(255,255,255,.12);--t1:#2997ff;--t2:#bf5af2;--t3:#ff375f;color-scheme:dark}
*{box-sizing:border-box}[hidden]{display:none!important}
html,body{margin:0}
body{background:var(--bg);color:var(--fg);font:17px/1.47 var(--font);letter-spacing:-.01em;-webkit-font-smoothing:antialiased;
padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-bottom:max(48px,env(safe-area-inset-bottom,0px))}
body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);background:var(--glass);-webkit-backdrop-filter:saturate(180%) blur(20px);backdrop-filter:saturate(180%) blur(20px);z-index:30}
.wrap{max-width:1040px;margin:0 auto}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px;border-radius:8px}
.hero{text-align:center;padding:calc(64px + env(safe-area-inset-top,0px)) 0 36px}
.eyebrow{font-size:17px;font-weight:600;color:var(--dim);letter-spacing:0}
h1{font-size:clamp(64px,17vw,136px);font-weight:700;letter-spacing:-.045em;line-height:1;margin:10px 0 0;
background:linear-gradient(100deg,var(--t1),var(--t2) 55%,var(--t3));-webkit-background-clip:text;background-clip:text;color:transparent;padding-bottom:.08em}
.sub{font-size:clamp(19px,3.4vw,26px);line-height:1.3;font-weight:500;color:var(--dim);max-width:30ch;margin:18px auto 0;letter-spacing:-.015em;text-wrap:balance}
.tools{position:sticky;top:env(safe-area-inset-top,0px);z-index:20;background:var(--glass);-webkit-backdrop-filter:saturate(180%) blur(20px);backdrop-filter:saturate(180%) blur(20px);
margin:0 calc(-1*max(16px,env(safe-area-inset-left,0px)));padding:10px max(16px,env(safe-area-inset-right,0px));border-bottom:1px solid var(--line)}
.tools-in{max-width:1040px;margin:0 auto;display:grid;gap:10px;grid-template-columns:minmax(0,1fr)}
.row{display:flex;gap:8px;align-items:center;min-width:0}
.fl{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none;flex:1;min-width:0;padding:3px;background:var(--pill);border-radius:999px}.fl::-webkit-scrollbar{display:none}
.f{flex:none;height:36px;padding:0 16px;border-radius:999px;border:0;background:transparent;color:var(--dim);font:500 14.5px var(--font);cursor:pointer;letter-spacing:-.005em}
.f[aria-pressed="true"]{background:var(--surface);color:var(--fg);box-shadow:0 1px 3px rgba(0,0,0,.2)}
.themebtn{flex:none;width:42px;height:42px;border-radius:50%;border:0;background:var(--pill);color:var(--fg);font-size:18px;cursor:pointer}
#q{width:100%;height:44px;border-radius:12px;border:0;background:var(--pill);color:var(--fg);font:17px var(--font);padding:0 14px}
#q::placeholder{color:var(--dim)}
.grp{margin-top:64px}
h2{font-size:clamp(32px,6vw,48px);font-weight:700;letter-spacing:-.035em;line-height:1.08;margin:0 0 22px}
.featgrid,.list{display:grid;gap:14px;grid-template-columns:1fr}
@media(min-width:760px){.featgrid{grid-template-columns:repeat(3,1fr)}.list{grid-template-columns:repeat(2,1fr)}}
.it{position:relative;background:var(--surface);border-radius:24px;padding:22px 24px 24px;transition:transform .25s ease;animation:rise .6s ease both}
.it:hover{transform:scale(1.012)}
.it h3 a::after{content:"";position:absolute;inset:0;border-radius:24px}
.meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:13px;color:var(--dim)}
.src{font-weight:600;color:var(--fg);letter-spacing:0}
.lang{border-radius:6px;background:var(--pill);padding:1px 6px;font-size:11px;font-weight:600}
time{margin-left:auto;font-variant-numeric:tabular-nums}
.it h3{margin:10px 0 0;font-size:21px;font-weight:600;line-height:1.22;letter-spacing:-.022em;text-wrap:balance}
.it h3 a{color:var(--fg);text-decoration:none}
.it p{margin:10px 0 0;color:var(--dim);font-size:15.5px;line-height:1.45}
.feat{min-height:300px;display:flex;flex-direction:column;padding:26px 26px 30px;border-radius:30px}
.feat h3::after{content:none}.feat h3 a::after{border-radius:30px}
.feat h3{font-size:clamp(26px,4.2vw,31px);letter-spacing:-.03em;line-height:1.12;font-weight:700;margin-top:auto;padding-top:32px}
.feat .meta{margin-bottom:0}
.feat p{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.feat.g0{background:linear-gradient(165deg,color-mix(in srgb,var(--g0) 30%,var(--surface)),var(--surface) 78%)}
.feat.g1{background:linear-gradient(165deg,color-mix(in srgb,var(--g1) 30%,var(--surface)),var(--surface) 78%)}
.feat.g2{background:linear-gradient(165deg,color-mix(in srgb,var(--g2) 30%,var(--surface)),var(--surface) 78%)}
@keyframes rise{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){.it{animation:none;transition:none}}
.empty,.none{color:var(--dim);margin-top:48px;text-align:center}
footer{margin-top:72px;border-top:1px solid var(--line);padding-top:20px;color:var(--dim);font-size:13px;text-align:center;line-height:1.6}
</style></head><body><div class="wrap">
<header class="hero"><div class="eyebrow">Édition du %%STAMP%%</div><h1>Veille IA</h1>
<p class="sub">Ce qui compte cette semaine dans l’intelligence artificielle.</p></header>
<div class="tools"><div class="tools-in"><div class="row"><div class="fl" role="group" aria-label="Filtrer par type de source">%%FILTERS%%</div>
<button type="button" class="themebtn" id="th" aria-label="Changer de thème">◐</button></div>
<input id="q" type="search" placeholder="Rechercher" aria-label="Rechercher dans les titres"></div></div>
<main id="main">%%BODY%%<p class="none" id="none" hidden>Aucun article ne correspond.</p></main>
<footer>%%COUNT%% articles · %%FOOT%%.<br>Nouvelle édition chaque lundi. Les titres et extraits appartiennent à leurs auteurs.</footer></div>
<script>
(function(){
var cat='tous',q='',items=[].slice.call(document.querySelectorAll('.it'));
function apply(){var n=0;items.forEach(function(el){var ok=(cat==='tous'||el.dataset.cat===cat)&&(!q||el.dataset.text.indexOf(q)>-1);el.hidden=!ok;if(ok)n++});
[].slice.call(document.querySelectorAll('.grp')).forEach(function(g){g.hidden=!g.querySelector('.it:not([hidden])')});document.getElementById('none').hidden=n>0||!items.length}
document.querySelector('.fl').addEventListener('click',function(e){var b=e.target.closest('.f');if(!b)return;cat=b.dataset.f;[].forEach.call(document.querySelectorAll('.f'),function(x){x.setAttribute('aria-pressed',x===b)});apply()});
document.getElementById('q').addEventListener('input',function(e){q=e.target.value.trim().toLowerCase();apply()});
var r=document.documentElement;try{var s=localStorage.getItem('veille-theme');if(s)r.setAttribute('data-theme',s)}catch(e){}
document.getElementById('th').addEventListener('click',function(){var dark=r.getAttribute('data-theme')?r.getAttribute('data-theme')==='dark':matchMedia('(prefers-color-scheme: dark)').matches;var n=dark?'light':'dark';r.setAttribute('data-theme',n);try{localStorage.setItem('veille-theme',n)}catch(e){}});
})();
</script></body></html>
"""


def main():
    now = datetime.now(timezone.utc)
    items, failed = collect(now)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(items, failed, now), encoding="utf-8")
    print(f"{len(items)} articles, {len(failed)} source(s) en échec -> {OUT}")


if __name__ == "__main__":
    main()
