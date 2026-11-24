"""Daily close summary for t.me/java_recomm: how the world moved gold today, and what to expect next session
(user, 2026-11-24: "once closed... a summary of how world changes affected gold, especially the AI comeback").

  python3 close_summary.py test   # print it, send nothing
  python3 close_summary.py send   # post it to java_recomm

Posted automatically by market_events.py at the US close (00:00 Istanbul, Mon-Fri), followed by the @@ plan.
Data: live TradingView day change for gold, the dollar, US 10-year yield, S&P 500, VIX, NVDA (the AI trade) and oil;
Google News headlines from the last day (gold, Fed, dollar, AI stocks); the event calendar. A free model (FreeLLMAPI,
then OmniRoute) writes the short read; if no model answers, a plain summary from the numbers is posted instead.
Info only, not financial advice.
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import gold_alerts as ga
import live
import recom_track
import regime

HERE = os.path.dirname(os.path.abspath(__file__))
QUOTES = {"gold": "OANDA:XAUUSD", "dollar": "TVC:DXY", "us10y": "TVC:US10Y", "sp500": "SP:SPX", "vix": "TVC:VIX",
          "nvda_ai": "NASDAQ:NVDA", "oil": "FX:USOIL"}
NEWS = ["gold price", "Federal Reserve rates", "US dollar", "AI stocks Nvidia rally"]


def headlines(n=6):
    out = []
    for q in NEWS:
        url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:1d") + "&hl=en-US&gl=US&ceid=US:en"
        try:
            items = ET.fromstring(ga.get(url, tries=2)).iter("item")
            out += [(q, (it.findtext("title") or "").strip()) for it in list(items)[:n]]
        except Exception as e:
            ga.log(f"close summary news '{q}' failed: {e}")
    return out


def llm(prompt):
    """FreeLLMAPI first (skipped for 6h after a rejected key), then OmniRoute. None when no model answers."""
    try:
        bad = json.load(open(os.path.join(HERE, "cache", "freellm_401.json"))).get("t", 0)
    except Exception:
        bad = 0
    env = ga.load_env(ga.ENV_PATH)
    for base, key in (("http://127.0.0.1:31415", env.get("FREELLM_KEY") or ga._key("FREELLMAPI_API_KEY")),
                      ("http://127.0.0.1:20128", ga._key("OMNIROUTE_API_KEY"))):
        if not key or ("31415" in base and time.time() - bad < 6 * 3600):
            continue
        try:
            req = urllib.request.Request(base + "/v1/chat/completions",
                                         json.dumps({"model": "auto", "messages": [{"role": "user", "content": prompt}]}).encode(),
                                         {"Content-Type": "application/json", "Authorization": "Bearer " + key})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())["choices"][0]["message"]["content"]
        except Exception as e:
            ga.log(f"close summary model via {base} failed: {e}")
    return None


def build():
    q = {k: live.quote(v) for k, v in QUOTES.items()}
    ch = {k: (v or {}).get("change") for k, v in q.items()}
    g = q.get("gold") or {}
    events = regime.upcoming("en", days=3)
    heads = headlines()
    facts = {k: f"{v:+.2f}%" for k, v in ch.items() if v is not None}
    prompt = (
        "You write the end-of-day gold summary for a Telegram trading channel. Use ONLY the facts and headlines below.\n"
        f"Gold today: close {g.get('close')}, high {g.get('high')}, low {g.get('low')}, change {facts.get('gold')}.\n"
        f"Other markets today: {json.dumps(facts)} (nvda_ai = the AI trade, Nvidia).\n"
        f"Upcoming events: {events}\n"
        "Headlines (last day):\n" + "\n".join(f"- [{t}] {h}" for t, h in heads[:24]) + "\n\n"
        "Explain in plain words how today's world changes moved gold, with a line on the AI / tech trade and whether it "
        "pulled money toward or away from gold, then what to watch next session (the key levels are today's high and "
        "low, plus the events). No advice to buy or sell. Answer with JSON only: "
        '{"ar": ["4 or 5 short lines in Arabic, each starting with an emoji"], "en": ["the same lines in English"]}')
    txt = llm(prompt)
    lines, plain = None, False
    if txt:
        try:
            v = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
            lines = (v["ar"][:5], v["en"][:5])
        except Exception:
            lines = None
    if not lines:  # no model: the plain numbers
        arrow = lambda x: "🟢▲" if (x or 0) > 0 else "🔴▼" if (x or 0) < 0 else "➖"
        en = [f"🥇 Gold {arrow(ch['gold'])} {facts.get('gold', '')} · high {g.get('high', 0):,.1f} · low {g.get('low', 0):,.1f}",
              f"💵 Dollar {facts.get('dollar', '')} · 🏦 US 10y {facts.get('us10y', '')}",
              f"🤖 AI trade (NVDA) {facts.get('nvda_ai', '')} · 📈 S&P {facts.get('sp500', '')} · 😨 VIX {facts.get('vix', '')}"]
        ar = [f"🥇 الذهب {arrow(ch['gold'])} {facts.get('gold', '')} · أعلى {g.get('high', 0):,.1f} · أدنى {g.get('low', 0):,.1f}",
              f"💵 الدولار {facts.get('dollar', '')} · 🏦 عائد السندات 10 سنوات {facts.get('us10y', '')}",
              f"🤖 صفقة الذكاء الاصطناعي (NVDA) {facts.get('nvda_ai', '')} · 📈 S&P {facts.get('sp500', '')} · 😨 VIX {facts.get('vix', '')}"]
        lines, plain = (ar, en), True  # bilingual even without a model
    hi, lo = g.get("high"), g.get("low")
    lv_ar = f"🎯 مستويات الجلسة القادمة: مقاومة {hi:,.1f} · دعم {lo:,.1f}" if hi and lo else ""
    lv_en = f"🎯 Next session levels: resistance {hi:,.1f} · support {lo:,.1f}" if hi and lo else ""
    ev_ar = regime.upcoming("ar", days=3)
    extra_ar = ([lv_ar] if lv_ar else []) + ev_ar[:2] if plain else []  # the model already covers levels + events
    extra_en = ([lv_en] if lv_en else []) + events[:2] if plain else []
    ar = "\n\n".join(["🌍🥇 ملخص إغلاق الذهب · كيف أثّر العالم على الذهب اليوم"] + lines[0] + extra_ar)
    en = "\n\n".join(["🌍🥇 Gold close summary · how the world moved gold today"] + lines[1] + extra_en)
    return ar + "\n\n━━━━━━━━━━━━\n\n" + en + "\n\n⚠️ للتعلّم، وليست نصيحة مالية / Not financial advice."


def send():
    text = build()
    chan = ga.load_env(ga.ENV_PATH).get("TELEGRAM_RECOM_ID")
    if len(text) > 4000:
        for part in text.split("\n\n━━━━━━━━━━━━\n\n"):
            recom_track.post(chan, part)
    else:
        recom_track.post(chan, text)
    ga.log("close summary posted")
    return text


if __name__ == "__main__":
    print(send() if (sys.argv[1:] or ["test"])[0] == "send" else build())
