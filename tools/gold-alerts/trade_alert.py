"""Gold trade alert (v2): direction, limit entry, stop loss, target, size. Arabic first, English translation below.

  python3 trade_alert.py send    # send the current alert to the owner and all readers (the "go!!" command)
  python3 trade_alert.py test    # print it, send nothing
  python3 trade_alert.py watch   # hourly: send only when a new limit order should be placed (once per level per day)

Rules are v2_signal.py (tested in backtester/gold_v2_bt.py + gold_v2_lm.py): sell when the daily close is below its
50-day average, buy when above; an hourly close beyond the latest 1-hour swing low/high arms a limit order back at
the level; stop 1.0 ATR beyond it, target 3R, close after 48 hours. Replayed on 2 years of GC=F 1h with Bybit fees:
189 trades, +0.24R per trade, profitable in both years. Break-even stops, trailing and partial profits all lowered
the result, so the alert gives one target and a fixed stop.
regime.py adds the playbook line (CRASH / REBOUND / BULL / BEAR / RANGE, from gold daily 2000-2026) and the two
daily swing signals (rebound reclaim, breakout buy); watch() also sends a daily signal once per day.
"""
import json
import os
import sys
from datetime import datetime, timezone

import gold_alerts as ga
import regime
import v2_signal as v2
import zone_plan as zp

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "cache", "trade_alert_sent.json")
TESTED = {"n": 189, "r": 0.24}
LAST_PLAN = {}
SEP = "━" * 12

AR = {
    "title": "🚨 تنبيه صفقة · الذهب 🥇",
    "ctx": "🧭 حالة سوق الذهب 🥇",
    "bias_sell": "📊 الاتجاه اليومي هابط (تحت متوسط 50 يوماً) ← بيع فقط",
    "bias_buy": "📊 الاتجاه اليومي صاعد (فوق متوسط 50 يوماً) ← شراء فقط",
    "go_sell": "🔴 بيع: ضع أمر بيع محدد (Limit) الآن",
    "go_buy": "🟢 شراء: ضع أمر شراء محدد (Limit) الآن",
    "valid": "⏱️ صالح حتى {t} بتوقيت UTC، ويُلغى إن لم يُنفَّذ",
    "open_sell": "✅ صفقة بيع مفتوحة منذ {t} UTC",
    "open_buy": "✅ صفقة شراء مفتوحة منذ {t} UTC",
    "close_by": "⌛ أغلقها عند {t} UTC إن لم يُصب الوقف أو الهدف",
    "wait_sell": "⏳ انتظار: إذا أغلقت شمعة ساعة تحت {e:,.0f} ضع أمر بيع محدد عند {e:,.0f}",
    "wait_buy": "⏳ انتظار: إذا أغلقت شمعة ساعة فوق {e:,.0f} ضع أمر شراء محدد عند {e:,.0f}",
    "wait_new": "⏳ انتظار: المستوى الأخير استُخدم، ننتظر قاعاً أو قمة جديدة على فريم الساعة.",
    "entry": "💵 الدخول (Limit): {e:,.0f}",
    "stop": "🛑 وقف الخسارة: {s:,.0f}",
    "tp": "🎯 الهدف: {p:,.0f}  (3R)",
    "risk": "📏 المخاطرة: {pct:g}% = ${m:,.0f} ← {oz:.2f} أونصة",
    "manage": "💡 لا تحرّك الوقف ولا تجنِ ربحاً جزئياً: كلاهما خفّض النتيجة في الاختبار.",
    "tested": "🧪 مُختبَرة: {n} صفقة في سنتين، المتوسط {r:+.2f}R بعد رسوم Bybit",
    "none": "لا اتجاه يومي واضح الآن، لا تنبيه.",
    "disc": "⚠️ معلومات للتعلّم وليست نصيحة مالية.",
    "live": "💰 السعر المباشر XAUUSD: {px:,.1f} ({ch:+.2f}% اليوم) · {t} بتوقيت إسطنبول",
    "desk": "🤖 قراءة فريق الوكلاء الآن: {side} (النتيجة {sc:+.1f}) · {why}",
    "desk_side": {"buy": "شراء 🟢", "sell": "بيع 🔴", None: "لا صفقة الآن ⏸️"},
    "open": "📌 توصية مفتوحة في java_recomm: {side} من {e:,.1f} ← الآن {move}",
    "now": "📍 السعر الآن {px:,.1f}، يبعد {gap:,.0f} عن الدخول",
}
EN = {
    "title": "🇬🇧 TRADE ALERT · Gold 🥇",
    "ctx": "🇬🇧 🧭 Gold market update 🥇",
    "bias_sell": "📊 Daily trend down (below the 50-day average) → sells only",
    "bias_buy": "📊 Daily trend up (above the 50-day average) → buys only",
    "go_sell": "🔴 SELL: place a sell LIMIT order now",
    "go_buy": "🟢 BUY: place a buy LIMIT order now",
    "valid": "⏱️ Valid until {t} UTC; cancel it if not filled",
    "open_sell": "✅ Sell trade open since {t} UTC",
    "open_buy": "✅ Buy trade open since {t} UTC",
    "close_by": "⌛ Close it at {t} UTC if neither the stop nor the target is hit",
    "wait_sell": "⏳ Waiting: if an hourly candle closes below {e:,.0f}, place a sell limit at {e:,.0f}",
    "wait_buy": "⏳ Waiting: if an hourly candle closes above {e:,.0f}, place a buy limit at {e:,.0f}",
    "wait_new": "⏳ Waiting: the last level was already used; waiting for a new 1-hour swing.",
    "entry": "💵 Entry (limit): {e:,.0f}",
    "stop": "🛑 Stop loss: {s:,.0f}",
    "tp": "🎯 Target: {p:,.0f}  (3R)",
    "risk": "📏 Risk: {pct:g}% = ${m:,.0f} → {oz:.2f} oz",
    "manage": "💡 Don't move the stop or take partial profit: both lowered the result in the test.",
    "tested": "🧪 Tested: {n} trades in 2 years, average {r:+.2f}R after Bybit fees",
    "none": "No clear daily trend right now, no alert.",
    "disc": "⚠️ Info for learning, not financial advice.",
    "live": "💰 Live XAUUSD: {px:,.1f} ({ch:+.2f}% today) · {t} Istanbul",
    "desk": "🤖 Agent desk now: {side} (score {sc:+.1f}) · {why}",
    "desk_side": {"buy": "BUY 🟢", "sell": "SELL 🔴", None: "no call now ⏸️"},
    "open": "📌 Open call in java_recomm: {side} from {e:,.1f} → now {move}",
    "now": "📍 Price now {px:,.1f}, {gap:,.0f} from the entry",
}


def live_lines():
    """{"ar": [...], "en": [...]}: the live spot, the agent desk's reading, the open gold call in java_recomm."""
    import live
    import recom_track
    out = {"ar": [], "en": []}
    q = live.quote("OANDA:XAUUSD")
    t = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + 3 * 3600, timezone.utc).strftime("%H:%M")
    try:
        import desk
        dk = desk.decide("GC=F")
    except Exception:
        dk = None
    op = next((v for v in recom_track.load(recom_track.OPEN, {}).values() if v["sym"] == "GC=F"), None)
    for lang, L in (("ar", AR), ("en", EN)):
        if q:
            out[lang].append(L["live"].format(px=q["close"], ch=q.get("change") or 0, t=t))
        if dk:
            why = ", ".join(f"{k} {v:+.1f}" for k, v in dk["votes"].items()) + (f" · veto: {dk['veto'][0]}" if dk["veto"] else "")
            out[lang].append(L["desk"].format(side=L["desk_side"][dk["side"]], sc=dk["score"], why=why))
        if op and q:
            out[lang].append(L["open"].format(side=L["desk_side"][op["side"]], e=op["entry"],
                                              move=recom_track.move(op, "en", q["close"]).split(" (")[0]))
    return out


def hhmm(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%a %H:%M")


def build(cfg):
    """(status, arabic text, english text, entry). status: go | open | wait | none."""
    # one 2-year daily fetch serves both the v2 bias and the regime playbook
    daily = regime.daily_closed()
    h1 = v2.closed_only(zp.yahoo_bars("GC=F", "1mo", "60m"))
    _, pos, pend, lv = v2.replay(h1, daily)
    rs = regime.state(daily)
    if not lv["side"]:
        return ("none", "\n".join([AR["title"], AR["none"], AR["disc"]]),
                "\n".join([EN["title"], EN["none"], EN["disc"]]), None)
    trade = pos or pend
    if trade:
        status, side = ("open" if pos else "go"), trade["side"]
        e, stop, tgt = trade["entry"], trade["stop"], trade["target"]
    else:
        status = "wait"
        side = "sell" if lv["side"] < 0 else "buy"
        q, a = v2.Q * lv["atr"], lv["atr"]
        lvl, used = (lv["lo"], lv["lo_used"]) if side == "sell" else (lv["hi"], lv["hi_used"])
        if lvl is None or used:
            e = stop = tgt = None
        else:
            e = lvl - q if side == "sell" else lvl + q
            stop = lvl + q + v2.STOP_ATR * a if side == "sell" else lvl - q - v2.STOP_ATR * a
            tgt = e - v2.TARGET_R * (stop - e) if side == "sell" else e + v2.TARGET_R * (e - stop)
    global LAST_PLAN  # the bare levels, for recom.py's chart card
    LAST_PLAN = {"status": status, "side": side, "entry": e, "stop": stop, "target": tgt,
                 "valid_ts": pend["ts"] + 3600 * (v2.VALID + 1) if status == "go" else None, "h1": h1}
    acc, rp = cfg.get("account", 3000), cfg.get("risk_pct", 1)
    now_lines = live_lines()  # live price, the desk's reading and the open java_recomm call (user: go!! up to date)
    spot = (__import__("live").quote("OANDA:XAUUSD") or {}).get("close") or h1[-1]["c"]
    ctx, card = [], []
    for L, lang in ((AR, "ar"), (EN, "en")):
        # market note: trend, regime, news dates, test record (one item per paragraph)
        ctx.append("\n\n".join([L["ctx"]] + now_lines[lang] + [L["bias_" + side]] + (regime.lines(rs, lang) if rs else [])
                               + [L["manage"], L["tested"].format(**TESTED), L["disc"]]))
        if e is None:
            card.append("")
            continue
        # trade card: only the recommendation and its numbers
        if status == "go":
            head = [L["go_" + side], L["valid"].format(t=hhmm(pend["ts"] + 3600 * (v2.VALID + 1)))]
        elif status == "open":
            head = [L["open_" + side].format(t=hhmm(pos["fill_ts"])),
                    L["close_by"].format(t=hhmm(pos["fill_ts"] + 3600 * (v2.HOLD + 1)))]
        else:
            head = [L["wait_" + side].format(e=e)]
        risk, m = abs(e - stop), acc * rp / 100
        head = head + [L["now"].format(px=spot, gap=abs(spot - e))]
        card.append("\n".join([L["title"], ""] + head + ["", L["entry"].format(e=e), L["stop"].format(s=stop),
                                                           L["tp"].format(p=tgt), "",
                                                           L["risk"].format(pct=rp, m=m, oz=m / risk if risk else 0)]))
    return status, ctx, card, e


def message(cfg):
    """(status, [messages to send in order], entry): the market note first, the trade card alone last."""
    status, a, b, e = build(cfg)
    if status == "none":
        return status, [a + "\n\n" + SEP + "\n" + b], e
    ctx, card = a, b
    msgs = [ctx[0] + "\n\n" + SEP + "\n\n" + ctx[1]]
    if card[0]:
        msgs.append(card[0] + "\n\n" + SEP + "\n\n" + card[1])
    return status, msgs, e


def watch_regime():
    """Daily swing signal (rebound reclaim or breakout buy): send once for the day it fires."""
    st = regime.state(regime.daily_closed())
    if not st["sig"]:
        return
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    sent = json.load(open(STATE)) if os.path.exists(STATE) else {}
    key = f"regime|{st['day']}|{st['sig'][0]}"
    if key in sent:
        return
    sent[key] = 1
    json.dump(sent, open(STATE, "w"))
    ga.telegram("\n".join([AR["title"]] + regime.lines(st, "ar") + ["", SEP, EN["title"]] + regime.lines(st, "en")
                          + [EN["disc"]]))


def watch(cfg):
    """Hourly: alert only when a new limit order should be placed, once per entry level per day."""
    try:
        watch_regime()
    except Exception as ex:
        print("regime watch failed:", ex)
    status, msgs, e = message(cfg)
    if status != "go":
        return
    day = ga.datetime.now().strftime("%Y-%m-%d")
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    sent = json.load(open(STATE)) if os.path.exists(STATE) else {}
    key = f"{day}|{round(e)}"
    if key in sent:
        return
    sent = {k: v for k, v in sent.items() if k.startswith(day) or k.startswith("regime|")} | {key: 1}
    json.dump(sent, open(STATE, "w"))
    ga.telegram(msgs[-1])  # the moment to act: the trade card alone


def main():
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    ga.LANG = zp.LANG = "ar"
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    if mode == "watch":
        watch(cfg)
        return
    status, msgs, _ = message(cfg)
    if mode == "send":
        for m in msgs:
            ga.telegram(m)
        print(f"sent {len(msgs)} messages, status:", status)
        try:  # the chart card for t.me/java_recomm (needs the .venv Python for matplotlib)
            import subprocess
            subprocess.run([os.path.join(HERE, ".venv", "bin", "python"), os.path.join(HERE, "recom.py"), "send"],
                           timeout=300)
        except Exception as ex:
            print("recom failed:", ex)
    else:
        print(("\n\n" + "▼" * 20 + " next message\n\n").join(msgs) + f"\n\n[status: {status}]")


if __name__ == "__main__":
    main()
