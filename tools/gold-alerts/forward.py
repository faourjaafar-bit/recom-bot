"""Forward test (the honest check from the user's video: "forward test them to check they're not lucky, overfit
or decayed"). Every signal the live bred bots give is recorded here, posted or not, and scored on live prices
with the bot's own stop and target. The backtest picked these bots partly on their unseen-data numbers, so only
this live record shows whether the 78% (gold, NVDA) and scalp (oil) results are real.

  python3 forward.py      # the forward record per market

live_recom.run() records signals; recom_track.py watch calls update() every minute. File: cache/forward.json.
"""
import json
import os
import time

import recom_track
import zone_plan as zp

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "cache", "forward.json")


def record(sym, bar_ts, plan):
    """Remember one bot signal (once per symbol and bar), with the bot's own levels."""
    with recom_track.lock():
        d = recom_track.load(FILE, {"open": {}, "done": []})
        key = f"{sym}|{bar_ts}"
        if key in d["open"] or any(x["key"] == key for x in d["done"]):
            return
        d["open"][key] = {"sym": sym, "gold": sym == "GC=F", "side": plan["side"], "entry": plan["entry"],
                          "stop": plan["stop"], "t1": plan["t1"], "t2": plan["t2"], "t3": plan["t3"],
                          "win_at": plan.get("win_at", 3), "posted": time.time(), "filled": time.time(),
                          "status": "open", "passed": 0, "hold": 4 * 3600, "close_by": plan.get("close_by")}
        json.dump(d, open(FILE, "w"), indent=1)


def update():
    """Score the open forward trades on 1-minute bars (same rules as the java_recomm tracker)."""
    with recom_track.lock():
        d = recom_track.load(FILE, {"open": {}, "done": []})
        for key, t in list(d["open"].items()):
            try:
                bars = zp.yahoo_bars(t["sym"], "5d", "1m")
            except Exception:
                continue
            recom_track.step(t, bars, margin=60)
            recom_track.past_close(t, bars)
            if t["status"] in ("win", "loss", "timeout"):
                d["done"].append({"key": key, "sym": t["sym"], "status": t["status"],
                                  "r": round(recom_track.r_of(t, t["exit"]), 2), "closed": time.time()})
                del d["open"][key]
            else:
                d["open"][key] = t
        json.dump(d, open(FILE, "w"), indent=1)
        return d


def summary():
    d = recom_track.load(FILE, {"open": {}, "done": []})
    out = {}
    for sym in ("GC=F", "CL=F", "NVDA"):
        rs = [x["r"] for x in d["done"] if x["sym"] == sym]
        out[sym] = {"n": len(rs), "open": sum(1 for t in d["open"].values() if t["sym"] == sym),
                    "win": round(100 * sum(r > 0 for r in rs) / len(rs)) if rs else None,
                    "avg": round(sum(rs) / len(rs), 3) if rs else None, "total": round(sum(rs), 2)}
    return out


if __name__ == "__main__":
    for s, v in summary().items():
        print(s, v)
