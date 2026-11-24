"""Trade journal with a postmortem after every loss.

  python3 journal.py add --side long --entry 3550 --stop 3480 --exit 3470 \
        --followed yes --reason "bought the hammer" [--lesson "..."] [--demo]
  python3 journal.py review
  add --lang en|ar to override the language (default: "lang" in config.json)

Results are stored in journal.csv next to this file. R = profit divided by the
money risked (entry to stop), so +2R means you made twice what you risked.
"""
import argparse
import csv
import json
import os
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "journal.csv")
FIELDS = ["date", "mode", "side", "entry", "stop", "exit", "R", "followed_rules", "reason", "lesson"]

T = {
    "en": {
        "bad_stop": "The stop must be on the losing side of the entry.",
        "win": "WIN", "loss": "LOSS", "flat": "flat",
        "saved": "Saved: {res} {r:+.2f}R",
        "postmortem": [
            "Loss recorded. Write the postmortem (--lesson), answering:",
            "  1. Did you follow your own rules? (an honest 'no' is the most common cause)",
            "  2. Was the stop sensible vs gold's daily range?",
            "  3. Was there news you ignored (Fed, inflation, jobs)?",
            "  4. What ONE rule changes so this does not repeat?",
        ],
        "broke": "You broke your rules on this loss. That is the loss to fix first.",
        "none": "No trades yet.",
        "summary": "Trades: {n}   Win rate: {w:.0f}%   Average: {a:+.2f}R   Total: {tot:+.2f}R",
        "avg": "Average win {aw:+.2f}R vs average loss {al:+.2f}R",
        "broke_n": "Trades where you broke your rules: {n} ({r:+.2f}R total)",
        "lessons": "Last lessons:",
        "lesson": "- {d} ({r}R): {text}",
        "missing": "{n} loss(es) still have NO postmortem. Fill them in.",
        "few": "Only {n} trades: too few to judge. Aim for 30+ on demo before real money.",
    },
    "ar": {
        "bad_stop": "يجب أن يكون الوقف في جهة الخسارة من سعر الدخول.",
        "win": "ربح", "loss": "خسارة", "flat": "تعادل",
        "saved": "حُفظت: {res} {r:+.2f}R",
        "postmortem": [
            "سُجّلت خسارة. اكتب تحليل ما بعد الصفقة (--lesson) مجيباً عن:",
            "  1. هل اتبعت قواعدك؟ (الجواب الصادق «لا» هو السبب الأكثر شيوعاً)",
            "  2. هل كان الوقف منطقياً مقارنة بالمدى اليومي للذهب؟",
            "  3. هل تجاهلت أخباراً مهمة (الفيدرالي، التضخم، الوظائف)؟",
            "  4. ما القاعدة الواحدة التي ستغيّرها كي لا يتكرر هذا؟",
        ],
        "broke": "خالفت قواعدك في هذه الخسارة. هذه أول خسارة يجب إصلاحها.",
        "none": "لا صفقات بعد.",
        "summary": "الصفقات: {n}   نسبة الربح: {w:.0f}%   المتوسط: {a:+.2f}R   المجموع: {tot:+.2f}R",
        "avg": "متوسط الربح {aw:+.2f}R مقابل متوسط الخسارة {al:+.2f}R",
        "broke_n": "صفقات خالفت فيها قواعدك: {n} (المجموع {r:+.2f}R)",
        "lessons": "آخر الدروس:",
        "lesson": "- {d} ({r}R): {text}",
        "missing": "{n} من الخسائر بلا تحليل حتى الآن. أكمِلها.",
        "few": "عدد الصفقات {n} فقط: قليل جداً للحكم. استهدف 30 صفقة تجريبية أو أكثر قبل المال الحقيقي.",
    },
}
LANG = "en"


def t(key, **kw):
    s = T[LANG][key]
    return s.format(**kw) if kw else s


def config_lang():
    try:
        return json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8")).get("lang", "en")
    except Exception:
        return "en"


def rows():
    if not os.path.exists(PATH):
        return []
    with open(PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def add(a):
    d = (a.entry - a.stop) if a.side == "long" else (a.stop - a.entry)
    if d <= 0:
        raise SystemExit(t("bad_stop"))
    pnl = (a.exit - a.entry) if a.side == "long" else (a.entry - a.exit)
    r = round(pnl / d, 2)
    new = not os.path.exists(PATH)
    with open(PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS)
        if new:
            w.writeheader()
        w.writerow({"date": date.today().isoformat(), "mode": "demo" if a.demo else "live",
                    "side": a.side, "entry": a.entry, "stop": a.stop, "exit": a.exit, "R": r,
                    "followed_rules": a.followed, "reason": a.reason, "lesson": a.lesson or ""})
    print(t("saved", res=t("win") if r > 0 else t("loss") if r < 0 else t("flat"), r=r))
    if r < 0 and not a.lesson:
        print("\n".join(T[LANG]["postmortem"]))
    if r < 0 and a.followed == "no":
        print(t("broke"))


def review():
    rs = rows()
    if not rs:
        print(t("none"))
        return
    R = [float(r["R"]) for r in rs]
    wins = [x for x in R if x > 0]
    losses = [x for x in R if x < 0]
    print(t("summary", n=len(R), w=100 * len(wins) / len(R), a=sum(R) / len(R), tot=sum(R)))
    if wins and losses:
        print(t("avg", aw=sum(wins) / len(wins), al=sum(losses) / len(losses)))
    broke = [r for r in rs if r["followed_rules"] == "no"]
    if broke:
        print(t("broke_n", n=len(broke), r=sum(float(r["R"]) for r in broke)))
    lessons = [r for r in rs if float(r["R"]) < 0 and r["lesson"]]
    if lessons:
        print("\n" + t("lessons"))
        for r in lessons[-5:]:
            print(t("lesson", d=r["date"], r=r["R"], text=r["lesson"]))
    miss = [r for r in rs if float(r["R"]) < 0 and not r["lesson"]]
    if miss:
        print("\n" + t("missing", n=len(miss)))
    if len(R) < 30:
        print("\n" + t("few", n=len(R)))


def main():
    global LANG
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=list(T), help="output language (default from config.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("--side", choices=["long", "short"], required=True)
    p.add_argument("--entry", type=float, required=True)
    p.add_argument("--stop", type=float, required=True)
    p.add_argument("--exit", type=float, required=True)
    p.add_argument("--followed", choices=["yes", "no"], required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--lesson")
    p.add_argument("--demo", action="store_true")
    # also accept --lang after the subcommand; SUPPRESS keeps a value given before it
    p.add_argument("--lang", choices=list(T), default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    r = sub.add_parser("review")
    r.add_argument("--lang", choices=list(T), default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    a = ap.parse_args()
    LANG = a.lang or config_lang()
    if LANG not in T:
        LANG = "en"
    add(a) if a.cmd == "add" else review()


if __name__ == "__main__":
    main()
