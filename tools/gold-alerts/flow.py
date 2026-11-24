"""Trading analysis flow on Telegram, one message per market: gold first (the main one), then each stock.

  python3 flow.py           # everything in 4 messages max: gold (3) + all stocks in one   <- the "!!" command
  python3 flow.py gold      # gold only
  python3 flow.py stocks    # stocks only
  python3 flow.py hourly    # only new important news / 3%+ moves, one message per stock (hourly weekday job)
  python3 flow.py test      # build everything, print captions, send nothing
  add --lang en|ar to override the language (default: "lang" in config.json)

Gold: 1) candle chart + price, gram price in TL, candle read  2) gold news + this week's events
      3) the v2 trade card alone (trade_alert.py). Gold messages 1 and 2 hold news, events and the market note.
Stocks: one message, a line per stock (price, move, trend, RSI) + the tested breakout levels.
Charts are drawn by chart_png.py (no extra installs). Information only, not advice.
"""
import live
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import uuid

import candle_read as cr
import chart_png
import gold_alerts as ga
import stock_news as sn
import stock_signal

HERE = os.path.dirname(os.path.abspath(__file__))
CHARTS = os.path.join(HERE, "cache", "charts")
LANG = "en"
SEND = True
CAP = 1024  # Telegram photo caption limit

STOCK_LOOK = {  # emoji + name that resemble each company
    "NVDA": ("🟩🧠🎮", "Nvidia", "إنفيديا"), "AAPL": ("🍎📱", "Apple", "آبل"),
    "MSFT": ("🪟💻", "Microsoft", "مايكروسوفت"), "GOOGL": ("🔍🌐", "Alphabet (Google)", "ألفابت (غوغل)"),
    "AMZN": ("📦🛒", "Amazon", "أمازون"), "META": ("👓🌐", "Meta", "ميتا"),
    "TSLA": ("🚗⚡", "Tesla", "تسلا"), "AVGO": ("📡🔌", "Broadcom", "برودكوم"),
    "AMD": ("🖥️🔴", "AMD", "إيه إم دي"), "TSM": ("🏭🔬", "TSMC", "تي إس إم سي"),
    "PLTR": ("🛰️🔐", "Palantir", "بالانتير"), "NFLX": ("🎬🍿", "Netflix", "نتفليكس"),
    "JPM": ("🏦💼", "JPMorgan", "جي بي مورغان"), "V": ("💳💸", "Visa", "فيزا"),
    "LLY": ("💊🧬", "Eli Lilly", "إيلي ليلي"), "XOM": ("🛢️⛽", "Exxon Mobil", "إكسون موبيل"),
}
GOLD_WORDS = re.compile(r"\bgold\b|\bxau\b|bullion|precious metal|safe[- ]haven|\bfed\b|federal reserve|"
                        r"rate (cut|hike)|central bank|\bPCE\b|\bCPI\b|inflation|dollar|yield", re.I)
GOLD_QUERIES = ["gold price", "gold XAU", "gold Federal Reserve", "central banks gold buying",
                "gold ETF demand", "Turkey gold price"]

T = {
    "en": {
        "g_head": "🥇🪙✨ GOLD · XAU/USD  {px:,.2f}  {arrow} {pct:+.2f}% {mood}",
        "g_gram": "🇹🇷 Gram gold ≈ {g:,.0f} TL  (USD/TRY {fx:.2f})",
        "g_news": "📰🥇 GOLD NEWS (24h)",
        "g_events": "🗓️ THIS WEEK",
        "no_news": "No gold headlines in the last 24 hours.",
        "s_head": "{look} {name} · {sym}  {mood}",
        "s_px": "💵 ${px:,.2f}  {arrow} {pct:+.2f}% {move}",
        "s_news": "📰 News:",
        "moods": {"UP": "🐂", "DOWN": "🐻", "MIXED": "⚖️"},
        "big_up": "🚀", "big_down": "💥",
        "foot": "⚠️ Info only, not advice. You decide.",
        "s_all": "📊 US STOCKS · {n} stocks (biggest move first)",
        "s_cards": "🎯 Tested breakout levels (daily):",
        "s_buy": "🟢 {sym}: BUY now · entry {e:,.2f} · stop {st:,.2f} · target {tg:,.2f}",
        "s_wait": "⏳ {sym}: buy only on a daily close above {e:,.2f} · stop {st:,.2f} · target {tg:,.2f}",
        "start": "🤖🚦 TRADING FLOW STARTED · {d}\n🥇 Gold first, then {n} stocks, one message each.",
        "end": "✅🏁 Flow done: gold + {n} stocks.",
    },
    "ar": {
        "g_head": "🥇🪙✨ الذهب · XAU/USD  {px:,.2f}  {arrow} {pct:+.2f}% {mood}",
        "g_gram": "🇹🇷 غرام الذهب ≈ {g:,.0f} ليرة  (الدولار {fx:.2f} ليرة)",
        "g_news": "📰🥇 أخبار الذهب (24 ساعة)",
        "g_events": "🗓️ أحداث هذا الأسبوع",
        "no_news": "لا عناوين عن الذهب خلال آخر 24 ساعة.",
        "s_head": "{look} {name} · {sym}  {mood}",
        "s_px": "💵 ${px:,.2f}  {arrow} {pct:+.2f}% {move}",
        "s_news": "📰 الأخبار:",
        "moods": {"UP": "🐂", "DOWN": "🐻", "MIXED": "⚖️"},
        "big_up": "🚀", "big_down": "💥",
        "foot": "⚠️ معلومات وليست نصيحة. القرار لك.",
        "s_all": "📊 الأسهم الأمريكية · {n} سهماً (الأكبر حركة أولاً)",
        "s_cards": "🎯 مستويات الاختراق المختبَرة (يومي):",
        "s_buy": "🟢 {sym}: شراء الآن · الدخول {e:,.2f} · الوقف {st:,.2f} · الهدف {tg:,.2f}",
        "s_wait": "⏳ {sym}: شراء فقط بإغلاق يومي فوق {e:,.2f} · الوقف {st:,.2f} · الهدف {tg:,.2f}",
        "start": "🤖🚦 بدء تحليل التداول · {d}\n🥇 الذهب أولاً، ثم {n} سهماً، كل واحد في رسالة.",
        "end": "✅🏁 انتهى التحليل: الذهب + {n} سهماً.",
    },
}


def t(key, **kw):
    s = T[LANG][key]
    return s.format(**kw) if kw else s


SEP = "═" * 12
BI = True  # every message in Arabic, then English under it (--lang forces a single language)


def set_lang(lang):
    import zone_plan
    global LANG
    LANG = ga.LANG = cr.LANG = sn.LANG = zone_plan.LANG = lang


def both(build):
    """build() makes one message in the current language; return Arabic + separator + English."""
    if not BI:
        return build()
    out = []
    for lang in ("ar", "en"):
        set_lang(lang)
        out.append(build())
    return out[0] + "\n\n" + SEP + "\n" + out[1]


# ---------- telegram ----------
def _post(method, fields, files=None):
    env = ga.load_env(ga.ENV_PATH)
    for chat in ga.chats(env):  # the owner first, then TELEGRAM_SHARE_IDS
        try:
            _post_one(env.get("TELEGRAM_BOT_TOKEN"), method, dict(fields, chat_id=chat), files)
        except Exception as e:
            ga.log(f"flow: telegram to {chat} failed: {e}")


def _post_one(token, method, fields, files):
    url = f"https://api.telegram.org/bot{token}/{method}"
    if not files:
        urllib.request.urlopen(url, urllib.parse.urlencode(fields).encode(), timeout=30)
        return
    bd = uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += f"--{bd}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    for k, path in files.items():
        body += (f"--{bd}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{os.path.basename(path)}\"\r\n"
                 "Content-Type: image/png\r\n\r\n").encode() + open(path, "rb").read() + b"\r\n"
    body += f"--{bd}--\r\n".encode()
    req = urllib.request.Request(url, body, {"Content-Type": f"multipart/form-data; boundary={bd}"})
    urllib.request.urlopen(req, timeout=60)


def send(text, photo=None):
    """Photo with the text as caption (split if too long), or plain text. Prints instead in test mode."""
    ga.log(text)
    if not SEND:
        print(("[photo " + os.path.basename(photo) + "]\n" if photo else "") + text + "\n" + "-" * 40)
        return
    if len(text) > 4000 and not photo and SEP in text:
        for part in text.split("\n\n" + SEP + "\n"):
            send(part)
        return
    try:
        if photo and len(text) <= CAP:
            _post("sendPhoto", {"caption": text}, {"photo": photo})
        elif photo:
            head, _, rest = text.partition("\n")
            _post("sendPhoto", {"caption": head}, {"photo": photo})
            _post("sendMessage", {"text": rest, "disable_web_page_preview": "true"})
        else:
            _post("sendMessage", {"text": text, "disable_web_page_preview": "true"})
    except Exception as e:
        ga.log(f"flow: telegram failed: {e}")
    time.sleep(1.2)  # stay under Telegram's per-chat rate


# ---------- pieces ----------
def chart(sym, a, bars):
    os.makedirs(CHARTS, exist_ok=True)
    c = [x["c"] for x in bars]
    ma = [sum(c[i - 49:i + 1]) / 50 if i >= 49 else None for i in range(len(c))]
    return chart_png.render(bars, os.path.join(CHARTS, sym.replace("=", "_") + ".png"), a["sup"], a["res"], ma)


def quote(sym):
    q = live.live(sym)  # TradingView first (user, 2026-11-23)
    if q:
        return q
    m = json.loads(ga.get("https://query1.finance.yahoo.com/v8/finance/chart/"
                          + urllib.parse.quote(sym) + "?range=1d&interval=1d", tries=2))["chart"]["result"][0]["meta"]
    return m["regularMarketPrice"], m["chartPreviousClose"]


def gold(cfg):
    import zone_plan
    zone_plan.LANG = LANG
    a = cr.read("GC=F")
    bars, _ = ga.load_bars("GC=F")
    px, prev = quote("GC=F")
    pct = 100 * (px - prev) / prev
    try:
        fx = quote("USDTRY=X")[0]
    except Exception:
        fx = None

    def head():
        lines = [t("g_head", px=px, arrow=ga.arrow(pct), pct=pct, mood=t("moods")[a["trend"]])]
        if fx:
            lines.append(t("g_gram", g=px * fx / 31.1035, fx=fx))
        return "\n".join(lines)
    send(both(head), chart("GC=F", a, bars))  # short caption: one photo message, never split

    ga.NEWS_QUERIES = GOLD_QUERIES
    set_lang("en")  # filter on the English text first, translate only what survives
    try:
        news = [(h, s) for h, s in ga.headlines(n=20) if GOLD_WORDS.search(h)][:4]
    except Exception:
        news = []
    ar_news = news
    if news:
        ar = ga.translate([h for h, _ in news])
        ar_news = [(a or h, s) for (h, s), a in zip(news, ar)]
    ga_a = ga.analyse(cfg)

    def news_msg():
        shown = ar_news if LANG == "ar" else news
        msg = [cr.card(a), "", t("g_news")]
        msg += ["🔸 " + h + (f"  ({s})" if s else "") for h, s in shown] or [t("no_news")]
        if ga_a["events"]:
            msg += ["", t("g_events")]
            for d, ev in ga_a["events"]:
                name, note = ga.ev_text(ev)
                msg.append(f"📅 {d:%d/%m} {name}: {note}")
        return "\n".join(msg)
    import trade_alert
    try:
        _, msgs, _ = trade_alert.message(cfg)
    except Exception as e:
        ga.log(f"flow: gold v2 card failed: {e}")
        msgs = []
    # v2 levels (same as "go!!"): the market note joins the news message, the trade card goes alone
    note = msgs[0] if len(msgs) > 1 else ""
    text = both(news_msg)
    if note and len(text) + len(note) < 3900:
        text += "\n\n" + SEP + "\n\n" + note
    send(text)
    if msgs:
        send(msgs[-1])


def item_lines(flat):
    """Headline lines for every item in both languages: {"ar": [...], "en": [...]}."""
    out = {}
    for lang in ("ar", "en"):
        set_lang(lang)
        out[lang] = sn.lines_for(flat)  # one translation call per language for all headlines
    return out


def stock_message(sym, move, items):
    """One stock: chart + price + candle read + its headlines (items = {"ar": [...], "en": [...]})."""
    a = cr.read(sym)
    bars, _ = ga.load_bars(sym)
    look, en, ar = STOCK_LOOK.get(sym, ("📈", sym, sym))
    px = move["price"] if move else a["px"]
    pct = move["pct"] if move else 0.0

    def build():
        big = t("big_up") if pct >= sn.MOVE_PCT else t("big_down") if pct <= -sn.MOVE_PCT else ""
        lines = [t("s_head", look=look, name=ar if LANG == "ar" else en, sym=sym, mood=t("moods")[a["trend"]]),
                 t("s_px", px=px, arrow=ga.arrow(pct), pct=pct, move=big), "", cr.card(a)]
        if items.get(LANG):
            lines += ["", t("s_news")] + items[LANG]
        lines += ["", t("foot")]
        return "\n".join(lines)
    send(both(build), chart(sym, a, bars))
    try:  # the trade card goes alone, after the chart and news
        c = stock_signal.card(sym, ar, en)
        if c:
            send(c)
    except Exception as e:
        ga.log(f"flow: {sym} card failed: {e}")


def stocks(cfg, only=None):
    """All stocks in ONE message: a line per stock (price, move, trend, RSI) and the tested buy levels under it."""
    tickers = only or cfg.get("stocks", sn.DEFAULT_STOCKS)
    try:
        moves = {m["ticker"]: m for m in sn.fetch(tickers, 24, remember=False).get("moves", [])}
    except Exception:
        moves = {}
    rows, setups = [], []
    for s in tickers:
        try:
            a = cr.read(s)
        except Exception as e:
            ga.log(f"flow: {s} failed: {e}")
            continue
        m = moves.get(s)
        rows.append((s, m["price"] if m else a["px"], m["pct"] if m else 0.0, a))
        try:
            su = stock_signal.setup(s)
            if su:
                setups.append((s, su))
        except Exception as e:
            ga.log(f"flow: card check {s} failed: {e}")
    rows.sort(key=lambda r: abs(r[2]), reverse=True)

    def build():
        lines = [t("s_all", n=len(rows)), ""]
        for s, px, pct, a in rows:
            look, en, ar = STOCK_LOOK.get(s, ("📈", s, s))
            big = t("big_up") if pct >= sn.MOVE_PCT else t("big_down") if pct <= -sn.MOVE_PCT else ""
            lines.append(f"{look} {s} ${px:,.2f} {ga.arrow(pct)} {pct:+.2f}% {t('moods')[a['trend']]} RSI {a['rsi']:.0f} {big}".rstrip())
        if setups:
            lines += ["", t("s_cards")]
            for s, su in setups:
                lines.append(t("s_buy" if su["status"] == "buy" else "s_wait", sym=s, e=su["e"], st=su["s"], tg=su["t"]))
        return "\n".join(lines + ["", t("foot")])
    send(both(build))
    return len(rows)


def hourly(cfg):
    """Important news or a 3%+ move, each stock in its own message; silent when nothing is new."""
    tickers = cfg.get("stocks", sn.DEFAULT_STOCKS)
    d = sn.fetch(tickers, 3, remember=True)
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    state = json.load(open(sn.STATE_PATH)) if os.path.exists(sn.STATE_PATH) else {}
    today = datetime.now().strftime("%Y-%m-%d")
    sent = set(state.get(today, []))
    hot = {m["ticker"]: m for m in d.get("moves", [])
           if m.get("moving") and m.get("time") and now - datetime.fromisoformat(m["time"]) < timedelta(hours=12)
           and f"{m['ticker']}|{m['time'][:10]}" not in sent}
    per = {}
    for it in sn.rank([i for i in d.get("items", []) if sn.IMPORTANT & set(i.get("tags", []))]):
        s = it["ticker"] if it["ticker"] in tickers else next((x for x in it.get("touches", []) if x in tickers), None)
        if s and len(per.setdefault(s, [])) < 2:
            per[s].append(it)
    # a breakout BUY on yesterday's close: send its trade card alone, once per stock per day
    for s in tickers:
        key = f"card|{s}|{today}"
        if key in sent or s in hot or s in per:
            continue  # a stock with news/moves gets its card inside stock_message below
        try:
            su = stock_signal.setup(s)
            if su and su["status"] == "buy":
                look, en, ar = STOCK_LOOK.get(s, ("📈", s, s))
                send(stock_signal.card(s, ar, en, cfg))
                sent.add(key)
        except Exception as e:
            ga.log(f"flow: card check {s} failed: {e}")
    json.dump({today: sorted(sent | {f"{m['ticker']}|{m['time'][:10]}" for m in hot.values()})},
              open(sn.STATE_PATH, "w"))
    names = sorted(set(per) | set(hot))
    if not names:
        return 0
    flat = [it for s in names for it in per.get(s, [])]
    both_lines = item_lines(flat)
    pos = 0
    for s in names:
        k = len(per.get(s, []))
        items = {L: both_lines[L][pos:pos + k] for L in both_lines}
        pos += k
        try:
            stock_message(s, hot.get(s), items)
        except Exception as e:
            ga.log(f"flow: hourly {s} failed: {e}")
    return len(names)


def main():
    global LANG, SEND
    args = sys.argv[1:]
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    LANG = cfg.get("lang", "en")
    forced = "--lang" in args
    if forced:
        i = args.index("--lang")
        LANG = args[i + 1]
        del args[i:i + 2]
    global BI
    BI = not forced
    set_lang(LANG)
    mode = args[0] if args else "all"
    SEND = mode != "test"
    if mode == "hourly":
        hourly(cfg)
        return
    from datetime import datetime
    n = len(cfg.get("stocks", sn.DEFAULT_STOCKS))
    if mode in ("all", "test", "gold"):
        gold(cfg)
    if mode in ("all", "test", "stocks"):
        n = stocks(cfg)


if __name__ == "__main__":
    main()
