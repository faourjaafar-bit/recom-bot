"""The NEWSROOM v2 (2026-11-24, after a gold buy was stopped out by a hawkish Fed headline + a big US data beat that
the old agent missed). Replaces news_rt as the desk's news vote. Three parts:

  1. Better sources: news_rt's feeds + Google News limited to top outlets (Reuters, Bloomberg, WSJ, CNBC, FT,
     Kitco, MarketWatch) + a Fed-speakers feed. Each headline is weighted by its source and by its theme.
  2. Data surprises: the live TradingView economic calendar (actual vs forecast). A US beat (strong economy or hot
     inflation) is bad for gold, a miss is good; a crude stock build is bad for oil. Fades over 2 hours.
  3. Learning from mistakes: every headline is graded by what gold / oil really did in the 30 min after it. Each
     theme and each source keeps a hit rate; once it has 10+ graded headlines its weight moves (0.3x-2x). A theme
     that keeps calling the move wrong goes quiet by itself. After every losing call, lesson() saves the headlines and
     releases around it (cache/lessons.jsonl) and tells the owner what moved the market.

  python3 news_agent.py            # the vote now, the latest graded lessons, theme / source weights
  python3 news_agent.py learn      # grade the stored headlines now
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import gold_alerts as ga
import news_rt
import recom_track
import zone_plan as zp

HERE = os.path.dirname(os.path.abspath(__file__))
LEARN = os.path.join(HERE, "cache", "news_learn.json")
CAL = os.path.join(HERE, "cache", "tv_calendar.json")
LESSONS = os.path.join(HERE, "cache", "lessons.jsonl")
GN = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="
TOP = "(site:reuters.com OR site:bloomberg.com OR site:wsj.com OR site:cnbc.com OR site:ft.com OR site:kitco.com OR site:marketwatch.com)"
EXTRA = [GN + urllib.parse.quote(f"(gold OR bullion OR dollar OR treasury yields) {TOP} when:2h"),
         GN + urllib.parse.quote(f"(oil OR crude OR OPEC) {TOP} when:2h"),
         GN + urllib.parse.quote("Fed (Powell OR Williams OR Waller OR Logan OR Bowman OR Jefferson OR Goolsbee OR Hammack OR Musalem) when:2h")]
for u in EXTRA:
    if u not in news_rt.FEEDS:
        news_rt.FEEDS.append(u)

SOURCE_W = {"reuters": 1.5, "bloomberg": 1.5, "wsj": 1.5, "wall street journal": 1.5, "cnbc": 1.4, "financial times": 1.5,
            "kitco": 1.4, "marketwatch": 1.3, "fxstreet": 1.2, "yahoo": 1.1, "investing.com": 1.1, "fxempire": 1.0}
THEMES = [("fed", r"\b(fed|fomc|powell|williams|waller|logan|bowman|rate hikes?|rate cuts?|hawkish|dovish|tightening)\b"),
          ("dollar", r"\b(dollar|dxy|greenback|yields?|treasur)"),
          ("geo", r"\b(war|attack|missile|escalat|invasion|conflict|tensions?|ceasefire|truce|hormuz|sanction)"),
          ("flows", r"\b(etf|central banks?|safe[- ]haven|outflows?|inflows?|profit[- ]taking)\b"),
          ("supply", r"\b(opec|inventor|stockpile|output|production|supply)\b"),
          ("probe", r"\b(megaspeed|smuggl|probe|investigat|congress|briefing|export|entity list|doj)")]
CUT = 1.5
HALF_LIFE = 45 * 60
WINDOW = 3 * 3600


def source_of(title):
    tail = title.rsplit(" - ", 1)[-1].lower() if " - " in title else ""
    return next((k for k in SOURCE_W if k in tail), "other")


def theme_of(title):
    s = title.lower()
    return next((name for name, pat in THEMES if re.search(pat, s)), "price")


def _w(table, key, base=1.0):
    st = table.get(key)
    if not st or st["n"] < 10:
        return base
    return round(min(2.0, max(0.3, base * (0.5 + st["ok"] / st["n"]))), 2)


# ---------- data surprises (TradingView economic calendar) ----------
STRONG_IS_BAD = re.compile(r"claims|unemployment|jobless|continuing", re.I)  # higher = weaker economy
OIL_STOCKS = re.compile(r"crude oil (stock|inventor)|crude stock", re.I)


def calendar(hours_back=6, hours_fwd=36):
    c = recom_track.load(CAL, {})
    if time.time() - c.get("t", 0) > 15 * 60:
        now = datetime.now(timezone.utc)
        q = urllib.parse.urlencode({"from": datetime.fromtimestamp(now.timestamp() - hours_back * 3600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                                    "to": datetime.fromtimestamp(now.timestamp() + hours_fwd * 3600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                                    "countries": "US", "minImportance": "0"})
        try:
            req = urllib.request.Request("https://economic-calendar.tradingview.com/events?" + q,
                                         headers={"Origin": "https://www.tradingview.com", "User-Agent": "Mozilla/5.0"})
            ev = json.loads(urllib.request.urlopen(req, timeout=20).read()).get("result") or []
            c = {"t": time.time(), "events": ev}
        except Exception as e:  # keep the old copy, retry in 5 min
            ga.log(f"news_agent calendar failed: {e}")
            c["t"] = time.time() - 10 * 60
        json.dump(c, open(CAL, "w"))
    return c.get("events", [])


# Only real market movers block a call (user, 2026-11-25: "stopping all trades like an idiot"). Importance 0 items
# (MBA mortgage rates, bill/note auctions, ethanol) vetoed every trade around them: an oil buy at 81.57 on 11-25
# was blocked by "MBA 5/1 ARM Contract Rate". Importance 1+ or a named mover still blocks.
MOVERS = re.compile(r"\b(cpi|pce|ppi|payrolls?|non ?farm|unemployment rate|jobless claims|gdp growth|retail sales|"
                    r"ism|fomc|fed|powell|interest rate decision|consumer confidence|michigan|jolts|eia crude oil stocks)\b", re.I)


def moves_market(e):
    return e.get("importance", -1) >= 1 or bool(MOVERS.search(e.get("title", "")))


def release_near(ts, before=30 * 60, after=15 * 60):
    """(title, time) of a medium/high US release from 30 min before to 15 min after ts, or None."""
    for e in calendar():
        try:
            et = datetime.fromisoformat(e["date"].replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        if et - before <= ts <= et + after and moves_market(e):
            return f"{e['title']} at {datetime.fromtimestamp(et).strftime('%H:%M')}"
    return None


def surprises(sym, now=None):
    """[(score, text)] for releases in the last 2 h with actual vs forecast. + = good for a buy of sym."""
    now = now or time.time()
    out = []
    for e in calendar():
        a, f = e.get("actual"), e.get("forecast")
        if a is None or f is None:
            continue
        try:
            et = datetime.fromisoformat(e["date"].replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        age = now - et
        if not 0 <= age <= 2 * 3600:
            continue
        surp = (a - f) / (abs(f) or 1)
        if abs(surp) < 0.02:
            continue
        mag = (2 if e.get("importance", 0) >= 1 else 1) * (1 if abs(surp) < 0.08 else 1.5) * 0.5 ** (age / 3600)
        title = e.get("title", "")
        if sym == "GC=F" and not OIL_STOCKS.search(title):
            sign = 1 if STRONG_IS_BAD.search(title) else -1  # a beat on growth / inflation data hurts gold
            out.append((round(sign * (1 if surp > 0 else -1) * mag, 2), f"{title} {a} vs {f} forecast"))
        elif sym == "CL=F" and OIL_STOCKS.search(title):
            out.append((round(-(1 if surp > 0 else -1) * mag, 2), f"{title} {a} vs {f} forecast"))
    return out


# ---------- learning ----------
def learn():
    """Grade headlines 30 min to 24 h old by the real 30-min move after them; update theme / source hit rates."""
    st = news_rt.refresh()
    L = recom_track.load(LEARN, {"graded": {}, "theme": {}, "source": {}})
    bars = {}
    for s in ("GC=F", "CL=F", "NVDA"):
        for rng in ("2d", "1d"):  # small ranges: big responses sometimes arrive cut off
            try:
                bars[s] = [x for x in zp.yahoo_bars(s, rng, "5m") if x["c"]]
                break
            except Exception as e:
                ga.log(f"news_agent bars {s} {rng} failed: {e}")
    now = time.time()
    for k, h in st["items"].items():
        if k in L["graded"] or not h.get("score") or not 1800 <= now - h["ts"] <= 86400:
            continue
        for sym, sc in h["score"].items():
            b = bars.get(sym) or []
            p0 = next((x["c"] for x in b if x["ts"] >= h["ts"]), None)
            p1 = next((x["c"] for x in b if x["ts"] >= h["ts"] + 1800), None)
            if not p0 or not p1 or not sc:
                continue
            ret = (p1 - p0) / p0
            if abs(ret) < 0.0005:  # no real move: not graded
                continue
            ok = int((sc > 0) == (ret > 0))
            for table, key in (("theme", f"{sym}|{theme_of(h['title'])}"), ("source", source_of(h["title"]))):
                t = L[table].setdefault(key, {"n": 0, "ok": 0})
                t["n"] += 1
                t["ok"] += ok
        L["graded"][k] = now
    L["graded"] = {k: v for k, v in L["graded"].items() if now - v < 3 * 86400}
    L["t"] = now
    json.dump(L, open(LEARN, "w"), indent=1)
    return L


def vote(sym):
    """(vote, reason, n): learned-weight news sentiment over 3 h + data surprises. Same shape as news_rt.vote."""
    L = recom_track.load(LEARN, {"theme": {}, "source": {}})
    if time.time() - L.get("t", 0) > 15 * 60:
        try:
            L = learn()
        except Exception as e:
            ga.log(f"news_agent learn failed: {e}")
    st, now = news_rt.refresh(), time.time()
    hits = [h for h in st["items"].values() if sym in (h.get("score") or {}) and now - h["ts"] < WINDOW]
    parts = []
    for h in hits:
        w = SOURCE_W.get(source_of(h["title"]), 0.6) * _w(L["source"], source_of(h["title"])) \
            * _w(L["theme"], f"{sym}|{theme_of(h['title'])}") * 0.5 ** ((now - h["ts"]) / HALF_LIFE)
        parts.append((h["score"][sym] * w, h["title"]))
    data = surprises(sym, now)
    net = sum(p for p, _ in parts) + sum(s for s, _ in data)
    v = 1 if net >= CUT else -1 if net <= -CUT else 0
    top = max(parts + [(s, "DATA: " + t) for s, t in data], key=lambda x: abs(x[0]), default=None)
    why = f"newsroom v2 net {net:+.1f} ({len(hits)} headlines, {len(data)} data surprises)" + (f"; top: {top[1][:85]}" if top else "")
    return v, why, len(hits) + len(data)


# ---------- emergency: news turning against an open call ----------
def shift_against(sym, side, window=20 * 60):
    """Text of a fresh strong reason against an open call, or None: a score-2 headline (|score| >= 2) or a US
    data surprise against the side, in the last 20 min. recom_track.watch() checks this every minute."""
    if sym not in ("GC=F", "CL=F", "NVDA"):
        return None
    sign = 1 if side == "buy" else -1
    now = time.time()
    for sc, txt in surprises(sym, now):
        if sc * sign <= -1:
            return "📊 " + txt
    st = news_rt.refresh()
    for h in sorted(st["items"].values(), key=lambda h: -h["ts"]):
        if now - h["ts"] > window:
            break
        if (h.get("score") or {}).get(sym, 0) * sign <= -2:
            return "🗞 " + h["title"][:120]
    return None


# ---------- lessons from losses ----------
def lesson(t, key):
    """After a losing call: what moved the market around it. Saved + sent to the owner's bot chat."""
    sym, end = t.get("sym"), time.time()
    start = t.get("filled") or t.get("posted") or end - 3600
    st = news_rt.refresh()
    near = [h for h in st["items"].values() if start - 1800 <= h["ts"] <= end + 600 and sym in (h.get("score") or {})]
    against = sorted([h for h in near if h["score"][sym] * (1 if t.get("side") == "buy" else -1) < 0],
                     key=lambda h: -abs(h["score"][sym]))[:3]
    rel = [f"{e['title']} {e.get('actual')} vs {e.get('forecast')}" for e in calendar()
           if start - 1800 <= datetime.fromisoformat(e["date"].replace("Z", "+00:00")).timestamp() <= end + 600]
    rec = {"key": key, "sym": sym, "side": t.get("side"), "entry": t.get("entry"), "t": end,
           "against": [h["title"] for h in against], "releases": rel}
    with open(LESSONS, "a") as f:
        f.write(json.dumps(rec) + "\n")
    lines = [f"📚 Lesson from the {t.get('side', '')} {key.split('|')[0]} @{t.get('entry')} loss:"]
    lines += [f"🗞 {x[:110]}" for x in rec["against"]] or ["🗞 no headline against it: a pure price move"]
    lines += [f"📊 {x[:110]}" for x in rel[:3]]
    lines.append("The newsroom grades these themes on the real move and re-weights them.")
    try:
        e = ga.load_env(ga.ENV_PATH)
        data = urllib.parse.urlencode({"chat_id": e["TELEGRAM_CHAT_ID"], "text": "\n".join(lines)}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{e['TELEGRAM_BOT_TOKEN']}/sendMessage", data, timeout=20)
    except Exception as ex:
        ga.log(f"lesson send failed: {ex}")
    return rec


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "learn":
        L = learn()
    else:
        L = recom_track.load(LEARN, {"theme": {}, "source": {}})
    for sym in ("GC=F", "CL=F"):
        print(sym, vote(sym))
        print("  surprises:", surprises(sym))
    print("themes:", {k: f"{v['ok']}/{v['n']} -> {_w(L['theme'], k)}x" for k, v in L.get("theme", {}).items()})
    print("sources:", {k: f"{v['ok']}/{v['n']} -> {_w(L['source'], k)}x" for k, v in L.get("source", {}).items()})
    print("near release now:", release_near(time.time()))
