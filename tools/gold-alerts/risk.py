"""Gold position-size calculator. Information only: you place the order yourself.

  python3 risk.py --account 3000 --entry 3550 --stop 3480
  python3 risk.py --account 3000 --entry 3550 --stop 3480 --risk 1 --leverage 5 --short
  add --lang en|ar to override the language (default: "lang" in config.json)

Answers: how many ounces, how much money is at risk, how much margin it locks,
where the 2R / 3R targets are, and warns when the plan is unsafe.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_RISK_PCT = 2.0      # hard ceiling per trade (learning-path rule)
MAX_DAILY_LOSS_PCT = 3.0

T = {
    "en": {
        "above": "above", "below": "below",
        "bad_stop": "BLOCKED: the stop must be {side} the entry.",
        "too_risky": "BLOCKED: {r}% risk is above the {m}% limit. Use {m}% or less.",
        "w_size": "position bigger than your account allows at this leverage",
        "w_margin": "margin is {p:.0f}% of the account: little room if price moves against you",
        "w_liq": "liquidation (~{liq:,.0f}) comes BEFORE your stop: lower the leverage",
        "w_atr": "stop is {d:,.0f} away but gold moves ~{atr:,.0f}/day on average: normal noise will likely hit it",
        "w_no_atr": "could not read live volatility (ATR); check it yourself",
        "long": "LONG", "short": "SHORT",
        "head": "{side} gold  entry {e:,.0f}  stop {s:,.0f}  (distance {d:,.0f})",
        "risk": "Risk now:        ${m:,.0f}  ({r}% of ${acc:,.0f})",
        "size": "Size:            {oz:,.2f} oz  (position worth ${v:,.0f})",
        "margin": "Margin locked:   ${mg:,.0f} at {lev:g}x leverage",
        "t2": "Target 2R:       {t:,.0f}  -> +${p:,.0f}",
        "t3": "Target 3R:       {t:,.0f}  -> +${p:,.0f}",
        "liq": "Liquidation:     ~{liq:,.0f} (approximate, check your app)",
        "atr": "Daily range:     ~{atr:,.0f} (ATR 14)",
        "daily": "Daily loss rule: stop trading for the day after -${x:,.0f} ({p:g}% of account)",
        "warn": "WARNING: ",
        "disclaimer": "Info only, not financial advice. You decide and place every order.",
    },
    "ar": {
        "above": "فوق", "below": "تحت",
        "bad_stop": "مرفوض: يجب أن يكون الوقف {side} سعر الدخول.",
        "too_risky": "مرفوض: مخاطرة {r}% أعلى من الحد الأقصى {m}%. استخدم {m}% أو أقل.",
        "w_size": "المركز أكبر مما يسمح به حسابك بهذه الرافعة",
        "w_margin": "الهامش يساوي {p:.0f}% من الحساب: مساحة قليلة إذا تحرّك السعر ضدك",
        "w_liq": "التصفية (~{liq:,.0f}) تأتي قبل الوقف: خفّض الرافعة",
        "w_atr": "الوقف على بُعد {d:,.0f} فقط، والذهب يتحرك نحو {atr:,.0f} يومياً في المتوسط: "
                 "التذبذب العادي سيضربه على الأرجح",
        "w_no_atr": "تعذّرت قراءة التذبذب الحالي (ATR)؛ تحقّق منه بنفسك",
        "long": "شراء", "short": "بيع",
        "head": "{side} ذهب  الدخول {e:,.0f}  الوقف {s:,.0f}  (المسافة {d:,.0f})",
        "risk": "المخاطرة:          ${m:,.0f}  ({r}% من ${acc:,.0f})",
        "size": "الحجم:             {oz:,.2f} أونصة  (قيمة المركز ${v:,.0f})",
        "margin": "الهامش المحجوز:    ${mg:,.0f} برافعة {lev:g}x",
        "t2": "الهدف 2R:          {t:,.0f}  ← ربح ${p:,.0f}",
        "t3": "الهدف 3R:          {t:,.0f}  ← ربح ${p:,.0f}",
        "liq": "سعر التصفية:       ~{liq:,.0f} (تقريبي، تحقّق في تطبيقك)",
        "atr": "المدى اليومي:      ~{atr:,.0f} (ATR 14)",
        "daily": "قاعدة الخسارة اليومية: توقّف عن التداول لبقية اليوم بعد خسارة ${x:,.0f} ({p:g}% من الحساب)",
        "warn": "تحذير: ",
        "disclaimer": "معلومات فقط وليست نصيحة مالية. القرار وتنفيذ كل أمر عليك.",
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


def main():
    global LANG
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", type=float, required=True, help="account size in USD")
    ap.add_argument("--entry", type=float, required=True)
    ap.add_argument("--stop", type=float, required=True)
    ap.add_argument("--risk", type=float, default=1.0, help="percent of account to risk (default 1)")
    ap.add_argument("--leverage", type=float, default=1.0)
    ap.add_argument("--short", action="store_true")
    ap.add_argument("--no-atr", action="store_true", help="skip the live volatility check")
    ap.add_argument("--lang", choices=list(T), help="output language (default from config.json)")
    a = ap.parse_args()
    LANG = a.lang or config_lang()
    if LANG not in T:
        LANG = "en"

    dist = (a.stop - a.entry) if a.short else (a.entry - a.stop)
    if dist <= 0:
        sys.exit(t("bad_stop", side=t("above") if a.short else t("below")))

    warnings = []
    if a.risk > MAX_RISK_PCT:
        sys.exit(t("too_risky", r=a.risk, m=MAX_RISK_PCT))

    money_risk = a.account * a.risk / 100
    oz = money_risk / dist
    value = oz * a.entry
    margin = value / a.leverage
    if value > a.account * a.leverage:
        warnings.append(t("w_size"))
    if margin > a.account * 0.5:
        warnings.append(t("w_margin", p=100 * margin / a.account))

    liq = None
    if a.leverage > 1:
        liq = a.entry * (1 + 1 / a.leverage) if a.short else a.entry * (1 - 1 / a.leverage)
        if (a.short and liq <= a.stop) or (not a.short and liq >= a.stop):
            warnings.append(t("w_liq", liq=liq))

    atr = None
    if not a.no_atr:
        try:
            from gold_alerts import atr14, load_bars
            bars, _ = load_bars("GC=F")
            atr = atr14(bars)
            if dist < atr:
                warnings.append(t("w_atr", d=dist, atr=atr))
        except Exception:
            warnings.append(t("w_no_atr"))

    d = -1 if a.short else 1
    print(t("head", side=t("short") if a.short else t("long"), e=a.entry, s=a.stop, d=dist))
    print(t("risk", m=money_risk, r=a.risk, acc=a.account))
    print(t("size", oz=oz, v=value))
    print(t("margin", mg=margin, lev=a.leverage))
    print(t("t2", t=a.entry + d * 2 * dist, p=2 * money_risk))
    print(t("t3", t=a.entry + d * 3 * dist, p=3 * money_risk))
    if liq:
        print(t("liq", liq=liq))
    if atr:
        print(t("atr", atr=atr))
    print(t("daily", x=a.account * MAX_DAILY_LOSS_PCT / 100, p=MAX_DAILY_LOSS_PCT))
    for w in warnings:
        print(t("warn") + w)
    print(t("disclaimer"))


if __name__ == "__main__":
    main()
