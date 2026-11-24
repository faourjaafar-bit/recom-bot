"""Zone Plan (خطة الزون): a trade-zone card for gold built from the morning brief's own analysis.

  python3 zone_plan.py test    # print the card
  python3 zone_plan.py send    # send it to Telegram (gold_alerts.py brief also sends it after the brief)

It reuses the brief's readings (trend, regime, swing highs/lows, averages, RSI, candles, dollar)
and applies the rules of the technical-analysis skill (~/.agents/skills/technical-analysis):
  - support/resistance are ZONES (level +- 0.25 ATR), not lines
  - the higher timeframe decides the side: weekly trend + daily trend must agree
  - trade the reaction, not the level: wait for a rejection candle on a daily close inside the zone
  - every plan has a stop beyond the zone, an invalidation, R:R of at least 2, and a size from risk %
  - no entry the day before a big event (TA fails at news)
  - honest status: these zone rules are not backtested yet
Information only. A zone plan is a rules check, not a recommendation.
"""
import json
import os
import sys

import gold_alerts as ga
import live

HERE = os.path.dirname(os.path.abspath(__file__))
LANG = "en"
SEP = "━" * 12

T = {
    "en": {
        "tested_ok": "Tested: {n} trades in 2 years, avg {r:+.2f}R. The only scenario with an edge (small sample, mostly the 2026 downtrend).",
        "tested_bad": "{title}: tested {n} trades, avg {r:+.2f}R = loses. Skip it.",
        "ag_ok": "Silver confirms (Dow/Hamilton two-market rule, passed both halves): silver {sp:,.2f} is {rel} its 50-day {s50:,.2f}. "
                 "Tested with confirmation: {n} trades {r:+.2f}R vs {n2} trades {r2:+.2f}R without.",
        "ag_bad": "Silver does NOT confirm ({sp:,.2f} is {rel} its 50-day {s50:,.2f}). Tested without confirmation: {n2} trades {r2:+.2f}R. Skip today.",
        "rel_above": "above", "rel_below": "below",
        "dx_note": "Dollar check (Murphy, tested): at the trigger, is DXY up since the session open? "
                   "Yes: 53 trades {a:+.2f}R; DXY up 0.1%+: 23 trades +0.76R (small sample). No: 35 trades +0.23R.",
        "tested_none": "No day scenario has a tested edge in this trend. Stand aside today.",
        "now_title": "WHERE GOLD IS NOW",
        "inside_major": "Inside a major zone {lo:,.0f}-{hi:,.0f} (old {kind}, {n} weekly touches since {since})",
        "major_sup": "Major support below: {lo:,.0f}-{hi:,.0f}  ({d:,.0f} away; strength {n})",
        "major_res": "Major resistance above: {lo:,.0f}-{hi:,.0f}  ({d:,.0f} away; strength {n})",
        "day_lv": "Intraday: support {s:,.0f} | resistance {r:,.0f} | last session {lo:,.0f}-{hi:,.0f}",
        "k_sup": "support", "k_res": "resistance", "k_both": "support/resistance",
        "day_title": "DAY-TRADE PLAN (1-hour chart)",
        "sc_bounce": "Scenario A - bounce at {lv:,.0f}{ct}",
        "sc_break": "Scenario B - break below {lv:,.0f}{ct}",
        "sc_pull": "Scenario A - pullback buy at {lv:,.0f}{ct}",
        "sc_top": "Scenario B - rejection at {lv:,.0f}{ct}",
        "ct": " (against the daily trend: half size)", "wt": " (with the daily trend)",
        "d_trig_bull": "Trigger: a 1-hour hammer/bullish engulfing in {lo:,.0f}-{hi:,.0f}",
        "d_trig_bear_break": "Trigger: a 1-hour close below {lv:,.0f}, then sell the retest",
        "d_trig_bear": "Trigger: a 1-hour shooting star/bearish engulfing in {lo:,.0f}-{hi:,.0f}",
        "d_trig_bull_break": "Trigger: a 1-hour close above {lv:,.0f}, then buy the retest",
        "d_line": "Entry {e:,.0f} | stop {s:,.0f} | target {t:,.0f} ({r:.1f}R)",
        "d_risk": "Risk {rp:g}% = ${m:,.0f}  ->  {oz:.2f} oz",
        "d_close": "Day trade: close it before the session ends, win or lose.",
        "rr_low": " - reward too small, skip",
        "swing_title": "SWING PLAN (days to weeks)",
        "title": "ZONE PLAN · GOLD {d}",
        "based": "Built from this morning's brief: {trend} daily, {weekly} weekly, RSI {rsi:.0f}, price {px:,.0f}",
        "w_UP": "up", "w_DOWN": "down", "w_MIXED": "mixed",
        "side_sell": "SELL ZONE (with the trend)", "side_buy": "BUY ZONE (with the trend)",
        "zone": "Zone: {lo:,.0f} - {hi:,.0f}  ({dist:,.0f} away, {pct:+.1f}%)",
        "trigger": "Trigger: a daily close inside the zone with a {cndl} on above-average volume",
        "c_sell": "shooting star or bearish engulfing", "c_buy": "hammer or bullish engulfing",
        "entry": "Entry (planned): {e:,.0f}",
        "stop": "Stop: {s:,.0f}  (beyond the zone + half a day's range)",
        "t1": "Target 1: {t:,.0f}  ({r:.1f}R)", "t2": "Target 2: {t:,.0f}  ({r:.1f}R)",
        "risk": "Risk {rp:g}% of ${acc:,.0f} = ${m:,.0f}  ->  {oz:.2f} oz (margin ${mg:,.0f} at {lev:g}x)",
        "inval": "Cancelled if: gold closes {side} {lv:,.0f} before reaching the zone, or the trend flips",
        "inval_above": "above", "inval_below": "below",
        "now": "Now: {msg}",
        "now_wait": "price is not in the zone. Do nothing; wait for it to come to you.",
        "now_in": "price is IN the zone. Wait for the trigger candle on the daily close.",
        "now_chase": "oversold (RSI {rsi:.0f}): chasing a sell here is the classic late entry. Wait for the bounce.",
        "none": "No zone today: daily and weekly trends disagree ({d} vs {w}). The higher timeframe wins: stand aside.",
        "none_rr": "No zone today: the nearest zone gives less than 2R to the next level.",
        "check": "Skill checklist:",
        "ok": "✅", "no": "❌", "warn": "⚠️",
        "c_mtf": "Weekly and daily trend agree",
        "c_stop": "Stop defined beyond the zone",
        "c_rr": "Reward/risk at least 2 (target 1: {r:.1f}R)",
        "c_vol": "Volume confirmation required at the trigger",
        "c_news": "No big event tomorrow",
        "c_news_bad": "Big event soon ({name}): no new entry the day before",
        "c_dollar": "Dollar backs the side ({m})",
        "c_dollar_bad": "Dollar works against the side ({m})",
        "c_test": "Not backtested yet: practise on demo only",
        "dx_up": "dollar/yields up", "dx_down": "dollar/yields down", "dx_flat": "dollar quiet",
        "disclaimer": "Zone Plan = a rules check from the skill, not a recommendation. You decide and place every trade.",
    },
    "ar": {
        "tested_ok": "مُختبَرة: {n} صفقة في سنتين، المتوسط {r:+.2f}R. السيناريو الوحيد الذي أظهر أفضلية (عيّنة صغيرة، أغلبها في هبوط 2026).",
        "tested_bad": "{title}: اختُبر على {n} صفقة، المتوسط {r:+.2f}R = خاسر. تجاهله.",
        "ag_ok": "الفضة تؤكد (قاعدة داو/هاملتون للسوقين، نجحت في نصفي الاختبار): الفضة {sp:,.2f} {rel} متوسط 50 يوماً {s50:,.2f}. "
                 "مع التأكيد: {n} صفقة {r:+.2f}R مقابل {n2} صفقة {r2:+.2f}R بدونه.",
        "ag_bad": "الفضة لا تؤكد ({sp:,.2f} {rel} متوسط 50 يوماً {s50:,.2f}). بدون تأكيد: {n2} صفقة {r2:+.2f}R. تجاهلها اليوم.",
        "rel_above": "فوق", "rel_below": "دون",
        "dx_note": "فحص الدولار (مورفي، مُختبَر): عند شمعة الشرط، هل مؤشر الدولار صاعد منذ افتتاح الجلسة؟ "
                   "نعم: 53 صفقة {a:+.2f}R؛ صاعد 0.1% أو أكثر: 23 صفقة +0.76R (عيّنة صغيرة). لا: 35 صفقة +0.23R.",
        "tested_none": "لا سيناريو يومي أظهر أفضلية في هذا الاتجاه. ابقَ خارج السوق اليوم.",
        "now_title": "أين الذهب الآن",
        "inside_major": "داخل منطقة رئيسية {lo:,.0f}-{hi:,.0f} ({kind} سابقة، {n} لمسة أسبوعية منذ {since})",
        "major_sup": "أقرب دعم رئيسي: {lo:,.0f}-{hi:,.0f}  (على بُعد {d:,.0f}؛ القوة {n})",
        "major_res": "أقرب مقاومة رئيسية: {lo:,.0f}-{hi:,.0f}  (على بُعد {d:,.0f}؛ القوة {n})",
        "day_lv": "داخل اليوم: دعم {s:,.0f} | مقاومة {r:,.0f} | الجلسة الأخيرة {lo:,.0f}-{hi:,.0f}",
        "k_sup": "دعم", "k_res": "مقاومة", "k_both": "دعم/مقاومة",
        "day_title": "خطة المضاربة اليومية (شارت الساعة)",
        "sc_bounce": "السيناريو أ - ارتداد من {lv:,.0f}{ct}",
        "sc_break": "السيناريو ب - كسر تحت {lv:,.0f}{ct}",
        "sc_pull": "السيناريو أ - شراء التصحيح عند {lv:,.0f}{ct}",
        "sc_top": "السيناريو ب - رفض عند {lv:,.0f}{ct}",
        "ct": " (عكس الاتجاه اليومي: نصف الحجم)", "wt": " (مع الاتجاه اليومي)",
        "d_trig_bull": "الشرط: شمعة ساعة مطرقة أو ابتلاع صاعد داخل {lo:,.0f}-{hi:,.0f}",
        "d_trig_bear_break": "الشرط: إغلاق شمعة ساعة تحت {lv:,.0f}، ثم البيع عند إعادة الاختبار",
        "d_trig_bear": "الشرط: شمعة ساعة نجمة هابطة أو ابتلاع هابط داخل {lo:,.0f}-{hi:,.0f}",
        "d_trig_bull_break": "الشرط: إغلاق شمعة ساعة فوق {lv:,.0f}، ثم الشراء عند إعادة الاختبار",
        "d_line": "الدخول {e:,.0f} | الوقف {s:,.0f} | الهدف {t:,.0f} ({r:.1f}R)",
        "d_risk": "المخاطرة {rp:g}% = ${m:,.0f}  ←  {oz:.2f} أونصة",
        "d_close": "مضاربة يومية: أغلق الصفقة قبل نهاية الجلسة، ربحاً أو خسارة.",
        "rr_low": " - العائد صغير، تجاهلها",
        "swing_title": "خطة السوينغ (أيام إلى أسابيع)",
        "title": "خطة الزون · الذهب {d}",
        "based": "مبنية على موجز الصباح: الاتجاه اليومي {trend}، الأسبوعي {weekly}، RSI {rsi:.0f}، السعر {px:,.0f}",
        "w_UP": "صاعد", "w_DOWN": "هابط", "w_MIXED": "مختلط",
        "side_sell": "منطقة بيع (مع الاتجاه)", "side_buy": "منطقة شراء (مع الاتجاه)",
        "zone": "المنطقة: {lo:,.0f} - {hi:,.0f}  (على بُعد {dist:,.0f}، {pct:+.1f}%)",
        "trigger": "شرط الدخول: إغلاق يومي داخل المنطقة بشمعة {cndl} مع حجم أعلى من المتوسط",
        "c_sell": "نجمة هابطة أو ابتلاع هابط", "c_buy": "مطرقة أو ابتلاع صاعد",
        "entry": "الدخول المخطط: {e:,.0f}",
        "stop": "الوقف: {s:,.0f}  (خلف المنطقة + نصف المدى اليومي)",
        "t1": "الهدف 1: {t:,.0f}  ({r:.1f}R)", "t2": "الهدف 2: {t:,.0f}  ({r:.1f}R)",
        "risk": "المخاطرة {rp:g}% من ${acc:,.0f} = ${m:,.0f}  ←  {oz:.2f} أونصة (هامش ${mg:,.0f} برافعة {lev:g}x)",
        "inval": "تُلغى الخطة إذا: أغلق الذهب {side} {lv:,.0f} قبل الوصول إلى المنطقة، أو انقلب الاتجاه",
        "inval_above": "فوق", "inval_below": "دون",
        "now": "الآن: {msg}",
        "now_wait": "السعر ليس في المنطقة. لا تفعل شيئاً، انتظر أن يأتي السعر إليك.",
        "now_in": "السعر داخل المنطقة. انتظر شمعة الشرط عند الإغلاق اليومي.",
        "now_chase": "تشبّع بيعي (RSI {rsi:.0f}): البيع هنا دخول متأخر كلاسيكي. انتظر الارتداد.",
        "none": "لا منطقة اليوم: الاتجاه اليومي والأسبوعي مختلفان ({d} مقابل {w}). الإطار الأكبر يحكم: ابقَ خارج السوق.",
        "none_rr": "لا منطقة اليوم: أقرب منطقة تعطي أقل من 2R حتى المستوى التالي.",
        "check": "قائمة فحص المهارة:",
        "ok": "✅", "no": "❌", "warn": "⚠️",
        "c_mtf": "الاتجاه الأسبوعي واليومي متفقان",
        "c_stop": "الوقف محدد خلف المنطقة",
        "c_rr": "العائد إلى المخاطرة 2 أو أكثر (الهدف 1: {r:.1f}R)",
        "c_vol": "تأكيد الحجم مطلوب عند شمعة الشرط",
        "c_news": "لا حدث كبير غداً",
        "c_news_bad": "حدث كبير قريب ({name}): لا دخول جديد في اليوم السابق له",
        "c_dollar": "الدولار يدعم الاتجاه ({m})",
        "c_dollar_bad": "الدولار يعمل ضد الاتجاه ({m})",
        "c_test": "لم تُختبر تاريخياً بعد: على الحساب التجريبي فقط",
        "dx_up": "الدولار والعوائد صاعدة", "dx_down": "الدولار والعوائد هابطة", "dx_flat": "الدولار هادئ",
        "disclaimer": "خطة الزون = فحص قواعد من المهارة، وليست توصية. القرار والتنفيذ عليك.",
    },
}


# Backtest of the day scenarios (tools/backtester/zone_day_bt.py, gold 1h 2024-11 to 2026-11, $0.6/oz cost)
SILVER_TEST = {"sc_break": (62, 0.37, 26, 0.00)}  # with / without, tools/backtester/books_bt.py
TESTED = {"sc_bounce": (75, -0.25), "sc_pull": (106, -0.05), "sc_break": (88, 0.26), "sc_top": (103, -0.18)}


def t(key, **kw):
    s = T[LANG][key]
    return s.format(**kw) if kw else s


def weekly_trend(bars):
    """Higher timeframe: weekly closes vs their 10- and 30-week averages."""
    weeks = {}
    for b in bars:
        y, w, _ = __import__("datetime").date.fromisoformat(b["d"]).isocalendar()
        weeks[(y, w)] = b["c"]
    c = [weeks[k] for k in sorted(weeks)]
    if len(c) < 30:
        return "MIXED"
    s10, s30 = sum(c[-10:]) / 10, sum(c[-30:]) / 30
    return "UP" if c[-1] > s10 > s30 else "DOWN" if c[-1] < s10 < s30 else "MIXED"


def dollar_push(fx):
    d = next((q for q in fx if q["sym"] == "DX-Y.NYB"), None)
    y = next((q for q in fx if q["sym"] == "^TNX"), None)
    return (d["pct"] if d else 0) / 0.2 + (y["chg"] if y else 0) / 0.03


def plan(a, cfg, fx):
    px, g, atr = a["live"], a["regime"], a["regime"]["atr"]
    wk = weekly_trend(a["bars"])
    side = "sell" if a["trend"] == "DOWN" and wk == "DOWN" else "buy" if a["trend"] == "UP" and wk == "UP" else None
    out = {"wk": wk, "side": side}
    if not side:
        return out
    half = atr / 2
    if side == "sell":
        levels = sorted(x for x in g["res"] + [a["e20"], a["s50"]] if x > px + 0.5 * atr)
        targets = sorted((x for x in g["sup"] if x < px), reverse=True)
    else:
        levels = sorted((x for x in g["sup"] + [a["e20"], a["s50"]] if x < px - 0.5 * atr), reverse=True)
        targets = sorted(x for x in g["res"] if x > px)
    if not levels:
        return out
    lvl = levels[0]
    lo, hi = lvl - 0.25 * atr, lvl + 0.25 * atr
    entry = lvl
    stop = hi + half if side == "sell" else lo - half
    risk = abs(stop - entry)
    sign = -1 if side == "sell" else 1
    # target 1: the nearest real swing level beyond the price, never closer than 2R
    t1 = targets[0] if targets and abs(targets[0] - entry) >= 2 * risk else entry + sign * 2 * risk
    t2 = entry + sign * 3 * risk
    acc, rp, lev = cfg.get("account", 3000), cfg.get("risk_pct", 1), cfg.get("leverage", 5)
    money = acc * rp / 100
    oz = money / risk
    tomorrow = a["today"] + ga.timedelta(days=1)
    soon = [ev for d, ev in a["events"] if d <= tomorrow + ga.timedelta(days=1)]
    out.update(lvl=lvl, lo=lo, hi=hi, entry=entry, stop=stop, t1=t1, t2=t2, risk=risk,
               r1=abs(t1 - entry) / risk, r2=3.0, money=money, oz=oz, margin=oz * entry / lev,
               acc=acc, rp=rp, lev=lev, inside=lo <= px <= hi, push=dollar_push(fx), soon=soon,
               dist=abs(lvl - px), pct=100 * (lvl - px) / px)
    return out


def yahoo_bars(symbol, rng, interval):
    r = json.loads(ga.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng}&interval={interval}"))
    r = r["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = []
    for i, ts in enumerate(r["timestamp"]):
        if None in (q["high"][i], q["low"][i], q["close"][i], q["open"][i]):
            continue
        out.append({"ts": ts, "d": ga.datetime.fromtimestamp(ts, ga.timezone.utc).strftime("%Y-%m-%d"),
                    "o": q["open"][i], "h": q["high"][i], "l": q["low"][i], "c": q["close"][i],
                    "v": q["volume"][i] or 0})
    return live.apply(symbol, out, interval)  # live TradingView price on top (user, 2026-11-23)


def major_zones(symbol, px, atr):
    """Long-history zones from 5 years of weekly bars: where price spent time (weekly closes, weight 1)
    and turned (weekly swing highs/lows, weight 3), clustered within half a daily ATR.
    Fixes the 1-year window that missed older levels like the 2025 base."""
    b = yahoo_bars(symbol, "5y", "1wk")
    pts, n = [(x["c"], 1, x["d"]) for x in b[:-1]], 3
    for i in range(n, len(b) - n):
        if b[i]["l"] == min(x["l"] for x in b[i - n:i + n + 1]):
            pts.append((b[i]["l"], 3, b[i]["d"]))
        if b[i]["h"] == max(x["h"] for x in b[i - n:i + n + 1]):
            pts.append((b[i]["h"], 3, b[i]["d"]))
    pts = sorted(p for p in pts if abs(p[0] - px) / px < 0.2)
    zones, cur = [], [pts[0]] if pts else []
    for p in pts[1:]:
        if p[0] - cur[-1][0] <= 0.5 * atr and p[0] - cur[0][0] <= 1.5 * atr:
            cur.append(p)
        else:
            zones.append(cur)
            cur = [p]
    if cur:
        zones.append(cur)
    out = [{"lo": z[0][0], "hi": z[-1][0], "n": sum(w for _, w, _ in z), "since": min(d for _, _, d in z)[:7]}
           for z in zones]
    return [z for z in out if z["n"] >= 5]


def intraday(symbol):
    """1-hour bars (1 month): hourly ATR, last session range, 1-hour swing levels of the last 5 sessions."""
    b = yahoo_bars(symbol, "1mo", "60m")
    tr = [max(b[i]["h"] - b[i]["l"], abs(b[i]["h"] - b[i - 1]["c"]), abs(b[i]["l"] - b[i - 1]["c"]))
          for i in range(1, len(b))]
    atr = sum(tr[-24:]) / 24
    days = sorted({x["d"] for x in b})
    last = [x for x in b if x["d"] == days[-1]]
    recent = [x for x in b if x["d"] >= days[-5]]
    hi, lo = ga.swings(recent, n=3)
    return {"atr": atr, "s_hi": max(x["h"] for x in last), "s_lo": min(x["l"] for x in last),
            "res": [p for _, p in hi], "sup": [p for _, p in lo], "px": b[-1]["c"]}


def day_plan(a, cfg, z, major):
    """Two scenarios around the nearest intraday support (or resistance in an uptrend)."""
    px, atr = a["live"], z["atr"]
    sups = sorted([x for x in z["sup"] + [z["s_lo"]] if x < px - 0.2 * atr], reverse=True)
    ress = sorted(x for x in z["res"] + [z["s_hi"]] if x > px + 0.2 * atr)
    msup = [m for m in major if m["hi"] < px]
    mres = [m for m in major if m["lo"] > px]
    S = sups[0] if sups else (msup[-1]["hi"] if msup else px - 2 * atr)
    R = ress[0] if ress else (mres[0]["lo"] if mres else px + 2 * atr)
    nxt_dn = sups[1] if len(sups) > 1 else (msup[-1]["hi"] if msup else S - 3 * atr)
    nxt_up = ress[1] if len(ress) > 1 else (mres[0]["lo"] if mres else R + 3 * atr)
    acc, rp = cfg.get("account", 3000), cfg.get("risk_pct", 1)
    down = a["trend"] != "UP"
    out = []

    def sc(title, trig, entry, stop, target, ct, key=None):
        risk = abs(entry - stop)
        pct = rp / 2 if ct else rp
        m = acc * pct / 100
        return {"key": key, "title": title, "trig": trig, "e": entry, "s": stop, "t": target,
                "r": abs(target - entry) / risk if risk else 0, "rp": pct, "m": m, "oz": m / risk if risk else 0}

    q = 0.25 * atr
    if down:  # A: bounce at support (counter-trend), B: breakdown (with trend)
        out.append(sc(t("sc_bounce", lv=S, ct=t("ct")), t("d_trig_bull", lo=S - q, hi=S + q),
                      S, S - q - atr, R, True, key="sc_bounce"))
        out.append(sc(t("sc_break", lv=S, ct=t("wt")), t("d_trig_bear_break", lv=S - q),
                      S - q, S + q + 0.5 * atr, msup[-1]["hi"] if msup else nxt_dn, False, key="sc_break"))
    else:  # A: pullback buy at support (with trend), B: rejection at resistance (counter-trend)
        out.append(sc(t("sc_pull", lv=S, ct=t("wt")), t("d_trig_bull", lo=S - q, hi=S + q),
                      S, S - q - atr, max(R, nxt_up if R - S < atr else R), False, key="sc_pull"))
        out.append(sc(t("sc_top", lv=R, ct=t("ct")), t("d_trig_bear", lo=R - q, hi=R + q),
                      R, R + q + atr, S, True, key="sc_top"))
    return S, R, out


def silver_line(key, sp, s50s):
    if key not in SILVER_TEST or not sp:
        return []
    n, r, n2, r2 = SILVER_TEST[key]
    sell = key in ("sc_break", "sc_top")
    ok = sp < s50s if sell else sp > s50s
    rel = t("rel_below" if sp < s50s else "rel_above")
    return [("\U0001F948 " if ok else "\u274C ") + t("ag_ok" if ok else "ag_bad", sp=sp, s50=s50s, rel=rel,
                                                   n=n, r=r, n2=n2, r2=r2)]


def card(a, cfg, fx, log=False):
    """log=True when the card is really sent: logs today's scenarios and adds the live record."""
    p = plan(a, cfg, fx)
    blocks = ["\U0001F4CD " + t("title", d=a["today"]),
              "\U0001F4CE " + t("based", trend=t("w_" + a["trend"]), weekly=t("w_" + p["wk"]),
                                 rsi=a["rsi"], px=a["live"])]
    try:
        px, datr = a["live"], a["regime"]["atr"]
        major = major_zones(cfg["symbol"], px, datr)
        z = intraday(cfg["symbol"])
        S, R, scen = day_plan(a, cfg, z, major)
        now = [SEP, "\U0001F5FA\ufe0f " + t("now_title")]
        inside = [m for m in major if m["lo"] <= px <= m["hi"]]
        if inside:
            m = inside[0]
            now.append("\U0001F4CC " + t("inside_major", lo=m["lo"], hi=m["hi"], n=m["n"], since=m["since"],
                                           kind=t("k_both")))
        below = [m for m in major if m["hi"] < px]
        above = [m for m in major if m["lo"] > px]
        if below:
            m = below[-1]
            now.append("\U0001F7E2 " + t("major_sup", lo=m["lo"], hi=m["hi"], d=px - m["hi"], n=m["n"]))
        if above:
            m = above[0]
            now.append("\U0001F534 " + t("major_res", lo=m["lo"], hi=m["hi"], d=m["lo"] - px, n=m["n"]))
        now.append("\u23F0 " + t("day_lv", s=S, r=R, lo=z["s_lo"], hi=z["s_hi"]))
        blocks += now
        blocks += [SEP, "\u26A1 " + t("day_title")]
        good = [c for c in scen if TESTED.get(c["key"], (0, 0))[1] > 0]
        try:  # Dow/Hamilton: a second market must confirm. Silver vs its 50-day average.
            sb, slive = ga.load_bars("SI=F")
            sc_ = [x["c"] for x in sb]
            sp, s50s = slive or sc_[-1], ga.sma(sc_, 50)
        except Exception:
            sp = s50s = None
        for c in scen:
            n, r = TESTED.get(c["key"], (0, 0))
            if r <= 0:
                blocks.append("\u274C " + t("tested_bad", title=c["title"], n=n, r=r))
                continue
            sell = c["key"] in ("sc_break", "sc_top")
            blocks.append("\n".join([("\U0001F534 " if sell else "\U0001F7E2 ") + c["title"],
                                      "\U0001F56F\ufe0f " + c["trig"],
                                      "\U0001F6AA " + t("d_line", e=c["e"], s=c["s"], t=c["t"], r=c["r"])
                                      + (t("rr_low") if c["r"] < 1.5 else ""),
                                      "\U0001F4B5 " + t("d_risk", rp=c["rp"], m=c["m"], oz=c["oz"]),
                                      "\U0001F9EA " + t("tested_ok", n=n, r=r)]
                                     + (["\U0001F4B5 " + t("dx_note", a=0.28)] if c["key"] == "sc_break" else [])
                                     + silver_line(c["key"], sp, s50s)))
        if not good:
            blocks.append("\U0001F6D1 " + t("tested_none"))
        blocks.append("\u23F3 " + t("d_close"))
        if log:
            import scorecard
            scorecard.LANG = LANG
            try:
                scorecard.score_pending()
                scorecard.log_plans(str(a["today"]), scen, S, R, 0.25 * z["atr"], z["atr"],
                                    {c["key"] for c in good if c["r"] >= 1.5}, (sp < s50s) if sp else None)
                rec = scorecard.block()
                if rec:
                    blocks += [SEP] + rec
            except Exception as e:
                ga.log(f"scorecard failed: {e}")
    except Exception as e:
        ga.log(f"zone_plan day part failed: {e}")
    blocks += [SEP, "\U0001F5D3\ufe0f " + t("swing_title")]
    if not p["side"]:
        blocks += [SEP, "\U0001F6D1 " + t("none", d=t("w_" + a["trend"]), w=t("w_" + p["wk"]))]
        blocks += [SEP, "⚠️ " + t("disclaimer")]
        return "\n\n".join(blocks)
    if "lvl" not in p:
        blocks += [SEP, "\U0001F6D1 " + t("none_rr"), SEP, "⚠️ " + t("disclaimer")]
        return "\n\n".join(blocks)
    sell = p["side"] == "sell"
    blocks += [("\U0001F534 " if sell else "\U0001F7E2 ") + t("side_sell" if sell else "side_buy"),
               "\U0001F3AF " + t("zone", lo=p["lo"], hi=p["hi"], dist=p["dist"], pct=p["pct"]),
               "\U0001F56F️ " + t("trigger", cndl=t("c_sell" if sell else "c_buy")),
               "\U0001F6AA " + t("entry", e=p["entry"]),
               "\U0001F6D1 " + t("stop", s=p["stop"]),
               "\U0001F3C1 " + t("t1", t=p["t1"], r=p["r1"]) + "\n\U0001F3C1 " + t("t2", t=p["t2"], r=p["r2"]),
               "\U0001F4B5 " + t("risk", rp=p["rp"], acc=p["acc"], m=p["money"], oz=p["oz"], mg=p["margin"], lev=p["lev"]),
               "❎ " + t("inval", side=t("inval_above" if sell else "inval_below"), lv=p["stop"])]
    if p["inside"]:
        now = t("now_in")
    elif sell and a["rsi"] < 30:
        now = t("now_chase", rsi=a["rsi"]) + " " + t("now_wait")
    else:
        now = t("now_wait")
    blocks.append("⏱️ " + t("now", msg=now))

    dx = t("dx_up") if p["push"] >= 1 else t("dx_down") if p["push"] <= -1 else t("dx_flat")
    backs = (p["push"] >= 1) if sell else (p["push"] <= -1)
    against = (p["push"] <= -1) if sell else (p["push"] >= 1)
    checks = [(t("ok"), t("c_mtf")), (t("ok"), t("c_stop")),
              (t("ok") if p["r1"] >= 2 else t("no"), t("c_rr", r=p["r1"])),
              (t("warn"), t("c_vol"))]
    if p["soon"]:
        checks.append((t("warn"), t("c_news_bad", name=ga.ev_text(p["soon"][0])[0])))
    else:
        checks.append((t("ok"), t("c_news")))
    checks.append((t("no"), t("c_dollar_bad", m=dx)) if against else
                  (t("ok") if backs else t("warn"), t("c_dollar", m=dx)))
    checks.append((t("warn"), t("c_test")))
    blocks += [SEP, "\U0001F9EA " + t("check"), "\n".join(f"{i} {s}" for i, s in checks)]
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
    ga.LANG = LANG
    send = (args[0] if args else "test") == "send"
    msg = card(ga.analyse(cfg), cfg, ga.fx_quotes(), log=send)
    if (args[0] if args else "test") == "send":
        ga.telegram(msg)
    else:
        print(msg)


if __name__ == "__main__":
    main()
