"""Convert a gold plan (spot/futures prices) into GLD prices for the trader-* skills.

The trader skills (time machine, risk, budget) accept US stock/ETF tickers only, so gold is
checked through GLD. GLD tracks gold at a ratio that drifts slowly (fund fees), so the ratio
is read live from Yahoo: GLD price / gold futures price.

  python3 gold_to_gld.py --entry 3550 --stop 3440 --target 3770
  python3 gold_to_gld.py --entry 3550 --stop 3440 --target 3770 --short

Prints the GLD levels and the exact time-machine command to run. Info only.
"""
import argparse
import json
import shlex

from gold_alerts import get


def last_price(symbol):
    r = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"))
    meta = r["chart"]["result"][0]["meta"]
    return meta["regularMarketPrice"], meta.get("regularMarketTime")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", type=float, required=True)
    ap.add_argument("--stop", type=float, required=True)
    ap.add_argument("--target", type=float, required=True)
    ap.add_argument("--short", action="store_true")
    ap.add_argument("--date", help="session date YYYY-MM-DD for the time machine (default: it picks today)")
    a = ap.parse_args()

    gold, _ = last_price("GC=F")
    gld, _ = last_price("GLD")
    ratio = gld / gold

    def conv(x):
        return round(x * ratio, 2)

    e, s, t = conv(a.entry), conv(a.stop), conv(a.target)
    if a.short:
        ok = s > e > t
    else:
        ok = s < e < t
    print(f"Gold {gold:,.0f}  ->  GLD {gld:,.2f}   (1 gold point = {ratio:.4f} GLD dollars)")
    print(f"Entry {a.entry:,.0f} -> GLD {e}")
    print(f"Stop  {a.stop:,.0f} -> GLD {s}")
    print(f"Target {a.target:,.0f} -> GLD {t}")
    if not ok:
        raise SystemExit("BLOCKED: stop / entry / target are not in a sensible order for this side.")
    risk = abs(a.entry - a.stop)
    print(f"Reward:risk = {abs(a.target - a.entry) / risk:.1f} to 1")
    print("\nNote: GLD trades only 9:30-16:00 New York time; gold futures trade almost 24h, so gaps differ.")
    cmd = ["python3", "~/.claude/skills/trader-timemachine/timemachine.py", "run", "--symbol", "GLD",
           "--side", "sell" if a.short else "buy", "--entry", str(e), "--stop", str(s), "--target", str(t)]
    if a.date:
        cmd += ["--date", a.date]
    print("\nTime machine command:\n  " + " ".join(shlex.quote(c) if c[0] != "~" else c for c in cmd))


if __name__ == "__main__":
    main()
