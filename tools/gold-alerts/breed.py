"""Bot breeding (no AI guessing): generate thousands of rule-based bots, keep the ones that win on the first 70% of
the data (in-sample), then throw out every bot that does not ALSO win on the last 30% it never saw (out-of-sample),
and shake the survivors with a Monte Carlo test to see how bad a losing streak can get. Idea from the user's video:
"breed thousands of bots, optimise, then forward test to check they're not lucky, overfit or decayed".

  python3 breed.py            # breed gold, oil and NVDA on 60 days of 5-minute bars, print the survivors
  python3 breed.py GC=F       # one symbol
  python3 breed.py --highwin  # only bots that keep a 78%+ win rate AND a profit on the unseen data

A bot = one entry trigger x one trend filter x one session x one stop x one target x one holding time.
Results go to cache/breed_results.json. Survivors are NOT posted: they go to a forward test first (paper only).
"""
import itertools
import json
import os
import random
import sys
from datetime import datetime, timezone

import live_recom as lr
import zone_plan as zp

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "cache", "breed_results.json")
COST = {"GC=F": 0.3, "CL=F": 0.03, "NVDA": 0.02}
PIP = {"GC=F": 0.10, "CL=F": 0.01}
SPLIT = 0.7


def prep(b):
    c = [x["c"] for x in b]
    e20, e50, e200 = lr.ema(c, 20), lr.ema(c, 50), lr.ema(c, 200)
    atr, a = [], None
    for i, x in enumerate(b):
        tr = x["h"] - x["l"] if i == 0 else max(x["h"], b[i - 1]["c"]) - min(x["l"], b[i - 1]["c"])
        a = tr if a is None else a + (tr - a) / 14
        atr.append(a)
    rsi, up, dn = [50.0], 0.0, 0.0
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]
        up, dn = up + (max(d, 0) - up) / 14, dn + (max(-d, 0) - dn) / 14
        rsi.append(100 - 100 / (1 + up / dn) if dn else 100)
    vol = [sum(y["v"] for y in b[max(0, i - 20):i]) / max(1, min(20, i)) for i in range(len(b))]
    hour = [datetime.fromtimestamp(x["ts"], timezone.utc).hour for x in b]
    return {"c": c, "e20": e20, "e50": e50, "e200": e200, "atr": atr, "rsi": rsi, "vol": vol, "hour": hour}


def trig_at(name, b, P, i):
    """One trigger on bar i: +1 buy, -1 sell, 0 nothing (before trend / session filters)."""
    c, x = P["c"], b[i]
    if name == "pullback":
        s = lr.signal(b, i, (P["e20"], P["e50"], P["e200"]))
        return 0 if not s else (1 if s["side"] == "buy" else -1)
    if name in ("brk12", "brk24"):
        m = 12 if name == "brk12" else 24
        if not (P["vol"][i] and x["v"] >= 1.2 * P["vol"][i]):
            return 0
        hi, lo = max(y["h"] for y in b[i - m:i]), min(y["l"] for y in b[i - m:i])
        return 1 if c[i] > hi else -1 if c[i] < lo else 0
    if name == "rsi_rev":
        r0, r1 = P["rsi"][i - 1], P["rsi"][i]
        return 1 if r0 < 30 <= r1 else -1 if r0 > 70 >= r1 else 0
    if name == "ema_cross":
        e0, e1 = c[i - 1] - P["e20"][i - 1], c[i] - P["e20"][i]
        return 1 if e0 <= 0 < e1 else -1 if e0 >= 0 > e1 else 0
    d3 = [b[j]["c"] - b[j]["o"] for j in (i - 2, i - 1, i)]  # momentum3
    if not b[i]["v"] > b[i - 1]["v"] > b[i - 2]["v"]:
        return 0
    return 1 if all(d > 0 for d in d3) else -1 if all(d < 0 for d in d3) else 0


NAMES = ("pullback", "brk12", "brk24", "rsi_rev", "ema_cross", "momentum3")


def triggers(b, P):
    """Every trigger as a list: +1 buy, -1 sell, 0 nothing, for each bar (before any filter)."""
    out = {k: [0] * len(b) for k in NAMES}
    for i in range(210, len(b)):
        for k in NAMES:
            out[k][i] = trig_at(k, b, P, i)
    return out


# The bred bots in use (2026-11-23 breeding, 60 days of 5-min bars: in-sample 70% / unseen 30%, Monte Carlo):
# gold : RSI reversal with the trend, 50-pip stop, 3R      in +0.43R (70 trades)  unseen +0.34R (26)
# oil  : fade a 3-bar volume run, New York hours, 50 pips, 3R   in +0.28R (73)    unseen +0.27R (37)
# NVDA : 3-bar volume run with the trend, NY hours, 1 ATR, 3R   in +0.33R (57)    unseen +0.93R (28)
# 2026-11-23 (user: "78% win rate minimum... if it is better, change"): gold and NVDA moved to the high-win bots,
# which beat the scalp bots on profit per worst drawdown on the unseen data; oil stays on the scalp bot (its 78% bot
# had only 18 unseen trades and a similar ratio).
# gold : fade EMA20 crosses, NY hours, skip news, SL 120 pips, TP 0.33R   train 86% wins (106)  unseen 85% (55)
# NVDA : EMA20 crosses with the trend, NY hours, skip news, SL 2 ATR, TP 0.5R   train 80% (84)  unseen 90% (30)
# 2026-11-24 (user: "we run as the market opens, live coverage"): one tested bot PER SESSION, so the desk covers the
# market from the open. UTC sessions: asia 23-07, ldn 07-13, ny 13-20 (Istanbul = UTC+3).
# gold asia: EMA20 cross with trend, 120 pips, 0.33R   train 79% (122)  unseen 78% (60), thin edge +0.03R
# gold ldn : fade 1-hour breakouts, 3 ATR, 0.25R         train 87% (125)  unseen 92% (53), +0.13R
# oil asia : RSI reversal against trend, 80 pips, 1.5R   train 58% (48)   unseen 48% (25), +0.08R (no 78% bot survived)
# oil ldn  : pullback, 3 ATR, 0.33R                      train 80% (41)   unseen 84% (19), +0.07R
LIVE = {"GC=F": [("ema_cross", "with", "asia", ("pips", 120), 0.33, 24, "news_off"),
                 ("brk12", "against", "ldn", ("atr", 3.0), 0.25, 48, "skip_news"),
                 ("ema_cross", "against", "ny", ("pips", 120), 0.33, 48, "skip_news")],
        "CL=F": [("rsi_rev", "against", "asia", ("pips", 80), 1.5, 48),
                 ("pullback", "none", "ldn", ("atr", 3.0), 0.33, 12, "skip_news"),
                 ("momentum3", "against", "ny", ("pips", 50), 3.0, 48)],
        "NVDA": [("ema_cross", "with", "ny", ("atr", 2.0), 0.5, 48, "skip_news")]}


def active_gene(sym, hour=None):
    """The live bot for the session at this UTC hour (None between sessions)."""
    from datetime import datetime as _d, timezone as _tz
    h = _d.now(_tz.utc).hour if hour is None else hour
    return next((g for g in LIVE[sym] if in_session(g[2], h)), None)


def risk_of(sym, b):
    """The live bot's stop distance for sym, from its gene (pips, or x the 14-bar ATR of the 5-min bars)."""
    from datetime import datetime as _d, timezone as _tz
    g = active_gene(sym, _d.fromtimestamp(b[-2]["ts"], _tz.utc).hour) or LIVE[sym][0]
    stype, sval = g[3]
    if stype == "pips":
        return sval * PIP[sym]
    P = prep(b)
    return sval * P["atr"][-2]


def plan(sym, side, entry, risk, gene=None):
    """Card levels for the live bot. A 3R scalp bot: TP 1R / 2R / 3R, a win at TP3. A high-win bot: TP1 is its
    tested exit (rr x R) and the call is a win there; TP2 / TP3 = 2x / 3x that distance for anyone who holds on."""
    gene = gene or active_gene(sym) or LIVE[sym][0]
    rr = gene[4]
    d = 1 if side == "buy" else -1
    step = rr * risk if rr < 1 else risk
    import time as _t
    import recom_track
    now = _t.time()
    hold_end = now + gene[5] * 300  # the bot's tested holding time (5-min bars)
    mkt = recom_track.market_close(sym, now)  # live coverage until the market closes (no 23:00 cut any more)
    return {"side": side, "entry": entry, "stop": entry - d * risk, "t1": entry + d * step, "t2": entry + d * 2 * step,
            "t3": entry + d * 3 * step, "win_at": 1 if rr < 1 else 3, "rr": rr,
            "close_by": min(hold_end, mkt),
            "close_why": "market" if mkt < hold_end else "time"}


def live_rule(sym):
    """A rule for live_recom.RULE / the desk Hunter: f(b, i, E) -> {"side", "entry", "stop", "gene"} or None.
    It runs the bot of the session the bar is in (asia / London / New York)."""

    def f(b, i, E=None):
        if i < 210:
            return None
        P = prep(b[:i + 1])
        h = P["hour"][i]
        for g in LIVE[sym]:
            trig, trend, sess, (stype, sval) = g[:4]
            skip_news = len(g) > 6 and g[6] == "skip_news"
            if not in_session(sess, h) or (skip_news and in_news(b[i]["ts"])):
                continue
            v = trig_at(trig, b, P, i)
            if not v:
                continue
            tr = 1 if P["e50"][i] > P["e200"][i] else -1
            if trend == "with" and v != tr:
                continue
            d = -v if trend == "against" else v
            risk = sval * P["atr"][i] if stype == "atr" else sval * PIP[sym]
            return {"side": "buy" if d > 0 else "sell", "entry": P["c"][i], "stop": P["c"][i] - d * risk, "gene": g}
        return None
    f.__name__ = f"bred_sessions_{sym}"
    return f


NEWS_WINDOWS = ((12 * 60 + 25, 14 * 60), (17 * 60 + 55, 19 * 60 + 30))  # UTC: US data 8:30 ET, Fed / FOMC 2 pm ET


def in_news(ts):
    """True inside the usual US news windows (8:30 ET data, 2 pm ET Fed), when spreads jump and stops get run."""
    t = datetime.fromtimestamp(ts, timezone.utc)
    m = t.hour * 60 + t.minute
    return t.weekday() < 5 and any(lo <= m <= hi for lo, hi in NEWS_WINDOWS)


SESSIONS = {"all": None, "ldn_ny": range(7, 17), "ny": range(13, 20), "asia": (23, 0, 1, 2, 3, 4, 5, 6), "ldn": range(7, 13)}


def in_session(sess, hour):
    r = SESSIONS.get(sess)
    return r is None or hour in r


def genes_highwin(sym):
    """For a 78%+ win rate: small targets (0.25-0.75R) against wider stops, with and without the news filter."""
    stops = [("atr", m) for m in (1.0, 1.5, 2.0, 3.0)] + ([("pips", p) for p in (50, 80, 120)] if sym in PIP else [])
    return list(itertools.product(
        ["pullback", "brk12", "brk24", "rsi_rev", "ema_cross", "momentum3"], ["none", "with", "against"],
        ["all", "ldn_ny", "ny", "asia", "ldn"], stops, [0.25, 0.33, 0.5, 0.75], [12, 24, 48], ["news_off", "skip_news"]))


def genes(sym):
    stops = [("atr", m) for m in (0.75, 1.0, 1.5, 2.0)] + ([("pips", p) for p in (30, 50, 80)] if sym in PIP else [])
    return list(itertools.product(
        ["pullback", "brk12", "brk24", "rsi_rev", "ema_cross", "momentum3"],  # entry trigger
        ["none", "with", "against"],  # trend filter (EMA50 vs EMA200); "against" = fade the trigger
        ["all", "ldn_ny", "ny", "asia", "ldn"],  # session (UTC: 7-17 / 13-20 / 23-7 / 7-13)
        stops,  # stop distance
        [1.0, 1.5, 2.0, 3.0],  # target in R
        [12, 24, 48]))  # holding time in 5-min bars (1h / 2h / 4h)


def run_bot(sym, b, P, T, g, lo, hi):
    trig, trend, sess, (stype, sval), rr, hold = g[:6]
    skip_news = len(g) > 6 and g[6] == "skip_news"
    sig, rs, i = T[trig], [], max(lo, 210)
    while i < hi - 1:
        v = sig[i]
        if not v or not in_session(sess, P["hour"][i]) or (skip_news and in_news(b[i]["ts"])):
            i += 1
            continue
        tr = 1 if P["e50"][i] > P["e200"][i] else -1
        if trend == "with" and v != tr:
            i += 1
            continue
        d = -v if trend == "against" else v
        e = P["c"][i]
        risk = sval * P["atr"][i] if stype == "atr" else sval * PIP[sym]
        if risk <= 0:
            i += 1
            continue
        stop, tgt, r, j = e - d * risk, e + d * rr * risk, None, i + 1
        while j < hi and j - i <= hold:
            x = b[j]
            if (x["l"] <= stop) if d > 0 else (x["h"] >= stop):
                r = -1.0
                break
            if (x["h"] >= tgt) if d > 0 else (x["l"] <= tgt):
                r = rr
                break
            j += 1
        if r is None:
            j = min(j, hi - 1)
            r = (P["c"][j] - e) * d / risk
        rs.append(r - COST[sym] / risk)
        i = j + 1
    return rs


def stats(rs):
    if not rs:
        return {"n": 0, "avg": 0, "win": 0, "pf": 0}
    w = sum(r for r in rs if r > 0)
    l = -sum(r for r in rs if r < 0)
    return {"n": len(rs), "avg": round(sum(rs) / len(rs), 3), "win": round(100 * sum(r > 0 for r in rs) / len(rs)),
            "pf": round(w / l, 2) if l else 99}


def monte_carlo(rs, runs=1000):
    """Shuffle the trade order 1,000 times: the 95th-percentile worst drawdown in R and the chance of ending down."""
    dds, losing = [], 0
    for _ in range(runs):
        x = rs[:]
        random.shuffle(x)
        eq = peak = dd = 0.0
        for r in x:
            eq += r
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
        dds.append(dd)
        losing += eq < 0
    dds.sort()
    return {"dd95": round(dds[int(0.95 * runs)], 1), "p_loss": round(100 * losing / runs)}


def breed(sym, highwin=False, min_win=78, sessions=None):
    b = [x for x in zp.yahoo_bars(sym, "60d", "5m") if x["v"] is not None]
    P, cut = prep(b), int(len(b) * SPLIT)
    T = triggers(b, P)
    G = genes_highwin(sym) if highwin else genes(sym)
    if sessions:
        G = [g for g in G if g[2] in sessions]
    ins = []
    for g in G:
        s = stats(run_bot(sym, b, P, T, g, 0, cut))
        if s["n"] >= 30 and (not highwin or (s["win"] >= min_win and s["avg"] > 0)):
            ins.append((s["avg"], g, s))
    ins.sort(key=lambda t: t[0], reverse=True)
    survivors = []
    for avg, g, s in ins[:40]:  # the 40 best in-sample bots go to the unseen 30%
        rs = run_bot(sym, b, P, T, g, cut - 210, len(b))
        o = stats(rs)
        ok = (o["n"] >= 10 and o["win"] >= min_win and o["avg"] > 0.0) if highwin else \
            (o["n"] >= 10 and o["avg"] > 0.05 and avg - o["avg"] < 0.35)
        if ok:
            full = run_bot(sym, b, P, T, g, 0, len(b))
            survivors.append({"bot": g, "in": s, "out": o, "mc": monte_carlo(full)})
    survivors.sort(key=lambda d: d["out"]["avg"], reverse=True)
    return {"sym": sym, "bars": len(b), "bred": len(G), "in_sample_ok": len(ins), "survivors": survivors[:5]}


if __name__ == "__main__":
    random.seed(7)
    highwin = "--highwin" in sys.argv
    syms = [a for a in sys.argv[1:] if not a.startswith("--")] or ["GC=F", "CL=F", "NVDA"]
    res = {}
    for sym in syms:
        r = breed(sym, highwin=highwin)
        if highwin:
            r["mode"] = "highwin78"
        res[sym] = r
        print(f"\n=== {sym}: {r['bred']} bots bred on {r['bars']} bars, {r['in_sample_ok']} had 30+ trades in-sample, "
              f"{len(r['survivors'])} survived the unseen data")
        for s in r["survivors"]:
            print(f"  {s['bot']}\n     in  {s['in']}\n     out {s['out']}\n     MC  {s['mc']}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    old = json.load(open(OUT)) if os.path.exists(OUT) else {}
    old.update({(k + "|highwin" if highwin else k): dict(v, t=datetime.now(timezone.utc).isoformat()) for k, v in res.items()})
    json.dump(old, open(OUT, "w"), indent=1, default=list)
