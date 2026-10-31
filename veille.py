#!/usr/bin/env python3
"""Veille IA : récupère les flux RSS/Atom de la liste SOURCES et génère veille/index.html.

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
OUT = Path(__file__).resolve().parent / "veille" / "index.html"

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


def card(it):
    d = paris(it["date"])
    e = html.escape
    label = f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"
    summ = f'<p>{e(it["summary"])}</p>' if it["summary"] else ""
    return (
        f'<article class="it" data-cat="{it["cat"]}" data-text="{e((it["title"] + " " + it["src"]).lower(), quote=True)}">'
        f'<div class="meta"><span class="src">{e(it["src"])}</span><span class="lang">{it["lang"]}</span>'
        f'<time datetime="{it["date"].strftime("%Y-%m-%d")}">{label}</time></div>'
        f'<h3><a href="{e(it["link"], quote=True)}" target="_blank" rel="noopener noreferrer">{e(it["title"])}</a></h3>{summ}</article>'
    )


def render(items, failed, now):
    d = paris(now)
    stamp = f"{JOURS_L[d.weekday()]} {d.day} {MOIS_L[d.month - 1]} {d.year}, {d.hour:02d}:{d.minute:02d}"
    week = [i for i in items if i["period"] == "week"]
    prev = [i for i in items if i["period"] == "prev"]
    body = ""
    if week:
        body += '<section class="grp"><h2>Cette semaine</h2><div class="list">' + "".join(card(i) for i in week) + "</div></section>"
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
<meta name="apple-mobile-web-app-title" content="Veille IA"><meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="theme-color" content="#0f1420">
<link rel="apple-touch-icon" href="data:image/png;base64,%%ICON%%"><link rel="icon" href="data:image/png;base64,%%ICON%%">
<title>Veille IA</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Barlow:wght@400;500;600;700&display=swap">
<style>
:root{--bg:#eef1f5;--surface:#fff;--surface2:#e6eaf0;--line:#d3d9e3;--line2:#bcc5d3;--fg:#141a26;--dim:#566177;--accent:#1d5fd1;--focus:#1d5fd1;
--fd:"Barlow Condensed","Arial Narrow",system-ui,sans-serif;--fb:"Barlow",system-ui,-apple-system,"Segoe UI",sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0d1119;--surface:#161c28;--surface2:#1f2736;--line:#2a3447;--line2:#3b475e;--fg:#eef1f6;--dim:#9aa7bd;--accent:#6aa5ff;--focus:#7db0ff;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0d1119;--surface:#161c28;--surface2:#1f2736;--line:#2a3447;--line2:#3b475e;--fg:#eef1f6;--dim:#9aa7bd;--accent:#6aa5ff;--focus:#7db0ff;color-scheme:dark}
*{box-sizing:border-box}[hidden]{display:none!important}
html,body{margin:0}
body{background:var(--bg);color:var(--fg);font:16px/1.5 var(--fb);-webkit-font-smoothing:antialiased;
padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-top:env(safe-area-inset-top,0px);padding-bottom:max(40px,env(safe-area-inset-bottom,0px))}
.wrap{max-width:820px;margin:0 auto}
:focus-visible{outline:3px solid var(--focus);outline-offset:2px;border-radius:6px}
header{padding:28px 0 8px;display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
.eyebrow{font-size:13px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:var(--dim)}
h1{font:700 clamp(44px,10vw,72px)/.95 var(--fd);text-transform:uppercase;margin:6px 0 0;text-wrap:balance}
.sub{color:var(--dim);margin:12px 0 0;max-width:58ch}
.themebtn{flex:none;width:44px;height:44px;border-radius:50%;border:1px solid var(--line);background:var(--surface);color:var(--fg);font-size:18px;cursor:pointer}
.tools{position:sticky;top:env(safe-area-inset-top,0px);background:var(--bg);padding:12px 0;margin-top:14px;z-index:5;border-bottom:1px solid var(--line);display:grid;gap:10px}
.fl{display:flex;gap:6px;overflow-x:auto;scrollbar-width:none;padding-bottom:2px}.fl::-webkit-scrollbar{display:none}
.f{flex:none;height:40px;padding:0 14px;border-radius:999px;border:1.5px solid var(--line2);background:transparent;color:var(--fg);font:600 14.5px var(--fb);cursor:pointer}
.f[aria-pressed="true"]{background:var(--fg);border-color:var(--fg);color:var(--bg)}
#q{width:100%;height:44px;border-radius:12px;border:1.5px solid var(--line2);background:var(--surface);color:var(--fg);font:16px var(--fb);padding:0 14px}
.grp{margin-top:30px}
h2{font:700 28px var(--fd);text-transform:uppercase;letter-spacing:.02em;margin:0 0 12px}
.list{display:grid;gap:10px}
.it{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:13px;color:var(--dim)}
.src{font-weight:700;color:var(--fg)}
.lang{border:1px solid var(--line2);border-radius:5px;padding:0 5px;font-size:11px;font-weight:700;letter-spacing:.06em}
time{margin-left:auto;font-variant-numeric:tabular-nums}
.it h3{margin:6px 0 0;font:600 18px/1.3 var(--fb);text-wrap:balance}
.it h3 a{color:var(--fg);text-decoration:none}.it h3 a:hover{color:var(--accent);text-decoration:underline}
.it p{margin:6px 0 0;color:var(--dim);font-size:15px}
.empty,.none{color:var(--dim);margin-top:30px}
footer{margin-top:40px;border-top:1px solid var(--line);padding-top:16px;color:var(--dim);font-size:13.5px}
</style></head><body><div class="wrap">
<header><div><div class="eyebrow">Mise à jour le %%STAMP%%</div><h1>Veille IA</h1>
<p class="sub">Les derniers articles des labos, de la presse et des newsletters, sélectionnés automatiquement. Nouvelle édition chaque lundi.</p></div>
<button type="button" class="themebtn" id="th" aria-label="Changer de thème">◐</button></header>
<div class="tools"><div class="fl" role="group" aria-label="Filtrer par type de source">%%FILTERS%%</div>
<input id="q" type="search" placeholder="Rechercher dans les titres" aria-label="Rechercher dans les titres"></div>
<main id="main">%%BODY%%<p class="none" id="none" hidden>Aucun article ne correspond.</p></main>
<footer>%%COUNT%% articles · %%FOOT%%. Les titres et extraits viennent des sources et appartiennent à leurs auteurs.</footer></div>
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
