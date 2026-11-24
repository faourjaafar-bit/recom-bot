"""Market open / close alerts for t.me/java_recomm, so the channel always says why it is quiet (user, 2026-11-23:
"they must be alerted once the market is closed"). Checked every minute by recom_track.py watch; each alert once.

  US stocks (NVDA): open 09:30, close 16:00 New York, Monday to Friday.
  Gold and oil (CME): daily break 17:00-18:00 New York (Friday 17:00 = weekend close, Sunday 18:00 = reopen).
  JAVA bots cover the whole session (a tested bot for Asia, London and New York); open calls close at their market's close.
Times are shown in Istanbul time (UTC+3, no daylight saving); New York daylight saving is handled by the time zone.
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import gold_alerts as ga
import recom_track

HERE = os.path.dirname(os.path.abspath(__file__))
SENT = os.path.join(HERE, "cache", "market_events.json")
NY = ZoneInfo("America/New_York")
WINDOW = 5 * 60  # an event counts for 5 minutes after it happens


def ist(dt):
    return (dt.astimezone(timezone.utc) + timedelta(hours=3)).strftime("%a %H:%M")


def next_weekday(dt):
    while dt.weekday() >= 5:
        dt += timedelta(days=1)
    return dt


def events(now):
    """The events of the current New York day: [(key, epoch, text)]."""
    t = datetime.fromtimestamp(now, NY)
    d = t.replace(hour=0, minute=0, second=0, microsecond=0)
    wd = d.weekday()
    out = []
    if wd < 5:  # US stocks
        o, c = d.replace(hour=9, minute=30), d.replace(hour=16)
        nxt = next_weekday(d + timedelta(days=1)).replace(hour=9, minute=30)
        out.append((f"nvda_open|{d:%F}", o.timestamp(), "🟢 فتح السوق الأمريكي · US market OPEN\n🟩 NVDA"))
        out.append((f"nvda_close|{d:%F}", c.timestamp(),
                    f"🔔 أُغلق السوق الأمريكي · US market CLOSED\n🟩 NVDA · يفتح Reopens: {ist(nxt)} إسطنبول"))
    if wd < 5:  # gold / oil daily break or weekend close
        c = d.replace(hour=17)
        if wd == 4:
            txt = f"🔔 إغلاق نهاية الأسبوع · Weekend CLOSE\n🥇 Gold · 🛢️ Oil · يفتح Reopens: {ist(c + timedelta(days=2, hours=1))} إسطنبول"
        else:
            txt = f"🔔 استراحة يومية · Daily break\n🥇 Gold · 🛢️ Oil · يفتح Reopens: {ist(c + timedelta(hours=1))} إسطنبول"
        out.append((f"metals_close|{d:%F}", c.timestamp(), txt))
    if wd in (6, 0, 1, 2, 3):  # reopen after the break (Sunday = weekly open)
        o = d.replace(hour=18)
        out.append((f"metals_open|{d:%F}", o.timestamp(), "🟢 عاد التداول · Trading OPEN\n🥇 Gold · 🛢️ Oil"))
    return out


def check(send=True):
    now = time.time()
    sent = recom_track.load(SENT, {})
    due = [(k, t, txt) for k, t, txt in events(now) if t <= now < t + WINDOW and k not in sent]
    if not due or not send:
        return due
    chan = ga.load_env(ga.ENV_PATH).get("TELEGRAM_RECOM_ID")
    for k, _, txt in due:
        if k.startswith(("nvda_close", "metals_close")):  # open calls close when THEIR market closes (user, 2026-11-24)
            try:
                syms = ("NVDA",) if k.startswith("nvda") else ("GC=F", "CL=F")
                recom_track.close_all("أُغلقت مع إغلاق السوق", "closed at the market close", syms)
            except Exception as e:
                ga.log(f"close at market close failed: {e}")
        try:
            recom_track.post(chan, txt)
            sent[k] = now
            if k.startswith("nvda_close"):  # at the US close (00:00 Istanbul): the day's summary + the @@ plan (user, 2026-11-24)
                try:
                    import close_summary
                    close_summary.send()
                except Exception as e:
                    ga.log(f"close summary failed: {e}")
                try:  # @@ after every close: the tested plan for the next session (next_plan.py)
                    import next_plan
                    next_plan.send()
                except Exception as e:
                    ga.log(f"next plan failed: {e}")
            if k.startswith("metals_close"):  # after the last close of the day: the tool's day test, owner chat only
                try:
                    import subprocess
                    subprocess.run([sys.executable, os.path.join(HERE, "daytest.py"), "send"], timeout=120)
                except Exception as e:
                    ga.log(f"day test failed: {e}")
            ga.log("market event: " + txt.replace("\n", " | "))
        except Exception as e:
            ga.log(f"market event {k} failed: {e}")
    sent = {k: v for k, v in sent.items() if now - v < 8 * 86400}
    json.dump(sent, open(SENT, "w"))
    return due


if __name__ == "__main__":
    now = time.time()
    for k, t, txt in sorted(events(now), key=lambda x: x[1]):
        print(datetime.fromtimestamp(t, timezone.utc).strftime("%H:%M UTC"), k, "|", txt.replace("\n", " | "))
