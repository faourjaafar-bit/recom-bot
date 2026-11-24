"""Gold v2 live signal: the rules tested in backtester/gold_v2_bt.py + gold_v2_lm.py, replayed bar by bar.

Bias: last daily close below its 50-day average -> sells only, above -> buys only.
Setup: an hourly close beyond the latest confirmed 1-hour swing low (high), 3 bars each side, by 0.25 ATR
       (ATR = average true range of the last 24 hours), each level used once.
Entry: a limit order back at the broken level (level -/+ 0.25 ATR), valid for 6 hours.
Stop: 1.0 ATR beyond the level + 0.25 ATR. Target: 3R. No break-even, no trailing, no partials.
Exit: stop, target, or the close 48 hours after the fill. One position at a time.
2 years GC=F 1h with Bybit fees: 182 trades, +0.29R per trade, profitable in both years.
"""
from datetime import datetime, timezone

N, Q, STOP_ATR, TARGET_R, HOLD, VALID = 3, 0.25, 1.0, 3, 48, 6


def daily_bias(daily, days):
    out = {}
    for D in days:
        dc = [x["c"] for x in daily if x["d"] < D]
        out[D] = 0 if len(dc) < 50 else (-1 if dc[-1] < sum(dc[-50:]) / 50 else 1)
    return out


def replay(h1, daily):
    """Walk closed hourly bars. Returns (closed trades, open position or None, pending order or None, levels)."""
    bias = daily_bias(daily, sorted({x["d"] for x in h1}))
    tr = [h1[0]["h"] - h1[0]["l"]] + [max(b["h"] - b["l"], abs(b["h"] - a["c"]), abs(b["l"] - a["c"]))
                                      for a, b in zip(h1, h1[1:])]
    atr = [sum(tr[max(0, i - 23):i + 1]) / min(24, i + 1) for i in range(len(h1))]
    lastlo = lasthi = pos = pend = None
    used, trades = set(), []
    for i in range(60, len(h1)):
        b, p = h1[i], h1[i - 1]
        j = i - N
        if h1[j]["l"] == min(x["l"] for x in h1[j - N:j + N + 1]):
            lastlo = h1[j]["l"]
        if h1[j]["h"] == max(x["h"] for x in h1[j - N:j + N + 1]):
            lasthi = h1[j]["h"]
        if pos:
            if i > pos["fill_i"]:
                sell = pos["side"] == "sell"
                if (b["h"] >= pos["stop"]) if sell else (b["l"] <= pos["stop"]):
                    out = pos["stop"]
                elif (b["l"] <= pos["target"]) if sell else (b["h"] >= pos["target"]):
                    out = pos["target"]
                elif i - pos["fill_i"] >= HOLD:
                    out = b["c"]
                else:
                    continue
                trades.append(dict(pos, exit=out, exit_ts=b["ts"]))
                pos = None
            continue
        if pend:
            sell = pend["side"] == "sell"
            if (b["h"] >= pend["entry"]) if sell else (b["l"] <= pend["entry"]):
                pos, pend = dict(pend, fill_i=i, fill_ts=b["ts"]), None
                continue
            if i >= pend["i"] + VALID:
                pend = None
            else:
                continue
        side, q = bias.get(b["d"], 0), Q * atr[i]
        if side < 0 and lastlo and ("lo", lastlo) not in used and b["c"] < lastlo - q <= p["c"]:
            used.add(("lo", lastlo))
            pend = {"side": "sell", "level": lastlo, "entry": lastlo - q, "stop": lastlo + q + STOP_ATR * atr[i],
                    "i": i, "ts": b["ts"]}
        elif side > 0 and lasthi and ("hi", lasthi) not in used and b["c"] > lasthi + q >= p["c"]:
            used.add(("hi", lasthi))
            pend = {"side": "buy", "level": lasthi, "entry": lasthi + q, "stop": lasthi - q - STOP_ATR * atr[i],
                    "i": i, "ts": b["ts"]}
        if pend:
            risk = abs(pend["entry"] - pend["stop"])
            pend["target"] = pend["entry"] + (TARGET_R * risk if pend["side"] == "buy" else -TARGET_R * risk)
    last = len(h1) - 1
    side = bias.get(datetime.now(timezone.utc).strftime("%Y-%m-%d"), 0) or bias.get(h1[-1]["d"], 0)
    levels = {"side": side, "atr": atr[last], "lo": lastlo, "hi": lasthi,
              "lo_used": ("lo", lastlo) in used, "hi_used": ("hi", lasthi) in used, "px": h1[-1]["c"]}
    return trades, pos, pend, levels


def closed_only(h1, now=None):
    """Drop the still-forming hourly bar."""
    now = now or datetime.now(timezone.utc).timestamp()
    return h1[:-1] if h1 and h1[-1]["ts"] + 3600 > now else h1
