"""Continuous @@: every 5 minutes, read the 5-minute candles of gold (GC=F) and oil (CL=F) and post a call to
t.me/java_recomm when a setup forms. One open call per symbol; the next one can come as soon as it closes.

  python3 live_recom.py run         # one pass (launchd every 5 minutes)
  python3 live_recom.py test        # show the current reading, post nothing
  python3 live_recom.py backtest    # replay the last 60 days of 5-minute bars, with costs

Chosen by backtest (60 days of 5-min bars, after costs, both 30-day halves positive; picked from ~40 variants,
so the edge is small and may be partly luck):
  NVDA = signal() itself, the trend pullback with the candle + volume trigger, ATR stop, 3R (US hours only)
  GOLD = fade(): the pullback trigger below taken the OTHER way, 3R: 149 trades, 34% wins, +0.115R per trade
  OIL  = breakout(): close beyond the 12-bar high/low with the trend, volume 1.2x, 07-17 UTC, stop 1.5 ATR, 3R:
         147 trades, 33% wins, +0.098R per trade
The pullback trigger (signal()), which lost on its own (-0.26R gold, -0.15R oil):
  trend   : 5-min EMA50 above EMA200 and price above EMA200 = buys only (below = sells only); about 4h/16h
  setup   : the last 3 bars pulled back to touch the EMA20
  trigger : the closed bar is a bullish engulfing / hammer (bearish engulfing / shooting star for sells),
            closes back beyond the EMA20, volume at least the 20-bar average
  stop    : beyond the trigger bar's extreme + 0.2 ATR, at least 1 ATR (ATR 14 on 5-min)
  targets : TP1 1R, TP2 2R, TP3 3R; the call is closed after 4 hours
  SCALP LEVELS (user, 2026-11-23, after Abusidu's critique that 350-pip stops are not scalping): the posted stop is
  always 50 pips and the targets 50 / 100 / 150 pips; the backtest with these levels: gold +0.09R, oil +0.11R.
Results are posted as replies under the card by recom_track.watch() (every minute). Info only, not advice.
"""
import json
import os
import sys
from datetime import datetime, timezone

import gold_alerts as ga
import recom_track
import zone_plan as zp

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "cache", "live_recom.json")
SYMS = {"GC=F": ("GOLD", "XAUUSD", "🥇", 0.3), "CL=F": ("OIL", "USOIL", "🛢️", 0.03),
        "NVDA": ("NVDA", "NVDA", "🟩🧠🎮", 0.02)}  # cost = spread + fees
HOLD = 4 * 3600
SCALP = {"GC=F": 5.0, "CL=F": 0.5}  # scalp stop = 50 pips (gold 1 pip = $0.10, oil $0.01); TP = 1R / 2R / 3R = 50 / 100 / 150 pips


def ema(c, n):
    k, out, e = 2 / (n + 1), [], None
    for v in c:
        e = v if e is None else e + k * (v - e)
        out.append(e)
    return out


def emas(b):
    c = [x["c"] for x in b]
    return ema(c, 20), ema(c, 50), ema(c, 200)


def signal(b, i, E=None):
    """The setup on CLOSED bar i, or None: {"side", "entry", "stop"}. E = emas(b), precomputed."""
    if i < 210:
        return None
    E = E or emas(b[:i + 1])
    e20, e50, e200 = E[0][i], E[1][i], E[2][i]
    tr = [max(x["h"], p["c"]) - min(x["l"], p["c"]) for p, x in zip(b[i - 14:i], b[i - 13:i + 1])]
    atr = sum(tr) / len(tr)
    x, p = b[i], b[i - 1]
    vol = sum(y["v"] for y in b[i - 20:i]) / 20
    if atr <= 0 or (vol and x["v"] < vol):
        return None
    body, rng = abs(x["c"] - x["o"]), x["h"] - x["l"]
    if rng <= 0:
        return None
    touched_lo = min(y["l"] for y in b[i - 2:i + 1]) <= e20
    touched_hi = max(y["h"] for y in b[i - 2:i + 1]) >= e20
    if e50 > e200 and x["c"] > e200 and touched_lo and x["c"] > e20:
        engulf = x["c"] > x["o"] and p["c"] < p["o"] and x["c"] >= p["o"] and x["o"] <= p["c"]
        hammer = min(x["o"], x["c"]) - x["l"] >= 2 * body and x["h"] - max(x["o"], x["c"]) <= body
        if engulf or hammer:
            return {"side": "buy", "entry": x["c"], "stop": min(x["l"] - 0.2 * atr, x["c"] - atr)}
    if e50 < e200 and x["c"] < e200 and touched_hi and x["c"] < e20:
        engulf = x["c"] < x["o"] and p["c"] > p["o"] and x["c"] <= p["o"] and x["o"] >= p["c"]
        star = x["h"] - max(x["o"], x["c"]) >= 2 * body and min(x["o"], x["c"]) - x["l"] <= body
        if engulf or star:
            return {"side": "sell", "entry": x["c"], "stop": max(x["h"] + 0.2 * atr, x["c"] + atr)}
    return None


def fade(b, i, E):
    """GOLD: the pullback trigger above, taken the other way (a failed-pattern trade). Stop at the same distance."""
    s = signal(b, i, E)
    if not s:
        return None
    risk = abs(s["entry"] - s["stop"])
    if s["side"] == "buy":
        return {"side": "sell", "entry": s["entry"], "stop": s["entry"] + risk}
    return {"side": "buy", "entry": s["entry"], "stop": s["entry"] - risk}


def breakout(b, i, E, n=12):
    """OIL: a close beyond the last hour's high/low (12 bars) with the EMA50/200 trend, volume 1.2x average,
    London + New York hours only (07-17 UTC). Stop 1.5 ATR."""
    if i < 210 or datetime.fromtimestamp(b[i]["ts"], timezone.utc).hour not in range(7, 17):
        return None
    x = b[i]
    tr = [max(y["h"], p["c"]) - min(y["l"], p["c"]) for p, y in zip(b[i - 14:i], b[i - 13:i + 1])]
    atr = sum(tr) / len(tr)
    vol = sum(y["v"] for y in b[i - 20:i]) / 20
    if vol and x["v"] < 1.2 * vol:
        return None
    hi, lo = max(y["h"] for y in b[i - n:i]), min(y["l"] for y in b[i - n:i])
    if E[1][i] > E[2][i] and x["c"] > hi:
        return {"side": "buy", "entry": x["c"], "stop": x["c"] - 1.5 * atr}
    if E[1][i] < E[2][i] and x["c"] < lo:
        return {"side": "sell", "entry": x["c"], "stop": x["c"] + 1.5 * atr}
    return None


RULE = {"GC=F": fade, "CL=F": breakout, "NVDA": signal}  # first hand-picked rules (kept for the record)


def _bred():
    """The live hunters are the bred bots that survived unseen data (breed.py, 2026-11-23)."""
    import breed
    return {sym: breed.live_rule(sym) for sym in breed.LIVE}


try:
    RULE.update(_bred())
except (ImportError, AttributeError):  # breed.py imported first (it imports this module): it fills RULE itself
    pass


def stop_dist(sym, b):
    """The live bot's stop distance (breed.LIVE): gold 120 pips (78% bot), oil 50 pips, NVDA 2 x ATR (78% bot)."""
    try:
        import breed
        return breed.risk_of(sym, b)
    except Exception:
        pass
    if sym in SCALP:
        return SCALP[sym]
    tr = [max(x["h"], p["c"]) - min(x["l"], p["c"]) for p, x in zip(b[-15:-1], b[-14:])]
    return 1.0 * sum(tr) / len(tr)  # chosen by the 60-day backtest (both halves positive)


def backtest(sym, exit_r=3):
    """Every signal from bar to bar, one trade at a time: R per trade after costs (stop first on a tie)."""
    b = [x for x in zp.yahoo_bars(sym, "60d", "5m") if x["v"] is not None]
    cost = SYMS[sym][3]
    rs, i, E = [], 210, emas(b)
    while i < len(b) - 1:
        s = RULE[sym](b, i, E)
        if not s:
            i += 1
            continue
        d = 1 if s["side"] == "buy" else -1
        risk = abs(s["entry"] - s["stop"])
        tgt = s["entry"] + d * exit_r * risk
        r, j = None, i + 1
        while j < len(b) and b[j]["ts"] - b[i]["ts"] <= HOLD:
            x = b[j]
            if (x["l"] <= s["stop"]) if d > 0 else (x["h"] >= s["stop"]):
                r = -1
                break
            if (x["h"] >= tgt) if d > 0 else (x["l"] <= tgt):
                r = exit_r
                break
            j += 1
        if r is None:
            j = min(j, len(b) - 1)
            r = (b[j]["c"] - s["entry"]) * d / risk
        rs.append(r - cost / risk)
        i = j + 1
    return rs


def run(post=True):
    op = recom_track.load(recom_track.OPEN, {})
    busy = {t["sym"] for t in op.values() if t.get("kind") != "plan"}
    state = recom_track.load(STATE, {})
    chan = ga.load_env(ga.ENV_PATH).get("TELEGRAM_RECOM_ID")
    now = datetime.now(timezone.utc).timestamp()
    for sym, (tag, name, icon, _) in SYMS.items():
        b = [x for x in zp.yahoo_bars(sym, "5d", "5m") if x["v"] is not None]
        if len(b) < 212 or now - b[-1]["ts"] > 15 * 60:
            print(sym, "market closed or no data")
            continue
        E, s, i = emas(b), None, None
        for j in (len(b) - 3, len(b) - 2):  # the last 2 CLOSED bars (the final one is still forming)
            if b[j]["ts"] > state.get(sym, 0):  # each bar only once, even when runs drift against bar closes
                sj = RULE[sym](b, j, E)
                if sj:
                    s, i = sj, j
        if s:
            try:  # forward test: every bot signal is scored live, posted or not (forward.py)
                import breed
                import forward
                forward.record(sym, b[i]["ts"], breed.plan(sym, s["side"], s["entry"], abs(s["entry"] - s["stop"]), s.get("gene")))
            except Exception as e:
                print(sym, "forward record failed:", e)
        print(sym, "setup:", s, "| open call" if sym in busy else "")
        state[sym] = max(state.get(sym, 0), b[-2]["ts"])
        if not s or sym in busy:
            continue
        try:  # the same gate as @@: the desk must agree and the Risk agent must not veto (stale data, news, spike)
            import desk
            dk = desk.decide(sym)
        except Exception as e:
            print(sym, "desk failed, no post:", e)
            continue
        if dk["side"] != s["side"]:
            print(sym, "desk blocks it:", dk["veto"] or f"score {dk['score']}")
            continue
        import recom
        d = 1 if s["side"] == "buy" else -1
        import breed
        plan = breed.plan(sym, s["side"], s["entry"], abs(s["entry"] - s["stop"]), s.get("gene"))  # that bot's own levels
        text = recom_track.card_text(plan, name, sym == "GC=F", icon)
        if not post or not chan:
            print(text)
            continue
        for x in b:
            x["lab"] = datetime.fromtimestamp(x["ts"] + 3 * 3600, timezone.utc).strftime("%H:%M")
        path = os.path.join(recom.OUT, f"{tag}LIVE.png")
        recom.chart(b, plan, f"{tag} ({name}) · 5-min", path, 60)
        ok = recom.send_photo(chan, path, text)
        ga.log(f"live_recom {sym} {s['side']} {s['entry']:.2f} posted msg={ok}")
        if ok:
            recom_track.add({"key": f"{tag}LIVE|{b[i]['ts']}", "plan": plan, "market": True, "hold": HOLD, "win_at": plan["win_at"],
                             "kind": "live5m", "msg": ok, "ysym": sym})
    if post:  # a test run must not mark bars as done, or the real run would skip them
        json.dump(state, open(STATE, "w"))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    if mode == "backtest":
        for sym in SYMS:
            for er in (1, 2, 3):
                rs = backtest(sym, er)
                if rs:
                    w = sum(r > 0 for r in rs)
                    print(f"{sym} exit {er}R: {len(rs)} trades, win {100 * w / len(rs):.0f}%, "
                          f"avg {sum(rs) / len(rs):+.3f}R, total {sum(rs):+.1f}R")
    else:
        run(post=mode == "run")
