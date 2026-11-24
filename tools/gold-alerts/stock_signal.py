"""Stock trade card: the daily breakout buy, the one stock rule that held up in testing.

Rule (backtester/regime_bt.py s_trend, run on the 16 stocks in backtester/data, max history, 0.085% costs):
  only when the stock is in BULL (close > 50-day > 200-day) or REBOUND (10%+ off its 1-year high and back above
  the 50-day avg); buy on a daily close above the 20-day high; stop 1 daily ATR under that high; target 3R;
  hold up to 20 trading days. 2,021 trades +0.22R per trade (before 2019 +0.20R, 2019+ +0.25R), 40% wins.
  Caveat: today's stock list (big winners) flatters any long rule; 5% of trades made 67% of the profit.
Sells are not carded: daily shorts lost on gold and were not tested on stocks.
"""
import json
import os
from datetime import datetime, timezone

import regime
import zone_plan as zp

TESTED = {"n": 2021, "r": 0.22}
T = {
    "ar": {"title": "🎯 تنبيه صفقة · {name} ({sym})",
           "buy": "🟢 شراء: أغلق السهم فوق قمة 20 يوماً اليوم",
           "wait": "⏳ انتظار: شراء إذا أغلق السهم يومياً فوق {e:,.2f}",
           "entry": "💵 الدخول: {e:,.2f}", "stop": "🛑 وقف الخسارة: {s:,.2f}", "tp": "🎯 الهدف: {t:,.2f}  (3R)",
           "hold": "⌛ مدة الاحتفاظ: حتى 20 يوم تداول",
           "risk": "📏 المخاطرة: {pct:g}% = ${m:,.0f} ← {q:.2f} سهم",
           "tested": "🧪 مُختبَرة على 16 سهماً: {n} صفقة، المتوسط {r:+.2f}R"},
    "en": {"title": "🇬🇧 🎯 TRADE ALERT · {name} ({sym})",
           "buy": "🟢 BUY: the stock closed above its 20-day high today",
           "wait": "⏳ Waiting: buy on a daily close above {e:,.2f}",
           "entry": "💵 Entry: {e:,.2f}", "stop": "🛑 Stop loss: {s:,.2f}", "tp": "🎯 Target: {t:,.2f}  (3R)",
           "hold": "⌛ Hold: up to 20 trading days",
           "risk": "📏 Risk: {pct:g}% = ${m:,.0f} → {q:.2f} shares",
           "tested": "🧪 Tested on 16 stocks: {n} trades, average {r:+.2f}R"},
}


def setup(sym):
    """None when the stock is not in an uptrend; else a dict with status (buy | wait) and levels."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bars = [b for b in zp.yahoo_bars(sym, "2y", "1d") if b["d"] < today]  # closed days only
    if len(bars) < 260:
        return None
    st = regime.state(bars)
    if st["sig"] and st["sig"][0] == "breakout":
        _, e, s, t = st["sig"]
        return {"status": "buy", "e": e, "s": s, "t": t, "reg": st["reg"]}
    if st["reg"] not in ("BULL", "REBOUND"):
        return None
    e = st["hi20"]
    s = e - st["atr"]
    return {"status": "wait", "e": e, "s": s, "t": e + 3 * (e - s), "reg": st["reg"]}


def card(sym, name_ar, name_en, cfg=None, sep="━" * 12):
    """Bilingual trade card text, or "" when there is no setup."""
    if cfg is None:
        cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"), encoding="utf-8"))
    su = setup(sym)
    if not su:
        return ""
    acc, rp = cfg.get("account", 3000), cfg.get("risk_pct", 1)
    m = acc * rp / 100
    out = []
    for lang, name in (("ar", name_ar), ("en", name_en)):
        L = T[lang]
        head = L["buy"] if su["status"] == "buy" else L["wait"].format(e=su["e"])
        out.append("\n".join([L["title"].format(name=name, sym=sym), "", head, "",
                              L["entry"].format(e=su["e"]), L["stop"].format(s=su["s"]), L["tp"].format(t=su["t"]),
                              L["hold"], "", L["risk"].format(pct=rp, m=m, q=m / (su["e"] - su["s"])),
                              L["tested"].format(**TESTED)]))
    return out[0] + "\n\n" + sep + "\n\n" + out[1]
