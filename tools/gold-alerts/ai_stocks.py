"""AI stocks card on Telegram: daily and long-term hints for the main US AI names.

  python3 ai_stocks.py test   # print
  python3 ai_stocks.py send   # send (market_report.py send also sends it, right after the US report)

Per stock, from free Yahoo data:
  daily     : trend (price vs 50/200-day), RSI, nearest daily support/resistance (swings + 20/50-day averages)
  long term : weekly trend (10/30-week), 30-week average, major zones from 5 years of weekly bars
Hints follow what the gold backtest showed (tools/backtester/zone_day_bt.py): trading WITH the trend
(breakdown/pullback) held up, buying bounces against the trend lost. These stock hints are not
backtested on stocks yet. Information only, not a buy list.
"""
import json
import os
import sys

import gold_alerts as ga
import zone_plan as zp

HERE = os.path.dirname(os.path.abspath(__file__))
STOCKS = ["NVDA", "AMD", "AVGO", "TSM", "MSFT", "GOOGL", "META", "PLTR"]
SEP = "━" * 12
LANG = "en"

T = {
    "en": {
        "title": "AI STOCKS · DAILY & LONG-TERM HINTS {d}",
        "head": "{icon} {sym}  ${px:,.2f}  {arrow} {pct:+.1f}%",
        "daily": "Daily: {trend}, RSI {rsi:.0f}{tag} | support {s} | resistance {r}",
        "long": "Long term: weekly {wk}, 30-week avg {a30:,.2f} | major support {ms} | major resistance {mr}",
        "UP": "up", "DOWN": "down", "MIXED": "mixed",
        "os": " oversold", "ob": " overbought", "na": "-",
        "h_d_down": "Day: downtrend. Do not buy bounces (counter-trend lost in our test). Watch a break below {s} and sell the retest.",
        "h_d_down_os": "Day: downtrend but very oversold: selling now is late. Wait for a bounce or a clean break of {s}.",
        "h_d_up": "Day: uptrend. Watch a pullback to {s} with a bullish candle.",
        "h_d_mixed": "Day: no clear trend. No edge, wait.",
        "h_l_up_zone": "Long: weekly uptrend and price is at major support {ms}: the area where long-term buyers stepped in before.",
        "h_l_up": "Long: weekly uptrend. Historically better entries are near support {ms}, not after big green weeks.",
        "h_l_down": "Long: weekly downtrend. No long-term buying until a weekly close back above {a30:,.2f}, or price reaches {ms}.",
        "h_l_mixed": "Long: weekly trend unclear. Keep it on watch; size small.",
        "summary": "Summary: {up} up / {down} down / {mixed} mixed of {n} AI stocks (daily)",
        "disclaimer": "Hints from rules, not tested on stocks yet. Not a buy list, not financial advice. You decide.",
    },
    "ar": {
        "title": "أسهم الذكاء الاصطناعي · تلميحات يومية وطويلة الأمد {d}",
        "head": "{icon} {sym}  ${px:,.2f}  {arrow} {pct:+.1f}%",
        "daily": "يومي: {trend}، RSI {rsi:.0f}{tag} | دعم {s} | مقاومة {r}",
        "long": "طويل الأمد: الأسبوعي {wk}، متوسط 30 أسبوعاً {a30:,.2f} | دعم رئيسي {ms} | مقاومة رئيسية {mr}",
        "UP": "صاعد", "DOWN": "هابط", "MIXED": "مختلط",
        "os": " تشبّع بيعي", "ob": " تشبّع شرائي", "na": "-",
        "h_d_down": "يومياً: اتجاه هابط. لا تشترِ الارتدادات (عكس الاتجاه خسر في اختبارنا). راقب كسر {s} والبيع عند إعادة الاختبار.",
        "h_d_down_os": "يومياً: هابط لكن بتشبّع بيعي شديد: البيع الآن متأخر. انتظر ارتداداً أو كسراً واضحاً لـ {s}.",
        "h_d_up": "يومياً: اتجاه صاعد. راقب التصحيح نحو {s} مع شمعة صاعدة.",
        "h_d_mixed": "يومياً: لا اتجاه واضح. لا أفضلية، انتظر.",
        "h_l_up_zone": "طويل الأمد: الأسبوعي صاعد والسعر عند الدعم الرئيسي {ms}: المنطقة التي دخل فيها المستثمرون سابقاً.",
        "h_l_up": "طويل الأمد: الأسبوعي صاعد. أفضل نقاط الدخول تاريخياً قرب الدعم {ms}، لا بعد أسابيع خضراء كبيرة.",
        "h_l_down": "طويل الأمد: الأسبوعي هابط. لا شراء طويل الأمد قبل إغلاق أسبوعي فوق {a30:,.2f}، أو وصول السعر إلى {ms}.",
        "h_l_mixed": "طويل الأمد: الاتجاه الأسبوعي غير واضح. ضعه تحت المراقبة، وبحجم صغير.",
        "summary": "الخلاصة: {up} صاعد / {down} هابط / {mixed} مختلط من {n} أسهم ذكاء اصطناعي (يومي)",
        "disclaimer": "تلميحات من قواعد، لم تُختبر على الأسهم بعد. ليست قائمة شراء ولا نصيحة مالية. القرار لك.",
    },
}


def t(key, **kw):
    s = T[LANG][key]
    return s.format(**kw) if kw else s


def zone_txt(z):
    return f"{z['lo']:,.0f}-{z['hi']:,.0f}" if z else t("na")


def one(sym):
    bars, live = ga.load_bars(sym)
    c = [x["c"] for x in bars]
    px = live or c[-1]
    s50, s200, e20, r = ga.sma(c, 50), ga.sma(c, 200), ga.ema(c, 20), ga.rsi(c)
    # stocks: price under (over) both averages counts as down (up); a crash below both reads as down
    trend = "UP" if px > s50 and px > s200 else "DOWN" if px < s50 and px < s200 else "MIXED"
    g = ga.regime(bars)
    atr = g["atr"]
    sups = sorted([x for x in g["sup"] + [e20, s50] if x < px - 0.3 * atr], reverse=True)
    ress = sorted(x for x in g["res"] + [e20, s50] if x > px + 0.3 * atr)
    wk = zp.weekly_trend(bars)
    weeks = {}
    for b in bars:
        y, w, _ = __import__("datetime").date.fromisoformat(b["d"]).isocalendar()
        weeks[(y, w)] = b["c"]
    wc = [weeks[k] for k in sorted(weeks)]
    a30 = sum(wc[-30:]) / min(30, len(wc))
    try:
        major = zp.major_zones(sym, px, atr)
    except Exception:
        major = []
    below = [m for m in major if m["lo"] < px]
    above = [m for m in major if m["lo"] > px]
    ms = below[-1] if below else None
    mr = above[0] if above else None
    if not sups and ms:  # price below every daily swing: fall back to the major zone below
        sups = [ms["hi"] if ms["hi"] < px else ms["lo"]]
    s_txt = f"{sups[0]:,.2f}" if sups else t("na")
    r_txt = f"{ress[0]:,.2f}" if ress else t("na")
    tag = t("os") if r < 30 else t("ob") if r > 70 else ""

    if trend == "DOWN":
        hd = t("h_d_down_os" if r < 30 else "h_d_down", s=s_txt)
    elif trend == "UP":
        hd = t("h_d_up", s=s_txt)
    else:
        hd = t("h_d_mixed")
    if wk == "UP":
        near = ms and ms["lo"] - atr <= px <= ms["hi"] + atr
        hl = t("h_l_up_zone" if near else "h_l_up", ms=zone_txt(ms))
    elif wk == "DOWN":
        hl = t("h_l_down", a30=a30, ms=zone_txt(ms))
    else:
        hl = t("h_l_mixed")
    try:
        m = json.loads(ga.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=1d", tries=2))
        prev = m["chart"]["result"][0]["meta"]["chartPreviousClose"]
    except Exception:
        prev = c[-2]
    pct = 100 * (px - prev) / prev
    icon = {"UP": "\U0001F7E2", "DOWN": "\U0001F534", "MIXED": "\U0001F7E1"}[trend]
    block = "\n".join([
        t("head", icon=icon, sym=sym, px=px, arrow=ga.arrow(pct), pct=pct),
        "⚡ " + t("daily", trend=t(trend), rsi=r, tag=tag, s=s_txt, r=r_txt),
        "\U0001F4A1 " + hd,
        "\U0001F5D3️ " + t("long", wk=t(wk), a30=a30, ms=zone_txt(ms), mr=zone_txt(mr)),
        "\U0001F4A1 " + hl,
    ])
    return trend, block


def card():
    from datetime import date
    blocks, trends = ["\U0001F916 " + t("title", d=date.today())], []
    for sym in STOCKS:
        try:
            tr, b = one(sym)
        except Exception as e:
            ga.log(f"ai_stocks {sym} failed: {e}")
            continue
        trends.append(tr)
        blocks += [SEP, b]
    blocks += [SEP, "\U0001F9ED " + t("summary", up=trends.count("UP"), down=trends.count("DOWN"),
                                     mixed=trends.count("MIXED"), n=len(trends))]
    blocks += [SEP, "⚠️ " + t("disclaimer")]
    return "\n\n".join(blocks)


def main():
    global LANG
    args = sys.argv[1:]
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    LANG = cfg.get("lang", "en")
    if "--lang" in args:
        i = args.index("--lang")
        LANG = args[i + 1]
        del args[i:i + 2]
    ga.LANG = zp.LANG = LANG
    msg = card()
    if (args[0] if args else "test") == "send":
        ga.telegram(msg)
    else:
        print(msg)


if __name__ == "__main__":
    main()
