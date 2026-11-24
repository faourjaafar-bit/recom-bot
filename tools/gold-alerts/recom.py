"""Recommendations channel (t.me/java_recomm): ONE message per trade = a zoomed candle chart + a short caption.

  .venv/bin/python recom.py send        # post every actionable signal not posted yet (hourly job)
  .venv/bin/python recom.py test        # build the charts and captions, post nothing (PNG in cache/recom/)
  .venv/bin/python recom.py test --any  # also show waiting setups (pending levels), to preview the look
  .venv/bin/python recom.py preview     # send one sample (even a waiting setup) to the OWNER's chat only

Only tested signals, only when they are actionable:
  gold   : trade_alert.py v2 status "go" (place the limit order now): 189 trades, +0.24R after fees
  stocks : stock_signal.py status "buy" (daily close above the 20-day high in BULL/REBOUND): 2,021 trades, +0.22R
The chart marks Entry, Stop, T1 (1R), T2 (2R) and T3 (3R). T3 is the tested exit; T1 and T2 are checkpoints
(taking partial profit there lowered the tested result). Posted once per symbol and level; a gold order that expired or a closed market is not posted.
Runs with the .venv Python (matplotlib); needs the network outside the sandbox. Info only, not financial advice.
"""
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import gold_alerts as ga  # noqa: E402
import stock_signal  # noqa: E402
import trade_alert  # noqa: E402
import zone_plan as zp  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "cache", "recom")
STATE = os.path.join(HERE, "cache", "recom_sent.json")
BG, GRID, UP, DN = "#11141c", "#222735", "#26c281", "#ef5350"
COL = {"entry": "#4f8cff", "stop": "#ef5350", "t1": "#9be7c4", "t2": "#5fd4a0", "t3": "#26c281"}


def chart(bars, plan, title, path, n):
    """Zoomed candles: the last n bars, y-axis fitted to the candles AND every level, labels on the right."""
    b = bars[-n:]
    lv = [("ENTRY", plan["entry"], "entry"), ("STOP", plan["stop"], "stop"),
          ("T1 1R", plan["t1"], "t1"), ("T2 2R", plan["t2"], "t2"), ("T3 3R", plan["t3"], "t3")]
    lo = min([x["l"] for x in b] + [p for _, p, _ in lv])
    hi = max([x["h"] for x in b] + [p for _, p, _ in lv])
    pad = (hi - lo) * 0.06
    fig, ax = plt.subplots(figsize=(10, 5.6), dpi=110)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    w = 0.62
    for i, x in enumerate(b):
        c = UP if x["c"] >= x["o"] else DN
        ax.vlines(i, x["l"], x["h"], color=c, linewidth=1)
        ax.add_patch(plt.Rectangle((i - w / 2, min(x["o"], x["c"])), w, max(abs(x["c"] - x["o"]), (hi - lo) * 0.002),
                                   color=c))
    sell = plan["side"] == "sell"
    # shaded risk (entry to stop) and reward (entry to T3) zones
    xr = (len(b) + 1.2) / (len(b) + 10)  # shading stops where the labels start
    ax.axhspan(min(plan["entry"], plan["stop"]), max(plan["entry"], plan["stop"]), xmax=xr, color=DN, alpha=0.10)
    ax.axhspan(min(plan["entry"], plan["t3"]), max(plan["entry"], plan["t3"]), xmax=xr, color=UP, alpha=0.08)
    for name, p, k in lv:
        ax.hlines(p, -1, len(b) + 0.2, color=COL[k], linewidth=1.6 if k in ("entry", "stop", "t3") else 1.1,
                  linestyle="-" if k in ("entry", "stop", "t3") else "--")
        ax.text(len(b) + 0.5, p, f"{name}  {p:,.2f}", color=COL[k], va="center", fontsize=10.5, fontweight="bold")
    ax.set_xlim(-1, len(b) + 9)  # room on the right for the level labels
    ax.set_ylim(lo - pad, hi + pad)
    ax.grid(color=GRID, linewidth=0.6)
    ax.tick_params(colors="#9aa3b5", labelsize=9)
    for s in ax.spines.values():
        s.set_color(GRID)
    step = max(1, len(b) // 6)
    ax.set_xticks(range(0, len(b), step))
    ax.set_xticklabels([x["lab"] for x in b][::step])
    ax.set_title(title, color="white", fontsize=13, fontweight="bold", loc="left")
    ax.text(0.99, 0.97 if sell else 0.03, "SELL" if sell else "BUY", transform=ax.transAxes, ha="right",
            va="top" if sell else "bottom", fontsize=22, fontweight="bold", color=DN if sell else UP, alpha=0.9)
    fig.tight_layout()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.savefig(path, facecolor=BG)
    plt.close(fig)


def levels(side, e, s):
    r = abs(e - s)
    d = -1 if side == "sell" else 1
    return {"side": side, "entry": e, "stop": s, "t1": e + d * r, "t2": e + d * 2 * r, "t3": e + d * 3 * r}


def caption(name_ar, name_en, plan, *_):
    """The channel card (user's sample): side + symbol + entry zone, the 3 targets, the stop. No other info."""
    import recom_track
    return recom_track.card_text(plan, "XAUUSD" if "Gold" in name_en else name_en, plan["entry"] >= 1000)


def gold_signal(cfg, any_status):
    trade_alert.build(cfg)
    p = trade_alert.LAST_PLAN
    if not p or p.get("entry") is None or (p["status"] != "go" and not any_status):
        return None
    now = datetime.now(timezone.utc).timestamp()
    stale = (p.get("valid_ts") and p["valid_ts"] < now) or now - p["h1"][-1]["ts"] > 3 * 3600
    if p["status"] == "go" and stale and not any_status:
        return None
    plan = levels(p["side"], p["entry"], p["stop"])
    h1 = p["h1"]
    for x in h1:
        x["lab"] = datetime.fromtimestamp(x["ts"], timezone.utc).strftime("%d %H:%M")
    acc, rp = cfg.get("account", 3000), cfg.get("risk_pct", 1)
    m = acc * rp / 100
    oz = m / abs(plan["entry"] - plan["stop"])
    valid = datetime.fromtimestamp(p["valid_ts"], timezone.utc).strftime("%a %H:%M") if p.get("valid_ts") else "-"
    st_ar = {"go": "أمر محدد (Limit) الآن", "open": "صفقة مفتوحة", "wait": "انتظار: ينتظر إغلاق شمعة الساعة"}[p["status"]]
    st_en = {"go": "limit order now", "open": "trade already open", "wait": "waiting for the hourly close"}[p["status"]]
    return {"key": f"GOLD|{round(plan['entry'])}", "valid_ts": p.get("valid_ts"), "bars": h1, "n": 40, "plan": plan, "status": p["status"],
            "title": "GOLD (XAUUSD) · 1-hour",
            "caption": caption("الذهب 🥇 XAUUSD", "Gold XAUUSD", plan,
                               f"⏱️ {st_ar} · صالح حتى {valid} UTC · إغلاق خلال 48 ساعة",
                               f"⏱️ {st_en} · valid until {valid} UTC · close within 48h",
                               f"🧪 مُختبَرة: {trade_alert.TESTED['n']} صفقة، {trade_alert.TESTED['r']:+.2f}R بعد الرسوم",
                               f"🧪 Tested: {trade_alert.TESTED['n']} trades, {trade_alert.TESTED['r']:+.2f}R after fees",
                               f"📏 مخاطرة {rp:g}% = ${m:,.0f} ← {oz:.2f} أونصة",
                               f"📏 Risk {rp:g}% = ${m:,.0f} → {oz:.2f} oz")}


def stock_signals(cfg, any_status):
    out = []
    for sym in cfg.get("stocks", []):
        try:
            su = stock_signal.setup(sym)
        except Exception as e:
            ga.log(f"recom {sym} failed: {e}")
            continue
        if not su or (su["status"] != "buy" and not any_status):
            continue
        plan = levels("buy", su["e"], su["s"])
        bars = [b for b in zp.yahoo_bars(sym, "6mo", "1d")]
        for x in bars:
            x["lab"] = x["d"][5:]
        acc, rp = cfg.get("account", 3000), cfg.get("risk_pct", 1)
        m = acc * rp / 100
        q = m / abs(plan["entry"] - plan["stop"])
        tested = stock_signal.TESTED
        out.append({"key": f"{sym}|{round(plan['entry'], 2)}", "bars": bars, "n": 45, "plan": plan,
                    "status": su["status"], "title": f"{sym} · daily",
                    "caption": caption(sym, sym, plan,
                                       "⏱️ إغلاق يومي فوق قمة 20 يوماً · احتفاظ حتى 20 يوم تداول"
                                       if su["status"] == "buy" else f"⏳ انتظار إغلاق يومي فوق {plan['entry']:,.2f}",
                                       "⏱️ daily close above the 20-day high · hold up to 20 trading days"
                                       if su["status"] == "buy" else f"⏳ waiting for a daily close above {plan['entry']:,.2f}",
                                       f"🧪 مُختبَرة: {tested['n']} صفقة على 16 سهماً، {tested['r']:+.2f}R",
                                       f"🧪 Tested: {tested['n']} trades on 16 stocks, {tested['r']:+.2f}R",
                                       f"📏 مخاطرة {rp:g}% = ${m:,.0f} ← {q:.2f} سهم",
                                       f"📏 Risk {rp:g}% = ${m:,.0f} → {q:.2f} shares")})
    return out


NEWS_Q = {"GOLD": "gold price OR XAUUSD OR Federal Reserve", "OIL": "crude oil price OR WTI OR OPEC"}


def research(sym, side):
    """News check before posting: last-2-day Google News headlines, judged by FreeLLMAPI (OmniRoute as backup).
    Returns {"verdict": support|neutral|against, "ar", "en"} or None when no free model answered (then nothing is posted)."""
    q = NEWS_Q.get(sym, f"{sym} stock")
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:2d") + "&hl=en-US&gl=US&ceid=US:en"
    try:
        heads = [(it.findtext("title") or "").strip() for it in ET.fromstring(ga.get(url, tries=2)).iter("item")][:15]
    except Exception as e:
        ga.log(f"recom news {sym} failed: {e}")
        heads = []
    prompt = (f"You check a trade before it is posted. Asset: {sym}. Planned trade: {side.upper()}.\n"
              "Headlines from the last 2 days:\n" + ("\n".join("- " + h for h in heads) or "- (none found)") +
              "\n\nDo the news, market mood and upcoming events support this trade, leave it neutral, or go against it "
              "(for example a scheduled event or a strong story pushing the other way)? Judge only from these headlines. "
              'Answer with JSON only: {"verdict": "support|neutral|against", '
              '"en": "one short reason, max 110 characters", "ar": "the same reason in Arabic, max 110 characters"}')
    routers = [("http://127.0.0.1:31415", ga.load_env(ga.ENV_PATH).get("FREELLM_KEY") or ga._key("FREELLMAPI_API_KEY")),
               ("http://127.0.0.1:20128", ga._key("OMNIROUTE_API_KEY"))]
    skip = os.path.join(HERE, "cache", "freellm_401.json")  # a rejected key: skip FreeLLMAPI for 6 hours
    try:
        bad_since = json.load(open(skip)).get("t", 0)
    except Exception:
        bad_since = 0
    for base, key in routers:
        if not key or ("31415" in base and time.time() - bad_since < 6 * 3600):
            continue
        try:
            req = urllib.request.Request(
                base + "/v1/chat/completions",
                json.dumps({"model": "auto", "messages": [{"role": "user", "content": prompt}]}).encode(),
                {"Content-Type": "application/json", "Authorization": "Bearer " + key})
            with urllib.request.urlopen(req, timeout=90) as r:
                txt = json.loads(r.read())["choices"][0]["message"]["content"]
            raw = re.search(r"\{.*\}", txt, re.S).group(0)
            try:
                v = json.loads(raw)
            except ValueError:  # a model wrote broken JSON (often unescaped quotes in Arabic): read the fields one by one
                grab = lambda k: (re.search(r'"%s"\s*:\s*"(.*?)"\s*[,}]' % k, raw, re.S) or [None, ""])[1]
                v = {"verdict": grab("verdict").strip().lower(), "en": grab("en"), "ar": grab("ar")}
            if v.get("verdict") in ("support", "neutral", "against"):
                v["n"] = len(heads)
                return v
        except Exception as e:
            if "31415" in base and "401" in str(e):
                json.dump({"t": time.time()}, open(skip, "w"))
            ga.log(f"recom research {sym} via {base} failed: {e}")
    return None


def send_photo(chat, path, text):
    env = ga.load_env(ga.ENV_PATH)
    token = env["TELEGRAM_BOT_TOKEN"]
    bd = uuid.uuid4().hex
    body = io.BytesIO()
    for k, v in (("chat_id", str(chat)), ("caption", text)):
        body.write(f"--{bd}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    body.write(f"--{bd}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"chart.png\"\r\n"
               f"Content-Type: image/png\r\n\r\n".encode())
    body.write(open(path, "rb").read())
    body.write(f"\r\n--{bd}--\r\n".encode())
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendPhoto", body.getvalue(),
                                 {"Content-Type": f"multipart/form-data; boundary={bd}"})
    r = json.loads(urllib.request.urlopen(req, timeout=60).read())
    return r["result"]["message_id"] if r.get("ok") else None  # the id: TP / SL results reply to this post


def main():
    args = sys.argv[1:]
    mode = args[0] if args else "test"
    any_status = "--any" in args or mode == "preview"
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    if mode == "send" and cfg.get("hunter_only"):  # user, 2026-11-24: only the tested Hunter bots post calls
        return print("recom: hunter_only is on in config.json, the v2/stock signals are not posted")
    ga.LANG = zp.LANG = "ar"
    sigs = []
    try:
        g = gold_signal(cfg, any_status)
        if g:
            sigs.append(g)
    except Exception as e:
        ga.log(f"recom gold failed: {e}")
    sigs += stock_signals(cfg, any_status)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sent = json.load(open(STATE)) if os.path.exists(STATE) else {}
    env = ga.load_env(ga.ENV_PATH)
    chan = env.get("TELEGRAM_RECOM_ID")
    for i, s in enumerate(sigs):
        path = os.path.join(OUT, s["key"].replace("|", "_") + ".png")
        chart(s["bars"], s["plan"], s["title"], path, s["n"])
        if s["key"] in sent and mode == "send":
            continue
        import recom_track
        ysym = {"GOLD": "GC=F"}.get(s["key"].split("|")[0], s["key"].split("|")[0])
        if mode == "send" and any(t["sym"] == ysym for t in recom_track.load(recom_track.OPEN, {}).values()):
            print("skipped", s["key"], "(a call on this market is already open in java_recomm)")
            continue  # one open call per market: never post a clashing tested signal next to it
        sym = s["key"].split("|")[0]
        v = research(sym, s["plan"]["side"])  # FreeLLMAPI news check: no answer or "against" = not posted
        if not v:
            ga.log(f"recom {s['key']} held: no free model answered the news check")
            print("held", s["key"], "(FreeLLMAPI / OmniRoute did not answer; open the FreeLLMAPI app)")
            continue
        if v["verdict"] == "against":
            ga.log(f"recom {s['key']} blocked by news: {v.get('en')}")
            print("blocked by news", s["key"], "-", v.get("en"))
            if mode == "send":
                continue
        if mode == "send" and s["status"] in ("go", "buy") and s["key"] not in sent and chan:
            ok = send_photo(chan, path, s["caption"])
            ga.log(f"recom sent {s['key']} ok={ok}")
            sent[s["key"]] = day  # once per symbol and level, not once per day
            if ok:
                try:  # followed every 30 minutes by recom_track.py (inside pulse.py)
                    import recom_track
                    recom_track.add(dict(s, msg=ok))
                except Exception as e:
                    ga.log(f"recom track add {s['key']} failed: {e}")
            print("posted", s["key"], ok)
        elif mode == "preview" and i == 0:  # the look, to the owner's private chat only
            print("preview to owner:", send_photo(env["TELEGRAM_CHAT_ID"], path, "👀 PREVIEW / معاينة\n" + s["caption"]))
        else:
            print(f"[{s['status']}] {s['key']} -> {path}\n{s['caption']}\n")
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    keep = sorted(sent.items(), key=lambda kv: kv[1])[-200:]
    json.dump(dict(keep), open(STATE, "w"))
    if not sigs:
        print("no actionable recommendation right now")


if __name__ == "__main__":
    main()
