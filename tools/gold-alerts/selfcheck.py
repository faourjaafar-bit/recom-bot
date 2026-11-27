"""Regression checks for every mistake the user has caught (memory: trading-critiques-never-repeat). Offline: no
network, no Telegram. Run after any change; recom_track watch runs it once a day and tells the owner if one fails.

  python3 selfcheck.py
"""
import sys
import time

import recom_track as rt


def trade(side="sell", entry=3615.6, risk=12.0):
    d = 1 if side == "buy" else -1
    return {"sym": "GC=F", "gold": True, "side": side, "entry": entry, "stop": entry - d * risk,
            "t1": entry + d * 4, "t2": entry + d * 8, "t3": entry + d * 12, "win_at": 1, "posted": 1000,
            "filled": 1000, "status": "open", "passed": 0, "hold": 10 ** 9}


def bars(prices):
    return [{"ts": 1000 + 60 * i, "o": p, "h": p + 0.2, "l": p - 0.2, "c": p} for i, p in enumerate(prices)]


def check():
    fails = []

    def ok(cond, rule):
        if not cond:
            fails.append(rule)

    # 1. follow every call to TP3 (user, 2026-11-24); 2026-11-27 rebuild: gold HOLDS to TP3 with the stop unchanged,
    # oil moves the stop to TP1 after TP2; Market Makers relays keep stop-to-entry after TP1
    t = trade()
    rt.step(t, bars([3615, 3611.5]))
    ok(t["status"] == "open" and t["passed"] == 1, "1: call closed at TP1 (must follow to TP3)")
    msgs = rt.short(t, ("open", 0))
    ok(any("TP²" in m for m in msgs) and any("TP³" in m for m in msgs), "1: gold TP1 reply must name TP² and say it holds for TP³")
    rt.step(t, bars([3615, 3611.5, 3607.5, 3603.5]))
    ok(t["status"] == "win" and t["passed"] == 3, "1: TP3 not reached / not reported")
    ok(abs(rt.realized_r(t, t["exit"]) - 1.0) < 0.01, "1: gold held to TP3 must book the full tested R (+1R here)")
    t = trade()
    rt.step(t, bars([3615, 3611.5, 3616]))
    ok(t["status"] == "open", "1: gold must NOT exit at entry after TP1 (hold to TP3, stop unchanged)")
    ok(not any("Congrats" in m or "مبروك" in m for m in rt.short(dict(trade(), passed=1), ("open", 0))),
       "16: no Congrats at TP1 while the full stop is still live (hold): a stop-loss message can follow it")
    ok(any("Congrats" in m for m in rt.short(dict(trade(), passed=3, status="win", exit=3603.6), ("open", 2))),
       "16: the last target must still say Congrats")
    t = dict(trade(), manage="be")  # posted under stop-to-entry: a later rule change must not touch it
    rt.step(t, bars([3615, 3611.5, 3616]))
    ok(t["status"] == "win" and t.get("be"), "16: an open call must keep the rule it was posted with")
    t = trade()
    t["kind"] = "relay"
    rt.step(t, bars([3615, 3611.5, 3616]))
    ok(t["status"] == "win" and t.get("be"), "1: a Market Makers relay keeps stop-to-entry after TP1")
    t = dict(trade("buy", 80.0, 0.5), sym="CL=F", gold=False, t1=80.2, t2=80.4, t3=80.9)
    rt.step(t, bars([80.0, 80.35, 80.1]))
    ok(t["status"] == "win" and t.get("locked") and t["exit"] == 80.2, "1: oil after TP2 must lock profit at TP1")
    t = trade()
    rt.step(t, bars([3615, 3628]))
    ok(t["status"] == "loss", "1: stop before any target must be a loss")
    # 1b. the watcher calls step() every minute on the growing bar list: a bar from BEFORE TP1 that dipped below the
    # entry must not be re-read as a breakeven exit once the stop sits at the entry (2026-11-27: BUY 3640.77)
    t = trade("buy", 3640.8)
    seq = [3640.0, 3640.8, 3645.0]
    rt.step(t, bars(seq))
    rt.step(t, bars(seq + [3646.0]))
    rt.step(t, bars(seq + [3646.0, 3649.0]))
    ok(t["status"] == "open" and t["passed"] == 2, "1: re-walked pre-TP1 bar booked a fake exit")
    # 3. noise headlines never count
    import news_rt
    ok(news_rt.score("Gold prices in Pakistan climb for a second consecutive day") == {}, "3: local price noise scored")
    ok(news_rt.score("The New York Fed's John Williams Won't Rule Out Back-to-Back Rate Hikes").get("GC=F", 0) <= -2,
       "2: back-to-back hike headline must be strongly against gold")
    # 2. data surprise direction: a US beat is bad for gold
    import news_agent
    news_agent.calendar = lambda *a, **k: [{"title": "CB Consumer Confidence", "actual": 103.3, "forecast": 92.5,
                                            "importance": 0, "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 300))}]
    s = news_agent.surprises("GC=F")
    ok(s and s[0][0] < 0, "2: a US data beat must count against gold")
    ok(news_agent.release_near(time.time()) is not None, "2: release window not detected")
    # 6. arrows
    import gold_alerts as ga
    if hasattr(ga, "arrow"):
        ok("🟢" in ga.arrow(1) and "🔴" in ga.arrow(-1), "6: rise must be 🟢▲, fall 🔴▼")
    return fails


if __name__ == "__main__":
    f = check()
    print("selfcheck:", "ALL PASS" if not f else "FAILED:\n  " + "\n  ".join(f))
    sys.exit(1 if f else 0)
