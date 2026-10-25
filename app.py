import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="GEM - podgląd ETF-ów", layout="wide")

DEFAULT_TICKERS = "CNDX.L, EXUS.L, XMME.L, IGLN.L, IB01.L"
# Opisy tickerów (ticker na Yahoo -> opis). Dla tickerów spoza słownika
# aplikacja próbuje pobrać nazwę z Yahoo.
TICKER_INFO = {
    "CNDX.L": "iShares NASDAQ 100 UCITS ETF (Acc), USD - Nasdaq-100, replikacja fizyczna",
    "EXUS.L": "Xtrackers MSCI World ex USA UCITS ETF 1C, USD - rynki rozwinięte bez USA",
    "XMME.L": "Xtrackers MSCI Emerging Markets UCITS ETF 1C, USD - rynki wschodzące",
    "IGLN.L": "iShares Physical Gold ETC, USD - złoto fizyczne",
    "IB01.L": "iShares $ Treasury Bond 0-1yr UCITS ETF (Acc), USD - krótkie obligacje USA (gotówka)",
}
HISTORY_START = "2000-01-01"
CURRENCY_OPTIONS = ["Bez przeliczania", "USD", "EUR", "PLN"]
PRESETS = {
    "1 miesiąc": pd.DateOffset(months=1),
    "3 miesiące": pd.DateOffset(months=3),
    "6 miesięcy": pd.DateOffset(months=6),
    "1 rok": pd.DateOffset(years=1),
    "3 lata": pd.DateOffset(years=3),
    "5 lat": pd.DateOffset(years=5),
}


@st.cache_data(ttl=3600, show_spinner="Pobieram notowania z Yahoo Finance...")
def load_prices(tickers: tuple) -> pd.DataFrame:
    raw = yf.download(list(tickers), start=HISTORY_START,
                      auto_adjust=True, progress=False)
    close = raw["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    close = close.dropna(how="all")
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close


@st.cache_data(ttl=86400)
def currency(ticker: str) -> str:
    try:
        return str(yf.Ticker(ticker).fast_info["currency"])
    except Exception:
        return "?"


@st.cache_data(ttl=3600)
def load_fx(pairs: tuple) -> pd.DataFrame:
    raw = yf.download(list(pairs), start=HISTORY_START,
                      auto_adjust=True, progress=False)
    fx = raw["Close"]
    if isinstance(fx, pd.Series):
        fx = fx.to_frame(pairs[0])
    fx.index = pd.to_datetime(fx.index).tz_localize(None)
    return fx


def convert(prices: pd.DataFrame, target: str):
    """Przelicza ceny na walutę docelową kursami dziennymi z Yahoo (np. EURUSD=X)."""
    out = prices.copy()
    ccy = {t: currency(t) for t in out.columns}
    notes = []
    for t, c in list(ccy.items()):
        if c in ("GBp", "GBX"):  # pensy -> funty
            out[t] = out[t] / 100
            ccy[t] = "GBP"
    needed = sorted({c for c in ccy.values() if c not in (target, "?")})
    fx = load_fx(tuple(f"{c}{target}=X" for c in needed)) if needed else None
    for t, c in list(ccy.items()):
        if c == target:
            continue
        pair = f"{c}{target}=X"
        if c == "?" or fx is None or pair not in fx.columns or fx[pair].isna().all():
            notes.append(f"{t}: brak przeliczenia {c} -> {target}, pokazuję w {c}")
            continue
        rate = fx[pair].reindex(out.index.union(fx.index)).ffill().reindex(out.index)
        out[t] = out[t] * rate
        ccy[t] = target
    return out, ccy, notes


@st.cache_data(ttl=86400)
def yahoo_name(ticker: str) -> str:
    try:
        return str(yf.Ticker(ticker).get_info().get("longName", ""))
    except Exception:
        return ""


def describe(ticker: str) -> str:
    return TICKER_INFO.get(ticker) or yahoo_name(ticker) or "-"


# ---------------------------------------------------------------- panel boczny
with st.sidebar:
    st.header("Ustawienia")
    raw_text = st.text_input("Tickery (po przecinku)", DEFAULT_TICKERS)
    tickers = tuple(dict.fromkeys(
        t.strip().upper() for t in raw_text.split(",") if t.strip()))
    target = st.selectbox("Waluta wyceny", CURRENCY_OPTIONS, index=1,
                          help="Ceny funduszy są przeliczane dziennym kursem z Yahoo.")
    if st.button("Odśwież dane"):
        st.cache_data.clear()
        st.rerun()

if not tickers:
    st.info("Wpisz co najmniej jeden ticker w panelu bocznym.")
    st.stop()

try:
    prices = load_prices(tickers)
except Exception as exc:  # Yahoo bywa niedostępne lub blokuje zapytania
    st.error(f"Nie udało się pobrać danych z Yahoo Finance: {exc}")
    st.stop()

missing = [t for t in tickers if t not in prices.columns or prices[t].isna().all()]
if missing:
    st.warning(f"Brak danych dla: {', '.join(missing)}. Sprawdź symbol (np. sufiks .L, .DE).")
prices = prices[[t for t in tickers if t not in missing]]
if prices.empty:
    st.error("Żaden ticker nie zwrócił danych.")
    st.stop()
shown = {t: currency(t) for t in prices.columns}
if target != "Bez przeliczania":
    try:
        prices, shown, fx_notes = convert(prices, target)
        for note in fx_notes:
            st.warning(note)
    except Exception as exc:
        st.warning(f"Nie udało się przeliczyć walut: {exc}. Pokazuję ceny w oryginalnych walutach.")
prices = prices.ffill(limit=5)  # różne święta giełd

data_min, data_max = prices.index.min(), prices.index.max()

with st.sidebar:
    end_choice = st.selectbox(
        "Data końcowa (od niej liczymy okres wstecz)",
        ["Koniec poprzedniego miesiąca", "Ostatnia sesja", "Własna data"], index=0)
    if end_choice == "Ostatnia sesja":
        end = data_max
    elif end_choice == "Koniec poprzedniego miesiąca":
        cutoff = data_max.replace(day=1) - pd.Timedelta(days=1)
        valid = prices.index[prices.index <= cutoff]
        end = valid[-1] if len(valid) else data_max
    else:
        picked_end = st.date_input("Data końcowa", value=data_max.date(),
                                   min_value=data_min.date(), max_value=data_max.date())
        valid = prices.index[prices.index <= pd.Timestamp(picked_end)]
        end = valid[-1] if len(valid) else data_max

    choice = st.selectbox(
        "Okres wstecz od daty końcowej",
        list(PRESETS) + ["Od początku roku (YTD)", "Maksimum", "Własna data początkowa"],
        index=3)
    if choice == "Własna data początkowa":
        picked_start = st.date_input(
            "Data początkowa",
            value=max(end - pd.DateOffset(years=1), data_min).date(),
            min_value=data_min.date(), max_value=end.date())
        start = pd.Timestamp(picked_start)
    elif choice == "Od początku roku (YTD)":
        start = pd.Timestamp(year=end.year, month=1, day=1)
    elif choice == "Maksimum":
        start = data_min
    else:
        start = end - PRESETS[choice]
    start = max(start, data_min)

    common = st.checkbox("Tylko wspólny okres (start od najmłodszej serii)", value=True)
    log_scale = st.checkbox("Skala logarytmiczna", value=False)

# ---------------------------------------------------------------- obliczenia
sub = prices.loc[start:end].dropna(how="all")
sub = sub.loc[:, sub.notna().any()]
if sub.empty:
    st.error("Brak danych w wybranym zakresie.")
    st.stop()
if common:
    first = max(sub[c].first_valid_index() for c in sub.columns)
    sub = sub.loc[first:]

base = sub.apply(lambda s: s.dropna().iloc[0])
returns = (sub / base - 1) * 100

st.title("Zwrot narastający ETF-ów")
st.caption(f"Zakres: {sub.index[0]:%Y-%m-%d} - {sub.index[-1]:%Y-%m-%d} "
           f"(data końcowa: {end:%Y-%m-%d}). "
           f"Ostatnie dostępne notowanie w danych: {data_max:%Y-%m-%d}.")

fig = go.Figure()
for t in returns.columns:
    fig.add_trace(go.Scatter(x=returns.index, y=returns[t], name=t, mode="lines"))
fig.update_layout(yaxis_title="%", hovermode="x unified",
                  margin=dict(l=10, r=10, t=10, b=10), height=520,
                  legend=dict(orientation="h", y=-0.15))
if log_scale:
    # skala log wymaga dodatnich wartości: pokazujemy wartość portfela (start = 100)
    fig = go.Figure()
    for t in sub.columns:
        fig.add_trace(go.Scatter(x=sub.index, y=sub[t] / base[t] * 100, name=t, mode="lines"))
    fig.update_yaxes(type="log")
    fig.update_layout(yaxis_title="wartość (start = 100)", hovermode="x unified",
                      margin=dict(l=10, r=10, t=10, b=10), height=520,
                      legend=dict(orientation="h", y=-0.15))
st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------- tabela
rows = []
for c in sub.columns:
    s = sub[c].dropna()
    full = prices[c].dropna()
    last = full.asof(end)
    row = {
        "Ticker": c,
        "Opis": describe(c),
        "Waluta": shown.get(c, "?"),
        "Zwrot w zakresie %": (s.iloc[-1] / s.iloc[0] - 1) * 100,
        "Max obsunięcie %": (s / s.cummax() - 1).min() * 100,
    }
    for m in (3, 6, 12):
        ref = full.asof(end - pd.DateOffset(months=m))
        row[f"{m}M do daty końcowej %"] = (last / ref - 1) * 100 if pd.notna(ref) else None
    rows.append(row)
st.subheader("Podsumowanie")
st.dataframe(pd.DataFrame(rows).round(2), hide_index=True, width="stretch",
             column_config={"Opis": st.column_config.TextColumn(width="large")})
st.caption("Zwroty 3M/6M/12M liczone na dzień końcowy zakresu, w walucie notowania. "
           "Przeliczenie walut używa dziennych kursów zamknięcia z Yahoo, więc wynik może się "
           "nieznacznie różnić od notowań w walucie bazowej funduszu. "
           "Dane z Yahoo Finance (nieoficjalne). To nie jest rekomendacja inwestycyjna.")