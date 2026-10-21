"""
Box Theory V3 (M15) - signal bot pour Telegram.
Tourne toutes les 15 min sur GitHub Actions. Aucun ordre n'est place: SIGNAUX seulement.
Les regles sont les memes que BoxTheory_V3.mq5.
Secrets (variables d'environnement): TWELVE_KEY, TG_TOKEN, TG_CHAT_ID
Optionnel: ACCOUNT_USD (defaut 1000), RISK_PCT (defaut 1)
"""
import json, os, sys, math
from datetime import datetime, timedelta, timezone
import requests

CFG = dict(
    zone_pct=10.0, wick_to_body=2.0, opp_wick_max=1.0,
    pitch_min=3, pitch_max=5, big_mult=1.5, avg_bars=10,
    expiry_bars=3, sl_buffer=0.50, max_trades=3,
    trade_end_hour=22, close_hour=23, min_body=0.01,
    use_wick=True, use_pitch=True, use_tower=True,
)
SYMBOL = "XAU/USD"
TF_MIN = 15
STATE_FILE = "state.json"


# ---------------------------------------------------------------- donnees
def fetch(interval, size, key):
    r = requests.get("https://api.twelvedata.com/time_series", params=dict(
        symbol=SYMBOL, interval=interval, outputsize=size, timezone="UTC", apikey=key), timeout=30)
    j = r.json()
    if j.get("status") == "error" or "values" not in j:
        raise RuntimeError("Twelve Data: %s" % j)
    out = []
    for v in reversed(j["values"]):  # du plus ancien au plus recent
        t = datetime.strptime(v["datetime"][:19].replace("T", " "),
                              "%Y-%m-%d %H:%M:%S" if len(v["datetime"]) > 10 else "%Y-%m-%d")
        out.append(dict(t=t, o=float(v["open"]), h=float(v["high"]), l=float(v["low"]), c=float(v["close"])))
    return out


# ---------------------------------------------------------------- patterns
def green(c): return c["c"] > c["o"]
def red(c): return c["c"] < c["o"]
def body(c): return abs(c["c"] - c["o"])


def avg_body(cs, i, n):
    """moyenne des n corps AVANT la bougie de confirmation: indices i-2 ... i-1-n"""
    lst = [body(cs[j]) for j in range(i - 1 - n, i - 1) if j >= 0]
    return sum(lst) / len(lst) if lst else 0.0


def detect(cs, i, top, bot, cfg):
    """cs[i] = bougie de confirmation C1 (fermee). Retourne (dir, nom, eh, el) ou None.
    dir = -1 SELL (bord haut), +1 BUY (bord bas)."""
    zone = (top - bot) * cfg["zone_pct"] / 100.0
    c1, c2 = cs[i], cs[i - 1]
    mb = cfg["min_body"]
    # ---- SELL (haut de la boite)
    tz = top - zone
    if cfg["use_tower"] and green(c2) and red(c1):
        a = avg_body(cs, i, cfg["avg_bars"])
        if a > 0 and body(c2) >= cfg["big_mult"] * a and body(c1) >= cfg["big_mult"] * a \
                and max(c1["h"], c2["h"]) >= tz:
            return (-1, "Power of Tower", max(c1["h"], c2["h"]), min(c1["l"], c2["l"]))
    if cfg["use_wick"] and red(c1):
        b = max(body(c1), mb)
        up = c1["h"] - max(c1["o"], c1["c"]); lo = min(c1["o"], c1["c"]) - c1["l"]
        if up >= cfg["wick_to_body"] * b and lo <= cfg["opp_wick_max"] * b and c1["h"] >= tz:
            return (-1, "John Wick", c1["h"], c1["l"])
    if cfg["use_pitch"] and red(c1):
        run = 0
        while run < 20 and i - 1 - run >= 0 and green(cs[i - 1 - run]):
            run += 1
        if cfg["pitch_min"] <= run <= cfg["pitch_max"]:
            mx = max([c1["h"]] + [cs[i - 1 - k]["h"] for k in range(run)])
            if mx >= tz:
                return (-1, "Pitchfork", c1["h"], c1["l"])
    # ---- BUY (bas de la boite)
    bz = bot + zone
    if cfg["use_tower"] and red(c2) and green(c1):
        a = avg_body(cs, i, cfg["avg_bars"])
        if a > 0 and body(c2) >= cfg["big_mult"] * a and body(c1) >= cfg["big_mult"] * a \
                and min(c1["l"], c2["l"]) <= bz:
            return (1, "Power of Tower", max(c1["h"], c2["h"]), min(c1["l"], c2["l"]))
    if cfg["use_wick"] and green(c1):
        b = max(body(c1), mb)
        lo = min(c1["o"], c1["c"]) - c1["l"]; up = c1["h"] - max(c1["o"], c1["c"])
        if lo >= cfg["wick_to_body"] * b and up <= cfg["opp_wick_max"] * b and c1["l"] <= bz:
            return (1, "John Wick", c1["h"], c1["l"])
    if cfg["use_pitch"] and green(c1):
        run = 0
        while run < 20 and i - 1 - run >= 0 and red(cs[i - 1 - run]):
            run += 1
        if cfg["pitch_min"] <= run <= cfg["pitch_max"]:
            mn = min([c1["l"]] + [cs[i - 1 - k]["l"] for k in range(run)])
            if mn <= bz:
                return (1, "Pitchfork", c1["h"], c1["l"])
    return None


# ---------------------------------------------------------------- simulation de la journee
def lot_size(entry, sl, account, risk_pct):
    dist = abs(entry - sl)
    if dist <= 0:
        return 0.01
    lot = (account * risk_pct / 100.0) / (dist * 100.0)
    return max(0.01, math.floor(lot * 100) / 100.0)


def simulate(cs, top, bot, day, cfg, account=1000.0, risk_pct=1.0):
    """cs = bougies M15 FERMEES (anciennes -> recentes). Retourne la liste d'evenements du jour."""
    ev = []
    pos = None; pend = None; trades = 0
    for k, c in enumerate(cs):
        if c["t"].date() != day or k < 15:
            continue
        close_t = c["t"] + timedelta(minutes=TF_MIN)
        # 1. position ouverte: SL / TP / fermeture forcee
        if pos:
            if pos["dir"] == -1:
                hit_sl, hit_tp = c["h"] >= pos["sl"], c["l"] <= pos["tp"]
            else:
                hit_sl, hit_tp = c["l"] <= pos["sl"], c["h"] >= pos["tp"]
            if hit_sl:   # prudent: si les deux, on compte le SL
                ev.append(dict(type="close", t=close_t, key="%s-close-%s" % (day, c["t"]), res="SL", pos=pos)); pos = None
            elif hit_tp:
                ev.append(dict(type="close", t=close_t, key="%s-close-%s" % (day, c["t"]), res="TP", pos=pos)); pos = None
            elif cfg["close_hour"] >= 0 and c["t"].hour >= cfg["close_hour"]:
                ev.append(dict(type="close", t=close_t, key="%s-close-%s" % (day, c["t"]), res="CLOSE", pos=pos)); pos = None
        # 2. setup en attente: cassure ?
        elif pend:
            d = pend["dir"]
            pend["bars"] -= 1
            sl_touched = (c["h"] >= pend["sl"]) if d == -1 else (c["l"] <= pend["sl"])
            broke = (c["l"] < pend["trigger"]) if d == -1 else (c["h"] > pend["trigger"])
            if broke and c["t"].hour < cfg["trade_end_hour"] and trades < cfg["max_trades"]:
                trades += 1
                pos = dict(dir=d, name=pend["name"], entry=pend["trigger"], sl=pend["sl"], tp=pend["tp"],
                           lot=lot_size(pend["trigger"], pend["sl"], account, risk_pct))
                ev.append(dict(type="entry", t=close_t, key="%s-entry-%s" % (day, c["t"]), pos=pos))
                pend = None
                # meme bougie: SL/TP deja touche ? (prudent)
                if sl_touched or ((c["l"] <= pos["tp"]) if d == -1 else (c["h"] >= pos["tp"])):
                    res = "SL" if sl_touched else "TP"
                    ev.append(dict(type="close", t=close_t, key="%s-close-%s" % (day, c["t"]), res=res, pos=pos)); pos = None
            elif sl_touched or pend["bars"] <= 0:
                ev.append(dict(type="cancel", t=close_t, key="%s-cancel-%s" % (day, c["t"]), pend=pend,
                               why="SL touche avant l'entree" if sl_touched else "expire (pas de cassure)"))
                pend = None
        # 3. nouvelle detection (plus de position ni de setup)
        if pos is None and pend is None and trades < cfg["max_trades"] and close_t.hour < cfg["trade_end_hour"] \
                and not (c["t"].hour >= cfg["close_hour"]):
            r = detect(cs, k, top, bot, cfg)
            if r:
                d, name, eh, el = r
                trig = el if d == -1 else eh
                sl = eh + cfg["sl_buffer"] if d == -1 else el - cfg["sl_buffer"]
                tp = bot if d == -1 else top
                pend = dict(dir=d, name=name, trigger=trig, sl=sl, tp=tp, bars=cfg["expiry_bars"], t=close_t)
                ev.append(dict(type="setup", t=close_t, key="%s-setup-%s" % (day, c["t"]), pend=dict(pend)))
    return ev


# ---------------------------------------------------------------- messages
def fmt(e, top, bot):
    box = "BOX %.2f - %.2f" % (bot, top)
    if e["type"] == "setup":
        p = e["pend"]; side = "SELL" if p["dir"] == -1 else "BUY"
        order = "SELL STOP" if p["dir"] == -1 else "BUY STOP"
        lot = lot_size(p["trigger"], p["sl"], float(os.environ.get("ACCOUNT_USD", 1000)), float(os.environ.get("RISK_PCT", 1)))
        until = (p["t"] + timedelta(minutes=TF_MIN * CFG["expiry_bars"])).strftime("%H:%M")
        return ("BOX V3 SETUP %s XAUUSD M15\nPattern: %s\nPlace un %s a %.2f\nSL %.2f\nTP %.2f\nLOT %.2f\n"
                "Valable jusqu'a %s UTC (sinon annule)\n%s") % (side, p["name"], order, p["trigger"], p["sl"], p["tp"], lot, until, box)
    if e["type"] == "entry":
        p = e["pos"]; side = "SELL" if p["dir"] == -1 else "BUY"
        return "BOX V3 DECLENCHE %s (cassure) @ %.2f\nSL %.2f | TP %.2f | LOT %.2f" % (side, p["entry"], p["sl"], p["tp"], p["lot"])
    if e["type"] == "close":
        p = e["pos"]; side = "SELL" if p["dir"] == -1 else "BUY"
        return "BOX V3 %s ferme: %s" % (side, e["res"])
    if e["type"] == "cancel":
        p = e["pend"]; side = "SELL" if p["dir"] == -1 else "BUY"
        return "BOX V3 setup %s annule: %s" % (side, e["why"])
    return str(e)


def tg(token, chat, text):
    r = requests.post("https://api.telegram.org/bot%s/sendMessage" % token,
                      data=dict(chat_id=chat, text=text), timeout=30)
    if r.status_code != 200:
        print("Telegram erreur", r.status_code, r.text[:200])
    return r.status_code == 200


# ---------------------------------------------------------------- main
def main():
    key = os.environ["TWELVE_KEY"]; token = os.environ["TG_TOKEN"]; chat = os.environ["TG_CHAT_ID"]
    if os.environ.get("TEST") == "1":
        tg(token, chat, "BOX V3: test OK (le bot est bien relie a Telegram)")
        return
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    m15 = fetch("15min", 200, key)
    daily = fetch("1day", 5, key)
    cs = [c for c in m15 if c["t"] + timedelta(minutes=TF_MIN) <= now]      # bougies fermees
    today = now.date()
    prev = [d for d in daily if d["t"].date() < today]
    if not prev or len(cs) < 30:
        print("Pas assez de donnees"); return
    top, bot = prev[-1]["h"], prev[-1]["l"]
    ev = simulate(cs, top, bot, today, CFG, float(os.environ.get("ACCOUNT_USD", 1000)), float(os.environ.get("RISK_PCT", 1)))
    state = {}
    if os.path.exists(STATE_FILE):
        try: state = json.load(open(STATE_FILE))
        except Exception: state = {}
    state = {k: v for k, v in state.items() if k[:10] >= str(today - timedelta(days=3))}
    print("Box %.2f-%.2f | evenements aujourd'hui: %d" % (bot, top, len(ev)))
    for e in ev:
        if e["key"] in state:
            continue
        if now - e["t"] > timedelta(minutes=60):      # evenement trop ancien: on ne spamme pas
            state[e["key"]] = "old"; continue
        if tg(token, chat, fmt(e, top, bot)):
            state[e["key"]] = "sent"
    json.dump(state, open(STATE_FILE, "w"), indent=1)


if __name__ == "__main__":
    main()
