"""@@ = a call RIGHT NOW for t.me/java_recomm: gold + the 2 strongest stock setups, each a chart + buy/sell card.

  .venv/bin/python recom_now.py send   # @@: GOLD + OIL, to java_recomm (add --stocks for 2 stock calls)
Runs by itself every 5 minutes (launchd com.jaafar.goldalerts.atat); it posts when a symbol has no open call and
its market is open. Open calls get a live price reply every 5 minutes from recom_track.watch().
  .venv/bin/python recom_now.py test   # build charts and captions, post nothing
  .venv/bin/python recom_now.py track  # only the live follow-up of the open calls, to java_recomm
Every "send" ends with the live follow-up of all open calls (recom_track.py).

Unlike recom.py (which waits for the tested signals), this always gives a direction, from a vote:
  gold  : daily trend (50/200-day) + intraday momentum (30-min, session VWAP) + RSI stretch + FreeLLMAPI news
  stocks: daily trend + 5-day momentum + RSI stretch, best scores first; news "against" = skipped, 2 are posted
Entry at the market price, stop 1.5 x ATR (gold 1-hour, stocks daily, capped at 5%), targets 1R / 2R / 3R.
Gold is held up to 24 hours, stocks up to 10 days. These calls are analysis, NOT a tested strategy, and every
card says so with its confidence (how many of the votes agree). Info only, not financial advice.
"""
import json
import os
import sys
from datetime import datetime, timezone

import candle_read as cr
import gold_alerts as ga
import pulse
import recom
import recom_track
import zone_plan as zp

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = {"ar": {3: "عالية", 2: "متوسطة", 1: "منخفضة", 0: "منخفضة"}, "en": {3: "high", 2: "medium", 1: "low", 0: "low"}}


def atr(bars, n=14):
    tr = [max(x["h"], p["c"]) - min(x["l"], p["c"]) for p, x in zip(bars[-n - 1:-1], bars[-n:])]
    return sum(tr) / len(tr)


SCALP = {"GC=F": 5.0, "CL=F": 0.5}  # 50 pips: gold 1 pip = $0.10, oil $0.01
COMMOD = {"GC=F": ("GOLD", "XAUUSD", "🥇"), "CL=F": ("OIL", "USOIL", "🛢️"), "NVDA": ("NVDA", "NVDA", "🟩🧠🎮")}  # @@ = gold + oil (user, 2026-11-23)


def gold_call(sym="GC=F"):
    """Gold or oil call from the DESK (desk.py: 2 agents, the Hunter votes and Risk vetoes).
    Returns None when the desk says no call (not enough agreement, or Risk vetoed)."""
    import desk
    dk = desk.decide(sym)
    if not dk["side"]:
        print(f"{sym}: desk says NO CALL, score {dk['score']}, veto: {dk['veto'] or 'none'}")
        return None
    side, px = dk["side"], dk["px"]
    d = 1 if side == "buy" else -1
    # never post an entry that is not the live price (2026-11-25: two NVDA sells at yesterday's 155.38 close while
    # NVDA traded near 142 were booked as instant wins)
    import live
    tv = desk.TV_BARS.get(sym) or live.tv_symbol(sym)
    q = live.quote(tv) if tv else None
    if not q or abs(px - q["close"]) / q["close"] > 0.004:
        print(f"{sym}: NO CALL, entry {px} is not the live price {q and q['close']}")
        ga.log(f"recom_now {sym} stale entry {px} vs live {q and q.get('close')}: no call")
        return None
    import live_recom
    import breed
    plan = breed.plan(sym, side, px, live_recom.stop_dist(sym, desk.bars(sym)))  # the live bot's stop + tested target
    h1 = [x for x in zp.yahoo_bars(sym, "1mo", "60m")]
    for x in h1:
        x["lab"] = datetime.fromtimestamp(x["ts"], timezone.utc).strftime("%d %H:%M")
    tag, name, icon = COMMOD[sym]
    return {"key": f"{tag}NOW|{round(px, 2)}|{datetime.now(timezone.utc):%m%d%H%M}", "sym": sym, "bars": h1, "n": 40,
            "plan": plan, "agree": abs(round(dk["score"])), "desk": dk, "size": dk.get("size", 1.0), "hold": 4 * 3600,
            "names": (name, name), "title": f"{tag} ({name}) · 1-hour", "icon": icon, "label": name,
            "horizon": ("خلال 4 ساعات", "within 4 hours"), "gold": sym == "GC=F"}


def look(sym):
    import flow
    return flow.STOCK_LOOK.get(sym, ("📈",))[0]


def names(sym):
    import flow
    _, en, ar = flow.STOCK_LOOK.get(sym, ("📈", sym, sym))
    return (f"{ar} ({sym})", f"{en} ({sym})")


def stock_calls(cfg):
    rows = []
    for sym in cfg.get("stocks", []):
        try:
            a = cr.read(sym)
            bars = zp.yahoo_bars(sym, "6mo", "1d")
        except Exception as e:
            ga.log(f"recom_now {sym} failed: {e}")
            continue
        if len(bars) < 30:
            continue
        mom = (bars[-1]["c"] - bars[-6]["c"]) / bars[-6]["c"]
        votes = {"daily": {"UP": 1, "DOWN": -1}.get(a["trend"], 0), "mom": 1 if mom > 0.01 else -1 if mom < -0.01 else 0,
                 "rsi": 1 if a["rsi"] < 30 else -1 if a["rsi"] > 70 else 0}
        score = sum(votes.values())
        if score == 0:
            continue
        rows.append((abs(score), abs(mom), sym, a, bars, votes, mom))
    rows.sort(reverse=True)
    out = []
    for _, _, sym, a, bars, votes, mom in rows:
        side = "buy" if sum(votes.values()) > 0 else "sell"
        d = 1 if side == "buy" else -1
        px = bars[-1]["c"]
        plan = recom.levels(side, px, px - d * min(1.5 * atr(bars), 0.05 * px))  # stop at most 5% away
        for x in bars:
            x["lab"] = x["d"][5:]
        out.append({"key": f"{sym}NOW|{round(px, 2)}|{datetime.now(timezone.utc):%m%d}", "sym": sym, "bars": bars,
                    "n": 45, "plan": plan, "agree": sum(1 for v in votes.values() if v == d),
                    "why": (f"الاتجاه {'صاعد' if votes['daily'] > 0 else 'هابط' if votes['daily'] < 0 else 'مختلط'}"
                            f" · 5 أيام {100 * mom:+.1f}% · RSI {a['rsi']:.0f}",
                            f"trend {a['trend'].lower()} · 5 days {100 * mom:+.1f}% · RSI {a['rsi']:.0f}"),
                    "hold": 10 * 86400, "names": names(sym), "look": look(sym), "title": f"{sym} · daily",
                    "horizon": ("خلال 10 أيام", "within 10 days"), "gold": False})
    return out


def card(c, news=None):
    """The channel card (user's sample): side + symbol + entry zone, the 3 targets, the stop. No other info."""
    return recom_track.card_text(c["plan"], c.get("label") or c["sym"], c["gold"], c.get("icon"))


def send_card(chan, path, text):
    return recom.send_photo(chan, path, text)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    if mode == "track":
        live_followup(ga.load_env(ga.ENV_PATH).get("TELEGRAM_RECOM_ID"))
        return
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    ga.LANG = zp.LANG = "ar"
    calls = []
    op = recom_track.load(recom_track.OPEN, {})
    busy = {t["sym"] for t in op.values() if t.get("kind") != "plan"}  # one open call per symbol (a plan does not count)
    chan = ga.load_env(ga.ENV_PATH).get("TELEGRAM_RECOM_ID")
    now = datetime.now(timezone.utc).timestamp()
    for sym in COMMOD:  # gold, then oil
        try:
            if sym in busy and mode == "send" and chan and market_shifted(sym, chan):
                busy.discard(sym)  # closed on a total market shift: a fresh call in the new direction follows
            last = zp.yahoo_bars(sym, "1d", "5m")
            if not last or now - last[-1]["ts"] > 15 * 60:  # market closed: no call on a stale price
                print(sym, "market closed")
                continue
            if sym in busy:
                repost_gold(op, chan, mode, sym)
            else:
                c = gold_call(sym)
                if c:
                    calls.append(c)
        except Exception as e:
            ga.log(f"recom_now {sym} failed: {e}")
    for c in calls:
        c["news"] = None
    try:
        import desk
        desk.review()  # the reviewer grades the agents on closed calls and nudges their weights
    except Exception as e:
        ga.log(f"desk review failed: {e}")
    picked = 0
    for c in (stock_calls(cfg) if "--stocks" in sys.argv else []):  # @@ = gold only (user, 2026-11-23)
        if picked == 2:
            break
        if c["sym"] in busy:
            continue
        c["news"] = recom.research(c["sym"], c["plan"]["side"])
        if c["news"] and c["news"]["verdict"] == "against":
            print("skipped (news against):", c["sym"], c["news"].get("en"))
            continue
        calls.append(c)
        picked += 1
    for c in calls:
        path = os.path.join(recom.OUT, c["key"].split("|")[0] + ".png")
        recom.chart(c["bars"], c["plan"], c["title"], path, c["n"])
        news = c["news"]
        text = card(c, news)
        if mode == "send" and chan:
            ok = send_card(chan, path, text)  # java_recomm only
            ga.log(f"recom_now sent {c['key']} ok={ok}")
            if ok:
                if c.get("desk"):
                    import desk
                    desk.log_call(c["key"], c["desk"])
                    desk.mark_seen(c["sym"], c["desk"].get("bar_ts"))
                replace_plan(c["sym"] if c["sym"] != "GOLD" else "GC=F", chan)
                recom_track.add({"key": c["key"], "plan": c["plan"], "market": True, "hold": c["hold"], "kind": "now", "msg": ok, "win_at": c["plan"].get("win_at", 3),
                                 "ysym": c["sym"] if c["sym"] != "GOLD" else "GC=F"})
            print("posted", c["key"], ok)
        else:
            print(f"[{path}]\n{text}\n")
    # java_recomm gets only the 3-line calls; results come from recom_track.watch() (congrats / hard luck)
    if mode == "send":  # trusted channels are checked every minute by recom_track watch (2026-11-25); @@ shows their status
        try:
            import channel_track
            for name in channel_track.TRIALS:
                st = recom_track.load(channel_track.trial_file(name), {"calls": [], "last_id": None})
                print(f"{channel_track.TRIALS[name]}: {len(st['calls'])} calls seen, last post {st['last_id']}")
        except Exception as e:
            ga.log(f"@@ channel check failed: {e}")


def market_shifted(sym, chan):
    """The ONLY early close (user, 2026-11-23): the market has totally shifted. That means the fresh vote points
    the other way with at least 2 of its 3 signals, and the open call is already down 0.5R or more.
    The call is closed with a reply under its card and counted in the scorecard at its real result."""
    with recom_track.lock():
        op = recom_track.load(recom_track.OPEN, {})
        key, t = next(((k, v) for k, v in op.items() if v["sym"] == sym and v.get("kind") == "now"), (None, None))
        if not t:
            return False
        import desk
        dk = desk.decide(sym)
        px = dk["px"]
        r = recom_track.r_of(t, px)
        # a total shift = the Hunter fires the other way (2-agent desk) and the call is down 0.5R or more
        h = dk["votes"].get("hunter", 0)
        opposite = (h < 0 if t["side"] == "buy" else h > 0)
        if not opposite or r > -0.5:
            return False
        f = (lambda v: f"{v:.1f}") if t["gold"] else (lambda v: f"{v:.2f}")
        try:
            recom_track.post(chan, f"🔄 تغيّر السوق بالكامل، أُغلقت عند {f(px)} {recom_track.move(t, 'en', px).split(' (')[0]}\n"
                                   f"🔄 Market shifted: closed at {f(px)}. A new call follows.", t.get("msg"))
        except Exception as e:
            ga.log(f"recom_now shift reply failed: {e}")
        hist = recom_track.load(recom_track.HIST, [])
        hist.append({"key": key, "status": "shifted", "r": round(r, 2), "closed": datetime.now(timezone.utc).timestamp()})
        json.dump(hist, open(recom_track.HIST, "w"), indent=1)
        del op[key]
        json.dump(op, open(recom_track.OPEN, "w"), indent=1)
        return True


def repost_gold(op, chan, mode, sym="GC=F"):
    """The gold call is still open: post its card again (fresh chart, same levels) when it has no linked message,
    so the TP / SL replies land under it. With a linked message there is nothing new to post."""
    tag, name, icon = COMMOD[sym]
    key, t = next((k, v) for k, v in op.items() if v["sym"] == sym)
    if t.get("msg"):
        print(f"{tag}: the open call is already posted and followed live; no new call")
        return
    h1 = zp.yahoo_bars(sym, "1mo", "60m")
    for x in h1:
        x["lab"] = datetime.fromtimestamp(x["ts"], timezone.utc).strftime("%d %H:%M")
    plan = {k2: t[k2] for k2 in ("side", "entry", "stop", "t1", "t2", "t3")}
    path = os.path.join(recom.OUT, f"{tag}NOW.png")
    recom.chart(h1, plan, f"{tag} ({name}) · 1-hour", path, 40)
    text = recom_track.card_text(plan, name, sym == "GC=F", icon)
    if mode != "send" or not chan:
        print(f"[{path}]\n{text}\n")
        return
    ok = recom.send_photo(chan, path, text)
    if ok:
        with recom_track.lock():
            o = recom_track.load(recom_track.OPEN, {})
            if key in o:
                o[key]["msg"] = ok
                json.dump(o, open(recom_track.OPEN, "w"), indent=1)
    print("reposted the open gold call", key, ok)


def replace_plan(sym, chan):
    """A live bot call on a market replaces that market's pending next-session plan (reply under the plan's card)."""
    with recom_track.lock():
        o = recom_track.load(recom_track.OPEN, {})
        for k, t in list(o.items()):
            if t.get("kind") == "plan" and t["sym"] == sym and t["status"] == "pending":
                try:
                    recom_track.post(chan, "🔄 أُلغيت الخطة: توصية مباشرة جديدة · plan replaced by a new live call", t.get("msg"))
                except Exception:
                    pass
                del o[k]
        json.dump(o, open(recom_track.OPEN, "w"), indent=1)


def live_followup(chan):
    """Every @@ ends with the live follow-up of ALL open calls, gold and stocks in separate messages, java_recomm only."""
    try:
        recom_track.watch()  # any target / stop hit first, as its own live result
        msgs = recom_track.follow()
    except Exception as e:
        ga.log(f"recom_now follow-up failed: {e}")
        return
    for m in msgs:
        try:
            recom_track.post(chan, m)
            print("follow-up posted")
        except Exception as e:
            ga.log(f"recom_now follow-up send failed: {e}")


if __name__ == "__main__":
    main()
