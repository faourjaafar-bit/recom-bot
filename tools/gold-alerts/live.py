"""Live prices from TradingView's public scanner (no key), laid over Yahoo's history.

Yahoo GC=F / CL=F are futures, about 15 min late, and the bots only saw closed candles. Readers watch
TradingView spot XAUUSD / USOIL, so (user, 2026-11-23):
- gold and oil history is shifted onto the spot price (offset = spot - futures, both read from TradingView);
- the still-forming candle gets the live price (it is added when Yahoo has not opened it yet).
Rules that need closed candles still drop the forming one (v2.closed_only, load_bars).
Any failure returns Yahoo's data unchanged, so the bots never stop because of this layer.
"""
import json
import os
import time
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
MAP_FILE = os.path.join(HERE, "cache", "tv_symbols.json")
# Yahoo symbol -> (TradingView spot the readers watch, TradingView futures matching Yahoo's history)
SPOT = {"GC=F": ("OANDA:XAUUSD", "COMEX:GC1!"), "CL=F": ("FX:USOIL", "NYMEX:CL1!")}
OTHER = {"USDTRY=X": "FX_IDC:USDTRY", "EURUSD=X": "FX:EURUSD", "GBPUSD=X": "FX:GBPUSD", "JPY=X": "FX:USDJPY",
         "DX-Y.NYB": "TVC:DXY", "^GSPC": "SP:SPX", "^IXIC": "NASDAQ:IXIC", "^DJI": "DJ:DJI"}
STEP = {"1m": 60, "2m": 120, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "1h": 3600, "90m": 5400,
        "1d": 86400, "5d": 432000, "1wk": 604800}
_quotes = {}


def quote(tv):
    """{'close', 'change', 'high', 'low'} for a TradingView symbol, cached 20 s; None if unknown."""
    hit = _quotes.get(tv)
    if hit and time.time() - hit[0] < 20:
        return hit[1]
    url = f"https://scanner.tradingview.com/symbol?symbol={tv}&fields=close,change,high,low"
    try:
        q = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                              timeout=8).read())
        q = q if q.get("close") else None
    except Exception:
        q = None
    _quotes[tv] = (time.time(), q)
    return q


def tv_symbol(sym):
    if sym in SPOT:
        return SPOT[sym][0]
    if sym in OTHER:
        return OTHER[sym]
    if not sym.replace(".", "").replace("-", "").isalnum() or not sym.isupper():
        return None
    try:
        known = json.load(open(MAP_FILE))
    except Exception:
        known = {}
    if sym in known:
        return known[sym]
    found = next((f"{ex}:{sym.replace('-', '.')}" for ex in ("NASDAQ", "NYSE", "AMEX")
                  if quote(f"{ex}:{sym.replace('-', '.')}")), None)
    known[sym] = found
    try:
        os.makedirs(os.path.dirname(MAP_FILE), exist_ok=True)
        json.dump(known, open(MAP_FILE, "w"))
    except Exception:
        pass
    return found


def live(sym):
    """(live price, previous close) from TradingView, or None."""
    tv = tv_symbol(sym)
    q = quote(tv) if tv else None
    if not q:
        return None
    return q["close"], q["close"] / (1 + (q.get("change") or 0) / 100)


def offset(sym):
    """Spot minus futures for gold/oil, 0 for everything else."""
    if sym not in SPOT:
        return 0
    s, f = quote(SPOT[sym][0]), quote(SPOT[sym][1])
    return s["close"] - f["close"] if s and f else 0


def apply(sym, bars, interval):
    """Shift gold/oil history onto spot and put the live price on the forming candle."""
    try:
        q = live(sym)
        if not q or not bars:
            return bars
        px, off = q[0], offset(sym)
        if off:
            bars = [dict(b, o=b["o"] + off, h=b["h"] + off, l=b["l"] + off, c=b["c"] + off) for b in bars]
        step, now = STEP.get(interval, 3600), time.time()
        last = bars[-1]
        if last.get("ts", 0) + step > now:  # Yahoo already opened the candle: update it
            last["c"], last["h"], last["l"] = px, max(last["h"], px), min(last["l"], px)
        elif step < 86400:  # intraday candle Yahoo has not shown yet
            start = int(now - now % step)
            bars.append({"ts": start, "d": datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%d"),
                         "o": last["c"], "h": max(last["c"], px), "l": min(last["c"], px), "c": px, "v": 0})
        return bars
    except Exception:
        return bars
