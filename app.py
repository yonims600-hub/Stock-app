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
