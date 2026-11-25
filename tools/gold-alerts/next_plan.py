"""@@ after every close (user, 2026-11-24: "send @@ always after closing"): the gold plan for the NEXT session,
posted to t.me/java_recomm right after the daily close summary.

The plan comes from the tested hourly gold system (trade_alert.py v2: 189 trades in 2 years, +0.24R after fees),
because the 5-minute bots only work live inside New York hours. It is a PENDING order: it becomes a live call only
if the price reaches the entry, and it expires at the next gold session's close (01:00 Istanbul). The tracker
follows it like any call (filled / TP / SL / close replies under the card). A live bot call on gold replaces it.

  python3 next_plan.py test   # print it, send nothing
  python3 next_plan.py send
"""
import json
import os
import sys
import time

import gold_alerts as ga
import recom
import recom_track
import trade_alert

HERE = os.path.dirname(os.path.abspath(__file__))


def build():
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    trade_alert.build(cfg)
    p = trade_alert.LAST_PLAN
    if not p or p.get("entry") is None or p.get("status") == "open":
        return None, None
    plan = recom.levels(p["side"], p["entry"], p["stop"])  # TP1/TP2/TP3 = 1R/2R/3R; the tested exit is TP3
    end = recom_track.market_close("GC=F", time.time() + 2 * 3600)  # the NEXT gold session's close
    plan.update({"win_at": 3, "close_by": end, "close_why": "market"})
    head = "📋 خطة الجلسة القادمة · Next session plan\n⏳ أمر معلّق Pending order · يُفعَّل عند الدخول / activates at the entry\n\n"
    return plan, head + recom_track.card_text(plan, "XAUUSD", True)


def send():
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    # hunter_only does not block the plan: it comes from the tested hourly v2 system (189 trades, +0.24R), and the user
    # wants the expectation after every close (2026-11-25: "no summary, no expectations").
    plan, text = build()
    if not plan:
        return print("no plan for the next session")
    chan = ga.load_env(ga.ENV_PATH).get("TELEGRAM_RECOM_ID")
    for k, t in recom_track.load(recom_track.OPEN, {}).items():  # one plan at a time: replace yesterday's
        if t.get("kind") == "plan":
            with recom_track.lock():
                o = recom_track.load(recom_track.OPEN, {})
                o.pop(k, None)
                json.dump(o, open(recom_track.OPEN, "w"), indent=1)
    import urllib.request  # noqa: F401
    msg = None
    try:
        r = json.loads(__import__("urllib.request").request.urlopen(
            __import__("urllib.request").request.Request(
                f"https://api.telegram.org/bot{ga.load_env(ga.ENV_PATH)['TELEGRAM_BOT_TOKEN']}/sendMessage",
                __import__("urllib.parse").parse.urlencode({"chat_id": chan, "text": text}).encode()), timeout=20).read())
        msg = r["result"]["message_id"]
    except Exception as e:
        ga.log(f"next plan post failed: {e}")
        return
    recom_track.add({"key": f"GOLDPLAN|{round(plan['entry'])}|{int(time.time())}", "plan": plan,
                     "valid_ts": plan["close_by"], "msg": msg, "kind": "plan", "win_at": 3})
    ga.log(f"next session plan posted: {plan['side']} {plan['entry']:.1f}")
    return text


if __name__ == "__main__":
    if (sys.argv[1:] or ["test"])[0] == "send":
        print(send())
    else:
        print(build()[1] or "no plan for the next session")
