"""Live 30-call trial of Market Makers (@mmsignalsfx), the only channel that passed the backtest (2026-11-24 council:
"demo only, after a live trial"). Nothing goes to java_recomm: every new call they post is recorded and scored on
live prices with the same rules as channel_eval.simulate; the owner's bot chat gets one line per new call and per
result, and the verdict once 30 calls are scored (gate: average above +0.05R).

  python3 channel_track.py          # check now (recom_track watch runs it every 5 minutes)
  python3 channel_track.py status   # the trial so far
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

import channel_eval as ce
import gold_alerts as ga
import recom_track

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "cache", "channels", "trial_mmsignalsfx.json")
NAME, GOAL, GATE = "mmsignalsfx", 30, 0.05
# every channel on a live 30-call trial -> its display name. Only NAME is relayed to java_recomm (through relay());
# the others are scored only (user, 2026-11-25: "add to trial" for XAUUSD_Signals, backtest +0.08R over 39 calls)
TRIALS = {"mmsignalsfx": "Market Makers", "XAUUSD_Signals": "XAUUSD_Signals"}


def trial_file(name):
    return os.path.join(HERE, "cache", "channels", f"trial_{name.lower()}.json")
NEED = 4  # checks out of 7 a source call must pass to be posted (user, 2026-11-24)
FINAL = ("win", "loss", "be", "timeout", "not filled")


def notify(text):
    e = ga.load_env(ga.ENV_PATH)
    data = urllib.parse.urlencode({"chat_id": e["TELEGRAM_CHAT_ID"], "text": text}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{e['TELEGRAM_BOT_TOKEN']}/sendMessage", data, timeout=20)
    except Exception as ex:
        ga.log(f"channel_track notify failed: {ex}")


def spot_bars():
    """Gold 1-min futures bars shifted to spot by the live basis (futures last close minus the TradingView spot)."""
    import live
    import zone_plan as zp
    bars = [x for x in zp.yahoo_bars("GC=F", "5d", "1m") if x["c"]]
    spot = (live.quote("OANDA:XAUUSD") or {}).get("close")
    s = bars[-1]["c"] - spot if spot and bars else 0
    return [{"ts": x["ts"], "o": x["o"] - s, "h": x["h"] - s, "l": x["l"] - s, "c": x["c"] - s} for x in bars]


def relay(c):
    """FILTER then post to java_recomm (user, 2026-11-24: "filter recommendations then drive them into our
    channel"). A Market Makers call is posted when at least NEED (4) of these 7 pass (user: "3 out of 7", then "let it be 4");
    the owner gets the score and each check either way:
      1 fresh      posted under 20 min ago, gold market open, live spot within 0.4% of our data
      2 no chase   live price still inside the zone or less than 0.3R past the entry, and not past TP1
      3 not busy   no open java_recomm call on gold
      4 desk       scout + flows + news do not lean against the side (> 0.5), no Risk veto (release window, stale)
      5 headline   no strong headline against the side in the last 30 min
      6 stop       their stop at least 0.8x the 5-min ATR (not inside the noise), TP1 at least 0.5R
      7 source     the channel's backtest is positive (channel_eval table)
    Posted with the same card, chart and live follow-up (TP1 -> TP3, stop to entry, emergency close) as our calls."""
    import desk
    import live
    import recom
    import recom_now
    from datetime import datetime, timezone
    sym, side, d = "GC=F", c["side"], (1 if c["side"] == "buy" else -1)
    risk = abs(c["entry"] - c["stop"])
    # each check: (passed, label). The user's rule (2026-11-24): NEED (4) of the 7 are enough to post. Only a call that can
    # no longer be traded (no live price, price already beyond the stop or already at TP1) is never posted.
    tab = recom_track.load(os.path.join(HERE, "cache", "channels", "table.json"), {}).get(NAME, {})
    spot = (live.quote("OANDA:XAUUSD") or {}).get("close")
    hard = []
    if not spot:
        hard.append("no live price")
    else:
        if (spot - c["t1"]) * d >= 0:
            hard.append("price already at TP1")
        if (spot - c["stop"]) * d <= 0:
            hard.append("price already beyond the stop")
    past = (c["entry"] - spot) * d if spot else 0  # >0: price already moved our way past the entry
    op = recom_track.load(recom_track.OPEN, {})
    dk = desk.decide(sym)
    w = desk.weights()
    others = sum(dk["votes"].get(k, 0) * w.get(k, 0) for k in ("scout", "flows", "news"))
    hl = desk.headline_against(sym, side)
    b = desk.bars(sym)
    tr = [max(x["h"], p["c"]) - min(x["l"], p["c"]) for p, x in zip(b[-15:-1], b[-14:])]
    atr = sum(tr) / len(tr) if tr else 0
    checks = [
        (time.time() - c["ts"] <= 20 * 60, "1 fresh (under 20 min)"),
        (past <= 0.3 * risk, f"2 no chasing ({past:+.1f} past entry)"),
        (not any(t["sym"] == sym and t.get("kind") != "plan" for t in op.values()), "3 no other gold call open"),
        (others * d >= -0.5 and not dk["veto"], f"4 desk agrees ({others:+.1f}" + (", veto: " + "; ".join(dk["veto"])[:80] if dk["veto"] else "") + ")"),
        (not hl, "5 no headline against" + (f" ({hl[:60]})" if hl else "")),
        ((not atr or risk >= 0.8 * atr) and abs(c["t1"] - c["entry"]) >= 0.5 * risk, f"6 stop outside the noise (${risk:.1f} vs ATR ${atr:.1f})"),
        ((tab.get("avg_r") or 0) > 0, "7 source backtest positive"),
    ]
    score = sum(ok for ok, _ in checks)
    lines = "\n".join(("✅ " if ok else "❌ ") + lab for ok, lab in checks)
    if hard or score < NEED:
        notify(f"📡 Market Makers {side.upper()} @{c['entry']:.1f} NOT posted: {score}/7"
               + (" · cannot be traded: " + ", ".join(hard) if hard else f" (needs {NEED})") + "\n" + lines)
        return None
    t2 = c.get("t2") or c["t1"] + d * risk
    plan = {"side": side, "entry": round(c["entry"], 2), "stop": c["stop"], "t1": c["t1"], "t2": t2,
            "t3": c.get("t3") or t2 + d * risk, "win_at": 3,
            "close_by": min(time.time() + 8 * 3600, recom_track.market_close(sym, time.time()))}
    h1 = list(zp_bars(sym))
    key = f"GOLDMM|{plan['entry']}|{datetime.now(timezone.utc):%m%d%H%M}"
    path = os.path.join(recom.OUT, "GOLDMM.png")
    recom.chart(h1, plan, "GOLD (XAUUSD) · 1-hour", path, 40)
    text = recom_track.card_text(plan, "XAUUSD", True, "🥇") + f"\n📡 المصدر Source: Market Makers · ✅ JAVA filter {score}/7"
    chan = ga.load_env(ga.ENV_PATH).get("TELEGRAM_RECOM_ID")
    ok = recom_now.send_card(chan, path, text)
    if ok:
        inside = abs(spot - c["entry"]) <= 0.15 * risk  # at the entry now: open; otherwise a pending order there
        recom_track.add({"key": key, "plan": plan, "market": inside, "hold": 8 * 3600, "kind": "relay", "msg": ok,
                         "win_at": 3, "ysym": sym, "valid_ts": time.time() + 4 * 3600, "size": dk.get("size", 1.0)})
        desk.log_call(key, dict(dk, side=side))
        notify(f"📡 Market Makers {side.upper()} @{plan['entry']} POSTED: {score}/7\n" + lines)
        ga.log(f"relay posted {key} ok={ok}")
    return ok


def zp_bars(sym):
    from datetime import datetime, timezone
    import zone_plan as zp
    for x in zp.yahoo_bars(sym, "1mo", "60m"):
        x["lab"] = datetime.fromtimestamp(x["ts"], timezone.utc).strftime("%d %H:%M")
        yield x


def score(calls):
    done = [c for c in calls if c.get("status") in ("win", "loss", "be", "timeout")]
    avg = sum(c["r"] for c in done) / len(done) if done else 0
    wins = sum(c["r"] > 0 for c in done)
    return done, avg, wins


def check_all():
    """Every trial channel; returns {name: state}."""
    out = {}
    for name in TRIALS:
        try:
            out[name] = check(name)
        except Exception as e:
            ga.log(f"channel_track {name} failed: {e}")
    return out


def check(name=NAME):
    label, FILE = TRIALS[name], trial_file(name)
    st = recom_track.load(FILE, {"started": time.time(), "calls": [], "last_id": None, "verdict": None})
    try:
        msgs = ce.page(name)
    except Exception as e:
        ga.log(f"channel_track page failed: {e}")
        msgs = []
    if st["last_id"] is None:  # first run: start from the newest post, only calls posted from now on count
        st["last_id"] = max((m["id"] for m in msgs), default=0)
    for m in sorted(msgs, key=lambda m: m["id"]):
        if m["id"] <= st["last_id"]:
            continue
        st["last_id"] = m["id"]
        c = ce.parse(name, m["text"])
        if c:
            c.update(id=m["id"], ts=m["ts"], status="new")
            st["calls"].append(c)
            tps = " / ".join(f"{c[k]:.1f}" for k in ("t1", "t2", "t3") if c.get(k))
            notify(f"📡 {label} #{len(st['calls'])}: {c['side'].upper()} gold @{c['entry']:.1f} "
                   f"SL {c['stop']:.1f} TP {tps}: " + ("checking it through the JAVA filter" if name == NAME else "trial only, not posted"))
            if name == NAME:
                try:  # the user wants the filtered calls in java_recomm now (2026-11-24); the trial score keeps running
                    c["relayed"] = bool(relay(c))
                except Exception as e:
                    ga.log(f"relay failed: {e}")
    live_calls = [c for c in st["calls"] if c["status"] not in FINAL]
    if live_calls:
        try:
            bars = spot_bars()
        except Exception as e:
            ga.log(f"channel_track bars failed: {e}")
            bars = []
        for c in live_calls:
            if not bars:
                break
            res = ce.simulate(c, bars)
            if res["status"] in FINAL:
                c.update(res)
                done, avg, wins = score(st["calls"])
                icon = "🟢▲" if c.get("r", 0) > 0 else "🔴▼" if c.get("r", 0) < 0 else "⚪"
                notify(f"📡 {label} #{st['calls'].index(c) + 1} {c['side'].upper()} @{c['entry']:.1f}: {res['status']}"
                       + (f" {icon} {c['r']:+.2f}R" if "r" in res else "")
                       + f"\nTrial {len(done)}/{GOAL}: {wins} wins, avg {avg:+.2f}R")
    done, avg, wins = score(st["calls"])
    if len(done) >= GOAL and not st["verdict"]:
        st["verdict"] = "PASS" if avg > GATE else "FAIL"
        notify(f"📡 {label} 30-call trial: {st['verdict']}\n{wins}/{len(done)} wins, avg {avg:+.2f}R (gate +{GATE}R)\n"
               + ("Ready to feed java_recomm as a credited source, with your OK." if st["verdict"] == "PASS" else "Not used."))
    json.dump(st, open(FILE, "w"), indent=1)
    return st


if __name__ == "__main__":
    if sys.argv[1:] == ["status"]:
        for name, label in TRIALS.items():
            st = recom_track.load(trial_file(name), {"calls": []})
            done, avg, wins = score(st["calls"])
            print(f"{label}: {len(st['calls'])} calls seen, {len(done)}/{GOAL} scored, {wins} wins, avg {avg:+.2f}R, verdict {st.get('verdict')}")
            for c in st["calls"][-10:]:
                print(" ", time.strftime("%d %H:%M", time.localtime(c["ts"])), c["side"], c["entry"], c["status"], c.get("r"))
    else:
        for name, st in check_all().items():
            print(f"tracking {TRIALS[name]}: {len(st['calls'])} calls, last post id {st['last_id']}")
