"""Executor: trades every java_recomm call on YOUR Alpaca account, inside the limits in
tools/trading-safety/risk_limits.json. Paper by default. Live only when YOU switch it on (see below).

  python3 alpaca_exec.py check    # account, limits, proof gate, what it would do now (no orders)
  python3 alpaca_exec.py run      # place / close orders (called every minute by recom_track.py watch)

How a call becomes an order:
  gold -> GLD, oil -> USO, NVDA -> NVDA (Alpaca lists US stocks and funds only).
  A bracket order: a LIMIT entry at the current price (market orders are blocked by your limits), plus a stop and
  a take-profit at the same % distance as the call (the target is the call's win level: TP1 for the 78% bots,
  TP3 for the scalp bot). A call that ends another way (time limit, market shift) has its position closed.
Size: risk max_loss_per_trade_pct of equity, but never a position bigger than max_position_pct_of_equity.
Guards (every run): the KILL_SWITCH file stops all new orders; max_daily_loss_pct (equity vs yesterday's close)
stops new orders for the day; max_open_positions; US market hours only; only calls under 10 minutes old.

LIVE TRADING (your money) is OFF unless ALL of these are true, and Claude never does any of them for you:
  1. you set "mode": "live" in risk_limits.json yourself,
  2. you put ALPACA_LIVE_KEY / ALPACA_LIVE_SECRET in tools/trading-safety/.env yourself,
  3. the forward test has proved the bot for that market (forward.py: 30+ signals, win rate and average R at the
     bar in PROOF below, always more than +0.05R on average). Until then that market stays on paper even in live mode,
  4. "require_human_approval_per_order": false. While it is true, a live order is NOT placed: it is sent to your
     Telegram bot chat for you to place yourself.
"""
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request

import gold_alerts as ga
import recom_track

HERE = os.path.dirname(os.path.abspath(__file__))
SAFE = os.path.join(HERE, "..", "trading-safety")
PROXY = {"GC=F": "GLD", "CL=F": "USO", "NVDA": "NVDA"}
# signals, min win %, min avg R. Gold and NVDA wins pay about +0.33R against a -1R loss, so 75% wins alone is break-even:
# every market must also average more than +0.05R per signal (council review, 2026-11-24).
PROOF = {"GC=F": (30, 75, 0.05), "CL=F": (30, 35, 0.05), "NVDA": (30, 75, 0.05)}
PAPER_URL, LIVE_URL = "https://paper-api.alpaca.markets", "https://api.alpaca.markets"


def limits():
    return json.load(open(os.path.join(SAFE, "risk_limits.json")))


def proved(sym):
    """(True/False, reason): has the forward test proved the live bot for this market?"""
    import forward
    f = forward.summary().get(sym, {})
    n, win, avg = PROOF[sym]
    if (f.get("n") or 0) < n:
        return False, f"forward test {f.get('n') or 0}/{n} signals"
    if f["win"] < win or f["avg"] <= avg:
        return False, f"forward test not good enough: {f['win']}% wins, {f['avg']:+.2f}R"
    return True, f"proved: {f['n']} signals, {f['win']}% wins, {f['avg']:+.2f}R"


class Alpaca:
    def __init__(self, live):
        e = ga.load_env(ga.ENV_PATH)
        if live:
            self.base, key, sec = LIVE_URL, e.get("ALPACA_LIVE_KEY"), e.get("ALPACA_LIVE_SECRET")
        else:
            self.base, key, sec = (e.get("ALPACA_BASE_URL") or "").rstrip("/"), e.get("ALPACA_KEY"), e.get("ALPACA_SECRET")
            if self.base != PAPER_URL:
                raise SystemExit("refused: ALPACA_BASE_URL is not the PAPER url")
        if not key or not sec:
            raise SystemExit(f"no Alpaca {'LIVE' if live else 'paper'} keys in tools/trading-safety/.env")
        self.live = live
        self.h = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec, "Content-Type": "application/json"}

    def call(self, method, path, body=None, base=None):
        req = urllib.request.Request((base or self.base) + path, data=json.dumps(body).encode() if body else None,
                                     headers=self.h, method=method)
        try:
            raw = urllib.request.urlopen(req, timeout=20).read()
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as err:
            return {"error": err.code, "message": err.read()[:300].decode(errors="ignore")}

    def price(self, sym):
        q = self.call("GET", f"/v2/stocks/{sym}/trades/latest?feed=iex", base="https://data.alpaca.markets")
        return (q.get("trade") or {}).get("p")


def notify_owner(text):
    e = ga.load_env(ga.ENV_PATH)
    data = urllib.parse.urlencode({"chat_id": e["TELEGRAM_CHAT_ID"], "text": text}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{e['TELEGRAM_BOT_TOKEN']}/sendMessage", data, timeout=20)
    except Exception as ex:
        ga.log(f"exec notify failed: {ex}")


def run(place=True):
    import urllib.parse  # noqa: F401  (used by notify_owner)
    lim = limits()
    live_mode = lim.get("mode") == "live"
    if os.path.exists(os.path.join(SAFE, lim.get("kill_switch_file", "KILL_SWITCH"))):
        return {"stopped": "KILL_SWITCH file present: no new orders"}
    report = {"mode": "LIVE" if live_mode else "paper", "actions": []}
    calls = recom_track.load(recom_track.OPEN, {})
    for account_live in ([False, True] if live_mode else [False]):
        try:
            api = Alpaca(account_live)
        except SystemExit as ex:
            report["actions"].append(str(ex))
            continue
        tag = "live" if account_live else "paper"
        state_file = os.path.join(HERE, "cache", f"alpaca_exec_{tag}.json")
        state = recom_track.load(state_file, {})
        acct = api.call("GET", "/v2/account")
        if "error" in acct:
            report["actions"].append(f"{tag}: Alpaca error {acct}")
            continue
        clock = api.call("GET", "/v2/clock")
        positions = {p["symbol"]: p for p in (api.call("GET", "/v2/positions") or []) if isinstance(p, dict)}
        equity, last = float(acct["equity"]), float(acct.get("last_equity") or acct["equity"])
        report[tag] = {"equity": equity, "day_pnl": round(equity - last, 2), "market_open": clock.get("is_open"),
                       "positions": [(p["symbol"], p["qty"], p.get("unrealized_pl")) for p in positions.values()]}
        # 1) close positions whose call ended another way
        for key, st in list(state.items()):
            if key not in calls and st.get("status") == "open":
                if st["symbol"] in positions and place:
                    api.call("DELETE", f"/v2/positions/{st['symbol']}")
                    report["actions"].append(f"{tag}: closed {st['symbol']} (call ended)")
                    notify_owner(f"↩️ Alpaca {tag}: closed {st['symbol']} (its call ended)")
                st["status"] = "closed"
        # 2) guards for NEW orders
        if equity - last <= -lim["max_daily_loss_pct_of_equity"] / 100 * last:
            report["actions"].append(f"{tag}: daily loss limit hit, no new orders today")
        else:
            for key, t in calls.items():
                if key in state or t["sym"] not in PROXY:
                    continue
                sym = PROXY[t["sym"]]
                if account_live:
                    ok, why = proved(t["sym"])
                    if not ok:  # an unproved market never trades live, only on paper
                        state[key] = {"status": "skipped", "symbol": sym, "why": why}
                        continue
                why = (None if clock.get("is_open") else "US market closed") or \
                      (None if time.time() - t["posted"] <= 600 else "call older than 10 minutes") or \
                      (None if sym not in positions else "position already open") or \
                      (None if len(positions) < lim["max_open_positions"] else "max open positions reached")
                if why:
                    state[key] = {"status": "skipped", "symbol": sym, "why": why}
                    continue
                px = api.price(sym)
                if not px:
                    continue
                w = t.get("win_at", 3)
                sl_pct = (t["stop"] - t["entry"]) / t["entry"]
                tp_pct = (t[f"t{w}"] - t["entry"]) / t["entry"]
                stop, target = round(px * (1 + sl_pct), 2), round(px * (1 + tp_pct), 2)
                by_risk = equity * lim["max_loss_per_trade_pct_of_equity"] / 100 / abs(px - stop) * min(t.get("size", 1.0), 1.0)  # desk confidence
                by_size = equity * lim["max_position_pct_of_equity"] / 100 / px  # never a position above the cap
                qty = math.floor(min(by_risk, by_size))
                if qty < 1:
                    state[key] = {"status": "skipped", "symbol": sym, "why": "size below 1 share"}
                    continue
                limit_px = round(px * (1.0005 if t["side"] == "buy" else 0.9995), 2)  # limit entry, not market
                order = {"symbol": sym, "qty": str(qty), "side": t["side"], "type": "limit",
                         "limit_price": f"{limit_px:.2f}", "time_in_force": "day", "order_class": "bracket",
                         "take_profit": {"limit_price": f"{target:.2f}"}, "stop_loss": {"stop_price": f"{stop:.2f}"}}
                line = f"{t['side']} {qty} {sym} limit {limit_px} SL {stop} TP {target} ({key})"
                if account_live and lim.get("require_human_approval_per_order", True):
                    if place:
                        notify_owner("🔔 LIVE order waiting for YOU (not placed by the bot):\n" + line)
                    state[key] = {"status": "sent_for_approval", "symbol": sym, "order": order}
                    report["actions"].append(f"{tag}: sent for your approval: {line}")
                    continue
                if place:
                    r = api.call("POST", "/v2/orders", order)
                    ok = "error" not in r
                    state[key] = {"status": "open" if ok else "failed", "symbol": sym, "qty": qty, "entry": limit_px,
                                  "stop": stop, "target": target, "order": r.get("id"), "error": None if ok else r}
                    ga.log(f"alpaca {tag} {line} ok={ok}")
                    notify_owner(f"{'✅' if ok else '⚠️'} Alpaca {tag} order {'placed' if ok else 'FAILED'}: {line}")
                report["actions"].append(f"{tag}: {'PLACED' if place else 'would place'} {line}")
        if place:
            json.dump(state, open(state_file, "w"), indent=1)
    return report


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    lim = limits()
    print("mode:", lim.get("mode"), "| approval per live order:", lim.get("require_human_approval_per_order"))
    for s in PROXY:
        print(f"proof gate {s}:", proved(s)[1])
    print(run(place=mode == "run"))
