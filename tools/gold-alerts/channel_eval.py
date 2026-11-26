"""Score other Telegram signal channels on their real gold calls (user, 2026-11-24: "track their last 50 calls and
evaluate"). Reads the public web view t.me/s/<channel> (no login, nothing posted), parses each gold call, and
simulates it on spot XAUUSD bars with one rule set for everyone:

  entry   the posted price (zone = its middle); filled if price touches it within 24 h of the post
  stop    the posted SL. SignalProvider posts no SL: its "fair" stop = the same distance as its target (1:1)
  targets TP1..TP3 as posted (Anabel: "Goal" = TP1). After TP1 the stop moves to entry (what they tell
          followers too). Same bar touching stop and target = stop. 48 h max, then closed at the market.
  R       a third booked at each target reached, the rest at the exit (same as our java_recomm scoring)

  python3 channel_eval.py collect        # cache/channels/<name>.json (last 50 gold calls each)
  python3 channel_eval.py score BARS.json  # BARS = spot XAUUSD bars [{ts,o,h,l,c}], prints the table
"""
import html
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "cache", "channels")
CHANNELS = ["mmsignalsfx", "signalsproviderfx", "anabelsignals", "fxgoldsignals", "XAUUSD_Signals"]
NUM = r"(\d{1,2},?\d{3}(?:\.\d+)?)"


def page(name, before=None):
    url = f"https://t.me/s/{name}" + (f"?before={before}" if before else "")
    t = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=25).read().decode("utf-8", "ignore")
    out = []
    for block in t.split('class="tgme_widget_message_wrap')[1:]:
        p = re.search(r'data-post="[^/]+/(\d+)"', block)
        m = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', block, re.S)
        d = re.search(r'datetime="([^"]+)"', block)
        if p and m and d:
            x = html.unescape(re.sub(r"<br/?>", "\n", m.group(1)))
            out.append({"id": int(p.group(1)), "ts": datetime.fromisoformat(d.group(1)).timestamp(),
                        "text": re.sub(r"<[^>]+>", "", x)})
    return out


def num(s):
    return float(s.replace(",", ""))


def parse(name, text):
    """A gold call {side, entry, stop, t1, t2, t3} or None."""
    s = text.replace("​", "")
    if not re.search(r"\b(gold|xau)", s, re.I):
        return None
    side = "buy" if re.search(r"\bbuy\b", s, re.I) else "sell" if re.search(r"\bsell\b", s, re.I) else None
    if not side or (re.search(r"\bbuy\b", s, re.I) and re.search(r"\bsell\b", s, re.I) and name != "mmsignalsfx"):
        return None
    c = {"side": side}
    if name == "mmsignalsfx":
        m = re.search(r"GOLD (BUY|SELL)\s*@\s*" + NUM + r"(?:\s*-\s*" + NUM + ")?", s, re.I)
        sl = re.search(r"SL:?\s*" + NUM, s, re.I)
        if not m or not sl:
            return None
        c["side"] = m.group(1).lower()
        c["entry"] = (num(m.group(2)) + num(m.group(3))) / 2 if m.group(3) else num(m.group(2))
        c["stop"] = num(sl.group(1))
        for i in (1, 2, 3):
            tp = re.search(rf"TP{i}:?\s*" + NUM, s, re.I)
            if tp:
                c[f"t{i}"] = num(tp.group(1))
    elif name == "anabelsignals":
        e = re.search(r"(?:key level|pivot level|level)\s*-?\s*" + NUM, s, re.I) or re.search(r"trading on\s*" + NUM, s, re.I)
        g = re.search(r"Goal\s*-\s*" + NUM, s, re.I)
        sl = re.search(r"Stop Loss\s*-\s*" + NUM, s, re.I)
        if not e or not g:
            return None
        c.update(entry=num(e.group(1)), t1=num(g.group(1)))
        c["stop"] = num(sl.group(1)) if sl else c["entry"] - (c["t1"] - c["entry"])
        c["no_sl"] = not sl
    elif name == "XAUUSD_Signals":  # "ENTER: #XAUUSD long trade / CURRENT PRICE: x / STOP LOSS: y / TAKE PROFIT: z"
        m = re.search(r"ENTER:\s*#(?:XAUUSD|GOLD)\s+(long|short)", s, re.I)
        e, sl, tp = (re.search(k + r":\s*" + NUM, s, re.I) for k in ("CURRENT PRICE", "STOP LOSS", "TAKE PROFIT"))
        if not (m and e and sl and tp):
            return None
        c.update(side="buy" if m.group(1).lower() == "long" else "sell", entry=num(e.group(1)), stop=num(sl.group(1)), t1=num(tp.group(1)))
    elif name == "fxgoldsignals":  # "Gold Sell 4038 / SL. 4050 / TP. 4030 / TP. 4025 / TP. 4015"
        m = re.search(r"(?:gold|xauusd)\W*(buy|sell)\W*(?:now\W*)?@?\s*" + NUM, s, re.I)
        sl = re.search(r"\bSL\W*" + NUM, s, re.I)
        tps = [num(x) for x in re.findall(r"\bTP\s*\d?\W*" + NUM, s, re.I)]
        if not (m and sl and tps) or re.search(r"\b(booked|running|update|hit)\b", s, re.I):
            return None
        c.update(side=m.group(1).lower(), entry=num(m.group(2)), stop=num(sl.group(1)), **{f"t{i + 1}": v for i, v in enumerate(tps[:3])})
    elif name == "MahmoudGoldFX":  # "GOLD BUY LIMIT / Buy 3563 / Tp 3568 (x5) / Sl 3550" (also on one line, also "NOW")
        m = re.search(r"GOLD\s+(BUY|SELL)(?:\s+(LIMIT|STOP|NOW))?[^0-9]{0,30}" + NUM, s, re.I)
        sl = re.search(r"\bSL\W*" + NUM, s, re.I)
        tps = [num(x) for x in re.findall(r"\bTP\s*\d?\W*" + NUM, s, re.I)]
        if not (m and sl and tps):
            return None
        # he posts 5 targets: the first, the middle one and the last cover his whole plan in our 3-target scoring
        pick = tps if len(tps) <= 3 else [tps[0], tps[len(tps) // 2], tps[-1]]
        c.update(side=m.group(1).lower(), entry=num(m.group(3)), stop=num(sl.group(1)), order=(m.group(2) or "now").lower(),
                 tps=tps, **{f"t{i + 1}": v for i, v in enumerate(pick)})
    elif name == "signalsproviderfx":
        if re.search(r"VIP|SALE|win rate", s) and not re.search(r"#freesignal|#gold|#xauusd", s, re.I):
            return None
        ns = [num(x) for x in re.findall(NUM, s) if 1000 < num(x) < 10000]  # 1st = the level, 2nd = the target
        if len(ns) < 2:
            return None
        c.update(entry=ns[0], t1=ns[1])
        c["stop"] = c["entry"] - (c["t1"] - c["entry"])  # no SL posted: a 1:1 stop
        c["no_sl"] = True
    d = 1 if c["side"] == "buy" else -1
    if not (c["entry"] - c["stop"]) * d > 0 or not (c["t1"] - c["entry"]) * d > 0 or not 1000 < c["entry"] < 10000:
        return None
    # a typo'd level (Market Makers' TP2 "35451" on 2026-11-26 booked -2832R) is dropped; relay() rebuilds it from the risk
    risk = abs(c["entry"] - c["stop"])
    if (c["t1"] - c["entry"]) * d > 15 * risk:
        return None
    for k in ("t2", "t3"):
        if k in c and not 0 < (c[k] - c["entry"]) * d <= 15 * risk:
            del c[k]
    return c


def collect(n=50, max_pages=80):
    os.makedirs(OUT, exist_ok=True)
    for name in CHANNELS:
        calls, before, pages = [], None, 0
        while len(calls) < n and pages < max_pages:
            try:
                msgs = page(name, before)
            except Exception as e:
                print(name, "page failed", e)
                time.sleep(3)
                pages += 1
                continue
            pages += 1
            if not msgs:
                break
            for m in sorted(msgs, key=lambda m: -m["id"]):
                c = parse(name, m["text"])
                if c and not any(x["id"] == m["id"] for x in calls):
                    calls.append(dict(c, id=m["id"], ts=m["ts"], text=m["text"][:200]))
            before = min(m["id"] for m in msgs)
            time.sleep(0.8)
        calls = sorted(calls, key=lambda c: -c["ts"])[:n]
        json.dump(calls, open(os.path.join(OUT, name + ".json"), "w"), indent=1)
        first = datetime.fromtimestamp(calls[-1]["ts"]).strftime("%d %b") if calls else "-"
        print(f"{name}: {len(calls)} gold calls since {first} ({pages} pages)")


def simulate(c, bars):
    d = 1 if c["side"] == "buy" else -1
    tps = [c[k] for k in ("t1", "t2", "t3") if c.get(k)]
    risk = abs(c["entry"] - c["stop"])
    r_of = lambda px: (px - c["entry"]) * d / risk
    after = [b for b in bars if b["ts"] >= c["ts"]]
    if not after or after[0]["ts"] - c["ts"] > 3 * 3600:
        return {"status": "no data"}
    fill = None
    for b in after:
        if b["ts"] - c["ts"] > 24 * 3600:
            break
        if b["l"] <= c["entry"] <= b["h"]:
            fill = b["ts"]
            break
    if fill is None:  # "not filled" only once 24 h of bars have passed; before that it is still waiting
        return {"status": "not filled" if after[-1]["ts"] - c["ts"] > 24 * 3600 else "pending"}
    passed, stop = 0, c["stop"]
    for b in after:
        if b["ts"] < fill:
            continue
        if (b["h"] >= stop) if d < 0 else (b["l"] <= stop):
            exit_px, status = stop, ("loss" if passed == 0 else "be")
            break
        best = b["l"] if d < 0 else b["h"]
        for i, t in enumerate(tps, 1):
            if (best - t) * d >= 0:
                passed = max(passed, i)
        if passed:
            stop = c["entry"]
        if passed == len(tps):
            exit_px, status = tps[-1], "win"
            break
        if b["ts"] - fill > 48 * 3600:
            exit_px, status = b["c"], "timeout"
            break
    else:
        return {"status": "open"}
    n = len(tps)
    booked = sum(r_of(tps[i]) for i in range(passed))
    r = (booked + (n - passed) * r_of(exit_px)) / n
    return {"status": status, "passed": passed, "r": round(r, 2), "pips": round((exit_px - c["entry"]) * d / 0.1)}


def score(bars_file):
    bars = sorted(json.load(open(bars_file)), key=lambda b: b["ts"])
    table = {}
    for name in CHANNELS:
        p = os.path.join(OUT, name + ".json")
        if not os.path.exists(p):
            continue
        rows = []
        for c in json.load(open(p)):
            res = simulate(c, bars)
            rows.append(dict(c, **res))
        done = [r for r in rows if r["status"] in ("win", "loss", "be", "timeout")]
        wins = [r for r in done if r["r"] > 0]
        tp1 = [r for r in done if r.get("passed", 0) >= 1]
        table[name] = {"calls": len(rows), "scored": len(done), "not_filled": sum(r["status"] == "not filled" for r in rows),
                       "no_data": sum(r["status"] == "no data" for r in rows), "open": sum(r["status"] == "open" for r in rows),
                       "win_rate": round(100 * len(wins) / len(done)) if done else None,
                       "tp1_rate": round(100 * len(tp1) / len(done)) if done else None,
                       "avg_r": round(sum(r["r"] for r in done) / len(done), 3) if done else None,
                       "total_r": round(sum(r["r"] for r in done), 2), "no_sl": any(r.get("no_sl") for r in rows),
                       "from": datetime.fromtimestamp(min(r["ts"] for r in rows)).strftime("%Y-%m-%d") if rows else None}
        json.dump(rows, open(os.path.join(OUT, name + "_scored.json"), "w"), indent=1)
    json.dump(table, open(os.path.join(OUT, "table.json"), "w"), indent=1)
    return table


if __name__ == "__main__":
    if sys.argv[1] == "collect":
        collect()
    else:
        print(json.dumps(score(sys.argv[2]), indent=1))
