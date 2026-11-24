"""Gold regime and playbook: which tested strategy fits the current market situation.

  python3 regime.py        # print today's regime, the playbook, and any daily signal

Regimes and numbers come from backtester/regime_bt.py (gold daily 2000-2026, Bybit-like costs):
  CRASH   1y drawdown <= -20% and below the 50-day avg. Next 60 days: avg +4.2%, up 68% of the time.
          Daily shorts lost (-0.19R); hourly v2 sells with short holds stay on. Wait for the reclaim buy.
  REBOUND drawdown <= -10% and back above the 50-day avg. Daily breakout buys +0.66R (22 trades).
  BULL    above 50-day > 200-day. Daily breakout buys +0.65R (122 trades), the most reliable edge.
  BEAR / RANGE: no daily edge; hourly v2 only.
Daily signals (entry at the daily close):
  reclaim : first close back above the 50-day avg after a 15%+ drop -> buy, stop 2 daily ATR, hold up to
            60 days, no fixed target (+0.53R, 17 trades since 2000: small sample)
  breakout: in BULL or REBOUND, a close above the 20-day high -> buy, stop 1 ATR under that high, target 3R,
            hold up to 20 days
The dollar and real-yield filters did not help these daily strategies, so they are shown for context only.
"""
import sys
import time
from datetime import datetime, timezone

import zone_plan as zp

PLAY = {
    "CRASH": {
        "ar": "انهيار: الهبوط {dd:.0f}% عن قمة السنة. تاريخياً بعد هذه الحالة: متوسط +4.2% خلال 60 يوماً، وارتفع 68% من المرات. "
              "صفقات البيع على فريم الساعة فقط وبمدة قصيرة، ولا بيع يومي. نراقب إشارة الارتداد: إغلاق يومي فوق {s50:,.0f}.",
        "en": "CRASH: {dd:.0f}% below the 1-year high. Historically next 60 days: avg +4.2%, up 68% of the time. "
              "Sell only on the hourly v2 with short holds, no daily shorts. Watching for the rebound buy: a daily close above {s50:,.0f}.",
    },
    "REBOUND": {
        "ar": "ارتداد بعد هبوط كبير: ابحث عن الشراء فقط. شراء الاختراق اليومي ربح +0.66R تاريخياً. اختراق عند إغلاق فوق {hi:,.0f}.",
        "en": "REBOUND after a big drop: look for buys only. Daily breakout buys made +0.66R historically. Breakout on a close above {hi:,.0f}.",
    },
    "BULL": {
        "ar": "اتجاه صاعد: أقوى حالة تاريخياً. شراء الاختراق اليومي +0.65R على 122 صفقة. اختراق عند إغلاق فوق {hi:,.0f}.",
        "en": "BULL trend: the strongest situation historically. Daily breakout buys +0.65R over 122 trades. Breakout on a close above {hi:,.0f}.",
    },
    "BEAR": {"ar": "اتجاه هابط بلا انهيار: لا ميزة يومية، تنبيهات الساعة فقط.",
             "en": "BEAR trend without a crash: no daily edge, hourly alerts only."},
    "RANGE": {"ar": "سوق عرضي: لا ميزة يومية، تنبيهات الساعة فقط.",
              "en": "RANGE: no daily edge, hourly alerts only."},
}
SIG = {
    "reclaim": {"ar": "🟢 إشارة ارتداد يومية: شراء عند {e:,.0f}، الوقف {s:,.0f}، احتفظ حتى 60 يوماً (عيّنة صغيرة: 17 صفقة، +0.53R)",
                "en": "🟢 Daily rebound signal: buy at {e:,.0f}, stop {s:,.0f}, hold up to 60 days (small sample: 17 trades, +0.53R)"},
    "breakout": {"ar": "🟢 إشارة اختراق يومية: شراء عند {e:,.0f}، الوقف {s:,.0f}، الهدف {t:,.0f} (3R)، حتى 20 يوماً",
                 "en": "🟢 Daily breakout signal: buy at {e:,.0f}, stop {s:,.0f}, target {t:,.0f} (3R), up to 20 days"},
}


# Known high-impact US events, with the historical lesson from backtester/fed_hike_study.py (38 hikes since 2004)
EVENTS = [
    ("2026-11-25", {"ar": "📅 الأربعاء 25 نوفمبر 8:30 بتوقيت نيويورك: التضخم PCE والنمو. أعلى من المتوقع = ضغط على الذهب، أهدأ = ارتداد.",
                    "en": "📅 Wed Nov 25, 8:30 ET: PCE inflation + GDP. Hotter = pressure on gold, softer = bounce."}),
    ("2026-12-09", {"ar": "📅 9 ديسمبر: قرار الفدرالي (رفع شبه مؤكد). تاريخياً بعد 38 رفعاً: الذهب +3.3% خلال 60 يوماً (ارتفع 76%)، "
                          "وبعد هبوط 5%+ قبل الرفع ارتفع خلال 20 يوماً في 3 من 3. لا تحتفظ بصفقة بيع خلال القرار.",
                    "en": "📅 Dec 9: Fed decision (hike almost certain). After 38 hikes gold averaged +3.3% over 60 days (up 76%); "
                          "after a 5%+ drop into the hike it rose over the next 20 days 3 of 3 times. Don't hold a sell through the decision."}),
]


def upcoming(lang, today=None, days=14):
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end = datetime.fromtimestamp(datetime.strptime(today, "%Y-%m-%d").timestamp() + days * 86400).strftime("%Y-%m-%d")
    return [txt[lang] for d, txt in EVENTS if today <= d <= end]


def daily_closed():
    try:
        bars = zp.yahoo_bars("GC=F", "2y", "1d")
    except Exception:  # Yahoo sometimes cuts a response short; one retry
        time.sleep(2)
        bars = zp.yahoo_bars("GC=F", "2y", "1d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return [b for b in bars if b["d"] < today]


def state(bars):
    """Regime of the next session from closed daily bars, plus a signal fired by the last close."""
    c = [b["c"] for b in bars]
    tr = [max(b["h"] - b["l"], abs(b["h"] - a["c"]), abs(b["l"] - a["c"])) for a, b in zip(bars, bars[1:])]
    atr = sum(tr[-14:]) / 14

    def at(k):
        s50, s200 = sum(c[k - 49:k + 1]) / 50, sum(c[k - 199:k + 1]) / 200
        dd = c[k] / max(c[k - 251:k + 1]) - 1
        if dd <= -0.20 and c[k] < s50:
            reg = "CRASH"
        elif dd <= -0.10 and c[k] > s50:
            reg = "REBOUND"
        elif c[k] > s50 > s200:
            reg = "BULL"
        elif c[k] < s50 < s200:
            reg = "BEAR"
        else:
            reg = "RANGE"
        return reg, dd, s50

    last = len(c) - 1
    reg, dd, s50 = at(last)
    prev_reg, prev_dd, prev_s50 = at(last - 1)
    hi20 = max(b["h"] for b in bars[-21:-1])
    sig = None
    # same rules as regime_bt: signal on the last close, levels from the bars before it
    if prev_dd <= -0.15 and c[last] > prev_s50 and c[last - 1] <= at(last - 2)[2]:
        sig = ("reclaim", c[last], c[last] - 2 * atr, None)
    elif prev_reg in ("BULL", "REBOUND") and c[last] > hi20 >= c[last - 1]:
        stop = hi20 - atr
        sig = ("breakout", c[last], stop, c[last] + 3 * (c[last] - stop))
    return {"reg": reg, "dd": dd, "s50": s50, "hi20": max(b["h"] for b in bars[-20:]), "atr": atr,
            "close": c[last], "day": bars[-1]["d"], "sig": sig}


def lines(st, lang):
    out = ["🧭 " + PLAY[st["reg"]][lang].format(dd=abs(100 * st["dd"]), s50=st["s50"], hi=st["hi20"])]
    if st["sig"]:
        kind, e, s, t = st["sig"]
        out.append(SIG[kind][lang].format(e=e, s=s, t=t or 0))
    return out + upcoming(lang)


def main():
    st = state(daily_closed())
    print(f"{st['day']}  regime {st['reg']}  drawdown {100 * st['dd']:.0f}%  close {st['close']:,.0f}  "
          f"50-day {st['s50']:,.0f}  20-day high {st['hi20']:,.0f}  signal {st['sig']}")
    for lang in ("ar", "en"):
        print("\n".join(lines(st, lang)))


if __name__ == "__main__":
    sys.exit(main())
