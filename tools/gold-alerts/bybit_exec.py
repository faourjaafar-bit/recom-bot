"""Bybit executor: trades every java_recomm call on YOUR Bybit account (USDT perpetuals), inside the limits in
tools/trading-safety/risk_limits.json. DEMO by default (Bybit demo trading, fake money). Live only when YOU switch
it on (see below).

  python3 bybit_exec.py check    # account, limits, proof gate, what it would do now (no orders)
  python3 bybit_exec.py run      # place / close orders (called every minute by recom_track.py watch)

Markets: gold -> XAUUSDT, oil -> CLUSDT, NVDA -> NVDAUSDT (Bybit linear perpetuals).
Each call becomes ONE limit order with its stop-loss and take-profit attached, at the same % distance as the
call (the take-profit is the call's win level: TP1 for the 78% bots, TP3 for the oil scalp bot).
Size: risk max_loss_per_trade_pct of equity, never a position above max_position_pct_of_equity, rounded down to
the contract step. Guards: KILL_SWITCH file, max_daily_loss_pct (vs equity at the first run of the UTC day),
max_open_positions, calls under 10 minutes old. A call that ends another way is closed with a reduce-only limit.

LIVE (your money) is OFF unless ALL are true, and Claude never does any of them for you:
  1. "bybit_mode": "live" in risk_limits.json, set by you,
  2. BYBIT_LIVE_KEY / BYBIT_LIVE_SECRET in tools/trading-safety/.env, put there by you
     (make the key trade-only: no withdrawals, IP-restricted),
  3. the forward test has proved the bot for that market (alpaca_exec.proved),
  4. "require_human_approval_per_order": false. While true, live orders are sent to your Telegram to place yourself.
Demo keys go in BYBIT_DEMO_KEY / BYBIT_DEMO_SECRET (created in Bybit -> Demo Trading -> API).
"""
import hashlib
import hmac
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import alpaca_exec as ax
import gold_alerts as ga
import recom_track

HERE = os.path.dirname(os.path.abspath(__file__))
MARKET = {"GC=F": "XAUUSDT", "CL=F": "CLUSDT", "NVDA": "NVDAUSDT"}
DEMO_URL, LIVE_URL = "https://api-demo.bybit.com", "https://api.bybit.com"


class Bybit:
    def __init__(self, live):
        e = ga.load_env(ga.ENV_PATH)
        key, sec = (e.get("BYBIT_LIVE_KEY"), e.get("BYBIT_LIVE_SECRET")) if live else \
                   (e.get("BYBIT_DEMO_KEY"), e.get("BYBIT_DEMO_SECRET"))
        if not key or not sec:
            raise SystemExit(f"no Bybit {'LIVE' if live else 'demo'} keys in tools/trading-safety/.env")
        self.base, self.key, self.sec, self.live = (LIVE_URL if live else DEMO_URL), key, sec, live

    def _req(self, method, path, params=None):
        ts, rw = str(int(time.time() * 1000)), "5000"
        if method == "GET":
            q = urllib.parse.urlencode(params or {})
            payload, url, data = q, self.base + path + ("?" + q if q else ""), None
        else:
            payload = json.dumps(params or {}, separators=(",", ":"))
            url, data = self.base + path, payload.encode()
        sign = hmac.new(self.sec.encode(), (ts + self.key + rw + payload).encode(), hashlib.sha256).hexdigest()
        h = {"X-BAPI-API-KEY": self.key, "X-BAPI-TIMESTAMP": ts, "X-BAPI-SIGN": sign, "X-BAPI-RECV-WINDOW": rw,
             "Content-Type": "application/json"}
        try:
            r = json.loads(urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h, method=method),
                                                  timeout=20).read())
        except urllib.error.HTTPError as err:
            return {"retCode": err.code, "retMsg": err.read()[:200].decode(errors="ignore")}
        return r

    def equity(self):
        r = self._req("GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED"})
        lst = (r.get("result") or {}).get("list") or []
        if not lst:
            return None, r
        if self.live:
            return float(lst[0]["totalEquity"]), r
        # Demo holds ~170k of Bybit's free BTC/ETH/USDC: count USDT only (our perps settle in it), so coin swings
        # neither size the trades nor trip the daily loss limit
        usdt = [c for c in lst[0].get("coin", []) if c["coin"] == "USDT"]
        return (float(usdt[0].get("equity") or 0) if usdt else 0.0), r

    def positions(self):
        r = self._req("GET", "/v5/position/list", {"category": "linear", "settleCoin": "USDT"})
        return {p["symbol"]: p for p in (r.get("result") or {}).get("list", []) if float(p.get("size") or 0) > 0}

    def order(self, body):
        return self._req("POST", "/v5/order/create", dict(body, category="linear"))


def public(path, params):
    q = urllib.parse.urlencode(params)
    return json.loads(urllib.request.urlopen(f"{LIVE_URL}{path}?{q}", timeout=20).read())["result"]["list"]


def spec(sym):
    i = public("/v5/market/instruments-info", {"category": "linear", "symbol": sym})[0]
    return float(i["lotSizeFilter"]["qtyStep"]), float(i["lotSizeFilter"]["minOrderQty"]), float(i["priceFilter"]["tickSize"])


def last_price(sym):
    return float(public("/v5/market/tickers", {"category": "linear", "symbol": sym})[0]["lastPrice"])


def rnd(v, step):
    return round(math.floor(v / step + 1e-9) * step, 10)


def rpx(v, tick):
    return f"{round(round(v / tick) * tick, 10):.{max(0, -int(math.floor(math.log10(tick))))}f}"


TERMS = os.path.join(HERE, "cache", "bybit_terms.json")


def probe_terms():
    """Hourly (from recom_track watch) until all three work: a smallest-size demo order far from the price (it can
    not fill) with TP/SL, cancelled at once. It tells you on Telegram the moment Bybit accepts a contract."""
    st = recom_track.load(TERMS, {})
    if all(st.get(m) == "ok" for m in MARKET.values()) or time.time() - st.get("_t", 0) < 3600:
        return st
    st["_t"] = time.time()
    try:
        api = Bybit(False)
    except SystemExit:
        return st
    for sym in MARKET.values():
        if st.get(sym) == "ok":
            continue
        step, minq, tick = spec(sym)
        lp = last_price(sym) * 0.9
        qty = max(minq, math.ceil(6 / lp / step) * step)  # Bybit's 5 USDT minimum order value
        r = api.order({"symbol": sym, "side": "Buy", "orderType": "Limit", "qty": f"{round(qty, 8)}", "positionIdx": 0,
                       "price": rpx(lp, tick), "timeInForce": "GTC", "takeProfit": rpx(lp * 1.004, tick),
                       "stopLoss": rpx(lp * 0.988, tick), "tpslMode": "Full"})
        oid = (r.get("result") or {}).get("orderId")
        if oid:
            api._req("POST", "/v5/order/cancel", {"category": "linear", "symbol": sym, "orderId": oid})
            st[sym] = "ok"
            ax.notify_owner(f"✅ Bybit demo now accepts {sym}: the JAVA tool will trade its calls automatically.")
        else:
            st[sym] = r.get("retMsg") or "blocked"
    json.dump(st, open(TERMS, "w"), indent=1)
    return st


def run(place=True):
    lim = ax.limits()
    live_mode = lim.get("bybit_mode") == "live"
    if os.path.exists(os.path.join(ax.SAFE, lim.get("kill_switch_file", "KILL_SWITCH"))):
        return {"stopped": "KILL_SWITCH file present: no new orders"}
    report = {"mode": "LIVE" if live_mode else "demo", "actions": []}
    calls = recom_track.load(recom_track.OPEN, {})
    for account_live in ([False, True] if live_mode else [False]):
        try:
            api = Bybit(account_live)
        except SystemExit as ex:
            report["actions"].append(str(ex))
            continue
        tag = "live" if account_live else "demo"
        sfile = os.path.join(HERE, "cache", f"bybit_exec_{tag}.json")
        state = recom_track.load(sfile, {})
        eq, raw = api.equity()
        if eq is None:
            report["actions"].append(f"{tag}: Bybit error {raw.get('retCode')} {raw.get('retMsg')}")
            continue
        if eq <= 0:
            report["actions"].append(f"{tag}: the account has no funds (demo: request demo USDT)")
            continue
        if not account_live:  # the demo mirrors the real account size (config.json "account"), plus what it has made
            state.setdefault("_base_usdt", eq)
            eq = json.load(open(os.path.join(HERE, "config.json"))).get("account", 400) + eq - state["_base_usdt"]
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if state.get("_day") != day or not state.get("_day_start"):
            state["_day"], state["_day_start"] = day, eq
        pos = api.positions()
        report[tag] = {"equity": eq, "day_pnl": round(eq - state["_day_start"], 2), "positions":
                       [(s, p["side"], p["size"], p.get("unrealisedPnl")) for s, p in pos.items()]}
        # 1) a call that ended another way (time limit, market shift): close its position, reduce-only limit
        for key, st in list(state.items()):
            if key.startswith("_") or key in calls or st.get("status") != "open":
                continue
            sym = st["symbol"]
            if sym in pos and place:
                p = pos[sym]
                step, _, tick = spec(sym)
                px = last_price(sym)
                close_side = "Sell" if p["side"] == "Buy" else "Buy"
                api.order({"symbol": sym, "side": close_side, "orderType": "Limit", "qty": p["size"],
                           "price": rpx(px * (0.998 if close_side == "Sell" else 1.002), tick),
                           "timeInForce": "IOC", "reduceOnly": True, "positionIdx": 0})
                report["actions"].append(f"{tag}: closed {sym} (call ended)")
                ax.notify_owner(f"↩️ Bybit {tag}: closed {sym} (its call ended)")
            st["status"] = "closed"
        # 2) guards for NEW orders
        if eq - state["_day_start"] <= -lim["max_daily_loss_pct_of_equity"] / 100 * state["_day_start"]:
            report["actions"].append(f"{tag}: daily loss limit hit, no new orders today")
        else:
            for key, t in calls.items():
                if key in state or t["sym"] not in MARKET:
                    continue
                sym = MARKET[t["sym"]]
                if account_live:
                    ok, why = ax.proved(t["sym"])
                    if not ok:
                        state[key] = {"status": "skipped", "symbol": sym, "why": why}
                        continue
                why = (None if time.time() - t["posted"] <= 600 else "call older than 10 minutes") or \
                      (None if sym not in pos else "position already open") or \
                      (None if len(pos) < lim["max_open_positions"] else "max open positions reached")
                if why:
                    state[key] = {"status": "skipped", "symbol": sym, "why": why}
                    continue
                step, minq, tick = spec(sym)
                px = last_price(sym)
                w = t.get("win_at", 3)
                stop = px * (1 + (t["stop"] - t["entry"]) / t["entry"])
                target = px * (1 + (t[f"t{w}"] - t["entry"]) / t["entry"])
                by_risk = eq * lim["max_loss_per_trade_pct_of_equity"] / 100 / abs(px - stop) * min(t.get("size", 1.0), 1.0)  # desk confidence
                # the demo may use leverage so that the 1% risk is real (demo_max_position_pct_of_equity); the live
                # account always keeps max_position_pct_of_equity
                cap = lim["max_position_pct_of_equity"] if account_live else \
                    lim.get("demo_max_position_pct_of_equity", lim["max_position_pct_of_equity"])
                by_size = eq * cap / 100 / px
                qty = rnd(min(by_risk, by_size), step)
                if qty < minq:
                    state[key] = {"status": "skipped", "symbol": sym, "why": f"size {qty} below the minimum {minq}"}
                    continue
                side = "Buy" if t["side"] == "buy" else "Sell"
                body = {"symbol": sym, "side": side, "orderType": "Limit", "qty": f"{qty}", "positionIdx": 0,
                        "price": rpx(px * (1.0005 if side == "Buy" else 0.9995), tick), "timeInForce": "GTC",
                        "takeProfit": rpx(target, tick), "stopLoss": rpx(stop, tick), "tpslMode": "Full"}
                line = f"{side} {qty} {sym} limit {body['price']} SL {body['stopLoss']} TP {body['takeProfit']} ({key})"
                if account_live and lim.get("require_human_approval_per_order", True):
                    if place:
                        ax.notify_owner("🔔 LIVE Bybit order waiting for YOU (not placed by the bot):\n" + line)
                    state[key] = {"status": "sent_for_approval", "symbol": sym, "order": body}
                    report["actions"].append(f"{tag}: sent for your approval: {line}")
                    continue
                if place:
                    r = api.order(body)
                    ok = r.get("retCode") == 0
                    state[key] = {"status": "open" if ok else "failed", "symbol": sym, "qty": qty, "order": body,
                                  "error": None if ok else r.get("retMsg")}
                    ga.log(f"bybit {tag} {line} ok={ok} {'' if ok else r.get('retMsg')}")
                    ax.notify_owner(f"{'✅' if ok else '⚠️'} Bybit {tag} order {'placed' if ok else 'FAILED: ' + str(r.get('retMsg'))}: {line}")
                report["actions"].append(f"{tag}: {'PLACED' if place else 'would place'} {line}")
        if place:
            json.dump(state, open(sfile, "w"), indent=1)
    return report


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    lim = ax.limits()
    print("bybit mode:", lim.get("bybit_mode", "demo"), "| approval per live order:", lim.get("require_human_approval_per_order"))
    for s, m in MARKET.items():
        print(f"{m}: last {last_price(m)} | proof gate: {ax.proved(s)[1]}")
    print(run(place=mode == "run"))
