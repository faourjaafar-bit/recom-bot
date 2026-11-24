"""Gold alerts on Telegram: candles + trend + news + calendar. No trading, alerts only.

  python3 gold_alerts.py brief   # full morning brief, always sends
  python3 gold_alerts.py watch   # sends only on something new (setup, level break, candle signal, event tomorrow)
  python3 gold_alerts.py test    # prints the brief without sending
  add --lang en|ar to override the language (default: "lang" in config.json, now Arabic)

Free data: Yahoo Finance gold futures (GC=F) + dollar index, main FX pairs, US 10y yield;
Google News RSS (many US-market/forex headlines, translated to Arabic via FreeLLMAPI or MyMemory). Telegram keys come from
../trading-safety/.env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID). Levels and events: config.json.
"""
import json
import re
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, "..", "trading-safety", ".env")
STATE_PATH = os.path.join(HERE, "state.json")
LOG_PATH = os.path.join(HERE, "alerts.log")
UA = {"User-Agent": "Mozilla/5.0"}
LANG = "en"

T = {
    "en": {
        "title": "GOLD BRIEF {d:%a %d %b}",
        "price": "Price now: {live:,.0f}  (last close {close:,.0f} on {date})",
        "trend_DOWN": "DOWNTREND (price < 50-day < 200-day)",
        "trend_UP": "UPTREND (price > 50-day > 200-day)",
        "trend_MIXED": "MIXED / changing",
        "trend_short_DOWN": "downtrend", "trend_short_UP": "uptrend", "trend_short_MIXED": "mixed",
        "trend_line": "Trend: {t}",
        "label_TREND DOWN": "TREND DOWN", "label_TREND UP": "TREND UP",
        "label_RANGE": "RANGE", "label_MIXED": "MIXED",
        "why_TREND DOWN": "swing highs and lows are both falling",
        "why_TREND UP": "swing highs and lows are both rising",
        "why_RANGE": "narrow box, no clear swing direction",
        "why_MIXED": "no clear structure",
        "regime": "Regime: {label} ({why}); 60-day range {w:.1f} ATRs wide, price at {pos:.0%} of it",
        "swings": "Swing highs {hi} | swing lows {lo}",
        "avgs": "20d avg {e20:,.0f} | 50d {s50:,.0f} | 200d {s200:,.0f} | RSI {rsi:.0f}",
        "oversold": " (oversold)", "overbought": " (overbought)",
        "candles": "Candles: {names} | volume {vol:.1f}x avg",
        "no_pattern": "no clear pattern",
        "hammer": "Hammer (buyers pushed back from the low)",
        "star": "Shooting star (sellers rejected the high)",
        "bull_engulf": "Bullish engulfing", "bear_engulf": "Bearish engulfing",
        "crows": "Three black crows (3 strong red candles)",
        "soldiers": "Three white soldiers (3 strong green candles)",
        "level_break": "Level break: {items}",
        "below": "closed BELOW {lv:,}", "above": "closed ABOVE {lv:,}",
        "expect": "What to expect:",
        "x_down_oversold": "Very oversold in a downtrend: a relief bounce is common, but trend is still down. "
                           "Bounces often stall near the 20-day average.",
        "x_down": "Downtrend: rallies tend to be sold. Your rules say no buying.",
        "x_up": "Uptrend: dips to the 20-day average are where your setup can appear.",
        "x_mixed": "Mixed trend: no clear edge. Waiting is a position too.",
        "x_range_mid": "Mid-range: wait for price to reach an edge, no trade in the middle.",
        "x_range_low": "At the range low ({lo:,.0f}): a bounce setup is possible; "
                       "stop below the low with a buffer, target the middle.",
        "x_range_high": "At the range high ({hi:,.0f}): a reversal setup is possible; "
                        "stop above the high with a buffer, target the middle.",
        "x_trend_edge": "At the edge of a trend, not a range: fading it means fighting the trend.",
        "x_bull": "Bullish candle today", "x_bull_end": ": watch for a close above today's high to confirm.",
        "x_bear": "Bearish candle today", "x_bear_end": ": sellers in control.",
        "x_loud": " on HIGH volume", "x_weak": " (low volume, weaker)",
        "setup": "YOUR TESTED SETUP: ",
        "setup_yes": "APPEARED. Check the chart and decide yourself; stop below today's low.",
        "setup_no": "no signal (no trade by your rules)",
        "coming": "Coming up:", "event": "- {d:%a %d %b}: {name} ({note})",
        "news": "News (24h):",
        "disclaimer": "Info only, not financial advice. You decide and place every trade.",
        "w_header": "GOLD ALERT  {live:,.0f}  (RSI {rsi:.0f}, {trend})",
        "w_setup": "YOUR TESTED SETUP APPEARED. Check the chart; stop below the signal candle's low.",
        "w_break": "Level break: gold {b}",
        "w_candle": "Candle: {n}",
        "w_tomorrow": "Tomorrow: {name} ({note})",
        "w_regime": "Regime changed: {old} -> {new}",
        "w_footer": "Info only, you decide.",
        "w_zone": "ZONE PLAN: gold reached the {side} zone {lo:,.0f}-{hi:,.0f}. Wait for the trigger candle on the daily close.",
        "w_side_sell": "sell", "w_side_buy": "buy",
        "no_keys": "(Telegram keys not set: message only logged)",
        "fx_title": "US DOLLAR & FOREX",
        "fx_dxy": "Dollar index (DXY)", "fx_eur": "EUR/USD", "fx_jpy": "USD/JPY", "fx_gbp": "GBP/USD",
        "fx_tnx": "US 10-year yield",
        "fx_strong": "Stronger dollar / higher yields = pressure on gold",
        "fx_weak": "Weaker dollar / lower yields = support for gold",
        "fx_flat": "Dollar and yields quiet: no big push on gold from them",
        "news_title": "US MARKETS & FOREX NEWS (24h)",
    },
    "ar": {
        "title": "موجز الذهب {d:%Y-%m-%d}",
        "price": "السعر الحالي: {live:,.0f}  (آخر إغلاق {close:,.0f} بتاريخ {date})",
        "trend_DOWN": "اتجاه هابط (السعر دون متوسط 50 يوماً، وهو دون متوسط 200 يوم)",
        "trend_UP": "اتجاه صاعد (السعر فوق متوسط 50 يوماً، وهو فوق متوسط 200 يوم)",
        "trend_MIXED": "مختلط / متغيّر",
        "trend_short_DOWN": "هابط", "trend_short_UP": "صاعد", "trend_short_MIXED": "مختلط",
        "trend_line": "الاتجاه: {t}",
        "label_TREND DOWN": "اتجاه هابط", "label_TREND UP": "اتجاه صاعد",
        "label_RANGE": "نطاق عرضي", "label_MIXED": "مختلط",
        "why_TREND DOWN": "القمم والقيعان كلها في تراجع",
        "why_TREND UP": "القمم والقيعان كلها في ارتفاع",
        "why_RANGE": "نطاق ضيق دون اتجاه واضح",
        "why_MIXED": "لا بنية واضحة",
        "regime": "نمط السوق: {label} ({why})؛ نطاق آخر 60 يوماً بعرض {w:.1f} من متوسط الحركة اليومية (ATR)، "
                  "والسعر عند {pos:.0%} منه",
        "swings": "القمم {hi} | القيعان {lo}",
        "avgs": "متوسط 20 يوماً {e20:,.0f} | 50 يوماً {s50:,.0f} | 200 يوم {s200:,.0f} | RSI {rsi:.0f}",
        "oversold": " (تشبّع بيعي)", "overbought": " (تشبّع شرائي)",
        "candles": "الشموع: {names} | الحجم {vol:.1f}× المتوسط",
        "no_pattern": "لا نموذج واضح",
        "hammer": "المطرقة (المشترون دفعوا السعر بعيداً عن القاع)",
        "star": "النجمة الهابطة (البائعون رفضوا القمة)",
        "bull_engulf": "ابتلاع صاعد", "bear_engulf": "ابتلاع هابط",
        "crows": "ثلاثة غربان سود (3 شموع حمراء قوية)",
        "soldiers": "ثلاثة جنود بيض (3 شموع خضراء قوية)",
        "level_break": "كسر مستوى: {items}",
        "below": "أُغلق دون {lv:,}", "above": "أُغلق فوق {lv:,}",
        "expect": "ما المتوقع:",
        "x_down_oversold": "تشبّع بيعي شديد في اتجاه هابط: الارتداد التصحيحي شائع، لكن الاتجاه ما زال هابطاً. "
                           "الارتدادات تتوقف غالباً قرب متوسط 20 يوماً.",
        "x_down": "اتجاه هابط: الصعود يُباع عادةً. قواعدك تقول لا شراء.",
        "x_up": "اتجاه صاعد: التراجعات نحو متوسط 20 يوماً هي حيث قد يظهر إعدادك.",
        "x_mixed": "اتجاه مختلط: لا أفضلية واضحة. الانتظار قرار أيضاً.",
        "x_range_mid": "منتصف النطاق: انتظر وصول السعر إلى أحد الحدّين، ولا صفقات في الوسط.",
        "x_range_low": "عند قاع النطاق ({lo:,.0f}): ارتداد محتمل؛ "
                       "الوقف تحت القاع مع هامش، والهدف منتصف النطاق.",
        "x_range_high": "عند قمة النطاق ({hi:,.0f}): انعكاس محتمل؛ "
                        "الوقف فوق القمة مع هامش، والهدف منتصف النطاق.",
        "x_trend_edge": "عند طرف اتجاه وليس نطاقاً: عكس الاتجاه يعني مقاومته.",
        "x_bull": "شمعة صاعدة اليوم", "x_bull_end": ": انتظر إغلاقاً فوق أعلى سعر اليوم للتأكيد.",
        "x_bear": "شمعة هابطة اليوم", "x_bear_end": ": البائعون يسيطرون.",
        "x_loud": " بحجم مرتفع", "x_weak": " (حجم ضعيف، إشارة أضعف)",
        "setup": "إعدادك المُختبَر: ",
        "setup_yes": "ظهر. راجع الرسم البياني وقرّر بنفسك؛ الوقف تحت أدنى سعر لشمعة اليوم.",
        "setup_no": "لا إشارة (لا صفقة وفق قواعدك)",
        "coming": "قريباً:", "event": "- {d:%Y-%m-%d}: {name} ({note})",
        "news": "أخبار الذهب (24 ساعة):",
        "disclaimer": "معلومات فقط وليست نصيحة مالية. القرار والتنفيذ عليك.",
        "w_header": "تنبيه الذهب  {live:,.0f}  (RSI {rsi:.0f}، {trend})",
        "w_setup": "ظهر إعدادك المُختبَر. راجع الرسم؛ الوقف تحت أدنى سعر لشمعة الإشارة.",
        "w_break": "كسر مستوى: الذهب {b}",
        "w_candle": "شمعة: {n}",
        "w_tomorrow": "غداً: {name} ({note})",
        "w_regime": "تغيّر نمط السوق: {old} ← {new}",
        "w_footer": "معلومات فقط، والقرار لك.",
        "w_zone": "📍 خطة الزون: وصل الذهب إلى منطقة {side} {lo:,.0f}-{hi:,.0f}. انتظر شمعة الشرط عند الإغلاق اليومي.",
        "w_side_sell": "البيع", "w_side_buy": "الشراء",
        "no_keys": "(مفاتيح تيليغرام غير مضبوطة: الرسالة سُجّلت فقط)",
        "fx_title": "الدولار الأمريكي والفوركس",
        "fx_dxy": "مؤشر الدولار DXY", "fx_eur": "اليورو/دولار", "fx_jpy": "دولار/ين", "fx_gbp": "الإسترليني/دولار",
        "fx_tnx": "عائد السندات الأمريكية 10 سنوات",
        "fx_strong": "دولار أقوى وعوائد أعلى = ضغط على الذهب",
        "fx_weak": "دولار أضعف وعوائد أدنى = دعم للذهب",
        "fx_flat": "الدولار والعوائد هادئة: لا دفع كبير على الذهب منها",
        "news_title": "أخبار الأسواق الأمريكية والفوركس (24 ساعة)",
    },
}


def t(key, **kw):
    s = T[LANG][key]
    return s.format(**kw) if kw else s


def load_env(path):
    env = {}
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(5)


def log(text):
    with open(LOG_PATH, "a") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M} {text.replace(chr(10), ' | ')}\n")


def chats(env):
    """The owner's chat, then everyone in TELEGRAM_SHARE_IDS (comma separated) who gets market alerts."""
    ids = [env.get("TELEGRAM_CHAT_ID", ""), env.get("TELEGRAM_CHANNEL_ID", "")] + env.get("TELEGRAM_SHARE_IDS", "").split(",")
    return [i.strip() for i in ids if i.strip()]


def telegram(text):
    env = load_env(ENV_PATH)
    token, ids = env.get("TELEGRAM_BOT_TOKEN"), chats(env)
    log(text)
    if not token or not ids:
        print(t("no_keys") + "\n")
        print(text)
        return
    for chat in ids:
        data = urllib.parse.urlencode({"chat_id": chat, "text": text,
                                       "disable_web_page_preview": "true"}).encode()
        try:
            urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data, timeout=20)
        except Exception as e:  # one blocked reader must not stop the others
            log(f"telegram to {chat} failed: {e}")


BI_SEP = "═" * 12  # between the Arabic message and its English translation


def bilingual(build):
    """build() makes one message in the current LANG; return it in Arabic, then English under a divider."""
    global LANG
    keep, out = LANG, []
    for LANG in ("ar", "en"):
        out.append(build())
    LANG = keep
    return out[0] + "\n\n" + BI_SEP + "\n" + out[1]


def telegram_bi(text):
    """Send a bilingual message; if it is over Telegram's 4096 limit, send Arabic and English apart."""
    parts = text.split("\n\n" + BI_SEP + "\n") if len(text) > 4000 else [text]
    for p in parts:
        telegram(p)


# ---------- data ----------
def load_bars(symbol):
    r = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1y&interval=1d"))
    r = r["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bars = []
    for i, ts in enumerate(r["timestamp"]):
        vals = [q[k][i] for k in ("open", "high", "low", "close", "volume")]
        if None in vals[:4]:
            continue
        d = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
        bars.append({"d": d, "o": vals[0], "h": vals[1], "l": vals[2], "c": vals[3], "v": vals[4] or 0})
    live = r["meta"].get("regularMarketPrice")
    try:  # live TradingView spot instead of late Yahoo futures (user, 2026-11-23)
        import live as lv
        off, q = lv.offset(symbol), lv.live(symbol)
        bars = [dict(b, o=b["o"] + off, h=b["h"] + off, l=b["l"] + off, c=b["c"] + off) for b in bars]
        live = q[0] if q else (live + off if live else live)
    except Exception:
        pass
    # analyse closed candles only: drop today's still-forming bar
    if bars and bars[-1]["d"] >= today:
        bars = bars[:-1]
    return bars, live


FX = [("DX-Y.NYB", "fx_dxy", "\U0001F1FA\U0001F1F8"), ("EURUSD=X", "fx_eur", "\U0001F1EA\U0001F1FA"),
      ("JPY=X", "fx_jpy", "\U0001F1EF\U0001F1F5"), ("GBPUSD=X", "fx_gbp", "\U0001F1EC\U0001F1E7"),
      ("^TNX", "fx_tnx", "\U0001F3E6")]
NEWS_QUERIES = ["forex dollar", "Federal Reserve", "Treasury yields", "US inflation economy",
                "gold price", "EUR/USD", "Wall Street stocks"]


def fx_quotes():
    """Last price and change vs previous close for the dollar, main pairs and the 10y yield."""
    out = []
    for sym, key, flag in FX:
        try:
            m = json.loads(get("https://query1.finance.yahoo.com/v8/finance/chart/"
                               + urllib.parse.quote(sym) + "?range=1d&interval=1d", tries=2))
            m = m["chart"]["result"][0]["meta"]
            px, prev = m["regularMarketPrice"], m["chartPreviousClose"]
            out.append({"sym": sym, "key": key, "flag": flag, "px": px, "chg": px - prev,
                        "pct": 100 * (px - prev) / prev})
        except Exception:
            continue
    return out


def headlines(n=8):
    """Read many US-market / forex / gold headlines, keep a varied top n (round-robin over topics)."""
    pools, seen = [], set()
    for q in NEWS_QUERIES:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:1d")
               + "&hl=en-US&gl=US&ceid=US:en")
        try:
            root = ET.fromstring(get(url, tries=2))
        except Exception:
            continue
        items = []
        for it in root.iter("item"):
            title, _, src = (it.findtext("title") or "").rpartition(" - ")
            title = title or src
            k = title.lower()[:60]
            if title and k not in seen:
                seen.add(k)
                items.append((title, src if title != src else ""))
        pools.append(items)
    picked = []
    while len(picked) < n and any(pools):
        for p in pools:
            if p and len(picked) < n:
                picked.append(p.pop(0))
    if LANG == "ar" and picked:
        ar = translate([h for h, _ in picked])
        picked = [(a or h, s) for (h, s), a in zip(picked, ar)]
    return picked


def _key(env_name):
    """A key from the environment, or an `export NAME="..."` line in ~/.zshrc (as arena_free.py does)."""
    if os.environ.get(env_name):
        return os.environ[env_name]
    try:
        m = re.search(r'^export %s="([^"]+)"' % env_name, open(os.path.expanduser("~/.zshrc")).read(), re.M)
        return m.group(1) if m else None
    except OSError:
        return None


def translate(texts):
    """English -> Arabic. Local free routers first (FreeLLMAPI, then OmniRoute), else MyMemory."""
    prompt = ("Translate each line to clear news-style Arabic. Keep numbers, tickers and names. "
              "Return exactly one line per input line, nothing else.\n\n" + "\n".join(texts))
    routers = [("http://127.0.0.1:31415", load_env(ENV_PATH).get("FREELLM_KEY") or _key("FREELLMAPI_API_KEY")),
               ("http://127.0.0.1:20128", _key("OMNIROUTE_API_KEY"))]
    for base, key in routers:
        if not key:
            continue
        try:
            req = urllib.request.Request(
                base + "/v1/chat/completions",
                json.dumps({"model": "auto", "messages": [{"role": "user", "content": prompt}]}).encode(),
                {"Content-Type": "application/json", "Authorization": "Bearer " + key})
            with urllib.request.urlopen(req, timeout=60) as r:
                lines = [x.strip() for x in json.loads(r.read())["choices"][0]["message"]["content"]
                         .strip().splitlines() if x.strip()]
            if len(lines) == len(texts):
                return lines
        except Exception:
            pass
    out = []
    for txt in texts:
        try:
            r = json.loads(get("https://api.mymemory.translated.net/get?langpair=en|ar&q="
                               + urllib.parse.quote(txt[:480]), tries=2))
            a = r["responseData"]["translatedText"]
            out.append(a if r.get("responseStatus") == 200 and "MYMEMORY" not in a.upper() else "")
        except Exception:
            out.append("")
    return out


# ---------- analysis ----------
def sma(c, n):
    return sum(c[-n:]) / n


def ema(c, n):
    e, a = sum(c[:n]) / n, 2 / (n + 1)
    for x in c[n:]:
        e = a * x + (1 - a) * e
    return e


def rsi(c, n=14):
    g = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]
    l = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
    ag, al = sum(g[:n]) / n, sum(l[:n]) / n
    for i in range(n, len(g)):
        ag, al = (ag * (n - 1) + g[i]) / n, (al * (n - 1) + l[i]) / n
    return 100 - 100 / (1 + ag / al) if al else 100


def atr14(b):
    tr = []
    for i in range(1, len(b)):
        h, l, pc = b[i]["h"], b[i]["l"], b[i - 1]["c"]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(tr[-14:]) / 14


def swings(b, n=5):
    """Swing highs/lows: a bar whose high (low) beats n bars on each side."""
    hi = [(b[i]["d"], b[i]["h"]) for i in range(n, len(b) - n)
          if b[i]["h"] == max(x["h"] for x in b[i - n:i + n + 1])]
    lo = [(b[i]["d"], b[i]["l"]) for i in range(n, len(b) - n)
          if b[i]["l"] == min(x["l"] for x in b[i - n:i + n + 1])]
    return hi, lo


def regime(b, window=60, range_atrs=7):
    """Trend or range: swing structure plus how wide the last `window` days are in ATRs."""
    atr = atr14(b)
    hi = max(x["h"] for x in b[-window:])
    lo = min(x["l"] for x in b[-window:])
    width = (hi - lo) / atr
    pos = (b[-1]["c"] - lo) / (hi - lo) if hi > lo else 0.5
    sh, sl = swings(b)
    hs, ls = [p for _, p in sh[-3:]], [p for _, p in sl[-3:]]
    tol = 0.25 * atr  # swings closer than this count as equal, not as a trend

    def steps(seq, sign):
        return len(seq) == 3 and all(sign * (y - x) > tol for x, y in zip(seq, seq[1:]))

    if steps(hs, -1) and steps(ls, -1):
        label = "TREND DOWN"
    elif steps(hs, 1) and steps(ls, 1):
        label = "TREND UP"
    elif width <= range_atrs:
        label = "RANGE"
    else:
        label = "MIXED"
    return {"label": label, "atr": atr, "hi": hi, "lo": lo, "width": width, "pos": pos,
            "res": [p for _, p in sh[-3:]], "sup": [p for _, p in sl[-3:]]}


def candle_signals(b):
    """Patterns on the last closed candle (b[-1]) as (kind, text key)."""
    x, p = b[-1], b[-2]
    body, rng = abs(x["c"] - x["o"]), x["h"] - x["l"]
    lw, uw = min(x["o"], x["c"]) - x["l"], x["h"] - max(x["o"], x["c"])
    vavg = sum(y["v"] for y in b[-21:-1]) / 20
    loud = vavg > 0 and x["v"] > 1.5 * vavg
    out = []
    if rng and body and lw >= 2 * body and uw <= body:
        out.append(("bull", "hammer"))
    if rng and body and uw >= 2 * body and lw <= body:
        out.append(("bear", "star"))
    if x["c"] > x["o"] and p["c"] < p["o"] and x["c"] >= p["o"] and x["o"] <= p["c"]:
        out.append(("bull", "bull_engulf"))
    if x["c"] < x["o"] and p["c"] > p["o"] and x["c"] <= p["o"] and x["o"] >= p["c"]:
        out.append(("bear", "bear_engulf"))
    last3 = b[-3:]
    if all(y["c"] < y["o"] for y in last3) and last3[0]["c"] > last3[1]["c"] > last3[2]["c"]:
        out.append(("bear", "crows"))
    if all(y["c"] > y["o"] for y in last3) and last3[0]["c"] < last3[1]["c"] < last3[2]["c"]:
        out.append(("bull", "soldiers"))
    return out, loud, (x["v"] / vavg if vavg else 0)


def analyse(cfg):
    bars, live = load_bars(cfg["symbol"])
    c = [x["c"] for x in bars]
    last = bars[-1]
    s20, e20, s50, s200, r = sma(c, 20), ema(c, 20), sma(c, 50), sma(c, 200), rsi(c)
    sigs, loud, vol_x = candle_signals(bars)

    if c[-1] > s50 > s200:
        trend = "UP"
    elif c[-1] < s50 < s200:
        trend = "DOWN"
    else:
        trend = "MIXED"

    # the tested rule from the backtest: uptrend + pullback + bull candle + volume
    setup = (trend == "UP" and last["l"] <= e20 * 1.01
             and any(k == "bull" and key in ("hammer", "bull_engulf") for k, key in sigs)
             and last["v"] > sum(y["v"] for y in bars[-21:-1]) / 20)

    breaks = []
    for lv in cfg["levels"]:
        if c[-2] >= lv > c[-1]:
            breaks.append(t("below", lv=lv))
        elif c[-2] <= lv < c[-1]:
            breaks.append(t("above", lv=lv))

    today = datetime.now(timezone.utc).date()
    events = []
    for ev in cfg["events"]:
        d = datetime.strptime(ev["date"], "%Y-%m-%d").date()
        if 0 <= (d - today).days <= 7:
            events.append((d, ev))

    return {"bars": bars, "live": live, "last": last, "regime": regime(bars), "s20": s20, "e20": e20,
            "s50": s50, "s200": s200, "rsi": r, "sigs": sigs, "loud": loud, "vol_x": vol_x,
            "trend": trend, "setup": setup, "breaks": breaks, "events": events, "today": today}


def ev_text(ev):
    if LANG == "ar" and ev.get("name_ar"):
        return ev["name_ar"], ev.get("note_ar", "")
    return ev["name"], ev["note"]


def expectation(a):
    """Plain-language 'what to expect' from the readings."""
    lines = []
    bull = [k for kind, k in a["sigs"] if kind == "bull"]
    bear = [k for kind, k in a["sigs"] if kind == "bear"]
    if a["trend"] == "DOWN":
        lines.append(t("x_down_oversold") if a["rsi"] < 30 else t("x_down"))
    elif a["trend"] == "UP":
        lines.append(t("x_up"))
    else:
        lines.append(t("x_mixed"))
    g = a["regime"]
    if g["label"] == "RANGE":
        if 0.3 < g["pos"] < 0.7:
            lines.append(t("x_range_mid"))
        elif g["pos"] <= 0.3:
            lines.append(t("x_range_low", lo=g["lo"]))
        else:
            lines.append(t("x_range_high", hi=g["hi"]))
    elif g["label"].startswith("TREND") and (g["pos"] <= 0.2 or g["pos"] >= 0.8):
        lines.append(t("x_trend_edge"))
    if bull:
        lines.append(t("x_bull") + (t("x_loud") if a["loud"] else t("x_weak")) + t("x_bull_end"))
    if bear:
        lines.append(t("x_bear") + (t("x_loud") if a["loud"] else "") + t("x_bear_end"))
    return lines


SEP = "\u2501" * 12


def arrow(v):
    # rising = green, falling = red (user, 2026-11-23: rising must never be a red triangle)
    return "\U0001F7E2\u25B2" if v > 0 else "\U0001F534\u25BC" if v < 0 else "\u2796"


def brief(a, news, fx):
    """Telegram brief: one idea per block, emojis, blank lines so it is easy on the eyes."""
    x, g = a["last"], a["regime"]
    trend_icon = {"UP": "\U0001F4C8", "DOWN": "\U0001F4C9", "MIXED": "\u2194\ufe0f"}[a["trend"]]
    rsi_tag = t("oversold") if a["rsi"] < 30 else t("overbought") if a["rsi"] > 70 else ""
    blocks = [
        "\U0001F7E1 " + t("title", d=a["today"]),
        "\U0001F4B0 " + t("price", live=a["live"], close=x["c"], date=x["d"]),
        trend_icon + " " + t("trend_line", t=t("trend_" + a["trend"])),
        "\U0001F9ED " + t("regime", label=t("label_" + g["label"]), why=t("why_" + g["label"]),
                          w=g["width"], pos=g["pos"]),
        "\U0001F4CA " + t("swings", hi=" / ".join(f"{p:,.0f}" for p in g["res"]),
                          lo=" / ".join(f"{p:,.0f}" for p in g["sup"])),
        "\U0001F4CF " + t("avgs", e20=a["e20"], s50=a["s50"], s200=a["s200"], rsi=a["rsi"]) + rsi_tag,
        "\U0001F56F\ufe0f " + t("candles", names="; ".join(t(k) for _, k in a["sigs"]) if a["sigs"]
                                  else t("no_pattern"), vol=a["vol_x"]),
    ]
    if a["breaks"]:
        blocks.append("\U0001F6A8 " + t("level_break", items=", ".join(a["breaks"])))

    if fx:
        lines = [SEP, "\U0001F4B5 " + t("fx_title")]
        for q in fx:
            if q["sym"] == "^TNX":
                val = f"{q['px']:.2f}%  ({q['chg']:+.2f})"
            else:
                val = f"{q['px']:,.{2 if q['px'] > 20 else 4}f}  ({q['pct']:+.2f}%)"
            lines.append(f"{q['flag']} {t(q['key'])}: {val} {arrow(q['chg'])}")
        blocks.append("\n\n".join(lines))
        d = next((q for q in fx if q["sym"] == "DX-Y.NYB"), None)
        y = next((q for q in fx if q["sym"] == "^TNX"), None)
        push = (d["pct"] if d else 0) / 0.2 + (y["chg"] if y else 0) / 0.03
        blocks.append("\u27A1\ufe0f " + t("fx_strong" if push >= 1 else "fx_weak" if push <= -1 else "fx_flat"))

    blocks += [SEP, "\U0001F52E " + t("expect")]
    blocks += ["\u2022 " + s for s in expectation(a)]
    blocks.append(("\u2705 " if a["setup"] else "\U0001F3AF ") + t("setup")
                  + (t("setup_yes") if a["setup"] else t("setup_no")))
    if a["events"]:
        blocks += [SEP, "\U0001F4C5 " + t("coming")]
        for d, ev in a["events"]:
            name, note = ev_text(ev)
            blocks.append("\u2022 " + t("event", d=d, name=name, note=note).lstrip("- "))
    if news:
        blocks += [SEP, "\U0001F4F0 " + t("news_title")]
        blocks += ["\U0001F539 " + h + (f"  ({src})" if src else "") for h, src in news]
    blocks += [SEP, "\u26A0\ufe0f " + t("disclaimer")]
    return "\n\n".join(blocks)


def watch(a):
    """Short alert only for new things; remembers what it already sent."""
    state = json.load(open(STATE_PATH)) if os.path.exists(STATE_PATH) else {}
    key_day = a["last"]["d"]
    items = []  # each item renders itself in the current LANG, so the alert can be built in both languages
    if a["setup"]:
        items.append(lambda: t("w_setup"))
    items += [lambda b=b: t("w_break", b=b) for b in a["breaks"]]
    items += [lambda k=k: t("w_candle", n=t(k)) + (t("x_loud") if a["loud"] else "") for _, k in a["sigs"]]
    tomorrow = a["today"] + timedelta(days=1)
    for d, ev in a["events"]:
        if d == tomorrow:
            items.append(lambda ev=ev: t("w_tomorrow", name=ev_text(ev)[0], note=ev_text(ev)[1]))
    try:  # Zone Plan: tell when the live price enters today's zone
        import zone_plan
        zp = zone_plan.plan(a, json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8")), [])
        if zp.get("lvl") and zp["lo"] <= a["live"] <= zp["hi"]:
            items.append(lambda: t("w_zone", side=t("w_side_" + zp["side"]), lo=zp["lo"], hi=zp["hi"]))
    except Exception:
        pass
    label = a["regime"]["label"]
    old = state.get("regime")
    if old and old != label:
        items.append(lambda: t("w_regime", old=t("label_" + old), new=t("label_" + label)))
    global LANG
    keep, LANG = LANG, "ar"  # remember sent items by their Arabic text, as before
    keys = [f"{key_day}|{f()}" for f in items]
    LANG = keep
    new = [f for f, k in zip(items, keys) if k not in state.get("sent", [])]
    state["regime"] = label
    state.setdefault("sent", []).extend(k for k in keys if k not in state.get("sent", []))
    state["sent"] = state["sent"][-200:]
    json.dump(state, open(STATE_PATH, "w"), ensure_ascii=False)
    if not new:
        return None
    return bilingual(lambda: "\U0001F514 " + t("w_header", live=a["live"], rsi=a["rsi"],
                                                trend=t("trend_short_" + a["trend"]))
                     + "\n\n" + "\n\n".join("\U0001F539 " + f() for f in new) + "\n\n\u26A0\ufe0f " + t("w_footer"))


def main():
    global LANG
    args = sys.argv[1:]
    cfg = json.load(open(os.path.join(HERE, "config.json")))
    LANG = cfg.get("lang", "en")
    if "--lang" in args:
        i = args.index("--lang")
        LANG = args[i + 1]
        del args[i:i + 2]
    if LANG not in T:
        sys.exit(f"unknown language {LANG!r}: use one of {', '.join(T)}")
    mode = args[0] if args else "test"
    a = analyse(cfg)
    if mode == "watch":
        msg = watch(a)
        if msg:
            telegram_bi(msg)
        try:  # the trade alert (entry/stop/targets) fires once, the moment the tested setup triggers
            import trade_alert
            trade_alert.watch(cfg)
        except Exception as e:
            log(f"trade_alert failed: {e}")
        return
    keep, LANG = LANG, "en"
    try:  # English headlines once, translated once for the Arabic half
        news = headlines()
    except Exception:
        news = []
    LANG = keep
    ar = translate([h for h, _ in news]) if news else []
    news_ar = [(x or h, s) for (h, s), x in zip(news, ar)]
    fx = fx_quotes()
    msg = bilingual(lambda: brief(a, news_ar if LANG == "ar" else news, fx))
    import zone_plan  # the Zone Plan card follows the brief, built from the same readings

    def zone_card():
        zone_plan.LANG = LANG
        return zone_plan.card(a, cfg, fx, log=(mode == "brief"))  # scorecard logging skips rows it already has
    zone = bilingual(zone_card)
    if mode == "brief":
        telegram_bi(msg)
        telegram_bi(zone)
    else:
        print(msg + "\n\n" + zone)


if __name__ == "__main__":
    main()
