"""Real-time candles from TradingView's public chart feed (no login, no key).

Why (2026-11-25): Yahoo's GC=F / CL=F 5-minute bars run about 10 minutes behind. The hunter saw each setup bar
only when it was still half-formed, so 6 gold setups that day never reached java_recomm, and a backtest showed a
10-minute-late entry erases the gold edge (+0.10R -> 0.00R). OANDA:XAUUSD on TradingView is real time and is the
price the readers watch.

  python3 tvbars.py OANDA:XAUUSD 5     # print the last bars and their age
"""
import json
import random
import re
import string
import sys
import time

URL = "wss://data.tradingview.com/socket.io/websocket"
_cache = {}


def _msg(func, args):
    body = json.dumps({"m": func, "p": args}, separators=(",", ":"))
    return f"~m~{len(body)}~m~{body}"


def bars(tv, interval="5", n=600, timeout=20):
    """[{ts, o, h, l, c, v}] oldest first, the last one still forming. Cached 30 s. Raises on failure."""
    key = (tv, interval, n)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 30:
        return [dict(x) for x in hit[1]]
    import websocket
    ws = websocket.create_connection(URL, header=["Origin: https://www.tradingview.com"], timeout=timeout)
    try:
        cs = "cs_" + "".join(random.choices(string.ascii_lowercase, k=12))
        for func, args in (("set_auth_token", ["unauthorized_user_token"]), ("chart_create_session", [cs, ""]),
                           ("resolve_symbol", [cs, "sym_1", "=" + json.dumps({"symbol": tv, "adjustment": "splits"})]),
                           ("create_series", [cs, "s1", "s1", "sym_1", interval, n, ""])):
            ws.send(_msg(func, args))
        out, t0 = {}, time.time()
        while time.time() - t0 < timeout:
            raw = ws.recv()
            for part in re.split(r"~m~\d+~m~", raw):
                if not part:
                    continue
                if part.startswith("~h~"):  # heartbeat: echo it back
                    ws.send(f"~m~{len(part)}~m~{part}")
                    continue
                try:
                    m = json.loads(part)
                except ValueError:
                    continue
                if m.get("m") in ("timescale_update", "du"):
                    for x in (m["p"][1].get("s1") or {}).get("s", []):
                        v = x["v"]
                        out[int(v[0])] = {"ts": int(v[0]), "o": v[1], "h": v[2], "l": v[3], "c": v[4],
                                          "v": v[5] if len(v) > 5 else 0}
                elif m.get("m") in ("symbol_error", "series_error", "critical_error"):
                    raise RuntimeError(f"tradingview {m.get('m')}: {m.get('p')}")
                elif m.get("m") == "series_completed" and out:
                    res = [out[k] for k in sorted(out)]
                    _cache[key] = (time.time(), res)
                    return [dict(x) for x in res]
        raise TimeoutError("tradingview: no series in time")
    finally:
        ws.close()


if __name__ == "__main__":
    b = bars(sys.argv[1] if len(sys.argv) > 1 else "OANDA:XAUUSD", sys.argv[2] if len(sys.argv) > 2 else "5")
    for x in b[-4:]:
        print(time.strftime("%H:%M", time.localtime(x["ts"])), x)
    print(len(b), "bars, last bar age", round((time.time() - b[-1]["ts"]) / 60, 1), "min")
