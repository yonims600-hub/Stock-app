import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as bg

# הגדרות עמוד
st.set_page_config(page_title="Under The Radar & Swing", layout="wide")

# עיצוב מותאם לנייד
st.markdown("""
    <style>
    .main { direction: rtl; text-align: right; }
    div[data-testid="stMetricValue"] { font-size: 1.8rem; }
    </style>
""", unsafe_allow_html=True)

st.title("🎯 Under The Radar & Swing System")
st.caption("פלטפורמת ניתוח מניות, מדדים טכניים וצ'ק-ליסט פיבוט")

# סרגל צד - הראשי בטלפון
st.sidebar.header("⚙️ הגדרות ניתוח")
symbol = st.sidebar.text_input("הזן סימול מניה (Ticker):", value="AAPL").upper()

st.sidebar.markdown("---")
st.sidebar.subheader("📋 פרמטרים לצ'ק-ליסט")
cash_runway = st.sidebar.number_input("מסלול מזומנים (בחודשים):", min_value=0, value=18)
insider_buying = st.sidebar.checkbox("רכישות אינסיידרים / שינוי הנהלה?", value=True)
segment_growth = st.sidebar.number_input("צמיחת מגזר חדש (%):", min_value=0, value=35)
anchor_client = st.sidebar.checkbox("קיים לקוח עוגן / שותף אסטרטגי?", value=True)

# פונקציה לחישוב RSI
def compute_rsi(data, window=14):
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# טעינת נתונים בזמן אמת
if symbol:
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="6mo")
        
        if not df.empty:
            # חישוב מדדים
            df['SMA_50'] = df['Close'].rolling(window=50).mean()
            df['RSI'] = compute_rsi(df['Close'])
            
            curr_price = df['Close'].iloc[-1]
            curr_sma50 = df['SMA_50'].iloc[-1]
            curr_rsi = df['RSI'].iloc[-1]
            
            # חישוב ציון צ'ק-ליסט
            score = sum([
                cash_runway >= 18,
                insider_buying,
                segment_growth >= 25,
                anchor_client
            ])
            
            # תצוגת מטריקות
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("מחיר נוכחי", f"${curr_price:.2f}")
            col2.metric("SMA 50", f"${curr_sma50:.2f}" if not np.isnan(curr_sma50) else "N/A")
            col3.metric("RSI (14)", f"{curr_rsi:.1f}" if not np.isnan(curr_rsi) else "N/A")
            col4.metric("ציון פיבוט", f"{score} / 4")
            
            # לשוניות
            tab1, tab2, tab3 = st.tabs(["📈 ניתוח טכני", "📋 צ'ק-ליסט הבראה", "⚔️ שורים vs דובים"])
            
            with tab1:
                fig = bg.Figure()
                fig.add_trace(bg.Scatter(x=df.index, y=df['Close'], mode='lines', name='מחיר סגירה', line=dict(color='#00BFFF', width=2)))
                fig.add_trace(bg.Scatter(x=df.index, y=df['SMA_50'], mode='lines', name='SMA 50', line=dict(color='#FFD700', width=1.5, dash='dash')))
                fig.update_layout(title=f"גרף מחיר עבור {symbol}", template="plotly_dark", height=400, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True)
                
            with tab2:
                st.subheader("סטטוס תנאי סף לשינוי כיוון")
                st.write(f"{'✅' if cash_runway >= 18 else '❌'} מסלול מזומנים מעל 18 חודשים ({cash_runway} חודשים)")
                st.write(f"{'✅' if insider_buying else '❌'} רכישות אינסיידרים (Form 4) / שינוי בהנהלה")
                st.write(f"{'✅' if segment_growth >= 25 else '❌'} צמיחת מגזר חדש מעל 25% ({segment_growth}%)")
                st.write(f"{'✅' if anchor_client else '❌'} קיים לקוח עוגן או שותף אסטרטגי")
                
            with tab3:
                c1, c2 = st.columns(2)
                with c1:
                    st.success("🐂 **הטיעון השורי:**\n- תמחור חסר ברמות שפל.\n- מאזן נקי המאפשר ספיגת השינוי.\n- מוצר חדש שתופס תאוצה בשוק.")
                with c2:
                    st.error("🐻 **הטיעון הדובי:**\n- סיכון לשריפת מזומנים מוגברת.\n- שחיקה בקצב מהיר של העסק הישן.\n- תחרות גוברת בסקטור החדש.")
        else:
            st.error("לא נמצאו נתונים עבור הסימול שהזנת.")
    except Exception as e:
        st.error(f"שגיאה בטעינת הנתונים: {e}")
"""
🎯 Under The Radar & Swing Pro
פלטפורמת ניתוח מניות: גרף אינטראקטיבי, אינדיקטורים, צ'ק-ליסט פיבוט אוטומטי,
ניהול סיכונים, בקטסט, רשימת מעקב (כולל סנכרון Google Sheets) וחדשות.

הרצה:  streamlit run app.py
"""
from __future__ import annotations

import io
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from plotly.subplots import make_subplots

# ───────────────────────── הגדרות כלליות ─────────────────────────
st.set_page_config(
    page_title="Under The Radar & Swing Pro",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
.stApp, [data-testid="stSidebar"] { direction: rtl; }
.stMarkdown, label, p, h1, h2, h3, h4 { text-align: right; }
.js-plotly-plot, [data-testid="stDataFrame"], code { direction: ltr; text-align: left; }
.block-container { padding-top: 1.5rem; max-width: 1400px; }
div[data-testid="stMetric"] {
    background: linear-gradient(135deg, rgba(0,191,255,.10), rgba(255,215,0,.05));
    border: 1px solid rgba(255,255,255,.08);
    border-radius: 16px; padding: 12px 16px;
}
div[data-testid="stMetricValue"] { font-size: 1.55rem; font-weight: 700; direction: ltr; text-align: right; }
.verdict { padding: 14px 18px; border-radius: 14px; font-weight: 700; margin: 8px 0 16px; }
.v-good { background: rgba(38,166,154,.18); border: 1px solid #26a69a; }
.v-mid  { background: rgba(255,215,0,.12);  border: 1px solid #FFD700; }
.v-bad  { background: rgba(239,83,80,.15);  border: 1px solid #ef5350; }
@media (max-width: 640px) { div[data-testid="stMetricValue"] { font-size: 1.25rem; } }
</style>
""",
    unsafe_allow_html=True,
)

PERIODS = {"חודש": "1mo", "3 חודשים": "3mo", "6 חודשים": "6mo", "שנה": "1y",
           "שנתיים": "2y", "5 שנים": "5y", "מקסימום": "max"}
PERIOD_ORDER = ["1mo", "3mo", "6mo", "1y", "2y", "5y", "max"]
INTERVALS = {"יומי": "1d", "שבועי": "1wk", "שעה": "1h", "15 דקות": "15m"}
INTERVAL_LIMIT = {"15m": "1mo", "1h": "1y"}  # מגבלות Yahoo לנתוני תוך-יום
BARS_PER_YEAR = {"1d": 252, "1wk": 52, "1h": 1638, "15m": 6552}
MARKETS = {"S&P 500": "^GSPC", "Nasdaq": "^IXIC", "VIX": "^VIX",
           "ת״א 125": "^TA125.TA", "דולר/שקל": "ILS=X", "Bitcoin": "BTC-USD"}


# ───────────────────────── שכבת נתונים ─────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def load_history(symbol: str, period: str, interval: str) -> pd.DataFrame:
    df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)
    if df.empty:
        return df
    df = df[~df.index.duplicated()]
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


@st.cache_data(ttl=10, show_spinner=False)
def get_quote(symbol: str) -> dict | None:
    try:
        fi = yf.Ticker(symbol).fast_info
        last, prev = float(fi["last_price"]), float(fi["previous_close"])
        return {"last": last, "prev": prev, "pct": (last / prev - 1) * 100}
    except Exception:
        return None


@st.cache_data(ttl=900, show_spinner=False)
def load_info(symbol: str) -> dict:
    try:
        return yf.Ticker(symbol).get_info() or {}
    except Exception:
        return {}


@st.cache_data(ttl=3600, show_spinner=False)
def load_insiders(symbol: str):
    try:
        return yf.Ticker(symbol).insider_transactions
    except Exception:
        return None


@st.cache_data(ttl=900, show_spinner=False)
def load_news(symbol: str) -> list:
    try:
        return yf.Ticker(symbol).news or []
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def load_multi(tickers: tuple, period: str = "1y") -> pd.DataFrame:
    data = yf.download(list(tickers), period=period, interval="1d",
                       auto_adjust=True, progress=False, group_by="column")
    close = data["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    return close.dropna(how="all")


def fit_period(period: str, interval: str) -> tuple[str, bool]:
    limit = INTERVAL_LIMIT.get(interval)
    if limit and PERIOD_ORDER.index(period) > PERIOD_ORDER.index(limit):
        return limit, True
    return period, False


# ───────────────────────── אינדיקטורים ─────────────────────────
def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c = d["Close"]
    for n in (20, 50, 200):
        d[f"SMA{n}"] = c.rolling(n).mean()
    d["EMA21"] = c.ewm(span=21, adjust=False).mean()
    d["RSI"] = rsi(c)
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    d["MACD"] = macd
    d["MACD_SIG"] = macd.ewm(span=9, adjust=False).mean()
    d["MACD_H"] = d["MACD"] - d["MACD_SIG"]
    std = c.rolling(20).std()
    d["BB_U"], d["BB_L"] = d["SMA20"] + 2 * std, d["SMA20"] - 2 * std
    pc = c.shift()
    tr = pd.concat([d["High"] - d["Low"], (d["High"] - pc).abs(), (d["Low"] - pc).abs()], axis=1).max(axis=1)
    d["ATR"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    return d


def technical_signals(d: pd.DataFrame) -> tuple[list, float]:
    l = d.iloc[-1]
    items = [
        ("מחיר מעל SMA50", None if pd.isna(l.SMA50) else l.Close > l.SMA50),
        ("SMA50 מעל SMA200 (Golden Cross)", None if pd.isna(l.SMA200) else l.SMA50 > l.SMA200),
        ("RSI בטווח בריא (45–70)", None if pd.isna(l.RSI) else 45 <= l.RSI <= 70),
        ("MACD מעל קו האות", None if pd.isna(l.MACD_SIG) else l.MACD > l.MACD_SIG),
        ("נפח 5 ימים מעל ממוצע 20", None if len(d) < 20 else d.Volume.tail(5).mean() > d.Volume.tail(20).mean()),
    ]
    valid = [bool(ok) for _, ok in items if ok is not None]
    return items, (sum(valid) / len(valid) * 100 if valid else 0.0)


# ───────────────────────── פונדמנטלס וצ'ק-ליסט ─────────────────────────
def fmt(v, kind="n") -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    if kind == "big":
        for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
            if abs(v) >= div:
                return f"${v / div:,.2f}{suf}"
        return f"${v:,.0f}"
    if kind == "pct":
        return f"{v * 100:.1f}%"
    if kind == "usd":
        return f"${v:,.2f}"
    return f"{v:,.2f}"


def auto_pivot_inputs(info: dict, insiders) -> dict:
    cash, fcf = info.get("totalCash"), info.get("freeCashflow")
    if cash is not None and fcf is not None:
        runway = 120 if fcf >= 0 else min(120, int(cash / (-fcf / 12)))
    else:
        runway = 0
    insider = False
    try:
        if insiders is not None and not insiders.empty:
            df = insiders.copy()
            if "Start Date" in df:
                df = df[pd.to_datetime(df["Start Date"], errors="coerce") >= pd.Timestamp.now() - pd.Timedelta(days=180)]
            txt = df.get("Text", pd.Series("", index=df.index)).astype(str) + " " + \
                df.get("Transaction", pd.Series("", index=df.index)).astype(str)
            insider = bool(txt.str.contains("purchase|buy", case=False).any())
    except Exception:
        pass
    growth = (info.get("revenueGrowth") or 0) * 100
    return {"runway": runway, "insider": insider, "growth": round(float(growth), 1)}


def parse_news(item: dict):
    c = item.get("content") or item
    url = (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url") or c.get("link")
    pub = (c.get("provider") or {}).get("displayName") or c.get("publisher")
    return c.get("title"), url, pub


# ───────────────────────── בקטסט וסטטיסטיקות ─────────────────────────
def backtest_sma(close: pd.Series, fast: int, slow: int, fee: float = 0.001):
    pos = (close.rolling(fast).mean() > close.rolling(slow).mean()).astype(int).shift(1).fillna(0)
    ret = close.pct_change().fillna(0)
    strat = pos * ret - pos.diff().abs().fillna(0) * fee
    return (1 + strat).cumprod(), (1 + ret).cumprod(), int(pos.diff().abs().sum())


def perf_stats(eq: pd.Series, ppy: int) -> dict:
    years = max(len(eq) / ppy, 1e-9)
    r = eq.pct_change().dropna()
    return {
        "תשואה כוללת": f"{(eq.iloc[-1] - 1) * 100:.1f}%",
        "תשואה שנתית": f"{(eq.iloc[-1] ** (1 / years) - 1) * 100:.1f}%",
        "ירידה מקסימלית": f"{(eq / eq.cummax() - 1).min() * 100:.1f}%",
        "Sharpe": f"{(r.mean() / r.std() * np.sqrt(ppy)):.2f}" if r.std() > 0 else "—",
    }


# ───────────────────────── גרף ─────────────────────────
def build_chart(d: pd.DataFrame, chart_type: str, overlays: list, daily: bool) -> go.Figure:
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.025,
                        row_heights=[0.55, 0.15, 0.15, 0.15])
    if chart_type == "נרות":
        fig.add_trace(go.Candlestick(x=d.index, open=d.Open, high=d.High, low=d.Low, close=d.Close,
                                     name="מחיר", increasing_line_color="#26a69a",
                                     decreasing_line_color="#ef5350"), 1, 1)
    else:
        fig.add_trace(go.Scatter(x=d.index, y=d.Close, name="מחיר", line=dict(color="#00BFFF", width=2)), 1, 1)

    colors = {"SMA20": "#9C27B0", "SMA50": "#FFD700", "SMA200": "#FF7043", "EMA21": "#4DD0E1"}
    for name in overlays:
        if name == "Bollinger":
            fig.add_trace(go.Scatter(x=d.index, y=d.BB_U, name="BB עליון", line=dict(width=1, color="rgba(180,180,255,.6)")), 1, 1)
            fig.add_trace(go.Scatter(x=d.index, y=d.BB_L, name="BB תחתון", line=dict(width=1, color="rgba(180,180,255,.6)"),
                                     fill="tonexty", fillcolor="rgba(180,180,255,.08)"), 1, 1)
        else:
            fig.add_trace(go.Scatter(x=d.index, y=d[name], name=name, line=dict(width=1.5, color=colors[name])), 1, 1)

    tail = d.tail(60)
    for lvl, lbl in ((tail.High.max(), "התנגדות"), (tail.Low.min(), "תמיכה")):
        fig.add_hline(y=lvl, line_dash="dot", line_color="rgba(255,255,255,.35)",
                      annotation_text=f"{lbl} {lvl:,.2f}", annotation_position="top left", row=1, col=1)

    vol_colors = np.where(d.Close >= d.Open, "#26a69a", "#ef5350")
    fig.add_trace(go.Bar(x=d.index, y=d.Volume, marker_color=vol_colors, name="נפח", showlegend=False), 2, 1)

    fig.add_trace(go.Scatter(x=d.index, y=d.RSI, name="RSI", line=dict(color="#FFD700", width=1.5)), 3, 1)
    for y, col in ((70, "#ef5350"), (30, "#26a69a")):
        fig.add_hline(y=y, line_dash="dot", line_color=col, row=3, col=1)

    fig.add_trace(go.Bar(x=d.index, y=d.MACD_H, name="Hist",
                         marker_color=np.where(d.MACD_H >= 0, "#26a69a", "#ef5350")), 4, 1)
    fig.add_trace(go.Scatter(x=d.index, y=d.MACD, name="MACD", line=dict(color="#00BFFF", width=1.2)), 4, 1)
    fig.add_trace(go.Scatter(x=d.index, y=d.MACD_SIG, name="Signal", line=dict(color="#FF7043", width=1.2)), 4, 1)

    fig.update_layout(template="plotly_dark", height=780, margin=dict(l=8, r=8, t=30, b=8),
                      legend=dict(orientation="h", y=1.03), xaxis_rangeslider_visible=False,
                      hovermode="x unified", dragmode="pan",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    fig.update_yaxes(title_text="RSI", row=3, col=1, range=[0, 100])
    if daily:
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    return fig


PLOT_CFG = {"scrollZoom": True, "displaylogo": False}

# ───────────────────────── סרגל צד (חלק 1) ─────────────────────────
with st.sidebar:
    st.header("⚙️ הגדרות")
    symbol = st.text_input("סימול מניה (Ticker)", value=st.query_params.get("symbol", "AAPL")).strip().upper()
    period_label = st.selectbox("טווח", list(PERIODS), index=3)
    interval_label = st.selectbox("רזולוציה", list(INTERVALS), index=0)
    chart_type = st.radio("סוג גרף", ["נרות", "קו"], horizontal=True)
    overlays = st.multiselect("שכבות על הגרף", ["SMA20", "SMA50", "SMA200", "EMA21", "Bollinger"],
                              default=["SMA50", "SMA200"])
    live = st.toggle("🔴 רענון חי", value=True)
    refresh = st.select_slider("תדירות רענון (שניות)", [15, 30, 60, 120], value=30)

if not symbol:
    st.info("הזן סימול מניה בסרגל הצד כדי להתחיל.")
    st.stop()
st.query_params["symbol"] = symbol  # קישור שיתוף: ?symbol=NVDA

# ───────────────────────── כותרת + נתונים חיים ─────────────────────────
st.title("🎯 Under The Radar & Swing Pro")
st.caption("ניתוח טכני, צ'ק-ליסט פיבוט אוטומטי, ניהול סיכונים ובקטסט במקום אחד")


@st.fragment(run_every=refresh if live else None)
def live_header(sym: str):
    q = get_quote(sym)
    c1, c2 = st.columns([2, 3])
    if q:
        c1.metric(f"{sym} · מחיר חי", f"${q['last']:,.2f}", f"{q['pct']:+.2f}%")
    else:
        c1.metric(f"{sym} · מחיר חי", "N/A")
    c2.caption(f"עודכן: {datetime.now():%H:%M:%S}  ·  הנתונים של Yahoo עשויים להיות מושהים עד ~15 דקות בבורסות מסוימות")
    with st.expander("🌍 שווקים עולמיים"):
        cols = st.columns(3)
        for i, (name, s) in enumerate(MARKETS.items()):
            mq = get_quote(s)
            cols[i % 3].metric(name, f"{mq['last']:,.2f}" if mq else "N/A", f"{mq['pct']:+.2f}%" if mq else None)


live_header(symbol)

links = {
    "Yahoo Finance": f"https://finance.yahoo.com/quote/{symbol}",
    "Google": f"https://www.google.com/search?q={symbol}+stock",
    "TradingView": f"https://www.tradingview.com/symbols/{symbol}/",
    "Finviz": f"https://finviz.com/quote.ashx?t={symbol}",
}
for col, (name, url) in zip(st.columns(len(links)), links.items()):
    col.link_button(f"↗ {name}", url, use_container_width=True)

# ───────────────────────── טעינת נתונים ─────────────────────────
period, adjusted = fit_period(PERIODS[period_label], INTERVALS[interval_label])
interval = INTERVALS[interval_label]
if adjusted:
    st.warning(f"ברזולוציה {interval_label} Yahoo מאפשר טווח מוגבל – הטווח הותאם אוטומטית.")

try:
    with st.spinner("טוען נתונים..."):
        raw = load_history(symbol, period, interval)
except Exception as e:
    st.error(f"שגיאה בטעינת הנתונים: {e}")
    st.stop()
if raw.empty:
    st.error("לא נמצאו נתונים עבור הסימול שהזנת.")
    st.stop()

d = add_indicators(raw)
last = d.iloc[-1]
info = load_info(symbol)
insiders = load_insiders(symbol)
auto = auto_pivot_inputs(info, insiders)

# ───────────────────────── סרגל צד (חלק 2) ─────────────────────────
with st.sidebar:
    st.divider()
    st.subheader("📋 פרמטרי צ'ק-ליסט")
    st.caption("ערכים מחושבים אוטומטית מהנתונים; ניתן לדרוס ידנית.")
    cash_runway = st.number_input("מסלול מזומנים (חודשים)", 0, 600, int(auto["runway"]), key=f"cr_{symbol}")
    insider_buying = st.checkbox("רכישות אינסיידרים (6 חודשים)", value=auto["insider"], key=f"ib_{symbol}")
    segment_growth = st.number_input("צמיחת הכנסות (%)", -100.0, 1000.0, float(auto["growth"]), 1.0, key=f"sg_{symbol}")
    anchor_client = st.checkbox("קיים לקוח עוגן / שותף אסטרטגי?", value=False, key=f"ac_{symbol}")
    min_runway = st.slider("סף מסלול מזומנים", 6, 36, 18)
    min_growth = st.slider("סף צמיחה (%)", 5, 60, 25)
    st.divider()
    st.download_button("⬇️ CSV", d.to_csv().encode("utf-8-sig"), f"{symbol}.csv", "text/csv", use_container_width=True)
    try:
        buf = io.BytesIO()
        d.to_excel(buf, sheet_name=symbol[:30])
        st.download_button("⬇️ Excel", buf.getvalue(), f"{symbol}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)
    except Exception:
        pass

# ───────────────────────── ציונים ─────────────────────────
tech_items, tech_score = technical_signals(d)
tech_confirm = bool(not pd.isna(last.SMA50) and last.Close > last.SMA50 and not pd.isna(last.RSI) and last.RSI > 50)
checklist = [
    (f"מסלול מזומנים ≥ {min_runway} חודשים", cash_runway >= min_runway,
     "FCF חיובי" if cash_runway >= 120 else f"{cash_runway} חודשים"),
    ("רכישות אינסיידרים / שינוי הנהלה", insider_buying, "Form 4"),
    (f"צמיחת הכנסות ≥ {min_growth}%", segment_growth >= min_growth, f"{segment_growth:.1f}%"),
    ("לקוח עוגן / שותף אסטרטגי", anchor_client, "ידני"),
    ("אישור טכני (מעל SMA50 ו-RSI>50)", tech_confirm, f"RSI {last.RSI:.0f}" if not pd.isna(last.RSI) else "—"),
]
score = sum(ok for _, ok, _ in checklist)

m = st.columns(4)
m[0].metric("SMA 50", fmt(last.SMA50, "usd"))
m[1].metric("RSI (14)", f"{last.RSI:.1f}" if not pd.isna(last.RSI) else "N/A")
m[2].metric("ציון טכני", f"{tech_score:.0f}/100")
m[3].metric("ציון פיבוט", f"{score} / {len(checklist)}")

# ───────────────────────── לשוניות ─────────────────────────
tabs = st.tabs(["📈 גרף", "🎯 פיבוט ושור/דוב", "🧠 פונדמנטלס", "🛡️ ניהול סיכונים",
                "🧪 בקטסט", "👀 מעקב", "📰 חדשות"])

# ── גרף
with tabs[0]:
    st.plotly_chart(build_chart(d, chart_type, overlays, interval == "1d"),
                    use_container_width=True, config=PLOT_CFG)
    with st.expander("סיגנלים טכניים"):
        for label, ok in tech_items:
            st.write(f"{'➖' if ok is None else '✅' if ok else '❌'} {label}")

# ── פיבוט + שור/דוב
with tabs[1]:
    st.subheader("סטטוס תנאי סף לשינוי כיוון")
    st.progress(score / len(checklist))
    cls, txt = (("v-good", "🟢 מועמד חזק לפיבוט") if score >= 4 else
                ("v-mid", "🟡 במעקב – חסרים תנאים") if score == 3 else
                ("v-bad", "🔴 מוקדם מדי"))
    st.markdown(f'<div class="verdict {cls}">{txt}</div>', unsafe_allow_html=True)
    for label, ok, detail in checklist:
        st.write(f"{'✅' if ok else '❌'} {label} — {detail}")

    bulls, bears = [], []
    (bulls if tech_confirm else bears).append("מומנטום טכני חיובי" if tech_confirm else "חוסר אישור טכני")
    if not pd.isna(last.RSI):
        if last.RSI > 70:
            bears.append(f"RSI {last.RSI:.0f} – קנייה יתר")
        elif last.RSI < 30:
            bulls.append(f"RSI {last.RSI:.0f} – מכירת יתר, פוטנציאל ריבאונד")
    if not pd.isna(last.MACD_SIG):
        (bulls if last.MACD > last.MACD_SIG else bears).append("MACD מעל קו האות" if last.MACD > last.MACD_SIG else "MACD מתחת לקו האות")
    target = info.get("targetMeanPrice")
    if target:
        up = target / last.Close - 1
        (bulls if up > 0.10 else bears if up < 0 else []).append(f"יעד אנליסטים ${target:,.0f} ({up * 100:+.0f}%)")
    if (info.get("forwardPE") and info.get("trailingPE")) and info["forwardPE"] < info["trailingPE"]:
        bulls.append("P/E עתידי נמוך מההיסטורי – צפי לצמיחת רווחים")
    if segment_growth >= min_growth:
        bulls.append(f"צמיחת הכנסות {segment_growth:.0f}%")
    elif segment_growth < 0:
        bears.append(f"הכנסות מתכווצות ({segment_growth:.0f}%)")
    if insider_buying:
        bulls.append("רכישות אינסיידרים")
    if info.get("freeCashflow") is not None and info["freeCashflow"] < 0:
        bears.append(f"שריפת מזומנים – מסלול ~{cash_runway} חודשים")
    if (info.get("debtToEquity") or 0) > 150:
        bears.append(f"מינוף גבוה (D/E {info['debtToEquity']:.0f}%)")
    if (info.get("shortPercentOfFloat") or 0) > 0.10:
        bears.append(f"שורט גבוה ({info['shortPercentOfFloat'] * 100:.0f}% מהפלואט)")

    c1, c2 = st.columns(2)
    c1.success("🐂 **הטיעון השורי**\n\n" + ("\n".join(f"- {b}" for b in bulls) or "- אין נקודות בולטות"))
    c2.error("🐻 **הטיעון הדובי**\n\n" + ("\n".join(f"- {b}" for b in bears) or "- אין נקודות בולטות"))

# ── פונדמנטלס
with tabs[2]:
    st.subheader(info.get("longName", symbol))
    st.caption(f"{info.get('sector', '—')} · {info.get('industry', '—')}")
    hi, lo = info.get("fiftyTwoWeekHigh"), info.get("fiftyTwoWeekLow")
    if hi and lo and hi > lo:
        st.write(f"טווח 52 שבועות: ${lo:,.2f} – ${hi:,.2f}")
        st.progress(float(np.clip((last.Close - lo) / (hi - lo), 0, 1)))
    stats = [
        ("שווי שוק", fmt(info.get("marketCap"), "big")), ("P/E", fmt(info.get("trailingPE"))),
        ("P/E עתידי", fmt(info.get("forwardPE"))), ("Beta", fmt(info.get("beta"))),
        ("מזומן", fmt(info.get("totalCash"), "big")), ("חוב", fmt(info.get("totalDebt"), "big")),
        ("תזרים חופשי", fmt(info.get("freeCashflow"), "big")), ("שולי רווח", fmt(info.get("profitMargins"), "pct")),
        ("תשואת דיבידנד", fmt(info.get("dividendYield"), "pct") if (info.get("dividendYield") or 0) < 1 else f"{info['dividendYield']:.2f}%"),
        ("יעד אנליסטים", fmt(info.get("targetMeanPrice"), "usd")),
        ("המלצה", str(info.get("recommendationKey", "—")).upper()), ("שורט מהפלואט", fmt(info.get("shortPercentOfFloat"), "pct")),
    ]
    for i in range(0, len(stats), 3):
        for col, (k, v) in zip(st.columns(3), stats[i:i + 3]):
            col.metric(k, v)
    if insiders is not None and not insiders.empty:
        with st.expander("עסקאות אינסיידרים אחרונות"):
            st.dataframe(insiders.head(20), use_container_width=True)
    if info.get("longBusinessSummary"):
        with st.expander("על החברה"):
            st.write(info["longBusinessSummary"])

# ── ניהול סיכונים
with tabs[3]:
    st.subheader("מחשבון גודל פוזיציה")
    c1, c2 = st.columns(2)
    account = c1.number_input("גודל תיק ($)", 1000.0, value=25000.0, step=1000.0)
    risk_pct = c2.slider("סיכון לעסקה (% מהתיק)", 0.25, 5.0, 1.0, 0.25)
    entry = c1.number_input("מחיר כניסה", 0.01, value=float(round(last.Close, 2)), key=f"entry_{symbol}")
    atr_mult = c2.slider("מכפיל ATR לסטופ", 0.5, 5.0, 2.0, 0.5)
    rr = st.slider("יחס סיכוי-סיכון (R:R)", 1.0, 5.0, 2.0, 0.5)
    atr = last.ATR if not pd.isna(last.ATR) else 0.0
    stop = entry - atr_mult * atr
    risk_ps = entry - stop
    if risk_ps > 0:
        shares = int(min(account * risk_pct / 100 / risk_ps, account / entry))
        target_px = entry + rr * risk_ps
        r1 = st.columns(3)
        r1[0].metric("סטופ", f"${stop:,.2f}")
        r1[1].metric("יעד", f"${target_px:,.2f}")
        r1[2].metric("כמות מניות", f"{shares:,}")
        r2 = st.columns(3)
        r2[0].metric("שווי פוזיציה", f"${shares * entry:,.0f}")
        r2[1].metric("הפסד מקסימלי", f"-${shares * risk_ps:,.0f}")
        r2[2].metric("רווח פוטנציאלי", f"+${shares * risk_ps * rr:,.0f}")
        st.progress(float(min(shares * entry / account, 1.0)), text=f"{shares * entry / account * 100:.0f}% מהתיק")
    else:
        st.info("אין מספיק נתונים לחישוב ATR.")

# ── בקטסט
with tabs[4]:
    st.subheader("בקטסט: חציית ממוצעים נעים")
    st.caption("לתוצאות משמעותיות מומלץ טווח של שנתיים ומעלה. כולל עמלה של 0.1% לעסקה.")
    c1, c2 = st.columns(2)
    fast = c1.slider("ממוצע מהיר", 5, 50, 20)
    slow = c2.slider("ממוצע איטי", 20, 200, 50)
    if fast >= slow:
        st.warning("הממוצע המהיר חייב להיות קטן מהאיטי.")
    elif len(raw) <= slow + 5:
        st.warning("אין מספיק נתונים לטווח הנבחר – הגדל את הטווח בסרגל הצד.")
    else:
        eq, bh, trades = backtest_sma(raw["Close"], fast, slow)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=eq.index, y=eq, name="אסטרטגיה", line=dict(color="#FFD700", width=2)))
        fig.add_trace(go.Scatter(x=bh.index, y=bh, name="קנה והחזק", line=dict(color="#00BFFF", width=1.5)))
        fig.update_layout(template="plotly_dark", height=380, margin=dict(l=8, r=8, t=20, b=8),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True, config=PLOT_CFG)
        ppy = BARS_PER_YEAR[interval]
        st.dataframe(pd.DataFrame({"אסטרטגיה": perf_stats(eq, ppy), "קנה והחזק": perf_stats(bh, ppy)}),
                     use_container_width=True)
        st.caption(f"מספר מעברי פוזיציה: {trades}. ביצועי עבר אינם מבטיחים תוצאות עתידיות.")

# ── רשימת מעקב
with tabs[5]:
    st.subheader("רשימת מעקב והשוואה")
    tickers_text = st.text_area("סימולים (מופרדים בפסיק)", "AAPL, MSFT, NVDA, TSLA")
    sheet_url = st.text_input("סנכרון Google Sheets (אופציונלי)",
                              placeholder="קישור CSV: קובץ ← שיתוף ← פרסום באינטרנט ← CSV",
                              help="העמודה הראשונה בגיליון צריכה לכלול סימולים. כל שינוי בגיליון יופיע ברענון הבא.")
    tickers = [t.strip().upper() for t in tickers_text.replace("\n", ",").split(",") if t.strip()]
    if sheet_url:
        try:
            gs = pd.read_csv(sheet_url)
            col0 = gs.iloc[:, 0].dropna().astype(str).str.upper().str.strip()
            tickers += [t for t in col0 if t not in ("TICKER", "SYMBOL", "סימול")]
        except Exception as e:
            st.warning(f"לא הצלחתי לקרוא את הגיליון: {e}")
    tickers = list(dict.fromkeys(tickers))[:30]

    if tickers:
        try:
            close = load_multi(tuple(tickers))
            rows = []
            for t in close.columns:
                s = close[t].dropna()
                if len(s) < 3:
                    continue
                sma50 = s.rolling(50).mean().iloc[-1]
                rows.append({
                    "סימול": t, "מחיר": s.iloc[-1],
                    "יומי %": s.pct_change().iloc[-1] * 100,
                    "שבוע %": (s.iloc[-1] / s.iloc[-6] - 1) * 100 if len(s) > 5 else np.nan,
                    "חודש %": (s.iloc[-1] / s.iloc[-22] - 1) * 100 if len(s) > 21 else np.nan,
                    "RSI": rsi(s).iloc[-1],
                    "מול SMA50 %": (s.iloc[-1] / sma50 - 1) * 100 if not np.isnan(sma50) else np.nan,
                    "טרנד": s.tail(60).tolist(),
                })
            if rows:
                st.dataframe(
                    pd.DataFrame(rows), hide_index=True, use_container_width=True,
                    column_config={
                        "מחיר": st.column_config.NumberColumn(format="$%.2f"),
                        "יומי %": st.column_config.NumberColumn(format="%.2f%%"),
                        "שבוע %": st.column_config.NumberColumn(format="%.2f%%"),
                        "חודש %": st.column_config.NumberColumn(format="%.2f%%"),
                        "RSI": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
                        "מול SMA50 %": st.column_config.NumberColumn(format="%.1f%%"),
                        "טרנד": st.column_config.LineChartColumn("60 ימים"),
                    })
                pick = st.multiselect("השוואה (מנורמל ל-100)", list(close.columns), default=list(close.columns)[:4])
                if pick:
                    norm = close[pick].dropna(how="all").ffill()
                    norm = norm / norm.iloc[0] * 100
                    fig = go.Figure([go.Scatter(x=norm.index, y=norm[c], name=c) for c in pick])
                    fig.update_layout(template="plotly_dark", height=380, margin=dict(l=8, r=8, t=20, b=8),
                                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", hovermode="x unified")
                    st.plotly_chart(fig, use_container_width=True, config=PLOT_CFG)
        except Exception as e:
            st.error(f"שגיאה בטעינת הרשימה: {e}")

# ── חדשות
with tabs[6]:
    news = load_news(symbol)
    shown = 0
    for item in news[:10]:
        title, url, pub = parse_news(item)
        if title:
            st.markdown(f"**[{title}]({url})**  \n<small>{pub or ''}</small>" if url else f"**{title}**",
                        unsafe_allow_html=True)
            shown += 1
    if not shown:
        st.info("לא נמצאו כותרות עבור הסימול.")

st.divider()
st.caption("⚠️ המידע להמחשה ולמטרות לימוד בלבד ואינו מהווה ייעוץ השקעות. נתוני Yahoo Finance עשויים להיות מושהים או לא מדויקים.")
