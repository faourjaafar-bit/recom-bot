"""Realtime newsroom for the desk (idea from the fidetolabs "realtime news processing" reel, 2026-11-24).

Every few minutes it pulls fresh headlines (Google News last hour, FXStreet, OilPrice), tags each one GOLD / OIL,
scores it with fixed keyword rules (no LLM per headline: instant and free) and keeps a 24h stream.
The vote is the NET sentiment of the recent headlines, each weighted by age (half-life 45 min):
  net >= +1.5 -> +1 (news supports a buy), net <= -1.5 -> -1, else 0.

  python3 news_rt.py            # pull now, print the scored headlines and both votes
"""
import email.utils, hashlib, json, math, os, re, time, urllib.parse
import xml.etree.ElementTree as ET

import gold_alerts as ga

HERE = os.path.dirname(os.path.abspath(__file__))
STREAM = os.path.join(HERE, "cache", "news_stream.json")
REFRESH, HALF_LIFE, WINDOW, CUT = 120, 45 * 60, 3 * 3600, 1.5

GN = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="
FEEDS = [GN + urllib.parse.quote("gold price OR XAUUSD OR bullion when:1h"),
         GN + urllib.parse.quote("crude oil OR brent OR WTI OR OPEC when:1h"),
         GN + urllib.parse.quote("Fed rate OR dollar index OR treasury yields when:1h"),
         "https://www.fxstreet.com/rss/news", "https://oilprice.com/rss/main"]

SUBJECT = {"GC=F": re.compile(r"\b(gold|xau|bullion|precious metal)", re.I),
           "CL=F": re.compile(r"\b(oil|crude|brent|wti|opec|petroleum|gasoline)", re.I)}
MACRO = re.compile(r"\b(fed|fomc|powell|rate cut|rate hike|dollar|dxy|treasury|yields?|inflation|cpi|payrolls|nfp)\b", re.I)
UP = r"(bullish|ris(e|es|ing)|jump|surg|climb|gain|rall|soar|advanc|rebound|record high|higher|up \d|extends? gains)"
DOWN = r"(bearish|pull(s|ed)? back|fall|fell|slip|drop|declin|tumbl|slid|sink|plung|retreat|lower|down \d|loss|extends? losses)"

# (pattern, gold score, oil score): applied to every headline that mentions the asset or the macro words
RULES = [
    (r"\b(dollar|dxy|greenback|yields?)\b.{0,40}" + UP, -1, -0.5),
    (r"\b(dollar|dxy|greenback|yields?)\b.{0,40}" + DOWN, +1, +0.5),
    (r"\brate cuts?\b|\bdovish\b|\beas(e|ing) (policy|rates)\b", +1, +0.5),
    (r"\brate hikes?\b|\bhawkish\b|\bhigher for longer\b|\b(more|further) tightening\b|\bmust act\b.{0,20}inflation", -1, -0.5),
    (r"\b(war|attack|missile|strike[sd]? on|escalat|invasion|conflict|tensions?)\b", +1, +1),
    (r"\b(ceasefire|truce|peace (deal|talks)|de-?escalat)", -1, -1),
    (r"\bsafe[- ]haven\b|\bcentral banks? (buy|add|purchas)", +1, 0),
    (r"\bprofit[- ]taking\b", -0.5, -0.5),
    (r"\bopec\+?\b.{0,40}\b(cut|curb|reduc|extend)", 0, +1),
    (r"\bopec\+?\b.{0,40}\b(hike|boost|rais|increas|unwind)", 0, -1),
    (r"\b(inventor(y|ies)|stockpiles?|stocks)\b.{0,30}\b(draw|fall|fell|drop|declin)", 0, +1),
    (r"\b(inventor(y|ies)|stockpiles?|stocks)\b.{0,30}\b(build|rise|rose|climb|jump)", 0, -1),
    (r"\b(sanction|supply (disruption|outage)|pipeline (attack|outage)|hurricane|red sea|houthi|strait of hormuz)", 0, +1),
    (r"\b(oversupply|glut|demand (worries|concerns|fears)|recession)", 0, -1),
]


def headlines():
    out = []
    for url in FEEDS:
        try:
            root = ET.fromstring(ga.get(url, tries=2))
        except Exception as e:
            ga.log(f"news_rt feed failed {url[:60]}: {e}")
            continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            try:
                ts = email.utils.parsedate_to_datetime(it.findtext("pubDate")).timestamp()
            except Exception:
                ts = time.time()
            if title:
                out.append({"title": title, "ts": ts, "src": urllib.parse.urlparse(url).netloc})
    return out


def score(title):
    """{sym: score} for the assets this headline is about (missing = not about it)."""
    s, out = title.lower(), {}
    for sym, subj in SUBJECT.items():
        about, macro = bool(subj.search(s)), sym == "GC=F" and bool(MACRO.search(s))
        if not (about or macro):
            continue
        v = sum(g if sym == "GC=F" else o for pat, g, o in RULES if re.search(pat, s))
        if about and not v:  # plain price headline about the asset itself: "Gold climbs to ..."
            v = 1 if re.search(UP, s) else -1 if re.search(DOWN, s) else 0
        out[sym] = max(-2, min(2, v))
    return out


def refresh(force=False):
    st = _load()
    if not force and time.time() - st["t"] < REFRESH:
        return st
    for h in headlines():
        k = hashlib.md5(h["title"].lower().encode()).hexdigest()[:12]
        if k not in st["items"]:
            st["items"][k] = h
    for h in st["items"].values():  # rescore all, so rule changes apply to stored headlines too
        h["score"] = score(h["title"])
    cutoff = time.time() - 24 * 3600
    st["items"] = {k: v for k, v in st["items"].items() if v["ts"] > cutoff}
    st["t"] = time.time()
    json.dump(st, open(STREAM, "w"))
    return st


def _load():
    try:
        return json.load(open(STREAM))
    except Exception:
        return {"t": 0, "items": {}}


def vote(sym):
    """(vote, reason, n) from the age-weighted net sentiment of the last 3 hours."""
    st, now = refresh(), time.time()
    hits = [h for h in st["items"].values() if sym in h["score"] and now - h["ts"] < WINDOW]
    net = sum(h["score"][sym] * 0.5 ** ((now - h["ts"]) / HALF_LIFE) for h in hits)
    v = 1 if net >= CUT else -1 if net <= -CUT else 0
    top = max(hits, key=lambda h: abs(h["score"][sym]) * 0.5 ** ((now - h["ts"]) / HALF_LIFE), default=None)
    why = f"realtime news net {net:+.1f} from {len(hits)} headlines (3h)" + (f"; top: {top['title'][:80]}" if top else "")
    return v, why, len(hits)


if __name__ == "__main__":
    st = refresh(force=True)
    now = time.time()
    for h in sorted(st["items"].values(), key=lambda h: -h["ts"])[:25]:
        if h["score"]:
            print(f"{(now - h['ts']) / 60:5.0f}m  {json.dumps(h['score']):26} {h['title'][:95]}")
    for sym in SUBJECT:
        print(sym, vote(sym))
