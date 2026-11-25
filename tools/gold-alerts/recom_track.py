"""Live follow-up of every recommendation posted to t.me/java_recomm (by "@@" / recom.py).

For each open trade: did the limit fill, which targets were passed, stop or target hit, how many pips/points it
moved, what that means, whether the strategy says hold or wait, and the expected range for the next 30 minutes.
Closed trades are reported once with their result, then moved to the history (running scorecard).
Gold and stocks always go in SEPARATE messages, one item per line with a blank line between (user's layout).

  python3 recom_track.py test    # print the follow-up, send nothing
  python3 recom_track.py watch   # every minute (launchd): post a fill / T1 / T2 / T3 / stop to java_recomm AT ONCE
pulse.py calls follow() every 30 minutes and posts it to java_recomm before the gold pulse; every @@ ends with it.

Rules follow the tests: the stop is never moved and there is no partial profit (both lowered the result);
T3 (3R) is the exit. Gold: 1 pip = $0.10, limit valid until valid_ts, close 48 hours after the fill.
Stocks: bought at the post, held up to 20 trading days (28 calendar days). Info only, not financial advice.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import gold_alerts as ga
import zone_plan as zp

HERE = os.path.dirname(os.path.abspath(__file__))
OPEN = os.path.join(HERE, "cache", "recom_open.json")
HIST = os.path.join(HERE, "cache", "recom_history.json")
LEVELS = ("sym", "side", "entry", "stop", "t1", "t2", "t3", "win_at", "posted", "filled", "exit")
SEP = "━" * 12
GOLD_HOLD = 48 * 3600
STOCK_HOLD = 28 * 86400

L = {
    "ar": {"title": {"gold": "🥇✨📋 متابعة توصية الذهب · كل 30 دقيقة", "stocks": "📈🇺🇸📋 متابعة توصيات الأسهم · كل 30 دقيقة"},
           "live_title": {"gold": "⚡🥇🔔 نتيجة فورية · الذهب", "stocks": "⚡📈🔔 نتيجة فورية · الأسهم"},
           "gold_name": "🥇🪙 الذهب XAUUSD",
           "name": {"sell": "🔴📉 بيع", "buy": "🟢📈 شراء"},
           "lv_e": "💵 الدخول: {v}", "lv_s": "🛑 الوقف: {v}", "lv_t": "🎯 الأهداف: T1 {a} · T2 {b} · T3 {c}",
           "fill": "✅🔓 نُفِّذ الأمر المحدد عند {e}. الصفقة مفتوحة الآن.",
           "hit": "🎯🔥 وصلت إلى T{i} عند {p}",
           "hit_move": "💰 الربح حتى الآن: {move} (+{i}R)",
           "hit_plan": "🧭 الاستراتيجية: أبقِها مفتوحة نحو T3، والوقف ثابت عند {s}.",
           "hit_cheer": "👏🎉 مبروك! الهدف {i} تحقق، والقراءة صحيحة حتى الآن. نكمل نحو الهدف التالي.",
           "pend": "⏳ لم يُنفَّذ بعد: السعر {px} يبعد {gap} عن الدخول {e}",
           "expired": "⌛🚫 انتهت صلاحية الأمر دون تنفيذ ← أُلغيت التوصية، لا ربح ولا خسارة",
           "since": "🕒 مفتوحة منذ: {since}",
           "now": "📍 السعر الآن: {px}",
           "pnl": "{icon} النتيجة حتى الآن: {move} ({r:+.2f}R)",
           "passed": "✅ تجاوز {t}",
           "none_passed": "🎯 لم يصل إلى T1 بعد",
           "win": "🏆🎯 ناجحة: أصابت الهدف T3 عند {t3}",
           "win_move": "💰 الربح: {move} (+3R)",
           "loss": "❌🛑 أصابت الوقف عند {s}",
           "loss_move": "📉 الخسارة: {move} (-1R)",
           "timeout": "⌛ انتهت مدة الاحتفاظ وأُغلقت عند {px}",
           "timeout_move": "{icon} النتيجة: {move} ({r:+.2f}R)",
           "m_hold": "💡 المعنى: الصفقة تسير وفق الخطة. الاستراتيجية تقول: احتفظ حتى T3، والوقف ثابت عند {s}.",
           "m_hold_red": "💡 المعنى: الصفقة في خسارة مؤقتة لكن الوقف {s} لم يُضرب. الاستراتيجية تقول: لا تتدخل.",
           "m_win": "🎉🥳 مبروك! توصية ناجحة وقراءة صحيحة للسوق. ننتظر التوصية التالية.",
           "m_loss": "🍀💪 حظ سيئ هذه المرة، لكن الخسارة محسوبة (1R) ويمكن تعويضها بالحركة والتوصية التالية. النتيجة تُقاس على عشرات الصفقات.",
           "m_pend": "💡 المعنى: لا صفقة بعد. الاستراتيجية تقول: اترك الأمر المحدد كما هو حتى يُنفَّذ أو تنتهي صلاحيته.",
           "next": "🔮 النصف ساعة القادمة: المدى المتوقع {a} – {b}",
           "score": "📊🏁 السجل حتى الآن: {n} صفقة · {w} ناجحة ✅ · {l} خاسرة ❌ · المجموع {r:+.1f}R",
           "pip": "{v:+,.0f} نقطة (${d:+,.2f})", "pt": "${d:+,.2f} ({p:+.2f}%)",
           "disc": "⚠️ متابعة آلية للتعلّم، وليست نصيحة مالية."},
    "en": {"title": {"gold": "🥇✨📋 GOLD call follow-up · every 30 min", "stocks": "📈🇺🇸📋 STOCK calls follow-up · every 30 min"},
           "live_title": {"gold": "⚡🥇🔔 LIVE RESULT · Gold", "stocks": "⚡📈🔔 LIVE RESULT · Stocks"},
           "gold_name": "🥇🪙 Gold XAUUSD",
           "name": {"sell": "🔴📉 SELL", "buy": "🟢📈 BUY"},
           "lv_e": "💵 Entry: {v}", "lv_s": "🛑 Stop: {v}", "lv_t": "🎯 Targets: T1 {a} · T2 {b} · T3 {c}",
           "fill": "✅🔓 The limit order filled at {e}. The trade is open now.",
           "hit": "🎯🔥 Reached T{i} at {p}",
           "hit_move": "💰 Profit so far: {move} (+{i}R)",
           "hit_plan": "🧭 Strategy: keep it open toward T3, the stop stays at {s}.",
           "hit_cheer": "👏🎉 Congrats! Target {i} reached, the reading is right so far. On toward the next target.",
           "pend": "⏳ Not filled yet: price {px} is {gap} from the entry {e}",
           "expired": "⌛🚫 The order expired unfilled → recommendation cancelled, no profit or loss",
           "since": "🕒 Open since: {since}",
           "now": "📍 Price now: {px}",
           "pnl": "{icon} Result so far: {move} ({r:+.2f}R)",
           "passed": "✅ passed {t}",
           "none_passed": "🎯 not at T1 yet",
           "win": "🏆🎯 Success: hit the T3 target at {t3}",
           "win_move": "💰 Profit: {move} (+3R)",
           "loss": "❌🛑 Hit the stop at {s}",
           "loss_move": "📉 Loss: {move} (-1R)",
           "timeout": "⌛ Holding time ended, closed at {px}",
           "timeout_move": "{icon} Result: {move} ({r:+.2f}R)",
           "m_hold": "💡 Meaning: the trade is on plan. Strategy says: hold to T3, the stop stays at {s}.",
           "m_hold_red": "💡 Meaning: a temporary loss, but the stop {s} was not hit. Strategy says: don't interfere.",
           "m_win": "🎉🥳 Congrats! A successful call and a correct market reading. On to the next recommendation.",
           "m_loss": "🍀💪 Hard luck this time, but the loss was planned (1R) and can be recovered with the next move and recommendation. Results count over dozens of trades.",
           "m_pend": "💡 Meaning: no trade yet. Strategy says: leave the limit order as it is until it fills or expires.",
           "next": "🔮 Next 30 min: expected range {a} – {b}",
           "score": "📊🏁 Record so far: {n} trades · {w} wins ✅ · {l} losses ❌ · total {r:+.1f}R",
           "pip": "{v:+,.0f} pips (${d:+,.2f})", "pt": "${d:+,.2f} ({p:+.2f}%)",
           "disc": "⚠️ Automatic follow-up for learning, not financial advice."},
}


class lock:
    """watch() (every minute) and follow() (every 30 min) must not write the state at the same time."""
    def __enter__(self):
        import fcntl
        os.makedirs(os.path.dirname(OPEN), exist_ok=True)
        self.f = open(OPEN + ".lock", "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)

    def __exit__(self, *a):
        self.f.close()


def load(path, empty):
    try:
        return json.load(open(path))
    except Exception:
        return empty


def add(sig):
    """Called by recom.py / recom_now.py right after a post: remember the trade so it is followed live."""
    os.makedirs(os.path.dirname(OPEN), exist_ok=True)
    op = load(OPEN, {})
    gold = sig["key"].startswith("GOLD")
    p = sig["plan"]
    now = datetime.now(timezone.utc).timestamp()
    op[sig["key"]] = {"sym": "GC=F" if gold else sig.get("ysym") or sig["key"].split("|")[0], "gold": gold, "side": p["side"],
                      "entry": p["entry"], "stop": p["stop"], "t1": p["t1"], "t2": p["t2"], "t3": p["t3"],
                      "posted": now, "valid": sig.get("valid_ts") or now + 4 * 3600,
                      "filled": now if sig.get("market") or not gold else None, "passed": 0,
                      "status": "open" if sig.get("market") or not gold else "pending",
                      "hold": sig.get("hold"), "kind": sig.get("kind", "tested"), "size": sig.get("size", 1.0),
                      "msg": sig.get("msg"), "win_at": sig.get("win_at") or sig["plan"].get("win_at", 3),
                      "close_by": sig["plan"].get("close_by")}  # Telegram id of the card: results are sent as replies to it
    json.dump(op, open(OPEN, "w"), indent=1)


def past_close(t, bars):
    """The call's closing time has passed (market close, or its holding time) with no bar after it yet: close it now
    at the last price, instead of at the next session's open."""
    if t["status"] == "open" and t.get("close_by") and time.time() >= t["close_by"] and bars:
        last = [x for x in bars if x["ts"] < t["close_by"]] or bars
        t["status"], t["exit"] = "timeout", last[-1]["c"]


def step(t, bars, margin=1800):
    """Walk the bars since the post and update the trade. Same bar touching stop and target = stop."""
    d = 1 if t["side"] == "buy" else -1
    for x in bars:
        if x["ts"] < t["posted"] - margin:
            continue
        if t["status"] == "pending":
            if x["ts"] > t["valid"]:
                t["status"] = "expired"
                return
            if x["l"] <= t["entry"] <= x["h"]:  # the bar touched the entry (works above or below the price)
                t["status"], t["filled"] = "open", x["ts"]
            else:
                continue
        if t["status"] != "open":
            return
        # every call is followed to TP3 (user, 2026-11-24: "where is TP2 and TP3"); after TP1 the stop moves to the
        # entry, so a call that hit a target can no longer lose. Same bar touching stop and target = stop.
        stop = t["entry"] if t["passed"] >= 1 else t["stop"]
        hit_stop = (x["h"] >= stop) if d < 0 else (x["l"] <= stop)
        best = x["l"] if d < 0 else x["h"]
        if hit_stop:
            if t["passed"] >= 1:
                t["status"], t["exit"], t["be"] = "win", t["entry"], True
            else:
                t["status"], t["exit"] = "loss", t["stop"]
            return
        for i, k in enumerate(("t1", "t2", "t3"), 1):
            if (best - t[k]) * d >= 0:
                t["passed"] = max(t["passed"], i)
        if t["passed"] >= 3:
            t["status"], t["exit"] = "win", t["t3"]
            return
        if (t.get("close_by") and x["ts"] >= t["close_by"]) or \
                x["ts"] - t["filled"] > (t.get("hold") or (GOLD_HOLD if t["gold"] else STOCK_HOLD)):
            t["status"], t["exit"] = "timeout", x["c"]
            return


def fmt(t, v):
    return f"{v:,.1f}" if t["gold"] else f"{v:,.2f}"


def move(t, lang, to):
    d = (to - t["entry"]) * (1 if t["side"] == "buy" else -1)
    d = 0.0 if abs(d) < 0.005 else d
    if t["gold"] or t["sym"] == "CL=F":  # gold 1 pip = $0.10, oil 1 pip = $0.01
        return L[lang]["pip"].format(v=d / (0.1 if t["gold"] else 0.01), d=d)
    return L[lang]["pt"].format(d=d, p=100 * d / t["entry"])


def realized_r(t, to):
    """R of the whole call when a third is booked at each target it reached and the rest closes at `to`."""
    n = min(t.get("passed", 0), 3)
    if not n:
        return r_of(t, to)
    return (sum(r_of(t, t[f"t{i}"]) for i in range(1, n + 1)) + (3 - n) * r_of(t, to)) / 3


def r_of(t, to):
    risk = abs(t["entry"] - t["stop"])
    return (to - t["entry"]) * (1 if t["side"] == "buy" else -1) / risk if risk else 0


def head(t, lang):
    """The trade's name and levels, one per line."""
    T = L[lang]
    if t["gold"]:
        name = T["gold_name"]
    else:
        try:
            import flow
            look, en, ar = flow.STOCK_LOOK.get(t["sym"], ("📈", t["sym"], t["sym"]))
        except Exception:
            look, en, ar = "📈", t["sym"], t["sym"]
        name = f"{look} {ar if lang == 'ar' else en} ({t['sym']})"
    return [f"{T['name'][t['side']]} · {name}", T["lv_e"].format(v=fmt(t, t["entry"])),
            T["lv_s"].format(v=fmt(t, t["stop"])),
            T["lv_t"].format(a=fmt(t, t["t1"]), b=fmt(t, t["t2"]), c=fmt(t, t["t3"]))]


def closed_lines(t, lang):
    T = L[lang]
    st = t["status"]
    if st == "win":
        return [T["win"].format(t3=fmt(t, t["t3"])), T["win_move"].format(move=move(t, lang, t["t3"])), T["m_win"]]
    if st == "loss":
        return [T["loss"].format(s=fmt(t, t["stop"])), T["loss_move"].format(move=move(t, lang, t["stop"])), T["m_loss"]]
    if st == "expired":
        return [T["expired"]]
    r = r_of(t, t["exit"])
    return [T["timeout"].format(px=fmt(t, t["exit"])),
            T["timeout_move"].format(icon="💰" if r > 0 else "📉", move=move(t, lang, t["exit"]), r=r),
            T["m_win"] if r > 0 else T["m_loss"]]


def close_out(key, t, op, hist, now):
    if t["status"] in ("pending", "open"):
        op[key] = t
        return
    if t["status"] != "expired":
        r = -1.0 if t["status"] == "loss" else None
        hist.append({"key": key, "status": t["status"], "r": round(r if r is not None else realized_r(t, t["exit"]), 2),
                     "closed": now, **{k: t.get(k) for k in LEVELS}})  # levels kept for the workflow replay
        if t["status"] == "loss":  # learn from it: what moved the market (news_agent.lesson, owner chat)
            try:
                import news_agent
                news_agent.lesson(t, key)
            except Exception as e:
                ga.log(f"lesson failed {key}: {e}")
    del op[key]  # closed trades are reported once


def render(blocks, hist, title, limit=3900):
    """One message per group (gold, then stocks): Arabic then English, one item per line, a blank line between.
    Over Telegram's 4,096 limit: Arabic and English apart, and a long language part split between trades."""
    cut = "\n\n" + "┄" * 10 + "\n\n"
    msgs = []
    for g in ("gold", "stocks"):
        if not blocks[g]["ar"]:
            continue
        gh = [h for h in hist if h["key"].startswith("GOLD") == (g == "gold")]
        parts = []
        for lang in ("ar", "en"):
            T = L[lang]
            tail = ([T["score"].format(n=len(gh), w=sum(h["r"] > 0 for h in gh), l=sum(h["r"] <= 0 for h in gh),
                                       r=sum(h["r"] for h in gh))] if gh else [])
            items = ["\n\n".join(b) for b in blocks[g][lang]]
            chunk = [T[title][g]]
            out = []
            for it in items:
                if len(cut.join(chunk + [it])) > limit - 200 and len(chunk) > 1:
                    out.append(cut.join(chunk))
                    chunk = [T[title][g] + " (…)"]
                chunk.append(it)
            out.append(cut.join(chunk + tail) + "\n\n" + T["disc"])
            parts.append(out)
        both = parts[0][-1] + "\n\n" + SEP + "\n\n" + parts[1][-1]
        if len(parts[0]) == 1 and len(parts[1]) == 1 and len(both) <= limit:
            msgs.append(both)
        else:
            msgs += parts[0] + parts[1]
    return msgs


def follow(save=True):
    """The follow-up of every open recommendation: [gold message, stocks message] (empty list when none)."""
    with lock():
        op = load(OPEN, {})
        if not op:
            return []
        hist = load(HIST, [])
        blocks = {g: {"ar": [], "en": []} for g in ("gold", "stocks")}
        now = datetime.now(timezone.utc).timestamp()
        for key, t in list(op.items()):
            try:
                bars = zp.yahoo_bars(t["sym"], "1mo", "30m")
            except Exception as e:
                ga.log(f"recom_track {key} bars failed: {e}")
                continue
            if not bars:
                continue
            step(t, bars)
            past_close(t, bars)
            px = bars[-1]["c"]
            tr = [max(x["h"], p["c"]) - min(x["l"], p["c"]) for p, x in zip(bars[-15:-1], bars[-14:])]
            atr = sum(tr) / len(tr) if tr else 0
            g = "gold" if t["gold"] else "stocks"
            for lang in ("ar", "en"):
                T = L[lang]
                lines = head(t, lang)
                st = t["status"]
                if st == "pending":
                    lines += [T["pend"].format(px=fmt(t, px), gap=fmt(t, abs(px - t["entry"])), e=fmt(t, t["entry"])),
                              T["m_pend"]]
                elif st == "open":
                    r = r_of(t, px)
                    since = datetime.fromtimestamp(t["filled"], timezone.utc).strftime("%d/%m %H:%M UTC")
                    lines += [T["since"].format(since=since), T["now"].format(px=fmt(t, px)),
                              T["pnl"].format(icon="💰" if r >= 0 else "📉", move=move(t, lang, px), r=r),
                              " · ".join(T["passed"].format(t=f"T{i}") for i in range(1, t["passed"] + 1))
                              or T["none_passed"],
                              (T["m_hold"] if r >= 0 else T["m_hold_red"]).format(s=fmt(t, t["stop"]))]
                else:
                    lines += closed_lines(t, lang)
                if st in ("pending", "open"):
                    lines.append(T["next"].format(a=fmt(t, px - atr), b=fmt(t, px + atr)))
                blocks[g][lang].append(lines)
            close_out(key, t, op, hist, now)
        if save:
            json.dump(op, open(OPEN, "w"), indent=1)
            json.dump(hist, open(HIST, "w"), indent=1)
        return render(blocks, hist, "title")


def post(chan, text, reply=None):
    env = ga.load_env(ga.ENV_PATH)
    f = {"chat_id": chan, "text": text, "disable_web_page_preview": "true"}
    if reply:
        f["reply_to_message_id"] = reply
        f["allow_sending_without_reply"] = "true"
    data = ga.urllib.parse.urlencode(f).encode()
    ga.urllib.request.urlopen(f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/sendMessage", data, timeout=20)


SUP = {1: "¹", 2: "²", 3: "³"}


def close_all(note_ar, note_en, syms=None):
    """Close every open java_recomm call now at the live price (user rule 2026-11-24: nothing stays open after the
    signal hours end at 23:00 Istanbul). Each card gets a reply: congrats in profit, hard luck in loss."""
    import live
    spot = {"GC=F": "OANDA:XAUUSD", "CL=F": "FX:USOIL", "NVDA": "NASDAQ:NVDA"}
    chan = ga.load_env(ga.ENV_PATH).get("TELEGRAM_RECOM_ID")
    done = []
    with lock():
        o, h = load(OPEN, {}), load(HIST, [])
        for key, t in list(o.items()):
            if t["status"] == "pending" or (syms and t["sym"] not in syms):  # unfilled orders expire on their own
                continue
            px = (live.quote(spot.get(t["sym"], t["sym"])) or {}).get("close")
            if not px:
                continue
            r = realized_r(t, px)
            f = (lambda v: f"{v:.1f}") if t["gold"] else (lambda v: f"{v:.2f}")
            mv = move(t, "en", px).split(" (")[0]
            try:
                post(chan, f"🔒 {f(px)} {note_ar} · {note_en} {mv}\n"
                     + ("🎉 مبروك Congrats! صفقة رابحة" if r > 0 else "🍀 حظ سيئ Hard luck، نعوّضها بالتوصية التالية"),
                     t.get("msg"))
            except Exception as e:
                ga.log(f"close_all reply failed {key}: {e}")
            h.append({"key": key, "status": "closed", "r": round(r, 2), "closed": time.time(), **{k: t.get(k) for k in LEVELS}})
            del o[key]
            done.append((key, round(r, 2)))
            ga.log(f"closed at end of signal hours: {key} at {px} {mv} r={r:.2f}")
        json.dump(o, open(OPEN, "w"), indent=1)
        json.dump(h, open(HIST, "w"), indent=1)
    return done


def signal_end(ts):
    """The end of the JAVA signal hours after ts: 20:00 UTC (23:00 Istanbul) on the same weekday."""
    from datetime import timedelta
    u = datetime.fromtimestamp(ts, timezone.utc)
    e = u.replace(hour=20, minute=0, second=0, microsecond=0)
    if e <= u:
        e += timedelta(days=1)
    while e.weekday() >= 5:
        e += timedelta(days=1)
    return e.timestamp()


def market_close(sym, ts):
    """The next market close after ts (epoch). US stocks: 16:00 New York on weekdays. Gold and oil (CME): the daily
    break at 17:00 New York, Monday to Friday (Friday 17:00 = the weekend close). DST is handled by the time zone."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    t = datetime.fromtimestamp(ts, ny)
    hour = 17 if sym in ("GC=F", "CL=F") else 16
    c = t.replace(hour=hour, minute=0, second=0, microsecond=0)
    if c <= t:
        c += timedelta(days=1)
    while c.weekday() >= 5:  # no close on Saturday / Sunday: the next one is Monday
        c += timedelta(days=1)
    return c.timestamp()


def ist(ts):
    """Istanbul time (UTC+3, no daylight saving) as 'HH:MM', with the weekday when it is not today."""
    t = datetime.fromtimestamp(ts + 3 * 3600, timezone.utc)
    today = datetime.fromtimestamp(time.time() + 3 * 3600, timezone.utc).date() if "time" in globals() else None
    return t.strftime("%H:%M") if today is None or t.date() == today else t.strftime("%a %H:%M")


def card_text(plan, sym, gold, icon=None):
    """java_recomm card in the user's sample layout:
    🥇BUY 📍XAUUSD @3530.4 / ✔️TP¹ / ✔️TP² / ✔️TP³ / 😮SL. One EXACT entry, no range (user, 2026-11-23)."""
    f = (lambda v: f"{v:.1f}") if gold else (lambda v: f"{v:.2f}")
    sell = plan["side"] == "sell"
    head = f"{icon or ('🥇' if gold else '📈')}{'SELL 🔴' if sell else 'BUY 🟢'} 📍{sym} @{f(plan['entry'])}"
    tps = "\n".join(f"✔️TP{SUP[i]} : {f(plan[f't{i}'])}" for i in (1, 2, 3))
    out = f"{head}\n\n{tps}\n\n😮SL : {f(plan['stop'])}"
    if plan.get("close_by"):  # when the call closes (user: "@@ provide time when stocks or gold trading closes")
        why = {"market": " (إغلاق السوق / market close)",
               "hours": " (نهاية ساعات التوصيات / end of signal hours)"}.get(plan.get("close_why"), "")
        out += f"\n\n⏰ تُغلق Closes: {ist(plan['close_by'])} إسطنبول{why}"
    return out


def short(t, before):
    """Replies under the card (user's sample): the level hit with 🔥💥❤️, congrats on targets, hard luck on the stop."""
    f = (lambda v: f"{v:.1f}") if t["gold"] else (lambda v: f"{v:.2f}")
    out = []
    if before[0] == "pending" and t["status"] != "expired":
        out.append(f"✅ {f(t['entry'])} تم التنفيذ / filled")
    if t["status"] == "expired":
        out.append("⌛ أُلغيت، لم يُنفَّذ / cancelled, not filled")
    for i in range(before[1] + 1, min(t["passed"], 3) + 1):
        p = t[f"t{i}"]
        line = f"TP{SUP[i]} {f(p)}🔥💥❤️ {move(t, 'en', p).split(' (')[0]}\n"
        if i == 3:
            line += "🏆🥳 مبروك Congrats! الأهداف الثلاثة تحققت · all 3 targets hit, صفقة ناجحة"
        else:
            line += f"👏🎉 مبروك Congrats! ➡️ الهدف التالي · next TP{SUP[i + 1]} {f(t[f't{i + 1}'])}"
            if i == 1:
                line += f"\n🔒 الوقف إلى الدخول · stop moved to entry {f(t['entry'])}: no loss now"
        out.append(line)
    if t["status"] == "win" and t.get("be"):
        out.append(f"🔒 {f(t['entry'])} خروج على الدخول بعد TP{SUP[t['passed']]} · out at entry after TP{SUP[t['passed']]}\n"
                   f"✅ صفقة رابحة · a winning call: {realized_r(t, t['exit']):+.2f}R booked")
    if t["status"] == "loss":
        out.append(f"😮SL {f(t['stop'])} {move(t, 'en', t['stop']).split(' (')[0]}\n"
                   "🍀 حظ سيئ Hard luck، نعوّضها بالتوصية التالية")
    elif t["status"] == "timeout":
        r = r_of(t, t["exit"])
        out.append(f"⌛ {f(t['exit'])} {move(t, 'en', t['exit']).split(' (')[0]}\n"
                   + ("🎉 مبروك Congrats!" if r > 0 else "🍀 حظ سيئ Hard luck، نعوّضها بالتوصية التالية"))
    return out


def watch(send=True):
    """Every minute: 1-minute bars for each open trade; on a fill, a new target, the stop or the end, post the
    result to java_recomm at once (gold and stocks in separate messages). Closed trades leave the list, so
    follow() does not repeat them; it keeps the scorecard."""
    with lock():
        op = load(OPEN, {})
        if not op:
            return []
        hist = load(HIST, [])
        now = datetime.now(timezone.utc).timestamp()
        gold_msgs, stock_msgs = [], []
        for key, t in list(op.items()):
            try:
                bars = zp.yahoo_bars(t["sym"], "5d", "1m")
            except Exception as e:
                ga.log(f"recom watch {key} bars failed: {e}")
                continue
            if not bars:
                continue
            before = (t["status"], t["passed"])
            step(t, bars, margin=60)
            past_close(t, bars)
            if (t["status"], t["passed"]) == before and t["status"] == "open" and t.get("msg"):
                # EMERGENCY (user, 2026-11-24): fresh news turning against the call. Price confirms (0.25R+ against,
                # or a 0.3R move against in the last 5 min) -> close at once with the reason; not yet -> one caution
                try:
                    import news_agent
                    why = news_agent.shift_against(t["sym"], t["side"])
                except Exception as e:
                    why = None
                    ga.log(f"news shift check failed {key}: {e}")
                if why:
                    px = bars[-1]["c"]
                    r = r_of(t, px)
                    r5 = r - r_of(t, bars[-6]["c"]) if len(bars) > 6 else 0
                    if t["passed"] >= 1:  # a target is already booked and the stop sits at the entry: no emergency
                        why = None
                    f = (lambda v: f"{v:.1f}") if t["gold"] else (lambda v: f"{v:.2f}")
                    out = gold_msgs if t["gold"] else stock_msgs
                    if why and (r <= -0.25 or r5 <= -0.3):
                        out.append((f"🚨 إغلاق طارئ · EMERGENCY CLOSE {f(px)} {move(t, 'en', px).split(' (')[0]}\n"
                                    f"⚠️ الأخبار تقلب السوق · News is shifting the market:\n{why}\n"
                                    + ("🎉 مبروك Congrats! خرجنا بربح" if r > 0 else "🍀 حظ سيئ Hard luck، خسارة أصغر من الوقف · smaller than the stop"),
                                    t["msg"]))
                        t["status"], t["exit"] = "emergency", px
                        hist.append({"key": key, "status": "emergency", "r": round(realized_r(t, px), 2), "closed": now,
                                     **{k: t.get(k) for k in LEVELS}})
                        ga.log(f"emergency close {key} at {px} r={r:.2f}: {why}")
                        if r < 0:
                            try:
                                news_agent.lesson(t, key)
                            except Exception as e:
                                ga.log(f"lesson failed {key}: {e}")
                        del op[key]
                        continue
                    if why and t.get("warned") != why:
                        out.append((f"⚠️ تحذير · CAUTION {f(px)}\nخبر ضد الصفقة · News against this {t['side'].upper()}:\n{why}\n"
                                    f"الوقف {f(t['stop'])} قائم، وإذا أكد السعر نغلق فوراً · stop stays, we close at once if price confirms",
                                    t["msg"]))
                        t["warned"] = why
                        op[key] = t
            if (t["status"], t["passed"]) == before:
                # live price reply under the card (user's sample: "3531🔥💥❤️"), ONLY when the price really moved
                # (user, 2026-11-24: "too many messages on the same pips"): at least 0.25R away from the last reply,
                # or crossing between profit and loss, and never more than once every 10 minutes
                px = bars[-1]["c"]
                r = r_of(t, px)
                last = t.get("tick_r", 0.0)
                moved = abs(r - last) >= 0.25 or (r > 0.05) != (last > 0.05)
                if t["status"] == "open" and t.get("msg") and now - t.get("tick", 0) >= 600 and moved:
                    f = (lambda v: f"{v:.1f}") if t["gold"] else (lambda v: f"{v:.2f}")
                    t["tick"], t["tick_r"] = now, r
                    mark = "🔥💥❤️" if r > 0.05 else "⏳ نتابع"
                    (gold_msgs if t["gold"] else stock_msgs).append(
                        (f"{f(px)} {mark} {move(t, 'en', px).split(' (')[0]}", t["msg"]))
                    op[key] = t
                continue
            (gold_msgs if t["gold"] else stock_msgs).extend((m, t.get("msg")) for m in short(t, before))
            close_out(key, t, op, hist, now)
        msgs = gold_msgs + stock_msgs  # gold first, every event its own short message
        if not msgs or not send:
            return msgs
        chan = ga.load_env(ga.ENV_PATH).get("TELEGRAM_RECOM_ID")  # java_recomm ONLY (user rule)
        if chan:
            for m, reply in msgs:
                try:
                    post(chan, m, reply)  # a reply on the recommendation's own message
                except Exception as e:
                    ga.log(f"recom watch send failed: {e}")
                    return msgs  # state not saved: the same result is retried next minute
                ga.log(m)
        json.dump(op, open(OPEN, "w"), indent=1)
        json.dump(hist, open(HIST, "w"), indent=1)
        return msgs


if __name__ == "__main__":
    if sys.argv[1:] == ["watch"]:
        watch()
        try:  # market open / close and signal-hours alerts to java_recomm (market_events.py)
            import market_events
            market_events.check()
        except Exception as e:
            ga.log(f"market events failed: {e}")
        try:  # phone control: /status /kill /resume from the owner's Telegram (exec_control.py)
            import exec_control
            exec_control.poll()
        except Exception as e:
            ga.log(f"exec_control failed: {e}")
        try:  # once a day: the regression checks for every mistake the user caught (selfcheck.py)
            mark = os.path.join(HERE, "cache", "selfcheck_day.txt")
            today = time.strftime("%Y-%m-%d")
            if not os.path.exists(mark) or open(mark).read() != today:
                open(mark, "w").write(today)
                import subprocess
                r = subprocess.run([sys.executable, os.path.join(HERE, "selfcheck.py")], capture_output=True, text=True, timeout=120)
                if r.returncode:
                    import alpaca_exec
                    alpaca_exec.notify_owner("⚠️ selfcheck failed, a past mistake is back:\n" + r.stdout[-800:])
                ga.log("selfcheck: " + r.stdout.strip().splitlines()[-1][:200] if r.stdout.strip() else "selfcheck: no output")
        except Exception as e:
            ga.log(f"selfcheck failed to run: {e}")
        try:  # forward test: score every live bot signal (forward.py)
            import forward
            forward.update()
        except Exception as e:
            ga.log(f"forward update failed: {e}")
        try:  # refresh the trading terminal page (terminal.py) every minute
            import terminal
            terminal.write()
        except Exception as e:
            ga.log(f"terminal write failed: {e}")
        try:  # trade every java_recomm call on the Alpaca PAPER account (alpaca_exec.py), once keys exist
            lim = load(os.path.join(HERE, "..", "trading-safety", "risk_limits.json"), {})
            if lim.get("paper_auto_orders"):
                import alpaca_exec
                alpaca_exec.run(place=True)
        except SystemExit:
            pass
        except Exception as e:
            ga.log(f"alpaca paper exec failed: {e}")
        try:  # and on Bybit (bybit_exec.py): demo unless the user switched bybit_mode to live
            lim = load(os.path.join(HERE, "..", "trading-safety", "risk_limits.json"), {})
            if lim.get("paper_auto_orders"):
                import bybit_exec
                bybit_exec.run(place=True)
                bybit_exec.probe_terms()  # hourly until Bybit accepts gold / oil / NVDA on demo
        except SystemExit:
            pass  # no demo keys yet: do nothing
        except Exception as e:
            ga.log(f"bybit exec failed: {e}")
    else:
        print(("\n\n" + "▼" * 20 + " next message\n\n").join(follow(save=False)) or "no open recommendations")
