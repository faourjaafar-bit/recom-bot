"""Candle read for one symbol: last daily candle in its context, and what the rules expect next.

  python3 candle_read.py NVDA AAPL GC=F [--lang ar]

Context first (technical-analysis skill: a pattern means nothing without trend and location):
  trend     : price vs 50/200-day averages
  location  : nearest support/resistance (swings + 20/50-day averages), at a level if within 0.5 ATR
  candle    : hammer, shooting star, engulfing, three soldiers/crows, doji; volume vs 20-day average
Expected = a scenario with its trigger, its target and the level that cancels it. A pattern only
counts once the next candle confirms it. Trading WITH the trend held up in our gold backtest,
buying bounces against it lost; the stock side is not backtested yet. Information, not advice.
"""
import sys

import gold_alerts as ga

LANG = "en"

T = {
    "en": {
        "UP": "uptrend", "DOWN": "downtrend", "MIXED": "no clear trend",
        "head": "\U0001F56F️ Candle: {candle} | {trend} | RSI {rsi:.0f} | volume x{vol:.1f}{vtag}",
        "loud": " (strong)", "quiet": " (weak)",
        "none": "plain candle",
        "hammer": "hammer", "star": "shooting star", "bull_engulf": "bullish engulfing",
        "bear_engulf": "bearish engulfing", "soldiers": "three white soldiers", "crows": "three black crows",
        "doji": "doji (indecision)",
        "at_sup": " at support {s}", "at_res": " at resistance {r}",
        "levels": "Support {s} | Resistance {r}",
        "rg_range": "Market: RANGE {lo}-{hi} ({w:.1f} ATR wide), price at {p:.0f}% of it ({where})",
        "rg_trend_up": "Market: TREND UP (higher highs and higher lows), price at {p:.0f}% of the 60-day range",
        "rg_trend_down": "Market: TREND DOWN (lower highs and lower lows), price at {p:.0f}% of the 60-day range",
        "rg_mixed": "Market: no clean trend or range ({w:.1f} ATR wide over 60 days), price at {p:.0f}%",
        "w_bottom": "near the bottom", "w_top": "near the top", "w_middle": "in the middle",
        "r_middle": "⛔ price is in the middle of the range {lo}-{hi}: no trade. Range traders act only near the edges.",
        "exp": "\U0001F52E Expected: {x}",
        "rule": "\U0001F4CC Rules say: {x}",
        "bull_up": "bullish candle with the uptrend{loc}: the strongest context. Confirmed by a close above {hi}; then the move aims at {r}. Cancelled below {lo}.",
        "bull_down": "bullish candle against the downtrend{loc}: a weak signal. Needs a close above {hi} on strong volume; even then expect a bounce toward {r}, not a new uptrend.",
        "bull_mixed": "bullish candle in a sideways market{loc}. Confirmed by a close above {hi}; target {r}.",
        "bear_down": "bearish candle with the downtrend{loc}: the strongest context. Confirmed by a close below {lo}; then the move aims at {s}. Cancelled above {hi}.",
        "bear_up": "bearish candle against the uptrend{loc}: a warning, not a reversal yet. Needs a close below {lo}; a pullback toward {s} is the likely move.",
        "bear_mixed": "bearish candle in a sideways market{loc}. Confirmed by a close below {lo}; target {s}.",
        "bear_down_os": "bearish candles with the downtrend, but very stretched (RSI {rsi:.0f}): selling now is late. Expect a pause or a bounce toward {r} first; the fall continues on a close below {lo}.",
        "bull_up_ob": "bullish candles with the uptrend, but very stretched (RSI {rsi:.0f}): buying now is chasing. Expect a pullback toward {s} first; the rise continues on a close above {hi}.",
        "down_os": "downtrend but stretched (RSI under 30): a pause or bounce toward {r} is likely before any new leg down. The fall resumes on a close below {s}.",
        "down": "the downtrend holds while price stays under {r}. A close below {s} opens the next leg down.",
        "up_ob": "uptrend but stretched (RSI over 70): a pullback toward {s} is likely before more upside.",
        "up": "the uptrend holds while price stays above {s}. A close above {r} opens the next leg up.",
        "mixed": "sideways between {s} and {r}. The next move starts with a daily close outside that range.",
        "r_down": "no buying while below the 50-day average {s50}. Selling is with the trend; buying bounces lost in our test.",
        "r_up": "buy only on a pullback to support with a bullish candle and a stop below it; do not chase green days.",
        "r_mixed": "no edge in the middle of a range. Wait for a close outside {s}-{r}.",
        "na": "-",
    },
    "ar": {
        "UP": "اتجاه صاعد", "DOWN": "اتجاه هابط", "MIXED": "لا اتجاه واضح",
        "head": "\U0001F56F️ الشمعة: {candle} | {trend} | RSI {rsi:.0f} | الحجم x{vol:.1f}{vtag}",
        "loud": " (قوي)", "quiet": " (ضعيف)",
        "none": "شمعة عادية",
        "hammer": "مطرقة", "star": "نجمة هابطة", "bull_engulf": "ابتلاع صاعد",
        "bear_engulf": "ابتلاع هابط", "soldiers": "ثلاثة جنود بيض", "crows": "ثلاثة غربان سود",
        "doji": "دوجي (تردد)",
        "at_sup": " عند الدعم {s}", "at_res": " عند المقاومة {r}",
        "levels": "الدعم {s} | المقاومة {r}",
        "rg_range": "نوع السوق: نطاق عرضي {lo}-{hi} (عرضه {w:.1f} ATR)، السعر عند {p:.0f}% منه ({where})",
        "rg_trend_up": "نوع السوق: اتجاه صاعد (قمم وقيعان أعلى)، السعر عند {p:.0f}% من نطاق 60 يوماً",
        "rg_trend_down": "نوع السوق: اتجاه هابط (قمم وقيعان أدنى)، السعر عند {p:.0f}% من نطاق 60 يوماً",
        "rg_mixed": "نوع السوق: لا اتجاه نظيف ولا نطاق (عرضه {w:.1f} ATR خلال 60 يوماً)، السعر عند {p:.0f}%",
        "w_bottom": "قرب القاع", "w_top": "قرب القمة", "w_middle": "في المنتصف",
        "r_middle": "⛔ السعر في منتصف النطاق {lo}-{hi}: لا صفقة. متداولو النطاق يتحركون عند الأطراف فقط.",
        "exp": "\U0001F52E المتوقع: {x}",
        "rule": "\U0001F4CC ماذا تقول القواعد: {x}",
        "bull_up": "شمعة صاعدة مع الاتجاه الصاعد{loc}: أقوى سياق. التأكيد بإغلاق فوق {hi}، ثم الهدف {r}. تُلغى تحت {lo}.",
        "bull_down": "شمعة صاعدة عكس الاتجاه الهابط{loc}: إشارة ضعيفة. تحتاج إغلاقاً فوق {hi} بحجم قوي، وحتى عندها المتوقع ارتداد نحو {r} وليس اتجاهاً صاعداً جديداً.",
        "bull_mixed": "شمعة صاعدة في سوق عرضي{loc}. التأكيد بإغلاق فوق {hi}، والهدف {r}.",
        "bear_down": "شمعة هابطة مع الاتجاه الهابط{loc}: أقوى سياق. التأكيد بإغلاق تحت {lo}، ثم الهدف {s}. تُلغى فوق {hi}.",
        "bear_up": "شمعة هابطة عكس الاتجاه الصاعد{loc}: تحذير وليست انعكاساً بعد. تحتاج إغلاقاً تحت {lo}، والمرجّح تصحيح نحو {s}.",
        "bear_mixed": "شمعة هابطة في سوق عرضي{loc}. التأكيد بإغلاق تحت {lo}، والهدف {s}.",
        "bear_down_os": "شموع هابطة مع الاتجاه الهابط لكن ممتدة جداً (RSI {rsi:.0f}): البيع الآن متأخر. المتوقع أولاً توقف أو ارتداد نحو {r}، ويستمر الهبوط بإغلاق تحت {lo}.",
        "bull_up_ob": "شموع صاعدة مع الاتجاه الصاعد لكن ممتدة جداً (RSI {rsi:.0f}): الشراء الآن ملاحقة. المتوقع أولاً تصحيح نحو {s}، ويستمر الصعود بإغلاق فوق {hi}.",
        "down_os": "اتجاه هابط لكن ممتد (RSI تحت 30): المرجّح توقف أو ارتداد نحو {r} قبل أي موجة هبوط جديدة. يستأنف الهبوط بإغلاق تحت {s}.",
        "down": "الاتجاه الهابط قائم ما دام السعر تحت {r}. الإغلاق تحت {s} يفتح موجة هبوط تالية.",
        "up_ob": "اتجاه صاعد لكن ممتد (RSI فوق 70): المرجّح تصحيح نحو {s} قبل صعود إضافي.",
        "up": "الاتجاه الصاعد قائم ما دام السعر فوق {s}. الإغلاق فوق {r} يفتح موجة صعود تالية.",
        "mixed": "حركة عرضية بين {s} و{r}. الحركة التالية تبدأ بإغلاق يومي خارج هذا النطاق.",
        "r_down": "لا شراء ما دام السعر تحت متوسط 50 يوماً {s50}. البيع مع الاتجاه؛ شراء الارتدادات خسر في اختبارنا.",
        "r_up": "الشراء فقط عند تصحيح إلى الدعم مع شمعة صاعدة ووقف تحتها؛ لا تلاحق الأيام الخضراء.",
        "r_mixed": "لا أفضلية في منتصف النطاق. انتظر إغلاقاً خارج {s}-{r}.",
        "na": "-",
    },
}


def t(key, **kw):
    s = T[LANG][key]
    return s.format(**kw) if kw else s


def fmt(x):
    return t("na") if x is None else f"{x:,.2f}"


def read(sym):
    """Readings for one symbol from free Yahoo daily bars."""
    bars, live = ga.load_bars(sym)
    c = [x["c"] for x in bars]
    px = live or c[-1]
    s50, s200, e20, r = ga.sma(c, 50), ga.sma(c, 200), ga.ema(c, 20), ga.rsi(c)
    trend = "UP" if px > s50 and px > s200 else "DOWN" if px < s50 and px < s200 else "MIXED"
    g = ga.regime(bars)
    atr = g["atr"]
    sups = sorted((x for x in g["sup"] + [e20, s50] if x < px - 0.3 * atr), reverse=True)
    ress = sorted(x for x in g["res"] + [e20, s50] if x > px + 0.3 * atr)
    sup = sups[0] if sups else min(x["l"] for x in bars[-60:])
    res = ress[0] if ress else max(x["h"] for x in bars[-60:])
    sigs, loud, vol_x = ga.candle_signals(bars)
    last = bars[-1]
    body, rng = abs(last["c"] - last["o"]), last["h"] - last["l"]
    if rng and body <= 0.1 * rng and not sigs:
        sigs = [("doji", "doji")]
    # targets sit beyond the candle that has to be confirmed; no level there = 2 ATR away
    below = [x for x in sups if x < last["l"] - 0.3 * atr]
    above = [x for x in ress if x > last["h"] + 0.3 * atr]
    return {"sym": sym, "px": px, "trend": trend, "rsi": r, "s50": s50, "atr": atr, "sup": sup, "res": res,
            "regime": g["label"], "width": g["width"], "pos": g["pos"], "r_lo": g["lo"], "r_hi": g["hi"],
            "sigs": sigs, "loud": loud, "vol_x": vol_x, "hi": last["h"], "lo": last["l"],
            "t_dn": below[0] if below else last["l"] - 2 * atr, "t_up": above[0] if above else last["h"] + 2 * atr}


def card(a):
    """Three lines: the candle in context, what is expected, what the rules say."""
    kinds = [k for k, _ in a["sigs"]]
    candle = " + ".join(t(key) for _, key in a["sigs"]) if a["sigs"] else t("none")
    vtag = t("loud") if a["loud"] else t("quiet") if a["vol_x"] < 0.8 else ""
    s, r, hi, lo = fmt(a["sup"]), fmt(a["res"]), fmt(a["hi"]), fmt(a["lo"])
    near_s = a["px"] - a["sup"] <= 0.5 * a["atr"]
    near_r = a["res"] - a["px"] <= 0.5 * a["atr"]
    tr = a["trend"].lower()
    tu, td = fmt(a["t_up"]), fmt(a["t_dn"])
    # counter-moves (bounce / pullback) are capped at 2 ATR: a far level is not a realistic bounce
    rb = fmt(min(a["res"], a["px"] + 2 * a["atr"]))
    sb = fmt(max(a["sup"], a["px"] - 2 * a["atr"]))
    if "bull" in kinds and a["trend"] == "UP" and a["rsi"] > 70:
        x = t("bull_up_ob", rsi=a["rsi"], s=sb, hi=hi)
    elif "bear" in kinds and a["trend"] == "DOWN" and a["rsi"] < 30:
        x = t("bear_down_os", rsi=a["rsi"], r=rb, lo=lo)
    elif "bull" in kinds and a["trend"] == "DOWN":
        x = t("bull_down", loc=t("at_sup", s=s) if near_s else "", hi=hi, r=rb)
    elif "bear" in kinds and a["trend"] == "UP":
        x = t("bear_up", loc=t("at_res", r=r) if near_r else "", lo=lo, s=sb)
    elif "bull" in kinds:
        x = t("bull_" + tr, loc=t("at_sup", s=s) if near_s else "", hi=hi, lo=lo, r=tu)
    elif "bear" in kinds:
        x = t("bear_" + tr, loc=t("at_res", r=r) if near_r else "", hi=hi, lo=lo, s=td)
    elif a["trend"] == "DOWN":
        x = t("down_os", s=s, r=rb) if a["rsi"] < 30 else t("down", s=s, r=r)
    elif a["trend"] == "UP":
        x = t("up_ob", s=sb, r=r) if a["rsi"] > 70 else t("up", s=s, r=r)
    else:
        x = t("mixed", s=s, r=r)
    rule = t("r_" + tr, s50=fmt(a["s50"]), s=s, r=r)
    # market type (Morin method): a range is narrow in ATRs; inside one, only the edges are tradable
    where = "bottom" if a["pos"] <= 0.3 else "top" if a["pos"] >= 0.7 else "middle"
    if a["regime"] == "RANGE":
        rg = t("rg_range", w=a["width"], p=100 * a["pos"], where=t("w_" + where),
               lo=fmt(a["r_lo"]), hi=fmt(a["r_hi"]))
        if where == "middle":
            rule = t("r_middle", lo=fmt(a["r_lo"]), hi=fmt(a["r_hi"]))
    else:
        rg = t("rg_" + a["regime"].replace(" ", "_").lower(), w=a["width"], p=100 * a["pos"])
    return "\n".join([
        t("head", candle=candle, trend=t(a["trend"]), rsi=a["rsi"], vol=a["vol_x"], vtag=vtag),
        "\U0001F4D0 " + rg,
        "\U0001F4CF " + t("levels", s=s, r=r),
        t("exp", x=x),
        t("rule", x=rule),
    ])


def main():
    global LANG
    args = sys.argv[1:]
    if "--lang" in args:
        i = args.index("--lang")
        LANG = ga.LANG = args[i + 1]
        del args[i:i + 2]
    for sym in args or ["NVDA"]:
        a = read(sym)
        print(f"{sym}  {a['px']:,.2f}\n{card(a)}\n")


if __name__ == "__main__":
    main()
