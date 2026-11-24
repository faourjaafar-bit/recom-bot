"""Company stock news on Telegram: a daily digest and hourly alerts for important chances.

  python3 stock_news.py daily    # morning digest: biggest movers + top headlines (24h), always sends
  python3 stock_news.py hourly   # sends only on something new: important news or a big move
  python3 stock_news.py test     # prints the daily digest without sending
  add --lang en|ar to override the language (default: "lang" in config.json)

Reads headlines and moves through the trader-news skill (Yahoo Finance RSS, free, no keys).
The watchlist is "stocks" in config.json. Important = earnings, analyst, deal, halt, regulatory,
legal or risk news, or a move of MOVE_PCT% or more from yesterday's close.
Each mover gets a candle read (candle_read.py): the candle in context, what is expected, what the rules say.
Information only. A headline or a move is a reason to look, not a trade.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import gold_alerts as ga

HERE = os.path.dirname(os.path.abspath(__file__))
NEWS_PY = os.path.expanduser("~/.claude/skills/trader-news/news.py")
NEWS_STATE = os.path.join(HERE, "cache", "stock_news_seen.json")  # trader-news dedupe (hourly only)
STATE_PATH = os.path.join(HERE, "stock_state.json")                # moves already alerted today
DEFAULT_STOCKS = ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "AMD", "TSM",
                  "PLTR", "NFLX", "JPM", "V", "LLY", "XOM"]
IMPORTANT = {"earnings", "analyst", "deal", "halt", "regulatory", "legal", "risk"}
MOVE_PCT = 3.0
SEP = "━" * 12
LANG = "en"

T = {
    "en": {
        "d_title": "STOCK NEWS · DAILY {d}",
        "gold": "GOLD (futures, USD/oz)",
        "movers": "BIGGEST MOVES (last session vs previous close)",
        "news": "TOP HEADLINES (24h)",
        "no_news": "No headlines in the last 24 hours.",
        "h_title": "STOCK ALERT · {t}",
        "h_move": "{icon} {sym} {pct:+.1f}% at ${px:,.2f}: a big move. Check the news before acting.",
        "disclaimer": "News and moves are a reason to look, not a trade. Not financial advice. You decide.",
        "tags": {"earnings": "earnings", "analyst": "analyst", "deal": "deal", "halt": "halt",
                 "regulatory": "regulator", "legal": "legal", "risk": "risk", "capital": "capital",
                 "people": "management", "macro": "macro"},
    },
    "ar": {
        "d_title": "أخبار الأسهم · الموجز اليومي {d}",
        "gold": "الذهب (العقود الآجلة، دولار للأونصة)",
        "movers": "أكبر التحركات (آخر جلسة مقارنة بالإغلاق السابق)",
        "news": "أهم العناوين (24 ساعة)",
        "no_news": "لا عناوين خلال آخر 24 ساعة.",
        "h_title": "تنبيه أسهم · {t}",
        "h_move": "{icon} {sym} {pct:+.1f}% عند ${px:,.2f}: تحرك كبير. راجع الخبر قبل أي قرار.",
        "disclaimer": "الخبر والتحرك سبب للنظر، وليس صفقة. ليست نصيحة مالية. القرار لك.",
        "tags": {"earnings": "نتائج", "analyst": "محللون", "deal": "صفقة", "halt": "إيقاف تداول",
                 "regulatory": "جهة رقابية", "legal": "قضائي", "risk": "مخاطر", "capital": "تمويل",
                 "people": "إدارة", "macro": "اقتصاد كلي"},
    },
}


def t(key, **kw):
    s = T[LANG][key]
    return s.format(**kw) if kw else s


def fetch(tickers, hours, remember):
    """Run trader-news; with remember=False it neither reads nor updates the hourly dedupe state."""
    os.makedirs(os.path.dirname(NEWS_STATE), exist_ok=True)
    state = NEWS_STATE if remember else os.path.join(HERE, "cache", "stock_news_daily.json")
    cmd = [sys.executable, NEWS_PY, "--tickers", *tickers, "--hours", str(hours), "--no-sec",
           "--move-pct", str(MOVE_PCT), "--state", state, "--json"]
    if not remember:
        cmd += ["--all", "--dry-run"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=HERE)
    try:
        return json.loads(r.stdout)
    except Exception:
        ga.log(f"stock_news: trader-news failed: {r.stderr[-300:]}")
        return {"moves": [], "items": []}


def rank(items):
    """Important tags first, then newest."""
    items = sorted(items, key=lambda it: it.get("time", ""), reverse=True)
    return sorted(items, key=lambda it: not IMPORTANT & set(it.get("tags", [])))


def lines_for(items):
    titles = [it["title"] for it in items]
    if LANG == "ar" and titles:
        ar = ga.translate(titles)
        titles = [a or h for h, a in zip(titles, ar)]
    out = []
    for it, title in zip(items, titles):
        tags = [T[LANG]["tags"].get(x, x) for x in it.get("tags", [])]
        star = "\U0001F525" if IMPORTANT & set(it.get("tags", [])) else "\U0001F539"
        who = ", ".join(it.get("touches") or [it["ticker"]])
        out.append(f"{star} {who}: {title}" + (f"  [{' · '.join(tags)}]" if tags else ""))
    return out


def candle(sym):
    """The candle read (candle_read.py) under a stock, or nothing if the data fails."""
    import candle_read as cr
    cr.LANG = LANG
    try:
        return "\n" + cr.card(cr.read(sym))
    except Exception as e:
        ga.log(f"stock_news: candle read {sym} failed: {e}")
        return ""


def move_line(m):
    icon = "\U0001F7E2" if m["pct"] > 0 else "\U0001F534"
    return t("h_move", icon=icon, sym=m["ticker"], pct=m["pct"], px=m["price"]) + candle(m["ticker"])


def daily(tickers):
    d = fetch(tickers, 24, remember=False)
    blocks = ["\U0001F4C8 " + t("d_title", d=datetime.now().strftime("%Y-%m-%d"))]
    gold = candle("GC=F")
    if gold:
        blocks += [SEP, "\U0001F947 " + t("gold") + gold]
    moves = sorted(d.get("moves", []), key=lambda m: abs(m["pct"]), reverse=True)[:5]
    if moves:
        blocks += [SEP, "⚡ " + t("movers")]
        blocks += [f"{ga.arrow(m['pct'])} {m['ticker']}  ${m['price']:,.2f}  ({m['pct']:+.1f}%)" + candle(m["ticker"])
                   for m in moves]
    blocks += [SEP, "\U0001F4F0 " + t("news")]
    items = rank(d.get("items", []))[:10]
    blocks += lines_for(items) if items else [t("no_news")]
    blocks += [SEP, "⚠️ " + t("disclaimer")]
    return "\n\n".join(blocks)


def hourly(tickers):
    """Only new important headlines and moves not alerted yet today."""
    d = fetch(tickers, 3, remember=True)
    state = json.load(open(STATE_PATH)) if os.path.exists(STATE_PATH) else {}
    today = datetime.now().strftime("%Y-%m-%d")
    sent = set(state.get(today, []))
    now = datetime.now(timezone.utc)
    moves = [m for m in d.get("moves", []) if m.get("moving") and m.get("time")  # live moves only, once
             and now - datetime.fromisoformat(m["time"]) < timedelta(hours=12)
             and f"{m['ticker']}|{m['time'][:10]}" not in sent]
    items = rank([it for it in d.get("items", []) if IMPORTANT & set(it.get("tags", []))])[:8]
    state = {today: sorted(sent | {f"{m['ticker']}|{m['time'][:10]}" for m in moves})}
    json.dump(state, open(STATE_PATH, "w"))
    if not moves and not items:
        return None
    blocks = ["\U0001F514 " + t("h_title", t=datetime.now().strftime("%H:%M"))]
    blocks += [move_line(m) for m in moves]
    blocks += lines_for(items)
    blocks += ["⚠️ " + t("disclaimer")]
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
    ga.LANG = LANG
    tickers = cfg.get("stocks", DEFAULT_STOCKS)
    mode = args[0] if args else "test"
    if mode == "hourly":
        msg = hourly(tickers)
        if msg:
            ga.telegram(msg)
        return
    msg = daily(tickers)
    if mode == "daily":
        ga.telegram(msg)
    else:
        print(msg)


if __name__ == "__main__":
    main()
