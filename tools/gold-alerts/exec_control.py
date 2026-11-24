"""Control the JAVA trading tool from your phone: send these to your Telegram bot chat ("bot by JaVa.trading").

  /status   what the tool is doing: mode, accounts, open positions, proof gates, kill switch
  /kill     stop ALL new orders now (creates tools/trading-safety/KILL_SWITCH)
  /resume   allow new orders again (deletes KILL_SWITCH)

Only messages from YOUR chat (TELEGRAM_CHAT_ID) are obeyed; anything else is ignored. Checked every minute by
recom_track.py watch. It never switches live trading on: that stays a manual change in risk_limits.json.
"""
import json
import os
import urllib.parse
import urllib.request

import alpaca_exec as ax
import gold_alerts as ga
import recom_track

HERE = os.path.dirname(os.path.abspath(__file__))
OFFSET = os.path.join(HERE, "cache", "exec_control_offset.json")
KILL = os.path.join(ax.SAFE, "KILL_SWITCH")


def tg(method, **params):
    e = ga.load_env(ga.ENV_PATH)
    data = urllib.parse.urlencode(params).encode()
    return json.loads(urllib.request.urlopen(f"https://api.telegram.org/bot{e['TELEGRAM_BOT_TOKEN']}/{method}", data,
                                             timeout=20).read())


def status_text():
    lim = ax.limits()
    lines = ["🤖 JAVA trading tool · status", ""]
    lines.append("🛑 KILL SWITCH ON: no new orders" if os.path.exists(KILL) else "🟢 running (kill switch off)")
    lines.append(f"Alpaca: {lim.get('mode', 'paper')} · Bybit: {lim.get('bybit_mode', 'demo')} · "
                 f"approval per live order: {'yes' if lim.get('require_human_approval_per_order', True) else 'no'}")
    env = ga.load_env(ga.ENV_PATH)
    keys = [n for n, k in (("Alpaca paper", "ALPACA_KEY"), ("Bybit demo", "BYBIT_DEMO_KEY")) if env.get(k)]
    lines.append("keys: " + (", ".join(keys) if keys else "none yet (paste demo keys to Claude)"))
    lines.append("")
    for name, mod in (("Alpaca", "alpaca_exec"), ("Bybit", "bybit_exec")):
        try:
            r = __import__(mod).run(place=False)
            for tag in ("paper", "demo", "live"):
                if tag in r:
                    a = r[tag]
                    lines.append(f"{name} {tag}: equity {a['equity']:,.2f} · today {a['day_pnl']:+,.2f} · "
                                 f"positions {len(a['positions'])}")
        except SystemExit:
            pass
        except Exception as ex:
            lines.append(f"{name}: {ex}")
    lines.append("")
    for sym, n in (("GC=F", "Gold"), ("CL=F", "Oil"), ("NVDA", "NVDA")):
        lines.append(f"{n} proof gate: {ax.proved(sym)[1]}")
    calls = recom_track.load(recom_track.OPEN, {})
    lines.append(f"\nopen java_recomm calls: {len(calls)}")
    return "\n".join(lines)


def poll():
    """Read new messages from the owner's chat and act on the commands."""
    env = ga.load_env(ga.ENV_PATH)
    me = str(env.get("TELEGRAM_CHAT_ID"))
    off = recom_track.load(OFFSET, {"offset": 0})
    try:
        r = tg("getUpdates", offset=off["offset"], timeout=0, allowed_updates=json.dumps(["message"]))
    except Exception as ex:
        return ga.log(f"exec_control poll failed: {ex}")
    for u in r.get("result", []):
        off["offset"] = u["update_id"] + 1
        m = u.get("message") or {}
        if str((m.get("chat") or {}).get("id")) != me:
            continue  # only the owner can control the tool
        cmd = (m.get("text") or "").strip().split()[0].lower() if m.get("text") else ""
        if cmd == "/kill":
            open(KILL, "w").write("created from Telegram /kill\n")
            reply = "🛑 KILL SWITCH ON. The tool places no new orders. Send /resume to allow them again."
        elif cmd == "/resume":
            if os.path.exists(KILL):
                os.remove(KILL)
            reply = "🟢 Kill switch off. The tool can place new orders again (demo/paper unless you set live)."
        elif cmd == "/status":
            reply = status_text()
        else:
            continue
        tg("sendMessage", chat_id=me, text=reply)
        ga.log(f"exec_control {cmd}")
    json.dump(off, open(OFFSET, "w"))


if __name__ == "__main__":
    print(status_text())
