"""Cloud runner (GitHub Actions): the same recom bots, running while the Mac is off.

One workflow run lasts about 50 minutes and starts the next run itself just before it ends (workflow_dispatch), so the
bot runs around the clock. GitHub's "every 5 min" cron only fires about once an hour (2026-11-25: the close summary
and the next plan were missed), so the cron is only the backup that restarts the chain.
  - every 5 min:   @@ (recom_now.py send: gold + oil calls) and the 5-min candle engine (live_recom.py run)
  - every minute:  recom_track.watch(): fills, TP / SL replies, price replies, and market_events (the closes,
                   the close summary and the next session plan)
State (open calls, message ids, history) lives in ../../state/*.json, copied into cache/ before each step
and committed back after, so no call is lost or posted twice between runs.
"""
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
STATE = os.path.join(ROOT, "state")
CACHE = os.path.join(HERE, "cache")
FILES = ("recom_open.json", "recom_history.json", "live_recom.json", "forward.json", "desk_log.jsonl",
         "desk_weights.json", "desk_last.json", "exec_control_offset.json", "bybit_exec_demo.json", "bybit_terms.json",
         "market_events.json", "hunter_seen.json",  # the alerts already sent, so a close is never posted twice
         # trusted-channel trials + backtest table (checked every minute by recom_track watch, 2026-11-25)
         "channels/trial_mmsignalsfx.json", "channels/trial_xauusd_signals.json", "channels/table.json",
         "channels/trial_mahmoudgoldfx.json", "patch_said.json",
         "nyopen_paper.json")  # NY-open rule paper test, owner only (2026-11-27)  # the priority channel (2026-11-26)
# The phone's /kill creates this file; it lives in state/ so it survives between runs (a /kill sent while the Mac is off still holds).
SAFE = os.path.join(ROOT, "tools", "trading-safety")
KILL = "KILL_SWITCH"
RUN_SECONDS = int(os.environ.get("RUN_SECONDS", "3000"))


def pull():
    os.makedirs(CACHE, exist_ok=True)
    for f in FILES:
        if os.path.exists(os.path.join(STATE, f)):
            os.makedirs(os.path.dirname(os.path.join(CACHE, f)), exist_ok=True)
            shutil.copy(os.path.join(STATE, f), os.path.join(CACHE, f))
    os.makedirs(SAFE, exist_ok=True)
    if os.path.exists(os.path.join(STATE, KILL)):
        shutil.copy(os.path.join(STATE, KILL), os.path.join(SAFE, KILL))
    elif os.path.exists(os.path.join(SAFE, KILL)):
        os.remove(os.path.join(SAFE, KILL))


def push():
    changed = False
    for f in FILES:
        src = os.path.join(CACHE, f)
        if os.path.exists(src):
            old = open(os.path.join(STATE, f), "rb").read() if os.path.exists(os.path.join(STATE, f)) else None
            if old != open(src, "rb").read():
                os.makedirs(os.path.dirname(os.path.join(STATE, f)), exist_ok=True)
                shutil.copy(src, os.path.join(STATE, f))
                changed = True
    live_kill, kept_kill = os.path.join(SAFE, KILL), os.path.join(STATE, KILL)
    if os.path.exists(live_kill) != os.path.exists(kept_kill):
        shutil.copy(live_kill, kept_kill) if os.path.exists(live_kill) else os.remove(kept_kill)
        changed = True
    if changed and os.environ.get("CI"):
        run = lambda *a: subprocess.run(a, cwd=ROOT, check=False, capture_output=True)
        run("git", "add", "state")
        run("git", "-c", "user.name=recom-bot", "-c", "user.email=bot@users.noreply.github.com",
            "commit", "-m", "state")
        for _ in range(3):
            if run("git", "pull", "--rebase", "--autostash", "-X", "theirs").returncode == 0 and run("git", "push").returncode == 0:
                break
            time.sleep(2)


def step(*args):
    r = subprocess.run([sys.executable, *args], cwd=HERE, capture_output=True, text=True, timeout=240)
    print((r.stdout + r.stderr)[-600:])


def next_run():
    """Queue the next run (it starts when this one ends: the workflow's concurrency group keeps one at a time)."""
    if os.environ.get("CI") and os.environ.get("GH_TOKEN"):
        r = subprocess.run(["gh", "workflow", "run", "recom.yml", "-R", os.environ.get("GITHUB_REPOSITORY", "")],
                           capture_output=True, text=True)
        print("next run queued" if r.returncode == 0 else "next run not queued: " + r.stderr[-300:])


def main():
    t0 = time.time()
    pull()
    n = 0
    while time.time() - t0 < RUN_SECONDS:
        if n % 5 == 0:
            step("recom_now.py", "send")
            step("live_recom.py", "run")
            step("nyopen_paper.py", "run")
            push()
        n += 1
        time.sleep(max(0, 60 - (time.time() - t0) % 60))
        step("recom_track.py", "watch")
        push()
    next_run()


if __name__ == "__main__":
    main()
