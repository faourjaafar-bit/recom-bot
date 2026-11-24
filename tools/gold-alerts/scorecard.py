"""Live scorecard: logs every gold day-trade scenario the Zone Plan sends, scores it after its session.

  python3 scorecard.py score        # score finished plans now (the morning brief also does it)
  python3 scorecard.py show         # print the record
  python3 scorecard.py backfill 10  # replay the last N sessions with today's rules (marked as backfill)

Every scenario is logged, the shown ones AND the skipped ones, so the record also shows whether the
skipped ones really lose. A plan is scored with the same rules as the backtest
(tools/backtester/zone_day_bt.py): trigger, entry, stop, target, flat at the session's last hourly bar,
$0.6/oz cost. Sessions are UTC days (gold's hourly bars). Results go to scorecard.csv.
"""
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import gold_alerts as ga

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "scorecard.csv")
sys.path.insert(0, os.path.join(HERE, "..", "backtester"))
import zone_day_bt as zb  # noqa: E402  same trade simulator as the backtest

FIELDS = ["date", "logged_utc", "key", "side", "shown", "S", "R", "q", "atr", "entry", "stop", "target",
          "silver_ok", "source", "result", "R_mult", "entry_utc", "scored_utc"]
SIDE = {"sc_bounce": "buy", "sc_pull": "buy", "sc_break": "sell", "sc_top": "sell"}
LANG = "en"

T = {
    "en": {
        "title": "BOT RECORD (live, gold day plans)",
        "last": "Last session {d}:",
        "row": "{icon} {name}: {res}",
        "res_target": "target hit {r:+.2f}R", "res_stop": "stopped {r:+.2f}R", "res_close": "closed at session end {r:+.2f}R",
        "res_none": "no trigger (no trade)",
        "skipped": " (skipped scenario, for checking only)",
        "total": "Shown plans so far: {n} trades, {w} wins, total {tot:+.2f}R ({days} sessions logged)",
        "total_skip": "Skipped scenarios (would have been): {n} trades, total {tot:+.2f}R",
        "week": "Last 7 days: {n} trades, {w} wins, {tot:+.2f}R",
        "early": "Too early to judge: wait for 30+ sessions before trusting it.",
        "names": {"sc_bounce": "bounce", "sc_pull": "pullback buy", "sc_break": "breakdown sell", "sc_top": "rejection sell"},
    },
    "ar": {
        "title": "سجل أداء البوت (حي، خطط الذهب اليومية)",
        "last": "آخر جلسة {d}:",
        "row": "{icon} {name}: {res}",
        "res_target": "وصل الهدف {r:+.2f}R", "res_stop": "ضُرب الوقف {r:+.2f}R", "res_close": "أُغلقت نهاية الجلسة {r:+.2f}R",
        "res_none": "لم يتحقق الشرط (لا صفقة)",
        "skipped": " (سيناريو متجاهَل، للمراجعة فقط)",
        "total": "الخطط المعروضة حتى الآن: {n} صفقة، {w} رابحة، المجموع {tot:+.2f}R ({days} جلسة مسجّلة)",
        "total_skip": "السيناريوهات المتجاهَلة (لو نُفّذت): {n} صفقة، المجموع {tot:+.2f}R",
        "week": "آخر 7 أيام: {n} صفقة، {w} رابحة، {tot:+.2f}R",
        "early": "مبكر جداً للحكم: انتظر 30 جلسة أو أكثر قبل الثقة به.",
        "names": {"sc_bounce": "ارتداد", "sc_pull": "شراء التصحيح", "sc_break": "بيع الكسر", "sc_top": "بيع الرفض"},
    },
}


def t(key, **kw):
    s = T[LANG][key]
    return s.format(**kw) if kw else s


def rows():
    if not os.path.exists(PATH):
        return []
    with open(PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save(rs):
    with open(PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rs)


def log_plans(date, scen, S, R, q, atr, shown_keys, silver_ok, source="live", logged=None):
    """Called by zone_plan when the morning card is SENT. One row per scenario, once per session."""
    if datetime.strptime(date, "%Y-%m-%d").weekday() >= 5:
        return  # no gold session on Saturday/Sunday (UTC)
    rs = rows()
    have = {(r["date"], r["key"]) for r in rs}
    now = logged or datetime.now(timezone.utc)
    for c in scen:
        if (date, c["key"]) in have:
            continue
        rs.append({"date": date, "logged_utc": now.strftime("%Y-%m-%d %H:%M"), "key": c["key"],
                   "side": SIDE[c["key"]], "shown": int(c["key"] in shown_keys),
                   "S": round(S, 2), "R": round(R, 2), "q": round(q, 2), "atr": round(atr, 2),
                   "entry": round(c["e"], 2), "stop": round(c["s"], 2), "target": round(c["t"], 2),
                   "silver_ok": "" if silver_ok is None else int(silver_ok), "source": source,
                   "result": "", "R_mult": "", "entry_utc": "", "scored_utc": ""})
    save(rs)


def hourly(symbol="GC=F"):
    r = json.loads(ga.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?range=1mo&interval=60m"))
    r = r["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = []
    for i, ts in enumerate(r["timestamp"]):
        v = [q[k][i] for k in ("open", "high", "low", "close")]
        if None not in v:
            out.append({"ts": ts, "d": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"),
                        "o": v[0], "h": v[1], "l": v[2], "c": v[3]})
    return out


def score_one(r, bars):
    """Replay one logged scenario on its session's hourly bars after the log time. Same rules as the backtest."""
    t0 = datetime.strptime(r["logged_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()
    day = [x for x in bars if x["d"] == r["date"]]
    prev_all = [x for x in bars if x["ts"] < t0]
    sess = [x for x in day if x["ts"] >= t0]
    if not sess:
        return "none", 0.0, ""
    seq = ([prev_all[-1]] if prev_all else [sess[0]]) + sess  # one bar before for the engulfing check
    S, R, q, atr = (float(r[k]) for k in ("S", "R", "q", "atr"))
    key, stop, target = r["key"], float(r["stop"]), float(r["target"])
    trade = None
    if key in ("sc_bounce", "sc_pull"):
        for i in range(1, len(seq)):
            x = seq[i]
            if x["l"] <= S + q and x["c"] >= S - q and zb.bull(x, seq[i - 1]) and target > x["c"]:
                trade = (i, "buy", x["c"], S - q - atr, target)
                break
    elif key == "sc_top":
        for i in range(1, len(seq)):
            x = seq[i]
            if x["h"] >= R - q and x["c"] <= R + q and zb.bear(x, seq[i - 1]) and target < x["c"]:
                trade = (i, "sell", x["c"], R + q + atr, target)
                break
    else:  # sc_break: an hourly close below the zone arms it, the retest sells
        armed = False
        for i in range(1, len(seq)):
            x = seq[i]
            if armed and x["h"] >= S - q:
                trade = (i, "sell", S - q, stop, target)
                break
            if x["c"] < S - q:
                armed = True
    if not trade:
        return "none", 0.0, ""
    i, side, e, st, tg = trade
    rm = zb.run_trade(seq, i, side, e, st, tg)
    risk = abs(e - st)
    win_r = (abs(tg - e) - zb.COST) / risk
    res = "target" if abs(rm - win_r) < 1e-6 else "stop" if rm <= -0.99 else "close"
    return res, rm, datetime.fromtimestamp(seq[i]["ts"], timezone.utc).strftime("%Y-%m-%d %H:%M")


def score_pending():
    """Score plans whose session is over (gold's day ends 21:00-22:00 UTC)."""
    rs = rows()
    now = datetime.now(timezone.utc)
    todo = [r for r in rs if not r["result"] and
            (r["date"] < now.strftime("%Y-%m-%d") or now.hour >= 22)]
    if not todo:
        return 0
    bars = hourly()
    for r in todo:
        if not any(x["d"] == r["date"] for x in bars):
            continue
        res, rm, ets = score_one(r, bars)
        r.update(result=res, R_mult=round(rm, 3) if res != "none" else "", entry_utc=ets,
                 scored_utc=now.strftime("%Y-%m-%d %H:%M"))
    save(rs)
    return len(todo)


def block():
    """Arabic/English lines for the morning card."""
    rs = [r for r in rows() if r["result"]]
    if not rs:
        return []
    last_d = max(r["date"] for r in rs)
    icons = {"target": "✅", "stop": "❌", "close": "➖", "none": "⚪"}
    lines = ["\U0001F4D2 " + t("title"), t("last", d=last_d)]
    for r in [r for r in rs if r["date"] == last_d]:
        res = t("res_none") if r["result"] == "none" else t("res_" + r["result"], r=float(r["R_mult"]))
        lines.append(t("row", icon=icons[r["result"]], name=T[LANG]["names"][r["key"]], res=res)
                     + ("" if r["shown"] == "1" else t("skipped")))
    traded = [r for r in rs if r["result"] != "none"]
    shown = [r for r in traded if r["shown"] == "1"]
    skip = [r for r in traded if r["shown"] != "1"]
    days = len({r["date"] for r in rs})
    lines.append(t("total", n=len(shown), w=sum(float(r["R_mult"]) > 0 for r in shown),
                   tot=sum(float(r["R_mult"]) for r in shown), days=days))
    if skip:
        lines.append(t("total_skip", n=len(skip), tot=sum(float(r["R_mult"]) for r in skip)))
    wk = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    w = [r for r in shown if r["date"] >= wk]
    lines.append(t("week", n=len(w), w=sum(float(r["R_mult"]) > 0 for r in w), tot=sum(float(r["R_mult"]) for r in w)))
    if days < 30:
        lines.append("⏳ " + t("early"))
    return ["\n".join(lines)]


def backfill(n):
    """Replay the last n sessions with today's rules, as if the plan had been logged at 05:00 UTC.
    Only to check the scorer works; marked source=backfill and kept out of the live totals."""
    import zone_plan as zp
    bars = hourly()
    days = sorted({x["d"] for x in bars})[-n - 1:-1]
    rs = rows()
    for d in days:
        t0 = datetime.strptime(d, "%Y-%m-%d").replace(hour=5, tzinfo=timezone.utc)
        before = [x for x in bars if x["ts"] < t0.timestamp()]
        prior_days = sorted({x["d"] for x in before})[-5:]
        recent = [x for x in before if x["d"] in prior_days]
        tr = [max(before[i]["h"] - before[i]["l"], abs(before[i]["h"] - before[i - 1]["c"]),
                  abs(before[i]["l"] - before[i - 1]["c"])) for i in range(len(before) - 24, len(before))]
        atr = sum(tr) / 24
        last = [x for x in before if x["d"] == prior_days[-1]]
        hi, lo = ga.swings(recent, n=3)
        px = before[-1]["c"]
        z = {"atr": atr, "s_hi": max(x["h"] for x in last), "s_lo": min(x["l"] for x in last),
             "res": [p for _, p in hi], "sup": [p for _, p in lo]}
        a = {"live": px, "trend": "DOWN"}
        S, R, scen = zp.day_plan(a, {"account": 3000, "risk_pct": 1}, z, [])
        shown = {c["key"] for c in scen if zp.TESTED.get(c["key"], (0, 0))[1] > 0}
        for c in scen:
            if (d, c["key"]) in {(r["date"], r["key"]) for r in rs}:
                continue
            row = {"date": d, "logged_utc": t0.strftime("%Y-%m-%d %H:%M"), "key": c["key"], "side": SIDE[c["key"]],
                   "shown": int(c["key"] in shown), "S": round(S, 2), "R": round(R, 2), "q": round(0.25 * atr, 2),
                   "atr": round(atr, 2), "entry": round(c["e"], 2), "stop": round(c["s"], 2),
                   "target": round(c["t"], 2), "silver_ok": "", "source": "backfill"}
            res, rm, ets = score_one(row, bars)
            row.update(result=res, R_mult=round(rm, 3) if res != "none" else "", entry_utc=ets,
                       scored_utc=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))
            rs.append(row)
    return rs


def main():
    global LANG
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    LANG = cfg.get("lang", "en")
    import zone_plan as zp
    ga.LANG = zp.LANG = LANG
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "score":
        print("scored", score_pending())
    elif cmd == "backfill":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        for r in backfill(n):
            if r["source"] == "backfill":
                print(r["date"], r["key"], "shown" if r["shown"] else "skip", r["result"], r["R_mult"], r["entry_utc"])
    print("\n".join(block()) or "no scored plans yet")


if __name__ == "__main__":
    main()
