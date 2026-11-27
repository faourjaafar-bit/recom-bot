"""NY-open 12-EMA rule (SCUTA reel), 4-week PAPER forward test. Owner's private chat only, never java_recomm.

Why (2026-11-27): on 50-64 recent days the rule made +7.6R to +15R on gold and oil (2xATR trail), but over 2.4 years of
hourly bars it lost on both. Too thin to post from (critique 9: only tested bots post), so the user said "Yes,
paper-test it": each weekday the first 5-min candle after 9:30 New York closes above the 12 EMA -> paper BUY, below ->
paper SELL; stop 2xATR(14) trailing behind the best price; out at 16:55 New York. Results in R after costs.
The trade is re-walked from its entry bar every run (a trailing stop from the same bars always gives the same answer,
so no bar is walked with a stop from the future, cf. critique 14). Ends 2026-12-25 with a verdict to the owner.
  python3 nyopen_paper.py run      # cloud_run calls it every 5 min
  python3 nyopen_paper.py status
"""
import json
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import gold_alerts as ga
import tvbars

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "cache", "nyopen_paper.json")
NY = ZoneInfo("America/New_York")
SYMS = {"GOLD": ("OANDA:XAUUSD", 0.30, 2), "OIL": ("FX:USOIL", 0.03, 2)}  # TradingView, cost per round trip, decimals
K = 2.0                       # trail = K x ATR(14) on 5-min bars, also the first stop (1R)
START_DAY, END_DAY = "2026-11-30", "2026-12-25"  # 4 weeks, forward only (no trade from before the user said yes)
OPEN_HM, CLOSE_HM = (9, 30), (16, 55)


def ema(xs, n=12):
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


def ny(ts):
    return datetime.fromtimestamp(ts, NY)


def walk(t, b, now):
    """Exit of trade t on bars b (closed bars only): ('open', None) or (why, price)."""
    side, stop, best = t["side"], t["stop0"], t["entry"]
    last = None
    for y in b:
        ty = ny(y["ts"])
        if y["ts"] <= t["ts"] or ty.date().isoformat() != t["day"]:
            continue
        if (ty.hour, ty.minute) >= CLOSE_HM:
            return "close", last if last is not None else t["entry"]
        if y["ts"] + 300 > now:  # still forming
            break
        if (side == 1 and y["l"] <= stop) or (side == -1 and y["h"] >= stop):
            return "trail" if stop * side > t["stop0"] * side else "stop", stop
        best = max(best, y["h"]) if side == 1 else min(best, y["l"])
        stop = max(stop, best - t["risk"]) if side == 1 else min(stop, best + t["risk"])
        last = y["c"]
    if (ny(now).hour, ny(now).minute) >= CLOSE_HM or ny(now).date().isoformat() != t["day"]:
        return "close", last if last is not None else t["entry"]
    return "open", None


def board(st):
    lines = []
    for s in SYMS:
        rs = [h["r"] for h in st["done"] if h["sym"] == s]
        if rs:
            w = sum(r > 0 for r in rs)
            lines.append(f"{s}: {len(rs)} trades, {w} wins, {sum(rs):+.2f}R")
    return " | ".join(lines) or "no trades yet"


def tell(text):
    env = ga.load_env(ga.ENV_PATH)
    chat = env.get("TELEGRAM_CHAT_ID")
    if not chat:
        print("no owner chat:", text)
        return
    data = ga.urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    ga.urllib.request.urlopen(f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/sendMessage", data, timeout=20)


def run(now=None, send=True):
    now = now or time.time()
    st = json.load(open(STATE)) if os.path.exists(STATE) else {"open": {}, "done": [], "ended": False}
    say = tell if send else print
    today = ny(now).date().isoformat()
    if st["ended"]:
        return st
    for s, (tv, cost, dp) in SYMS.items():
        try:
            b = tvbars.bars(tv, "5", n=400)
        except Exception as e:
            print(s, "bars failed:", e)
            continue
        t = st["open"].get(s)
        if t is None and START_DAY <= today <= END_DAY and ny(now).weekday() < 5:
            done_today = any(h["sym"] == s and h["day"] == today for h in st["done"])
            e, a = ema([x["c"] for x in b]), atr(b)
            for i, x in enumerate(b):
                tx = ny(x["ts"])
                if (not done_today and tx.date().isoformat() == today and (tx.hour, tx.minute) == OPEN_HM
                        and x["ts"] + 300 <= now and x["c"] != e[i]):
                    side = 1 if x["c"] > e[i] else -1
                    t = {"sym": s, "day": today, "ts": x["ts"], "side": side, "entry": x["c"], "risk": K * a[i],
                         "stop0": x["c"] - side * K * a[i]}
                    st["open"][s] = t
                    say(f"📝 Paper test (owner only, not posted)\n{s} {'BUY 🟢▲' if side == 1 else 'SELL 🔴▼'} "
                        f"{t['entry']:.{dp}f}  trail stop {t['stop0']:.{dp}f}\nNY-open candle closed "
                        f"{'above' if side == 1 else 'below'} the 12 EMA ({e[i]:.{dp}f})")
                    break
        if t is None:
            continue
        why, px = walk(t, b, now)
        if why == "open":
            continue
        r = (t["side"] * (px - t["entry"]) - cost) / t["risk"]
        st["done"].append(dict(t, exit=px, why=why, r=round(r, 2)))
        del st["open"][s]
        mark = "🟢▲" if r > 0 else "🔴▼"
        say(f"📝 Paper test closed: {s} {'BUY' if t['side'] == 1 else 'SELL'} {t['entry']:.{dp}f} → {px:.{dp}f} "
            f"{mark} {r:+.2f}R ({ {'stop': 'stop hit', 'trail': 'trailing stop', 'close': 'day close'}[why] })\n"
            f"Score: {board(st)}")
    if today > END_DAY and not st["open"]:
        rs = [h["r"] for h in st["done"]]
        verdict = ("🟢▲ positive: worth a longer test" if rs and sum(rs) > 0 else "🔴▼ not positive: drop it")
        say(f"📝 NY-open rule, 4-week paper test finished\n{board(st)}\nTotal {sum(rs):+.2f}R on {len(rs)} trades: "
            f"{verdict}")
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
