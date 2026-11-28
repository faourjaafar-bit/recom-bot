"""Two more rules in the owner-only PAPER test (user, 2026-11-28: "Yes, add both"). Never posted to java_recomm.

Why: tested on 70 days of 5-min futures bars (scratchpad reels7_test.py / elder_test.py), both were positive with
wins >= 2x losses, but negative on 2.4 years of hourly bars: too thin to post (critique 9), so 4 weeks on paper first.
  VWAP  (jeff.tradz, oil only): NY 9:30-15:30 a 5-min candle closes across the session VWAP (from 18:00 NY) -> enter
        that way; exit when a candle closes back through the EMA20, or at 16:00. 1R = ATR(14) at entry.
        Backtest: +25R / 96 trades, PF 1.41, avg win 2.7x avg loss.
  VALUE (Elder Santis, gold + oil): context = yesterday's POC above the day before's -> longs only, below -> shorts
        only. Location = yesterday's value-area high or low (70% of volume). Trigger (NY 9:30-16:00) = a candle trades
        through the level, closes back on our side in its outer third, volume above its 20-bar average. Stop beyond
        that candle +0.1 ATR; target gold 2R, oil 3R; out at 16:55.
        Backtest: gold 62% wins PF 2.86 (24 trades); oil PF 2.30, wins 2.7x losses (28 trades).
  SHIFT (Elder Santis "5-min structure shift", added 2026-11-28 "Yes, add it"): 4h close above a rising 4h EMA20 ->
        longs only (mirror for shorts); a 30m demand zone = a small base (< 0.8 ATR30) right before a >= 2 ATR30 move,
        last 5 days; NY 9:30-11:30 price taps the zone, then 5m makes a higher high and a higher low; enter when a
        candle closes above the prior candle's high; stop under the tap low; target 2R; one a day. Backtest
        (replayed through this code on 70 days of Yahoo 5m): gold 5 trades 4 wins +3.5R, oil 9 trades 7 wins +6.6R
        (79% wins, PF 4-6) - very few trades.
Bars: TradingView COMEX:GC1! / NYMEX:CL1! (the same futures the backtest used, with real volume; the free feed may
be ~10 min late, so messages can lag, but entries/exits are the bar prices the backtest uses). Every run re-walks each
trade from its own entry bar with its fixed stop/target, so no bar is walked with a stop from the future (critique 14).
Ends 2026-12-25 with a verdict, next to nyopen_paper.py.
  python3 paper_rules.py run | status
"""
import json
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import gold_alerts as ga
import tvbars
from nyopen_paper import START_DAY, END_DAY, tell

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "cache", "paper_rules.json")
NY = ZoneInfo("America/New_York")
SYMS = {"GOLD": {"tv": "COMEX:GC1!", "cost": 0.30, "dp": 1, "step": 1.0, "tgt": 2.0, "rules": ("VALUE", "SHIFT")},
        "OIL": {"tv": "NYMEX:CL1!", "cost": 0.03, "dp": 2, "step": 0.05, "tgt": 3.0, "rules": ("VWAP", "VALUE", "SHIFT")}}


def ny(ts):
    return datetime.fromtimestamp(ts, NY)


def sess(ts):
    t = ny(ts)
    return t.toordinal() + (1 if t.hour >= 18 else 0)


def hm(ts):
    t = ny(ts)
    return t.hour, t.minute


def ema(xs, n):
    k, e, out = 2 / (n + 1), xs[0], []
    for x in xs:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def atr(b, n=14):
    a, out = b[0]["h"] - b[0]["l"], []
    for i, x in enumerate(b):
        tr = x["h"] - x["l"] if i == 0 else max(x["h"], b[i - 1]["c"]) - min(x["l"], b[i - 1]["c"])
        a = (a * (n - 1) + tr) / n
        out.append(a)
    return out


def vwap(b):
    out, pv, vv, cur = [], 0, 0, None
    for x in b:
        if sess(x["ts"]) != cur:
            cur, pv, vv = sess(x["ts"]), 0, 0
        pv += (x["h"] + x["l"] + x["c"]) / 3 * max(x["v"], 1)
        vv += max(x["v"], 1)
        out.append(pv / vv)
    return out


def profile(bars, step):
    vol = {}
    for x in bars:
        lo, hi = int(x["l"] / step), int(x["h"] / step)
        for k in range(lo, hi + 1):
            vol[k] = vol.get(k, 0) + max(x["v"], 1) / (hi - lo + 1)
    if not vol:
        return None
    poc = max(vol, key=vol.get)
    tot, inside, lo, hi = sum(vol.values()), vol[poc], poc, poc
    while inside < 0.7 * tot:
        up, dn = vol.get(hi + 1, 0), vol.get(lo - 1, 0)
        if up >= dn:
            hi, inside = hi + 1, inside + up
        else:
            lo, inside = lo - 1, inside + dn
    return {"poc": poc * step, "vah": (hi + 1) * step, "val": lo * step}


def signals(b, cfg, closed):
    """Entries on closed bars today: [(rule, i, side, entry, stop, target_or_None, risk, note)]."""
    out = []
    today = sess(b[closed]["ts"])
    a, e20, vw = atr(b), ema([x["c"] for x in b], 20), vwap(b)
    days = sorted({sess(x["ts"]) for x in b})
    pre = [d for d in days if d < today]
    prof = {d: profile([x for x in b if sess(x["ts"]) == d], cfg["step"]) for d in pre[-2:]}
    for i in range(1, closed + 1):
        x = b[i]
        if sess(x["ts"]) != today or ny(x["ts"]).hour >= 18:
            continue
        t = hm(x["ts"])
        if "VWAP" in cfg["rules"] and (9, 30) <= t < (15, 30):
            side = 1 if b[i - 1]["c"] <= vw[i - 1] < x["c"] else -1 if b[i - 1]["c"] >= vw[i - 1] > x["c"] else 0
            if side:
                out.append(("VWAP", i, side, x["c"], None, None, a[i], f"closed {'above' if side == 1 else 'below'} "
                            f"VWAP {vw[i]:.{cfg['dp']}f}; exit on a close back through EMA20"))
        if "VALUE" in cfg["rules"] and (9, 30) <= t < (16, 0) and len(pre) >= 2:
            y, yy = prof.get(pre[-1]), prof.get(pre[-2])
            if not y or not yy or y["poc"] == yy["poc"]:
                continue
            ctx = 1 if y["poc"] > yy["poc"] else -1
            w = b[max(0, i - 20):i]
            rng = x["h"] - x["l"]
            if rng <= 0 or not w or x["v"] <= sum(z["v"] for z in w) / len(w):
                continue
            for lv in ("vah", "val"):
                L = y[lv]
                ok = (x["l"] < L < x["c"] and (x["c"] - x["l"]) / rng >= 2 / 3) if ctx == 1 else \
                     (x["h"] > L > x["c"] and (x["h"] - x["c"]) / rng >= 2 / 3)
                if ok:
                    stop = x["l"] - 0.1 * a[i] if ctx == 1 else x["h"] + 0.1 * a[i]
                    risk = abs(x["c"] - stop)
                    out.append(("VALUE", i, ctx, x["c"], stop, x["c"] + ctx * cfg["tgt"] * risk, risk,
                                f"value moving {'up' if ctx == 1 else 'down'}; rejected yesterday's "
                                f"{'value high' if lv == 'vah' else 'value low'} {L:.{cfg['dp']}f} on high volume"))
                    break
    return out


def resample(b, mins):
    out, cur = [], None
    for x in b:
        k = x["ts"] - x["ts"] % (mins * 60)
        if cur and cur["ts"] == k:
            cur.update(h=max(cur["h"], x["h"]), l=min(cur["l"], x["l"]), c=x["c"], v=cur["v"] + x["v"])
        else:
            cur = dict(x, ts=k)
            out.append(cur)
    return out


def shift_signals(b, closed):
    """SHIFT entries on today's closed bars, same logic as the scratchpad backtest elder_shift_test.py."""
    b = b[:closed + 1]
    a5 = atr(b)
    b30, b4 = resample(b, 30), resample(b, 240)
    a30, e4 = atr(b30), ema([x["c"] for x in b4], 20)
    today, out, i4 = sess(b[-1]["ts"]), [], 0
    for i in range(50, len(b)):
        x = b[i]
        t = hm(x["ts"])
        if sess(x["ts"]) != today or not ((9, 30) <= t < (11, 30)) or ny(x["ts"]).hour >= 18:
            continue
        while i4 + 1 < len(b4) and b4[i4 + 1]["ts"] + 14400 <= x["ts"]:
            i4 += 1
        if i4 < 21:
            continue
        trend = 1 if b4[i4]["c"] > e4[i4] > e4[i4 - 1] else -1 if b4[i4]["c"] < e4[i4] < e4[i4 - 1] else 0
        if not trend:
            continue
        zs = []
        for k in range(1, len(b30) - 2):
            z = b30[k]
            if z["ts"] + 3 * 1800 > x["ts"] or z["ts"] < x["ts"] - 5 * 86400 or z["h"] - z["l"] > 0.8 * a30[k]:
                continue
            nxt = b30[k + 1:k + 3]
            if trend == 1 and max(y["h"] for y in nxt) - z["h"] >= 2 * a30[k]:
                zs.append((z["l"], z["h"]))
            elif trend == -1 and z["l"] - min(y["l"] for y in nxt) >= 2 * a30[k]:
                zs.append((z["l"], z["h"]))
        if not any((trend == 1 and x["l"] <= hi and x["c"] >= lo) or (trend == -1 and x["h"] >= lo and x["c"] <= hi)
                   for lo, hi in zs):
            continue
        ext, swing, hh, hl, entry = (x["l"], x["h"]) if trend == 1 else (x["h"], x["l"]), None, False, None, None
        ext, swing = ext
        for j in range(i + 1, min(i + 30, len(b))):
            y = b[j]
            if sess(y["ts"]) != today or hm(y["ts"]) >= (12, 30):
                break
            if trend == 1:
                if y["l"] < ext and not hh:
                    ext, swing = y["l"], y["h"]
                    continue
                if y["l"] < ext:
                    break
                if not hh:
                    swing = max(swing, b[j - 1]["h"])
                    hh = y["c"] > swing
                    continue
                if hl is None and y["c"] < b[j - 1]["c"]:
                    hl = y["l"]
                    continue
                if hl is not None and y["c"] > b[j - 1]["h"]:
                    entry = j
                    break
            else:
                if y["h"] > ext and not hh:
                    ext, swing = y["h"], y["l"]
                    continue
                if y["h"] > ext:
                    break
                if not hh:
                    swing = min(swing, b[j - 1]["l"])
                    hh = y["c"] < swing
                    continue
                if hl is None and y["c"] > b[j - 1]["c"]:
                    hl = y["h"]
                    continue
                if hl is not None and y["c"] < b[j - 1]["l"]:
                    entry = j
                    break
        if entry is None:
            continue
        ent, stop = b[entry]["c"], ext - trend * 0.05 * a5[entry]
        risk = abs(ent - stop)
        if risk > 0:
            out.append(("SHIFT", entry, trend, ent, stop, ent + trend * 2 * risk, risk,
                        f"4h trend {'up' if trend == 1 else 'down'}; tapped a 30m {'demand' if trend == 1 else 'supply'}"
                        f" zone, 5m made a {'higher high + higher low' if trend == 1 else 'lower low + lower high'}"))
        return out  # one a day
    return out


def walk(t, b, closed, e20, now):
    """('open', None) or (why, price) for trade t on closed bars."""
    start = next((j for j, x in enumerate(b) if x["ts"] == t["ts"]), None)
    if start is None:
        return "close", t["entry"]  # entry bar left the window (should not happen within a day)
    for j in range(start + 1, closed + 1):
        z, side = b[j], t["side"]
        if sess(z["ts"]) != t["sess"] or hm(z["ts"]) >= ((16, 0) if t["rule"] == "VWAP" else (16, 55)):
            return "day close", b[j - 1]["c"]
        if t["rule"] == "VWAP":
            if (side == 1 and z["c"] < e20[j]) or (side == -1 and z["c"] > e20[j]):
                return "EMA20 close", z["c"]
            continue
        if (side == 1 and z["l"] <= t["stop"]) or (side == -1 and z["h"] >= t["stop"]):
            return "stop", t["stop"]
        if (side == 1 and z["h"] >= t["target"]) or (side == -1 and z["l"] <= t["target"]):
            return "target", t["target"]
    if sess(now) != t["sess"]:
        return "day close", b[closed]["c"]
    return "open", None


def board(st):
    lines = []
    for key in sorted({(h["rule"], h["sym"]) for h in st["done"]}):
        rs = [h["r"] for h in st["done"] if (h["rule"], h["sym"]) == key]
        lines.append(f"{key[0]} {key[1]}: {len(rs)} trades, {sum(r > 0 for r in rs)} wins, {sum(rs):+.2f}R")
    return " | ".join(lines) or "no trades yet"


def run(now=None, send=True):
    now = now or time.time()
    st = json.load(open(STATE)) if os.path.exists(STATE) else {"open": {}, "done": [], "seen": [], "ended": False}
    say = tell if send else print
    day = ny(now).date().isoformat()
    if st["ended"]:
        return st
    for sym, cfg in SYMS.items():
        try:
            b = tvbars.bars(cfg["tv"], "5", n=5000)  # ~17 days: the 4h EMA20 needs them
        except Exception as e:
            print(sym, "bars failed:", e)
            continue
        closed = max(j for j, x in enumerate(b) if x["ts"] + 300 <= now) if b and b[0]["ts"] + 300 <= now else None
        if closed is None:
            continue
        e20 = ema([x["c"] for x in b], 20)
        for rule in cfg["rules"]:
            key = f"{rule}|{sym}"
            t = st["open"].get(key)
            if t is None and START_DAY <= day <= END_DAY:
                sigs = shift_signals(b, closed) if rule == "SHIFT" else signals(b, cfg, closed)
                for r, i, side, ent, stop, tgt, risk, note in sigs:
                    sid = f"{key}|{b[i]['ts']}"
                    if r != rule or sid in st["seen"] or (st["done"] and any(
                            h["rule"] == rule and h["sym"] == sym and h["exit_ts"] > b[i]["ts"] for h in st["done"])):
                        continue
                    st["seen"] = (st["seen"] + [sid])[-400:]
                    t = {"rule": rule, "sym": sym, "ts": b[i]["ts"], "sess": sess(b[i]["ts"]), "side": side,
                         "entry": ent, "stop": stop, "target": tgt, "risk": risk}
                    st["open"][key] = t
                    dp = cfg["dp"]
                    lv = (f"  stop {stop:.{dp}f}  target {tgt:.{dp}f}" if stop is not None else "")
                    say(f"📝 Paper test ({rule}, owner only, not posted)\n{sym} {'BUY 🟢▲' if side == 1 else 'SELL 🔴▼'} "
                        f"{ent:.{dp}f}{lv}\n{note}")
                    break
            if t is None:
                continue
            why, px = walk(t, b, closed, e20, now)
            if why == "open":
                continue
            r = (t["side"] * (px - t["entry"]) - cfg["cost"]) / t["risk"]
            exit_ts = b[closed]["ts"]
            st["done"].append(dict(t, exit=px, why=why, r=round(r, 2), exit_ts=exit_ts))
            del st["open"][key]
            say(f"📝 Paper test closed ({rule}): {sym} {'BUY' if t['side'] == 1 else 'SELL'} "
                f"{t['entry']:.{cfg['dp']}f} → {px:.{cfg['dp']}f} {'🟢▲' if r > 0 else '🔴▼'} {r:+.2f}R ({why})\n"
                f"Score: {board(st)}")
    if day > END_DAY and not st["open"]:
        rs = [h["r"] for h in st["done"]]
        say(f"📝 VWAP + VALUE rules, 4-week paper test finished\n{board(st)}\nTotal {sum(rs):+.2f}R on {len(rs)} trades")
        st["ended"] = True
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(st, open(STATE, "w"), indent=1)
    return st


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        run()
    else:
        st = json.load(open(STATE)) if os.path.exists(STATE) else {"open": {}, "done": []}
        print(json.dumps(st["open"], indent=1), "\n", board(st))
