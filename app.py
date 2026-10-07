"""
core.py · מנוע הלוגיקה של Swing & Pivot 2.0

אין כאן תלות ב-Streamlit, כדי שגם alerts_worker.py (שרץ ברקע, בלי ממשק)
ישתמש בדיוק באותם כללים ובאותם חישובים כמו האפליקציה.
"""
from __future__ import annotations

import functools
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field, fields
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

# ════════════════════════════ קבועים ════════════════════════════
DATA_DIR = Path(os.getenv("SWING_DATA_DIR", Path(__file__).parent / "data"))
STORE_PATH = DATA_DIR / "store.json"
DEFAULT_TZ = "America/New_York"
CLOSE_HOUR = {"America/New_York": 16.0, "Asia/Jerusalem": 17.5, "Europe/London": 16.5}
SURGE_LOOKBACK = 10  # כמה נרות אחורה נחשבת "קפיצה" כעדכנית

UNIVERSES: dict[str, list[str]] = {
    "ארה״ב · ענקיות (≈100)": (
        "AAPL MSFT NVDA AMZN GOOGL META AVGO TSLA BRK-B LLY JPM V UNH XOM MA COST HD PG JNJ ABBV WMT NFLX BAC "
        "CRM ORCL CVX KO MRK AMD PEP TMO ADBE LIN ACN MCD CSCO ABT WFC TMUS DIS GE IBM QCOM TXN VZ CAT INTU AMGN "
        "PM ISRG NOW DHR GS UBER AMAT NEE T RTX SPGI LOW BKNG PFE HON UNP AXP BLK PGR C ETN COP LMT SYK MS TJX "
        "VRTX ADP BSX MDT PLD SCHW MMC SBUX CB GILD ADI MU LRCX BA DE KLAC CMG MO SO DUK ICE CME NKE UPS MMM GM F "
        "INTC CVS BMY ELV ZTS EQIX SHW PYPL MDLZ TGT"
    ).split(),
    "טכנולוגיה וצמיחה (≈60)": (
        "PLTR SNOW CRWD PANW NET DDOG ZS MDB SHOP COIN HOOD SOFI RBLX U TTD ROKU DASH ABNB SPOT ARM SMCI ANET MRVL "
        "ON MPWR ENPH FSLR TSM ASML SNPS CDNS FTNT WDAY TEAM HUBS ZM DOCU OKTA TWLO PINS SNAP AFRM UPST RIVN DKNG "
        "PATH APP DUOL CELH ELF ONON DECK AXON TOST GTLB RDDT"
    ).split(),
    "ישראליות בארה״ב": (
        "NICE CHKP CYBR WIX MNDY TEVA ESLT ICL GLBE FVRR SEDG NVMI TSEM CAMT INMD LMND PAYO RDWR SPNS KRNT ODD S AUDC"
    ).split(),
}


# ════════════════════════════ מטמון עם TTL ════════════════════════════
def ttl_cache(seconds: int):
    def deco(fn):
        store: dict = {}
        lock = threading.Lock()

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()
            with lock:
                hit = store.get(key)
                if hit and now - hit[0] < seconds:
                    return hit[1]
            val = fn(*args, **kwargs)
            empty = val is None or (hasattr(val, "empty") and val.empty) or (isinstance(val, (dict, list)) and not val)
            if not empty:
                with lock:
                    if len(store) > 300:
                        store.clear()
                    store[key] = (now, val)
            return val

        wrapper.clear = lambda: store.clear()  # type: ignore[attr-defined]
        return wrapper

    return deco


# ════════════════════════════ נתוני שוק ════════════════════════════
def tz_for(symbol: str) -> str:
    s = symbol.upper()
    if s.endswith(".TA"):
        return "Asia/Jerusalem"
    if s.endswith(".L"):
        return "Europe/London"
    return DEFAULT_TZ


def is_live(last_ts, tz: str) -> bool:
    """האם הנר היומי האחרון עדיין פתוח (השוק באמצע מסחר)? הערכה לפי שעות סגירה."""
    try:
        now = datetime.now(ZoneInfo(tz))
    except Exception:
        return False
    if now.weekday() >= 5:
        return False
    return pd.Timestamp(last_ts).date() == now.date() and (now.hour + now.minute / 60) < CLOSE_HOUR.get(tz, 16.0)


def _clean(sub: pd.DataFrame) -> pd.DataFrame | None:
    need = ["Open", "High", "Low", "Close"]
    if sub is None or sub.empty or any(c not in sub.columns for c in need):
        return None
    if "Volume" not in sub.columns:
        sub = sub.assign(Volume=0.0)
    sub = sub[need + ["Volume"]].dropna(subset=need).copy()
    sub["Volume"] = sub["Volume"].fillna(0.0)
    sub.index = pd.to_datetime(sub.index)
    if sub.index.tz is not None:
        sub.index = sub.index.tz_localize(None)
    sub = sub[~sub.index.duplicated()].sort_index()
    return sub if len(sub) >= 5 else None


def _split(raw: pd.DataFrame, symbols: tuple) -> dict:
    out: dict = {}
    if raw is None or raw.empty:
        return out
    cols = raw.columns
    for s in symbols:
        try:
            if isinstance(cols, pd.MultiIndex):
                if s in cols.get_level_values(0):
                    sub = raw[s]
                elif s in cols.get_level_values(1):
                    sub = raw.xs(s, axis=1, level=1)
                else:
                    continue
            else:
                if len(symbols) != 1:
                    continue
                sub = raw
            sub = _clean(sub)
            if sub is not None:
                out[s] = sub
        except Exception:
            continue
    return out


@ttl_cache(300)
def download_ohlc(symbols: tuple, period: str = "2y") -> dict:
    """מוריד נרות יומיים (מתואמי דיבידנד/פיצול) לכמה סימולים בקריאה אחת."""
    symbols = tuple(dict.fromkeys(s for s in symbols if s))
    if not symbols:
        return {}
    try:
        raw = yf.download(list(symbols), period=period, interval="1d", auto_adjust=True,
                          group_by="ticker", progress=False, threads=True)
    except Exception:
        return {}
    return _split(raw, symbols)


@ttl_cache(20)
def get_quote(symbol: str) -> dict | None:
    try:
        fi = yf.Ticker(symbol).fast_info
        last, prev = float(fi["last_price"]), float(fi["previous_close"])
        return {"last": last, "prev": prev, "pct": (last / prev - 1) * 100}
    except Exception:
        return None


@ttl_cache(3600)
def get_info(symbol: str) -> dict:
    try:
        return yf.Ticker(symbol).get_info() or {}
    except Exception:
        return {}


@ttl_cache(3600)
def get_insiders(symbol: str):
    try:
        return yf.Ticker(symbol).insider_transactions
    except Exception:
        return None


@ttl_cache(900)
def get_news(symbol: str) -> list:
    try:
        return yf.Ticker(symbol).news or []
    except Exception:
        return []


def parse_news(item: dict):
    c = item.get("content") or item
    url = (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url") or c.get("link")
    pub = (c.get("provider") or {}).get("displayName") or c.get("publisher")
    return c.get("title"), url, pub


def clean_symbol(s: str) -> str:
    return re.sub(r"[^A-Z0-9.\-^=]", "", (s or "").upper())[:15]


# ════════════════════════════ כללי הסווינג ════════════════════════════
@dataclass(frozen=True)
class Params:
    ma_len: int = 50          # הממוצע הראשי
    max_dist: float = 4.0     # מקס' מרחק (%) מהממוצע לכניסה
    fast_len: int = 6         # ממוצע מהיר לקפיצות
    surge_days: int = 4       # כמה נרות ירוקים רצופים
    surge_pct: float = 20.0   # עלייה מצטברת מינימלית (%)
    strict_fast: bool = False # האם גם ב-MA6 נדרש נר שלא נוגע בקו
    closed_only: bool = True  # להתבסס על נרות סגורים בלבד


def params_from_dict(d: dict | None) -> Params:
    d = d or {}
    kw = {}
    for f in fields(Params):
        if f.name in d:
            try:
                kw[f.name] = type(getattr(Params(), f.name))(d[f.name])
            except Exception:
                pass
    return Params(**kw)


def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    res = 100 - (100 / (1 + rs))
    return res.fillna(100)


def prepare(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    """מחשב ממוצעים ואת תנאי הכניסה/יציאה לכל נר."""
    d = df.copy()
    c = d["Close"]
    d["MA"] = c.rolling(p.ma_len).mean()
    d["MAF"] = c.rolling(p.fast_len).mean()
    d["MA200"] = c.rolling(200).mean()
    d["green"] = c > d["Open"]
    d["red"] = c < d["Open"]
    d["dist"] = (c / d["MA"] - 1) * 100
    d["buy"] = d["green"] & (d["Low"] > d["MA"]) & (d["dist"] <= p.max_dist)
    d["sell"] = d["red"] & (d["High"] < d["MA"])
    run = d["green"].astype(int).rolling(p.surge_days).sum() == p.surge_days
    d["surge_gain"] = (c / c.shift(p.surge_days) - 1) * 100
    d["surge"] = run & (d["surge_gain"] > p.surge_pct)
    d["sellf"] = d["red"] & ((d["High"] < d["MAF"]) if p.strict_fast else (c < d["MAF"]))
    d["RSI"] = rsi(c)
    d["VOLX"] = d["Volume"] / d["Volume"].rolling(20).mean().replace(0, np.nan)
    return d


def run_state(d: pd.DataFrame, start: int = 0, in_pos: bool = False, stop_on_exit: bool = False):
    """
    מכונת מצבים: כניסה לפי נר קנייה; ביציאה - MA50, אלא אם התרחשה קפיצה
    (4 ירוקים רצופים ו->20%) ואז היציאה עוברת ל-MA6.
    מחזיר (events, in_position, mode); event = (index, kind, mode_at_event)
    """
    buy, sell, sellf, surge = (d[k].to_numpy(dtype=bool) for k in ("buy", "sell", "sellf", "surge"))
    pos, mode, events = in_pos, "MA50", []
    for i in range(max(start, 0), len(d)):
        if not pos:
            if buy[i]:
                pos, mode = True, "MA50"
                events.append((i, "entry", mode))
        else:
            if surge[i] and mode == "MA50":
                mode = "MA6"
                events.append((i, "surge", mode))
            if sellf[i] if mode == "MA6" else sell[i]:
                events.append((i, "exit", mode))
                pos, mode = False, "MA50"
                if stop_on_exit:
                    break
    return events, pos, mode


@dataclass
class Eval:
    symbol: str = ""
    asof: str = ""
    live_dropped: bool = False
    price: float = 0.0
    ma: float = float("nan")
    maf: float = float("nan")
    dist: float = float("nan")
    conds: list = field(default_factory=list)       # (תווית, עבר?, פירוט)
    sell_conds: list = field(default_factory=list)
    met: int = 0
    entry: bool = False
    exit_hint: bool = False
    surge_now: bool = False
    surge_recent: bool = False
    surge_gain: float = float("nan")
    mode: str = "MA50"
    held_exit: bool = False
    held_exit_date: str | None = None
    held_surge_date: str | None = None
    rsi: float = float("nan")
    volx: float = float("nan")
    score: float = 0.0
    code: str = ""
    label: str = ""
    tone: str = "neutral"
    missing: str = ""
    d: pd.DataFrame | None = field(default=None, repr=False)


def attractiveness(d: pd.DataFrame, p: Params) -> float:
    """דירוג עזר (0–100) למניות שעומדות בכללי הכניסה: קרבה לקו, מגמה, נפח ו-RSI."""
    r = d.iloc[-1]
    dist_val = float(r["dist"])
    s = max(0.0, min(1.0, 1 - dist_val / p.max_dist)) * 40 if p.max_dist > 0 else 0.0
    try:
        s += 15 if d["MA"].iloc[-1] > d["MA"].iloc[-11] else 0
    except Exception:
        s += 7
    s += 7.5 if pd.isna(r["MA200"]) else (15 if r["Close"] > r["MA200"] else 0)
    s += 7.5 if pd.isna(r["VOLX"]) else min(max(r["VOLX"], 0) / 1.5, 1) * 15
    rs = r["RSI"]
    s += 0 if pd.isna(rs) else (15 if 45 <= rs <= 65 else 8 if 40 <= rs <= 72 else 0)
    return round(float(s), 0)


def evaluate(df: pd.DataFrame, p: Params, symbol: str = "", tz: str = DEFAULT_TZ,
             held_since: str | None = None) -> Eval | None:
    live_dropped = False
    if p.closed_only and len(df) > 1 and is_live(df.index[-1], tz):
        df, live_dropped = df.iloc[:-1], True
    if len(df) < p.ma_len + 3:
        return None
    d = prepare(df, p)
    r = d.iloc[-1]
    o, h, l, c = (float(r[k]) for k in ("Open", "High", "Low", "Close"))
    ma, maf = float(r["MA"]), float(r["MAF"])
    dist = float(r["dist"])
    n = p.ma_len

    conds = [
        ("נר ירוק", bool(r["green"]), f"פתיחה {o:,.2f} ← סגירה {c:,.2f}"),
        (f"מעל ממוצע {n}", c > ma, f"סגירה {c:,.2f} מול MA{n} {ma:,.2f}"),
        ("לא נוגע בממוצע", l > ma, f"השפל {l:,.2f} {'מעל' if l > ma else 'נוגע/מתחת ל'}קו"),
        (f"עד {p.max_dist:g}% מהקו", 0 < dist <= p.max_dist, f"מרחק {dist:+.1f}% (מקס׳ {p.max_dist:g}%)"),
    ]
    sell_conds = [
        ("נר אדום", bool(r["red"]), f"פתיחה {o:,.2f} ← סגירה {c:,.2f}"),
        (f"מתחת לממוצע {n}", c < ma, f"סגירה {c:,.2f} מול MA{n} {ma:,.2f}"),
        ("לא נוגע בממוצע", h < ma, f"השיא {h:,.2f} {'מתחת' if h < ma else 'נוגע/מעל'} לקו"),
    ]
    met = sum(x[1] for x in conds)
    recent = d["surge"].iloc[-SURGE_LOOKBACK:]
    surge_recent, surge_now = bool(recent.any()), bool(r["surge"])
    exit_hint = bool(r["sell"] or (surge_recent and r["sellf"]))

    ev = Eval(symbol=symbol, asof=str(d.index[-1].date()), live_dropped=live_dropped, price=c, ma=ma, maf=maf,
              dist=dist, conds=conds, sell_conds=sell_conds, met=met, entry=bool(r["buy"]), exit_hint=exit_hint,
              surge_now=surge_now, surge_recent=surge_recent, surge_gain=float(r["surge_gain"]),
              mode="MA6" if surge_recent else "MA50", rsi=float(r["RSI"]), volx=float(r["VOLX"]), d=d)

    if held_since:
        start = int(d.index.searchsorted(pd.Timestamp(held_since)))
        events, _, mode = run_state(d, start, in_pos=True, stop_on_exit=True)
        ev.mode = mode
        for i, kind, md in events:
            if kind == "exit":
                ev.held_exit, ev.held_exit_date, ev.mode = True, str(d.index[i].date()), md
            elif kind == "surge":
                ev.held_surge_date = str(d.index[i].date())

    failing = [x[0] for x in conds if not x[1]]
    ev.missing = " · ".join(failing)
    if ev.entry:
        ev.score = attractiveness(d, p)
        ev.code, ev.label, ev.tone = "ENTRY", "נקודת כניסה", "good"
    elif exit_hint:
        ev.code, ev.label, ev.tone = "EXIT", f"סימן יציאה — נר אדום מתחת ל-MA{n if not surge_recent else p.fast_len}", "bad"
    elif surge_recent:
        ev.code, ev.label, ev.tone = "SURGE", f"קפיצה חדה ({ev.surge_gain:+.0f}%) — לא רודפים, עוקבים עם MA{p.fast_len}", "warn"
    elif met == 3:
        ev.code, ev.label, ev.tone = "NEAR", f"קרובה לכניסה — חסר: {failing[0]}", "warn"
        ev.score = met * 10 - max(dist, 0) / 10
    elif c < ma:
        ev.code, ev.label = "BELOW", f"מתחת ל-MA{n} — לא קונים"
    elif l <= ma <= h:
        ev.code, ev.label = "TOUCH", f"נוגעת ב-MA{n} — ממתינים לנר נקי"
    elif dist > p.max_dist:
        ev.code, ev.label = "FAR", f"מרוחקת {dist:.1f}% מהקו — מעבר לטווח הכניסה"
    else:
        ev.code, ev.label = "WAIT", "ממתינים לתנאים"
    return ev


def scan_universe(symbols: list[str], p: Params) -> list[Eval]:
    syms = tuple(dict.fromkeys(clean_symbol(s) for s in symbols if clean_symbol(s)))
    out: list[Eval] = []
    for i in range(0, len(syms), 60):  # חבילות, כדי לא להעמיס
        data = download_ohlc(syms[i:i + 60], "1y")
        for s, df in data.items():
            ev = evaluate(df, p, s, tz_for(s))
            if ev:
                ev.d = None
                out.append(ev)
    return out


# ════════════════════════════ בקטסט ════════════════════════════
def backtest(df: pd.DataFrame, p: Params, fee: float = 0.0005) -> dict | None:
    """סימולציה של הכללים: אות בסגירת נר, ביצוע בפתיחת הנר הבא, עמלה לכל צד."""
    if len(df) < p.ma_len + 20:
        return None
    d = prepare(df, p)
    n = len(d)
    o, c = d["Open"].to_numpy(float), d["Close"].to_numpy(float)
    events, _, _ = run_state(d)
    ret = np.zeros(n)
    inpos = np.zeros(n, dtype=bool)
    trades, cur = [], None
    for i, kind, _m in events:
        if kind == "entry" and i + 1 < n:
            cur = {"a": i + 1}
        elif kind == "exit" and cur is not None:
            b = i + 1 if i + 1 < n else None
            cur["b"] = b
            trades.append(cur)
            cur = None
    if cur is not None:
        cur["b"] = None
        trades.append(cur)

    rows = []
    for t in trades:
        a, b = t["a"], t["b"]
        end = b if b is not None else n - 1
        for k in range(a, end + 1):
            inpos[k] = True
            if k == a:
                ret[k] = (c[k] / o[a] - 1) - fee if b != a else 0.0
            elif b is not None and k == b:
                ret[k] = (o[b] / c[k - 1] - 1) - fee
            else:
                ret[k] = c[k] / c[k - 1] - 1
        exit_px = o[b] if b is not None else c[-1]
        rows.append({
            "כניסה": d.index[a].date(), "יציאה": d.index[b].date() if b is not None else "פתוחה",
            "מחיר כניסה": o[a], "מחיר יציאה": exit_px,
            "תשואה %": ((exit_px / o[a]) * (1 - fee) ** 2 - 1) * 100,
            "ימים": end - a + 1,
        })

    warm = p.ma_len
    eq = pd.Series((1 + ret[warm:]).cumprod(), index=d.index[warm:])
    bh = pd.Series(c[warm:] / c[warm], index=d.index[warm:])
    tr = pd.DataFrame(rows)

    def stats(curve: pd.Series) -> dict:
        yrs = max(len(curve) / 252, 1e-9)
        r = curve.pct_change().dropna()
        return {
            "תשואה כוללת": f"{(curve.iloc[-1] - 1) * 100:.1f}%",
            "תשואה שנתית": f"{(curve.iloc[-1] ** (1 / yrs) - 1) * 100:.1f}%",
            "ירידה מקסימלית": f"{(curve / curve.cummax() - 1).min() * 100:.1f}%",
            "Sharpe": f"{r.mean() / r.std() * np.sqrt(252):.2f}" if r.std() > 0 else "—",
        }

    s_strat, s_bh = stats(eq), stats(bh)
    if not tr.empty:
        wins, losses = tr[tr["תשואה %"] > 0]["תשואה %"], tr[tr["תשואה %"] <= 0]["תשואה %"]
        s_strat["עסקאות"] = str(len(tr))
        s_strat["אחוז הצלחה"] = f"{len(wins) / len(tr) * 100:.0f}%"
        s_strat["ממוצע רווח / הפסד"] = f"{wins.mean() if len(wins) else 0:.1f}% / {losses.mean() if len(losses) else 0:.1f}%"
        s_strat["חשיפה לשוק"] = f"{inpos[warm:].mean() * 100:.0f}%"
    return {"equity": eq, "bh": bh, "trades": tr, "stats": pd.DataFrame({"השיטה": s_strat, "קנה והחזק": s_bh}),
            "events": [(d.index[i], k) for i, k, _ in events]}


# ════════════════════════════ אחסון והתראות ════════════════════════════
def _base_store() -> dict:
    return {"version": 2, "params": {}, "positions": [], "pivot": {}, "log": [],
            "notify": {"enabled": True, "auto": True, "ntfy_topic": "", "ntfy_server": "https://ntfy.sh",
                       "tg_token": "", "tg_chat": ""}}


def load_store() -> dict:
    data = _base_store()
    try:
        saved = json.loads(STORE_PATH.read_text("utf-8"))
        for k, v in saved.items():
            if isinstance(v, dict) and isinstance(data.get(k), dict):
                data[k].update(v)
            else:
                data[k] = v
    except Exception:
        pass
    return data


def save_store(data: dict) -> None:
    try:
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, STORE_PATH)
    except Exception as e:
        print(f"שגיאה בשמירת קובץ הנתונים: {e}")


def upsert_position(store: dict, symbol: str, status: str, entry_price: float | None = None,
                    since: str | None = None) -> dict:
    today = date.today().isoformat()
    for pos in store["positions"]:
        if pos["symbol"] == symbol:
            pos["status"] = status
            if status == "held":
                pos["since"] = since or pos.get("since") or today
                if entry_price:
                    pos["entry_price"] = entry_price
            pos["last_alert"] = None
            return pos
    pos = {"symbol": symbol, "status": status, "entry_price": entry_price or None,
           "since": (since or today) if status == "held" else None, "added": today, "last_alert": None}
    store["positions"].append(pos)
    return pos


def remove_position(store: dict, symbol: str) -> None:
    store["positions"] = [x for x in store["positions"] if x["symbol"] != symbol]


def notify_config(store: dict) -> dict:
    n = store.get("notify", {})
    return {
        "ntfy_topic": os.getenv("NTFY_TOPIC") or n.get("ntfy_topic", ""),
        "ntfy_server": os.getenv("NTFY_SERVER") or n.get("ntfy_server") or "https://ntfy.sh",
        "tg_token": os.getenv("TELEGRAM_TOKEN") or n.get("tg_token", ""),
        "tg_chat": os.getenv("TELEGRAM_CHAT_ID") or n.get("tg_chat", ""),
    }


def has_channel(cfg: dict) -> bool:
    return bool(cfg["ntfy_topic"] or (cfg["tg_token"] and cfg["tg_chat"]))


def send_notification(cfg: dict, title: str, message: str, priority: int = 3, tags: tuple = ()) -> list[str]:
    """שולח לכל ערוץ שהוגדר (ntfy ו/או Telegram). מחזיר תוצאה לכל ערוץ."""
    results = []
    if cfg["ntfy_topic"]:
        try:
            payload = {"topic": cfg["ntfy_topic"], "title": title, "message": message,
                       "priority": priority, "tags": list(tags)}
            r = requests.post(cfg["ntfy_server"].rstrip("/"), json=payload, timeout=10)
            results.append("ntfy ✓" if r.ok else f"ntfy ✗ ({r.status_code})")
        except Exception as e:
            results.append(f"ntfy ✗ ({type(e).__name__})")
    if cfg["tg_token"] and cfg["tg_chat"]:
        try:
            r = requests.post(f"https://api.telegram.org/bot{cfg['tg_token']}/sendMessage",
                              json={"chat_id": cfg["tg_chat"], "text": f"{title}\n{message}"}, timeout=10)
            results.append("Telegram ✓" if r.ok else f"Telegram ✗ ({r.status_code})")
        except Exception as e:
            results.append(f"Telegram ✗ ({type(e).__name__})")
    return results


ALERT_STYLE = {"entry": ("🟢 כניסה", 4, ("green_circle", "chart_with_upwards_trend")),
               "exit": ("🔴 יציאה", 5, ("red_circle", "chart_with_downwards_trend")),
               "surge": ("🚀 קפיצה", 3, ("rocket",))}


def alert_text(kind: str, ev: Eval, p: Params) -> tuple[str, str, int, tuple]:
    head, prio, tags = ALERT_STYLE[kind]
    n = p.ma_len
    if kind == "entry":
        msg = f"נר ירוק נקי מעל MA{n}: סגירה {ev.price:,.2f}, {ev.dist:.1f}% מהקו ({ev.ma:,.2f}). נר {ev.asof}."
    elif kind == "exit":
        line = "MA6" if ev.mode == "MA6" else f"MA{n}"
        msg = f"נר אדום מתחת ל-{line}: סגירה {ev.price:,.2f}. אות היציאה נקבע בנר {ev.held_exit_date}."
    else:
        msg = f"הקפיצה אותתה בנר {ev.held_surge_date}. היציאה עוברת ל-MA{p.fast_len} (נר אדום מתחתיו)."
    return f"{head} · {ev.symbol}", msg, prio, tags


def check_positions(store: dict, p: Params, send: bool = True) -> list[dict]:
    """בודק את כל הרשימה; שולח התראה רק פעם אחת לכל אות (לפי תאריך הנר)."""
    positions = store.get("positions", [])
    if not positions:
        return []
    data = download_ohlc(tuple(sorted({x["symbol"] for x in positions})), "2y")
    cfg = notify_config(store)
    can_send = bool(send and store["notify"].get("enabled", True) and has_channel(cfg))
    changed, out = False, []
    for pos in positions:
        sym, held = pos["symbol"], pos["status"] == "held"
        row = {"pos": pos, "ev": None, "kind": None, "sent": [], "error": None}
        out.append(row)
        df = data.get(sym)
        ev = evaluate(df, p, sym, tz_for(sym), held_since=pos.get("since") if held else None) if df is not None else None
        if ev is None:
            row["error"] = "אין מספיק נתונים"
            continue
        row["ev"] = ev
        kind = stamp = None
        if held and ev.held_exit:
            kind, stamp = "exit", ev.held_exit_date
        elif held and ev.held_surge_date:
            kind, stamp = "surge", ev.held_surge_date
        elif not held and ev.entry:
            kind, stamp = "entry", ev.asof
        row["kind"] = kind
        key = f"{kind}:{stamp}"
        if kind and can_send and pos.get("last_alert") != key:
            title, msg, prio, tags = alert_text(kind, ev, p)
            res = send_notification(cfg, title, msg, prio, tags)
            row["sent"] = res
            if any("✓" in x for x in res):
                pos["last_alert"] = key
                store["log"] = (store.get("log", []) + [{"t": datetime.now().isoformat(timespec="minutes"),
                                                         "symbol": sym, "kind": kind, "msg": msg}])[-50:]
                changed = True
    if changed:
        save_store(store)
    return out


# ════════════════════════════ מתחת לרדאר: מדדים ════════════════════════════
@dataclass(frozen=True)
class PivotParams:
    band: float = 1.7             # יחס מקס'/מין' שעדיין נחשב דשדוש
    min_flat_days: int = 252      # אורך דשדוש מינימלי (ימי מסחר)
    min_dd: float = 40.0          # ירידה מינימלית משיא 3 שנים (%)
    max_rise: float = 40.0        # עלייה מקסימלית משפל 52 שבועות (%)
    max_3m: float = 30.0          # עלייה מקסימלית ב-3 חודשים (%)
    insider_days: int = 180
    runway_min: int = 18
    seg_min: float = 25.0


def flat_days(close: np.ndarray, band: float) -> int:
    hi = lo = close[-1]
    n = 0
    for x in close[::-1]:
        hi, lo = max(hi, x), min(lo, x)
        if lo <= 0 or hi / lo > band:
            break
        n += 1
    return n


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    return df[name].astype(str) if name in df.columns else pd.Series("", index=df.index)


def insider_summary(ins, days: int = 180) -> dict:
    out = {"buys": 0, "sells": 0, "buyers": 0, "value": 0.0, "rows": None, "top_role": False}
    if ins is None or getattr(ins, "empty", True):
        return out
    try:
        df = ins.copy()
        dates = pd.to_datetime(df["Start Date"], errors="coerce") if "Start Date" in df.columns else pd.Series(pd.NaT, index=df.index)
        recent = dates >= (pd.Timestamp.now() - pd.Timedelta(days=days))
        df = df[recent.fillna(False)]
        if df.empty:
            return out
        txt = _col(df, "Text") + " " + _col(df, "Transaction")
        buy = txt.str.contains(r"purchase|\bbought\b|\bbuy\b", case=False, regex=True) & ~txt.str.contains("gift", case=False)
        sell = txt.str.contains(r"\bsale\b|\bsold\b|\bsell\b", case=False, regex=True)
        b = df[buy].copy()
        out["buys"], out["sells"] = int(buy.sum()), int(sell.sum())
        if not b.empty:
            out["buyers"] = int(_col(b, "Insider").nunique())
            val = pd.to_numeric(b["Value"], errors="coerce") if "Value" in b.columns else pd.Series(np.nan, index=b.index)
            if val.isna().any() and "Shares" in b.columns:
                px = _col(b, "Text").str.extract(r"price\s+([\d.]+)")[0].astype(float)
                val = val.fillna(pd.to_numeric(b["Shares"], errors="coerce") * px)
            out["value"] = float(val.fillna(0).sum())
            out["top_role"] = bool(_col(b, "Position").str.contains(r"CEO|Chief Exec|Director|Chair|CFO|President", case=False, regex=True).any())
            keep = [c for c in ("Insider", "Position", "Start Date", "Shares", "Value", "Text") if c in b.columns]
            out["rows"] = b[keep].head(15)
    except Exception:
        pass
    return out


def fundamentals(info: dict) -> dict:
    g = info.get
    cash, fcf, ocf = g("totalCash"), g("freeCashflow"), g("operatingCashflow")
    basis = fcf if fcf is not None else ocf
    if cash is None or basis is None:
        runway = None
    elif basis >= 0:
        runway = 999.0
    else:
        runway = float(cash) / (-basis / 12)
    shares, rev = g("sharesOutstanding"), g("totalRevenue")
    rps = g("revenuePerShare") or (rev / shares if rev and shares else None)
    pct = lambda k: (g(k) * 100 if g(k) is not None else None)
    return {"name": g("longName") or g("shortName"), "sector": g("sector"), "industry": g("industry"),
            "cash": cash, "debt": g("totalDebt"), "fcf": fcf, "runway": runway,
            "rev_growth": pct("revenueGrowth"), "gross_margin": pct("grossMargins"), "op_margin": pct("operatingMargins"),
            "ps": g("priceToSalesTrailing12Months"), "rps": rps, "mcap": g("marketCap"),
            "target": g("targetMeanPrice"), "summary": g("longBusinessSummary")}


def pivot_metrics(df: pd.DataFrame, info: dict, ins, pp: PivotParams) -> dict:
    c = df["Close"].dropna()
    cv = c.to_numpy(float)
    price = float(cv[-1])
    hi3 = float(c.tail(756).max())
    lo52 = float(c.tail(252).min())
    fd = flat_days(cv, pp.band)
    seg = c.tail(fd)
    m = {
        "price": price, "hi3": hi3, "dd": (price / hi3 - 1) * 100, "lo52": lo52, "rise52": (price / lo52 - 1) * 100,
        "ret3m": (price / cv[-64] - 1) * 100 if len(cv) > 64 else float("nan"),
        "ret12m": (price / cv[-253] - 1) * 100 if len(cv) > 253 else float("nan"),
        "flat_days": fd, "flat_lo": float(seg.min()), "flat_hi": float(seg.max()), "flat_start": c.index[-fd],
        "ins": insider_summary(ins, pp.insider_days),
    }
    m.update(fundamentals(info))
    m["dormant"] = fd >= pp.min_flat_days
    m["battered"] = m["dd"] <= -pp.min_dd
    m["quiet"] = m["rise52"] <= pp.max_rise and (np.isnan(m["ret3m"]) or m["ret3m"] <= pp.max_3m)
    m["insider_buy"] = m["ins"]["buys"] >= 1
    m["s1_met"] = int(m["dormant"]) + int(m["battered"]) + int(m["quiet"]) + int(m["insider_buy"])
    g, om = m["rev_growth"], m["op_margin"]
    m["maturity_suggested"] = 2 if g is None else 4 if (g >= 15 and (om or 0) > 0) else 3 if g >= 10 else 2
    return m


# ════════════════════════════ מתחת לרדאר: שאלון ושלבים ════════════════════════════
PARTS = {  # id: (כותרת, משקל, אייקון)
    1: ("מהות הפיבוט והסביבה התחרותית", 15, ":material/swap_horiz:"),
    2: ("ניקוי האורוות", 10, ":material/cleaning_services:"),
    3: ("ניתוח פיננסי", 25, ":material/account_balance:"),
    4: ("הון אנושי ואינסיידרים", 20, ":material/groups:"),
    5: ("הוכחות שוק וזרזים", 15, ":material/bolt:"),
    6: ("הערכת שווי מחדש", 10, ":material/sell:"),
    7: ("בדיקת הטיעון הדובי", 5, ":material/shield:"),
}
MATURITY = {1: "תכנון והצהרות", 2: "השקעות וניקוי אורוות", 3: "הכנסות ראשוניות ואימוץ", 4: "רווחיות ופריצה בשוק"}

QUESTIONS = [
    ("1.1", 1, "הפיבוט ברור: ממודל עסקי ישן בתעשייה אחת למודל חדש בשוק אחר",
     "מהו המודל הישן ובאיזו תעשייה, ולאיזה מודל חדש ובאיזה שוק החברה עוברת כעת?", None),
    ("1.2", 1, "יש טריגר ברור ל״למה דווקא עכשיו״",
     "דעיכה טבעית של השוק הישן, לחץ של משקיעים אקטיביסטים, שיבוש טכנולוגי כמו AI או משבר פיננסי.", None),
    ("1.3", 1, "החברה ממנפת נכסי עבר (דאטה, מותג, לקוחות) לבניית חפיר חדש, ולא מתחילה מאפס",
     "בניית החפיר (Moat) מחדש: האם היתרון התחרותי החדש נשען על נכסים מהעסק הישן?", None),
    ("2.1", 2, "יש אסטרטגיית יציאה ברורה מהעסק הישן",
     "מכירת חטיבות ומותגים להזרמת מזומנים, סגירת קווי ייצור ומחיקות חד-פעמיות, או דעיכה איטית שמממנת את החדש.", None),
    ("2.2", 2, "ההנהלה מוכנה להקריב הכנסות עבר בשביל העתיד, והשוק מגיב בשקט להתכווצות",
     "האם המנכ״ל מוכן להקטין באופן פעיל הכנסות מוכרות, וכיצד השוק מגיב להתכווצות הזמנית?", None),
    ("3.1", 3, "מזומנים לפחות ל-18 חודשים, בלי דילול מניות או חוב חדש",
     "בהתחשב בקצב שריפת המזומנים בגלל ההשקעה בפיבוט, האם הקופה מספיקה? (הערכה אוטומטית מהדוחות)", "runway"),
    ("3.2", 3, "המגזר החדש צומח מהר יותר מקצב הדעיכה של הישן",
     "כשמפרקים את הדוח הכספי: צמיחת המגזר החדש מול דעיכת הישן. (הערכה אוטומטית: צמיחת ההכנסות הכוללות)", "growth"),
    ("3.3", 3, "לעסק החדש פוטנציאל לשולי רווח גולמי ותפעולי גבוהים מהישן",
     "למשל מעבר מחומרה ותעשייה מסורתית לתוכנה, דאטה או שירותים דיגיטליים. (הערכה אוטומטית: שולי רווח גולמי נוכחיים)", "margin"),
    ("4.1", 4, "גויס מנכ״ל או CTO חדש מבחוץ עם רקורד הבראה או מומחיות בשוק החדש",
     "שינויי הנהלה: מי גויס ומה הרקורד שלו?", None),
    ("4.2", 4, "אינסיידרים קונים מניות בשוק הפתוח (Form 4), בסכומים משמעותיים",
     "רכישות אינסיידרים אחרי הכרזת הפיבוט. (הערכה אוטומטית מעסקאות ב-180 הימים האחרונים)", "insider"),
    ("4.3", 4, "תמריצי ההנהלה קשורים להצלחת המגזר החדש ולא למדדים הישנים",
     "למשל בונוס שמותנה בהגעה ליעד מכירות במוצר החדש.", None),
    ("5.1", 5, "נחתם חוזה, פיילוט או שותפות עם לקוח ענק ומבוסס בשוק החדש",
     "זו ההוכחה שהפיבוט אינו רק מצגת יחסי ציבור.", None),
    ("5.2", 5, "ב-Earnings Calls עברו מ״התייעלות וקיצוצים״ ל-KPIs חדשים לגמרי",
     "האם ההנהלה מציגה מדדי מפתח חדשים לחלוטין?", None),
    ("5.3", 5, "שאלות האנליסטים לא חשפו נתון שההנהלה נמנעה לדבר עליו (שקיפות)",
     "אם בסוף השיחה האנליסטים חשפו נתון מוסתר, ענה ״לא״.", None),
    ("5.4", 5, "יש זרז קרוב וברור שיוכיח שהפיבוט עובד",
     "השקת מוצר דגל, סיום מכירת חטיבה ישנה, או דוח רבעוני שבו המגזר החדש הופך לרוב ההכנסות.", None),
    ("6.1", 6, "המניה מתומחרת במכפילי תעשייה גוססת, למרות המעבר לתעשייה צומחת",
     "עיוות מכפילים היסטוריים. (הערכה אוטומטית: מכפיל מכירות P/S נמוך)", "ps"),
    ("6.2", 6, "יש פוטנציאל Re-Rating משמעותי אם הפיבוט יצליח",
     "לאיזה מכפיל מכירות/רווח החברה יכולה לזנק כשוול סטריט תסווג אותה מחדש? (חישוב אוטומטי מהמכפיל שתזין בלשונית שווי)", "rerate"),
    ("7.1", 7, "הפיבוט אינו מהלך של ייאוש",
     "הטיעון הדובי: זה מהלך של ייאוש. ענה ״כן״ אם אינך מזהה כך.", None),
    ("7.2", 7, "השוק החדש אינו צפוף ותחרותי מדי",
     "הטיעון הדובי: השוק החדש צפוף ותחרותי מדי.", None),
    ("7.3", 7, "הלקוחות הישנים אינם נוטשים מהר מהצפוי",
     "הטיעון הדובי: הלקוחות הישנים נוטשים מהר מהצפוי והמזומנים ייגמרו לפני שהעסק החדש ירוויח.", None),
]
Q_BY_ID = {q[0]: q for q in QUESTIONS}


def new_pivot_record() -> dict:
    return {"answers": {}, "s2": {"cash": None, "mgmt": None, "seg": None, "anchor": None},
            "maturity": None, "target_ps": None, "note": ""}


def auto_answers(m: dict, rec: dict, pp: PivotParams) -> dict:
    a: dict = {}
    rw = m.get("runway")
    if rw is not None:
        a["3.1"] = 2 if rw >= pp.runway_min else 1 if rw >= 12 else 0
    g = m.get("rev_growth")
    if g is not None:
        a["3.2"] = 2 if g >= 15 else 1 if g > 0 else 0
    gm = m.get("gross_margin")
    if gm is not None:
        a["3.3"] = 2 if gm >= 55 else 1 if gm >= 35 else 0
    ins = m["ins"]
    a["4.2"] = 2 if (ins["buys"] >= 3 or ins["buyers"] >= 2) else 1 if ins["buys"] >= 1 else 0
    ps = m.get("ps")
    if ps:
        a["6.1"] = 2 if ps <= 1.5 else 1 if ps <= 3.5 else 0
    up = rerate_upside(m, rec.get("target_ps"))
    if up is not None:
        a["6.2"] = 2 if up >= 100 else 1 if up >= 40 else 0
    return a


def rerate_upside(m: dict, target_ps: float | None) -> float | None:
    if not target_ps or not m.get("rps") or not m.get("price"):
        return None
    return (target_ps * m["rps"] / m["price"] - 1) * 100


def stage2_eval(m: dict, rec: dict, pp: PivotParams) -> dict:
    """צ'ק-ליסט שלב 2: ארבעה תנאים; ממשיכים לשלב 3 רק אם כולם ״כן״."""
    s2 = rec["s2"]
    rw = m.get("runway")
    cash_auto = None if rw is None else rw >= pp.runway_min
    cash = s2["cash"] if s2["cash"] is not None else cash_auto
    ins_buy = m["ins"]["buys"] >= 1
    mgmt = True if (s2["mgmt"] or ins_buy) else (False if s2["mgmt"] is False else None)
    if s2["seg"] is not None:
        seg, seg_src = s2["seg"] >= pp.seg_min, "ידני"
    elif m.get("rev_growth") is not None:
        seg, seg_src = m["rev_growth"] >= pp.seg_min, "מקורב מצמיחת ההכנסות הכוללות"
    else:
        seg, seg_src = None, "אין נתון"
    anchor = s2["anchor"]
    items = [
        {"id": "cash", "label": f"מזומנים ל-{pp.runway_min}+ חודשים", "value": cash,
         "detail": "תזרים חיובי" if rw == 999 else (f"≈{rw:.0f} חודשים" if rw is not None else "אין נתון — הזן ידנית")},
        {"id": "mgmt", "label": "הוחלפה הנהלה או שהמנהלים קנו מניות", "value": mgmt,
         "detail": f"{m['ins']['buys']} רכישות אינסיידרים ב-{pp.insider_days} ימים" if ins_buy else "אין רכישות; שינוי הנהלה — ידני"},
        {"id": "seg", "label": f"המגזר החדש צומח מהר (≥{pp.seg_min:g}%)", "value": seg, "detail": seg_src},
        {"id": "anchor", "label": "לקוח עוגן או שותף אסטרטגי גדול", "value": anchor, "detail": "ידני"},
    ]
    vals = [i["value"] for i in items]
    passed = False if any(v is False for v in vals) else (True if all(v is True for v in vals) else None)
    return {"items": items, "passed": passed}


def score_pivot(answers: dict, auto: dict) -> dict:
    eff = {}
    for q in QUESTIONS:
        v, src = answers.get(q[0]), "user"
        if v is None:
            v = auto.get(q[0])
            src = "auto" if v is not None else None
        eff[q[0]] = (v, src)
    parts = {}
    for pid, (title, w, _icon) in PARTS.items():
        vals = [eff[q[0]][0] for q in QUESTIONS if q[1] == pid and eff[q[0]][0] is not None]
        total_q = sum(1 for q in QUESTIONS if q[1] == pid)
        parts[pid] = {"score": sum(vals) / (2 * len(vals)) * 100 if vals else None,
                      "answered": len(vals), "total": total_q, "weight": w, "title": title}
    ws = [(x["score"], x["weight"]) for x in parts.values() if x["score"] is not None]
    total = sum(s * w for s, w in ws) / sum(w for _, w in ws) if ws else None
    answered = sum(x["answered"] for x in parts.values())
    return {"eff": eff, "parts": parts, "total": total, "completeness": answered / len(QUESTIONS)}


def verdict(stage2_passed, score, completeness, runway, maturity) -> tuple[str, str, str]:
    """(קוד, כותרת, טון) — מודל דירוג עזר, לא ייעוץ השקעות."""
    if stage2_passed is False:
        return "STOP", "עצור בשלב 2 — לא כל ארבעת התנאים התקיימו", "bad"
    if stage2_passed is None or score is None:
        return "PENDING", "השלם את צ׳ק-ליסט שלב 2", "neutral"
    if completeness < 0.5:
        return "INCOMPLETE", "מחקר חלקי — ענה על עוד שאלות לפסק דין", "neutral"
    short_cash = runway is not None and runway < 12
    if score >= 70 and not short_cash and maturity in (2, 3):
        return "OPPORTUNITY", "הזדמנות הבראה אפשרית", "good"
    if score >= 50:
        why = " (מזומנים קצרים מ-12 חודשים)" if short_cash else (" (שלב בשלות לא אידיאלי)" if maturity not in (2, 3) else "")
        return "WATCH", f"במעקב — מחקר נוסף או המתנה לזרז{why}", "warn"
    return "TRAP", "סיכון למלכודת ערך — להימנע", "bad"


def bull_bear(m: dict, sc: dict, s2: dict, pp: PivotParams) -> tuple[list[str], list[str]]:
    e = {k: v[0] for k, v in sc["eff"].items()}
    bull, bear = [], []
    if m["dd"] <= -pp.min_dd:
        bull.append(f"נסחרת במחיר רצפה: {m['dd']:.0f}% משיא 3 שנים, דשדוש של {m['flat_days'] / 252:.1f} שנים")
    rw = m.get("runway")
    if rw is not None and rw >= pp.runway_min:
        bull.append("מאזן חזק מספיק כדי לשרוד את השינוי" + ("" if rw == 999 else f" (≈{rw:.0f} חודשי מזומן)"))
    elif rw is not None:
        bear.append(f"המזומנים עלולים להיגמר לפני שהעסק החדש ירוויח (≈{rw:.0f} חודשים)")
    if m["ins"]["buys"] >= 1:
        bull.append(f"אינסיידרים קונים בכסף פרטי ({m['ins']['buys']} רכישות, ≈${m['ins']['value']:,.0f})")
    if e.get("5.1") == 2:
        bull.append("לקוחות גדולים כבר מאמצים את המוצר החדש")
    if e.get("1.3") == 2:
        bull.append("חפיר חדש נבנה על נכסי העבר")
    if e.get("6.2") == 2:
        bull.append("פוטנציאל Re-Rating גבוה אם הפיבוט יצליח")
    if e.get("7.1") == 0:
        bear.append("הפיבוט נראה כמהלך של ייאוש")
    if e.get("7.2") == 0:
        bear.append("השוק החדש צפוף ותחרותי מדי")
    if e.get("7.3") == 0:
        bear.append("הלקוחות הישנים נוטשים מהר מהצפוי")
    if e.get("5.1") == 0:
        bear.append("אין עדיין לקוח ענק או שותף שמוכיח את הפיבוט")
    if e.get("5.3") == 0:
        bear.append("האנליסטים חשפו נתון שההנהלה נמנעה מלדבר עליו")
    if m["fcf"] is not None and m["fcf"] < 0 and rw is not None and rw >= pp.runway_min:
        bear.append("שריפת מזומנים מתמשכת בזמן ההשקעה בפיבוט")
    if m["rev_growth"] is not None and m["rev_growth"] <= 0:
        bear.append(f"ההכנסות לא צומחות ({m['rev_growth']:.0f}%): החדש עדיין לא מפצה על הישן")
    if m["dd"] > -pp.min_dd:
        bear.append("המניה לא חבוטה מספיק — ייתכן שחלק מהסיפור כבר במחיר")
    return bull, bear


# ════════════════════════════ סורק שלב 1 ════════════════════════════
def stage1_scan(symbols: list[str], pp: PivotParams, progress=None) -> list[dict]:
    syms = tuple(dict.fromkeys(clean_symbol(s) for s in symbols if clean_symbol(s)))[:40]
    data = {}
    for i in range(0, len(syms), 20):
        data.update(download_ohlc(syms[i:i + 20], "5y"))
    rows = []
    for k, s in enumerate(syms):
        if progress:
            progress((k + 1) / max(len(syms), 1), s)
        df = data.get(s)
        if df is None or len(df) < 60:
            continue
        pre = pivot_metrics(df, {}, None, pp)
        # אינסיידרים רק אם עברו לפחות שני מבחני מחיר (חוסך קריאות רשת)
        if int(pre["dormant"]) + int(pre["battered"]) + int(pre["quiet"]) >= 2:
            pre = pivot_metrics(df, {}, get_insiders(s), pp)
        rows.append({"symbol": s, **{k2: pre[k2] for k2 in ("price", "dd", "rise52", "ret3m", "flat_days",
                                                            "dormant", "battered", "quiet", "insider_buy", "s1_met")},
                     "buys": pre["ins"]["buys"]})
    return sorted(rows, key=lambda r: (-r["s1_met"], r["dd"]))


# ════════════════════════════ הרצה בדיקה ════════════════════════════
if __name__ == "__main__":
    print("=== בדיקת תקינות מנוע הלוגיקה (core.py) ===")
    p = Params()
    test_symbols = ["AAPL", "NVDA", "TEVA"]
    print(f"מוריד נתונים ובודק מניות: {test_symbols}...")
    
    results = scan_universe(test_symbols, p)
    print(f"הבדיקה הסתיימה בהצלחה! עובדו {len(results)} מניות.")
    for res in results:
        print(f"• [{res.symbol}] מחיר: {res.price:,.2f} | סטטוס: {res.label} (קוד: {res.code})")
