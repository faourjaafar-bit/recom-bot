"""US market report on Telegram: indices and ratios, scanner matches, then the Time Machine on each.

  python3 market_report.py send   # build and send to Telegram
  python3 market_report.py test   # print only
  add --lang en|ar to override the language (default: "lang" in config.json)

Pipeline (the trader-* skills in ~/.claude/skills):
  1. trader-scanner `daily` over a liquid US list (+ SPY, QQQ, GLD for gold).
  2. For each match: the plan is today's 10:15 AM bar close (or the last full session's),
     stop and target half a typical day's range away (1R).
  3. trader-timemachine replays the rest of the day 10,000 times and re-runs the rule on the
     last ~58 sessions. Matches are ranked by the real history first, then by the replays.
Information only. A match is a chart that fits a rule, not a stock to buy.
"""
import live
import json
import os
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import gold_alerts as ga

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
SKILLS = os.path.expanduser("~/.claude/skills")
PY = sys.executable
NY = ZoneInfo("America/New_York")
UNIVERSE = ("AAPL,MSFT,NVDA,AMZN,META,GOOGL,TSLA,AVGO,AMD,NFLX,JPM,BAC,WFC,GS,V,MA,XOM,CVX,UNH,LLY,"
            "JNJ,PFE,MRK,KO,PEP,WMT,COST,HD,MCD,NKE,DIS,BA,CAT,GE,INTC,ORCL,CRM,ADBE,PLTR,UBER,"
            "SPY,QQQ,GLD")
ALWAYS = ["SPY", "QQQ", "GLD"]
MAX_TM = 9
INDICES = [("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq"), ("^DJI", "Dow Jones"), ("^RUT", "Russell 2000")]
SEP = "━" * 12

T = {
    "en": {
        "title": "US MARKET REPORT {d}",
        "idx": "INDICES (vs previous close)",
        "ratios": "RATIOS",
        "vix": "VIX fear gauge: {v:.1f} ({m})",
        "vix_calm": "calm", "vix_normal": "normal", "vix_fear": "fear",
        "gs": "Gold / silver ratio: {r:.1f}",
        "spread": "10y minus 3m yield: {s:+.2f} ({m})",
        "spread_inv": "inverted: recession warning", "spread_ok": "normal",
        "risk": "Nasdaq vs S&P today: {d:+.2f} pts ({m})",
        "risk_on": "risk appetite", "risk_off": "defensive mood", "risk_flat": "neutral",
        "scan": "SCANNER: {hits} of {n} charts matched a rule ({asof})",
        "tm": "TIME MACHINE: best by the numbers",
        "tm_note": "Plan: buy at the {time} bar close of {date}, stop {stop}, target {target} (1R). "
                   "10,000 replays, seed 19.",
        "pick": "{medal} {sym} ({setups})",
        "pick_odds": "    target first {pt:.0%} | stop first {ps:.0%} | open at close {pn:.0%}",
        "pick_hist": "    real history: fired {trig} of {sess} sessions, {tg} target / {st} stop, avg {r:+.2f}R",
        "none_edge": "No match shows an edge in the replays or the history today. Waiting is a position.",
        "rule": "Rule: a candidate counts only if the real history averages +0.05R or better "
                "AND the replays lean to the target.",
        "closest": "Closest one (still no edge):",
        "matched": "Matched: {items}",
        "close_word": "close",
        "setup_names": {"breakout_20d": "20-day breakout", "bull_flag": "bull flag",
                        "reclaim_ma20": "back above 20-day avg", "oversold": "oversold",
                        "oversold_bounce": "oversold bounce", "watch": "watch"},
        "disclaimer": "Simulations from the last 60 days, not predictions, not a buy list. "
                      "Info only, not financial advice. You decide and place every trade.",
    },
    "ar": {
        "title": "تقرير السوق الأمريكية {d}",
        "idx": "المؤشرات (مقارنة بالإغلاق السابق)",
        "ratios": "النسب",
        "vix": "مؤشر الخوف VIX: {v:.1f} ({m})",
        "vix_calm": "هدوء", "vix_normal": "طبيعي", "vix_fear": "خوف",
        "gs": "نسبة الذهب إلى الفضة: {r:.1f}",
        "spread": "فارق عائد 10 سنوات و3 أشهر: {s:+.2f} ({m})",
        "spread_inv": "مقلوب: إنذار ركود", "spread_ok": "طبيعي",
        "risk": "ناسداك مقابل S&P اليوم: {d:+.2f} نقطة مئوية ({m})",
        "risk_on": "شهية للمخاطرة", "risk_off": "مزاج دفاعي", "risk_flat": "محايد",
        "scan": "الماسح: {hits} من {n} رسماً طابقت قاعدة ({asof})",
        "tm": "آلة الزمن: الأفضل حسب الأرقام",
        "tm_note": "الخطة: شراء عند إغلاق شمعة {time} بتوقيت نيويورك يوم {date}، الوقف {stop}، الهدف {target} (1R). "
                   "10,000 محاكاة، البذرة 19.",
        "pick": "{medal} {sym} ({setups})",
        "pick_odds": "    الهدف أولاً {pt:.0%} | الوقف أولاً {ps:.0%} | مفتوحة عند الإغلاق {pn:.0%}",
        "pick_hist": "    السجل الحقيقي: ظهرت {trig} مرة من {sess} جلسة، {tg} هدف / {st} وقف، المتوسط {r:+.2f}R",
        "none_edge": "لا مطابقة تُظهر أفضلية في المحاكاة أو السجل اليوم. الانتظار قرار أيضاً.",
        "rule": "القاعدة: لا يُحتسب المرشّح إلا إذا كان متوسط السجل الحقيقي +0.05R أو أفضل "
                "وكانت المحاكاة تميل إلى الهدف.",
        "closest": "الأقرب (ولا أفضلية بعد):",
        "matched": "المطابقات: {items}",
        "close_word": "إغلاق",
        "setup_names": {"breakout_20d": "اختراق قمة 20 يوماً", "bull_flag": "علم صاعد",
                        "reclaim_ma20": "عودة فوق متوسط 20 يوماً", "oversold": "تشبّع بيعي",
                        "oversold_bounce": "ارتداد من تشبّع بيعي", "watch": "متابعة"},
        "disclaimer": "محاكاة من آخر 60 يوماً، وليست توقعاً ولا قائمة شراء. "
                      "معلومات فقط وليست نصيحة مالية. القرار والتنفيذ عليك.",
    },
}
LANG = "en"


def t(key, **kw):
    s = T[LANG][key]
    return s.format(**kw) if kw else s


def quote(sym):
    q = live.live(sym)  # TradingView first (user, 2026-11-23)
    if q:
        return q
    m = json.loads(ga.get("https://query1.finance.yahoo.com/v8/finance/chart/"
                          + ga.urllib.parse.quote(sym) + "?range=1d&interval=1d", tries=2))
    m = m["chart"]["result"][0]["meta"]
    return m["regularMarketPrice"], m["chartPreviousClose"]


def market_blocks():
    out, pct = [SEP, "\U0001F3DB️ " + t("idx")], {}
    for sym, name in INDICES:
        try:
            px, prev = quote(sym)
        except Exception:
            continue
        pct[sym] = 100 * (px - prev) / prev
        out.append(f"{ga.arrow(px - prev)} {name}: {px:,.0f}  ({pct[sym]:+.2f}%)")
    out += [SEP, "⚖️ " + t("ratios")]
    try:
        v, _ = quote("^VIX")
        out.append("\U0001F628 " + t("vix", v=v, m=t("vix_calm" if v < 15 else "vix_fear" if v > 25 else "vix_normal")))
    except Exception:
        pass
    try:
        out.append("\U0001F947 " + t("gs", r=quote("GC=F")[0] / quote("SI=F")[0]))
    except Exception:
        pass
    try:
        s = quote("^TNX")[0] - quote("^IRX")[0]
        out.append("\U0001F3E6 " + t("spread", s=s, m=t("spread_inv" if s < 0 else "spread_ok")))
    except Exception:
        pass
    if "^IXIC" in pct and "^GSPC" in pct:
        d = pct["^IXIC"] - pct["^GSPC"]
        out.append("\U0001F3B2 " + t("risk", d=d, m=t("risk_on" if d > 0.3 else "risk_off" if d < -0.3 else "risk_flat")))
    return out


def scan():
    r = subprocess.run([PY, os.path.join(SKILLS, "trader-scanner", "scan.py"), "daily", "--symbols", UNIVERSE,
                        "--no-write", "--json"], capture_output=True, text=True, timeout=600)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"hits": [], "scanned": 0, "as_of": "?"}


def plan_for(sym):
    """Entry = close of the bar ending 10:15 AM ET on the latest session that has it; stop/target 1R."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{sym}-60d5m.json")
    raw = ga.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}?range=60d&interval=5m")
    open(path, "wb").write(raw)
    r = json.loads(raw)["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    days, entry = {}, {}
    for i, ts in enumerate(r["timestamp"]):
        h, l, c = q["high"][i], q["low"][i], q["close"][i]
        if None in (h, l, c):
            continue
        d = datetime.fromtimestamp(ts, NY)
        if not (9 * 60 + 30 <= d.hour * 60 + d.minute < 16 * 60):
            continue
        k = d.strftime("%Y-%m-%d")
        lo, hi = days.get(k, (l, h))
        days[k] = (min(lo, l), max(hi, h))
        if d.strftime("%H:%M") == "10:10":
            entry[k] = c
    if not entry:
        return None
    date = max(entry)
    rng = [hi - lo for k, (lo, hi) in sorted(days.items()) if k < date][-14:]
    half = sum(rng) / len(rng) / 2
    e = entry[date]
    return {"sym": sym, "date": date, "entry": round(e, 2), "stop": round(e - half, 2),
            "target": round(e + half, 2), "path": path}


def timemachine(p):
    r = subprocess.run([PY, os.path.join(SKILLS, "trader-timemachine", "timemachine.py"), "run",
                        "--symbol", p["sym"], "--side", "buy", "--date", p["date"], "--entry-time", "10:15 AM",
                        "--entry", str(p["entry"]), "--stop", str(p["stop"]), "--target", str(p["target"]),
                        "--offline", p["path"], "--json"], capture_output=True, text=True, timeout=300)
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def report():
    now = datetime.now(NY)
    blocks = ["\U0001F1FA\U0001F1F8 " + t("title", d=now.strftime("%Y-%m-%d"))]
    blocks += market_blocks()

    sc = scan()
    hits = sc.get("hits", [])
    names = T[LANG]["setup_names"]
    blocks += [SEP, "\U0001F50E " + t("scan", hits=len(hits), n=sc.get("scanned", 0),
                                      asof=str(sc.get("as_of", "?")).replace("close", t("close_word")))]
    if hits:
        blocks.append(t("matched", items=" / ".join(h["symbol"] for h in hits[:12])))
    cands = {h["symbol"]: h["setups"] for h in hits[:MAX_TM]}
    for s in ALWAYS:
        cands.setdefault(s, ["watch"])

    results = []
    for sym, setups in cands.items():
        try:
            p = plan_for(sym)
            res = timemachine(p) if p else None
        except Exception:
            res = None
        if not res:
            continue
        mc, hist = res["mc"], res["history"]
        side = mc["p_target"] + mc["p_stop"]
        edge = (mc["p_target"] / side - 0.5) if side else 0
        results.append({"sym": sym, "setups": setups, "p": p, "mc": mc, "hist": hist, "edge": edge})
    results.sort(key=lambda x: (x["hist"]["avg_R"], x["edge"]), reverse=True)
    good = [x for x in results if x["hist"]["avg_R"] >= 0.05 and x["edge"] >= 0][:3]

    blocks += [SEP, "⏳ " + t("tm")]
    if not good:
        blocks.append("\U0001F6D1 " + t("none_edge"))
        if results:
            blocks.append(t("closest"))
    shown = good or results[:1]
    if shown:
        medals = ["\U0001F947", "\U0001F948", "\U0001F949"] if good else ["\U0001F50D"]
        for medal, x in zip(medals, shown):
            mc, h, p = x["mc"], x["hist"], x["p"]
            blocks.append("\n".join([
                t("pick", medal=medal, sym=x["sym"], setups=", ".join(names.get(s, s) for s in x["setups"])),
                t("pick_odds", pt=mc["p_target"], ps=mc["p_stop"], pn=mc["p_neither"]),
                t("pick_hist", trig=h["triggered"], sess=h["sessions"], tg=h["target"], st=h["stop"], r=h["avg_R"]),
                "    " + t("tm_note", time="10:15", date=p["date"], stop=p["stop"], target=p["target"]),
            ]))
    blocks.append("\U0001F4CC " + t("rule"))
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
    if LANG not in T:
        sys.exit(f"unknown language {LANG!r}: use one of {', '.join(T)}")
    import ai_stocks
    me = sys.modules[__name__]
    cache_calls()  # the Arabic and English halves reuse the same downloads, scans and backtests
    msg = both(report, [me, ga])
    if (args[0] if args else "test") == "send":
        ga.telegram_bi(msg)
        try:  # the AI stocks card goes as its own message right after the US report
            ga.telegram_bi(both(ai_stocks.card, [me, ga, ai_stocks, ai_stocks.zp]))
        except Exception as e:
            ga.log(f"ai_stocks failed: {e}")
    else:
        print(msg)


def both(build, mods):
    """build() in Arabic, then in English under a divider (LANG set on every module it reads)."""
    out = []
    for lang in ("ar", "en"):
        for m in mods:
            m.LANG = lang
        out.append(build())
    return out[0] + "\n\n" + ga.BI_SEP + "\n" + out[1]


def cache_calls():
    global scan, timemachine
    memo = {}

    def keep(name, fn, key=lambda *a, **k: repr((a, sorted(k.items())))):
        def wrapped(*a, **k):
            kk = (name, key(*a, **k))
            if kk not in memo:
                memo[kk] = fn(*a, **k)
            return memo[kk]
        return wrapped
    ga.get = keep("get", ga.get)
    scan = keep("scan", scan)
    timemachine = keep("tm", timemachine, key=lambda p: json.dumps(p, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
