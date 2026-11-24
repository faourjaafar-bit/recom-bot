"""Gold pulse: a short reading every 30 minutes. Where price is, what it did in the last half hour and since the
session open, and the two levels that decide the next move (up case, down case). Arabic first, English under it.

  python3 pulse.py send    # send now to the owner's bot chat ONLY (skipped when the market is closed or this 30-min bar was already read)
  python3 pulse.py test    # print it, send nothing
java_recomm also gets the follow-up of open "@@" recommendations (recom_track.py) just before each pulse.

Levels come from 30-minute GC=F bars: resistance/support = high/low of the last 6 bars (3 hours), each case aims
2 x the 30-minute ATR beyond its level, and the next-30-min range is price +/- 1 ATR. These are reading aids, not a
tested strategy; the tested trade stays in trade_alert.py (v2), whose level is shown at the bottom.
"""
import json
import os
import sys
from datetime import datetime, timezone

import gold_alerts as ga
import regime
import trade_alert
import zone_plan as zp

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "cache", "pulse_sent.json")
SEP = "═" * 12
L = {
    "ar": {"title": "⏱️ نبض الذهب كل 30 دقيقة 🥇 · {t} بتوقيت إسطنبول",
           "px": "💰 السعر: {px:,.1f}  ({d30:+.1f} خلال 30 دقيقة)",
           "sess": "📍 منذ الافتتاح ({o:,.0f}): {ds:+.1f} ({dp:+.2f}%)  ·  أعلى {h:,.0f}  ·  أدنى {l:,.0f}",
           "bias": {"up": "📈 الزخم: صاعد (فوق متوسط الجلسة {v:,.0f})",
                    "down": "📉 الزخم: هابط (تحت متوسط الجلسة {v:,.0f})",
                    "flat": "↔️ الزخم: عرضي حول متوسط الجلسة {v:,.0f}"},
           "up": "🟢 سيناريو الصعود: اختراق {r:,.0f} ← الهدف التالي {t:,.0f}",
           "down": "🔴 سيناريو الهبوط: كسر {s:,.0f} ← الهدف التالي {t:,.0f}",
           "range": "🎯 المدى المتوقع لنصف الساعة القادمة: {a:,.0f} – {b:,.0f}",
           "v2": "🧪 صفقة v2 المختبَرة: {txt}",
           "v2_wait": "انتظار ({side} عند {e:,.0f}، يبعد {gap:,.0f})", "v2_go": "أمر محدد الآن عند {e:,.0f}",
           "v2_open": "صفقة مفتوحة من {e:,.0f}", "v2_none": "لا إعداد الآن",
           "sell": "بيع", "buy": "شراء",
           "disc": "⚠️ قراءة آلية للتعلّم، وليست نصيحة مالية."},
    "en": {"title": "🇬🇧 ⏱️ Gold 30-min pulse 🥇 · {t} Istanbul",
           "px": "💰 Price: {px:,.1f}  ({d30:+.1f} in 30 min)",
           "sess": "📍 Since the open ({o:,.0f}): {ds:+.1f} ({dp:+.2f}%)  ·  high {h:,.0f}  ·  low {l:,.0f}",
           "bias": {"up": "📈 Momentum: up (above the session average {v:,.0f})",
                    "down": "📉 Momentum: down (below the session average {v:,.0f})",
                    "flat": "↔️ Momentum: sideways around the session average {v:,.0f}"},
           "up": "🟢 Up case: a break above {r:,.0f} → next target {t:,.0f}",
           "down": "🔴 Down case: a break below {s:,.0f} → next target {t:,.0f}",
           "range": "🎯 Expected range, next 30 min: {a:,.0f} – {b:,.0f}",
           "v2": "🧪 Tested v2 trade: {txt}",
           "v2_wait": "waiting ({side} at {e:,.0f}, {gap:,.0f} away)", "v2_go": "limit order now at {e:,.0f}",
           "v2_open": "trade open from {e:,.0f}", "v2_none": "no setup now",
           "sell": "sell", "buy": "buy",
           "disc": "⚠️ Automatic reading for learning, not financial advice."},
}


def read(sym="GC=F"):
    """None when the market is closed; else the numbers for the message."""
    b = zp.yahoo_bars(sym, "5d", "30m")
    now = datetime.now(timezone.utc).timestamp()
    if not b or now - b[-1]["ts"] > 45 * 60:  # no fresh bar: weekend or the daily break
        return None
    # the session opens after the daily break (22:00-23:00 UTC); Yahoo also drops quiet bars mid-session, so a gap
    # only counts as the open when it ends in the evening UTC hours
    hour = lambda x: datetime.fromtimestamp(x["ts"], timezone.utc).hour
    start = max([i for i in range(1, len(b)) if b[i]["ts"] - b[i - 1]["ts"] > 50 * 60 and hour(b[i]) in (21, 22, 23)]
                or [0])
    s = b[start:]
    px = b[-1]["c"]  # the last bar is the live one
    ago30 = [x for x in b if x["ts"] + 1800 <= now - 1800]  # closed bars that ended 30+ minutes ago
    d30 = px - (ago30[-1]["c"] if ago30 else s[0]["o"])
    tr = [max(x["h"], p["c"]) - min(x["l"], p["c"]) for p, x in zip(b[-15:-1], b[-14:])]
    atr = sum(tr) / len(tr)
    vol = sum(x["v"] for x in s)
    vwap = sum((x["h"] + x["l"] + x["c"]) / 3 * x["v"] for x in s) / vol if vol else sum(x["c"] for x in s) / len(s)
    recent = b[-6:]
    res, sup = max(x["h"] for x in recent), min(x["l"] for x in recent)
    # momentum: price vs the session average and vs 2 hours ago, both must agree
    ago = b[-5]["c"] if len(b) >= 5 else s[0]["o"]
    bias = "up" if px > vwap and px > ago else "down" if px < vwap and px < ago else "flat"
    return {"ts": int(now // 1800 * 1800), "px": px, "d30": d30, "o": s[0]["o"], "h": max(x["h"] for x in s),
            "l": min(x["l"] for x in s), "atr": atr, "vwap": vwap, "res": res, "sup": sup, "bias": bias}


def message(cfg):
    r = read()
    if not r:
        return None, None
    try:
        status, _, _, e = trade_alert.build(cfg)
        side = trade_alert.LAST_PLAN.get("side")
    except Exception:
        status, e, side = "none", None, None
    ist = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + 3 * 3600, timezone.utc).strftime("%H:%M")
    out = []
    for lang in ("ar", "en"):
        T = L[lang]
        if e is None or status == "none":
            v2 = T["v2_none"]
        elif status == "go":
            v2 = T["v2_go"].format(e=e)
        elif status == "open":
            v2 = T["v2_open"].format(e=e)
        else:
            v2 = T["v2_wait"].format(side=T[side], e=e, gap=abs(r["px"] - e))
        lines = [T["title"].format(t=ist), "",
                 T["px"].format(**r),
                 T["sess"].format(o=r["o"], ds=r["px"] - r["o"], dp=100 * (r["px"] - r["o"]) / r["o"], h=r["h"], l=r["l"]),
                 T["bias"][r["bias"]].format(v=r["vwap"]), "",
                 T["up"].format(r=r["res"], t=r["res"] + 2 * r["atr"]),
                 T["down"].format(s=r["sup"], t=r["sup"] - 2 * r["atr"]),
                 T["range"].format(a=r["px"] - r["atr"], b=r["px"] + r["atr"]), "",
                 T["v2"].format(txt=v2)]
        lines += regime.upcoming(lang, days=2)
        out.append("\n".join(lines + ["", T["disc"]]))
    return r["ts"], out[0] + "\n\n" + SEP + "\n\n" + out[1]


def main():
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    ts, text = message(cfg)
    sent = json.load(open(STATE)) if os.path.exists(STATE) else {}
    if mode == "send" and text and str(ts) in sent:
        print("this bar was already read")
        return
    import recom_track
    try:
        track = recom_track.follow(save=mode == "send")  # [gold, stocks] follow-ups: result, pips, meaning, next 30 min
    except Exception as e:
        ga.log(f"recom follow-up failed: {e}")
        track = []
    if mode != "send":
        print("\n\n▼▼▼▼\n\n".join(track) or "(no open recommendations)", "\n\n" + "▼" * 20 + "\n")
        print(text or "market closed, no pulse")
        return
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    if text:
        json.dump({str(ts): 1}, open(STATE, "w"))  # java_recomm ONLY (user rule): not the bot chat, not java_trading
        ga.log(text)
    env = ga.load_env(ga.ENV_PATH)
    recom = env.get("TELEGRAM_CHAT_ID")  # the owner's bot chat ONLY (user, 2026-11-23); never java_recomm or java_trading
    for msg in [text] if text else []:
        if not recom:
            break
        data = ga.urllib.parse.urlencode({"chat_id": recom, "text": msg, "disable_web_page_preview": "true"}).encode()
        try:
            ga.urllib.request.urlopen(f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/sendMessage", data, timeout=20)
        except Exception as e:
            ga.log(f"pulse to recom failed: {e}")
    print("pulse sent")


if __name__ == "__main__":
    main()
