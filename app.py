import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="GEM - podgląd ETF-ów", layout="wide")

# Grupy tickerów (nazwa grupy -> tickery na Yahoo po przecinku).
# Benchmark: tylko pierwszy ticker z listy.
DEFAULT_GROUPS = {
    "Benchmark (akcje świata)": "IWDA.L",
    "Indeksy akcyjne": "CNDX.L, EXUS.L, XMME.L",
    "Złoto i obligacje": "IGLN.L, IB01.L",
}
G_BENCH, G_EQ, G_SAFE = DEFAULT_GROUPS  # klucze słownika w tej kolejności

# Opisy tickerów (ticker na Yahoo -> opis). Dla tickerów spoza słownika
# aplikacja próbuje pobrać nazwę z Yahoo.
TICKER_INFO = {
    "IWDA.L": "iShares Core MSCI World UCITS ETF (Acc), USD - benchmark: akcje rynków rozwiniętych",
    "CNDX.L": "iShares NASDAQ 100 UCITS ETF (Acc), USD - Nasdaq-100, replikacja fizyczna",
    "N100.L": "iShares NASDAQ 100 Swap UCITS ETF (Acc), USD - Nasdaq-100, replikacja syntetyczna (swap)",
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
PALETTE = ["#4c78a8", "#f58518", "#54a24b", "#e45756", "#b279a2",
           "#9d755d", "#eeca3b", "#72b7b2"]


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


@st.cache_data(ttl=86400)
def yahoo_name(ticker: str) -> str:
    try:
        return str(yf.Ticker(ticker).get_info().get("longName", ""))
    except Exception:
        return ""


def describe(ticker: str) -> str:
    return TICKER_INFO.get(ticker) or yahoo_name(ticker) or "-"


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


def parse(text: str) -> tuple:
    return tuple(dict.fromkeys(t.strip().upper() for t in text.split(",") if t.strip()))


# ---------------------------------------------------------------- panel boczny
with st.sidebar:
    st.header("Ustawienia")
    groups = {}
    for group, default in DEFAULT_GROUPS.items():
        label = f"{group} - tickery po przecinku" if group != G_BENCH \
            else f"{group} - jeden ticker"
        groups[group] = parse(st.text_input(label, default))
    groups[G_BENCH] = groups[G_BENCH][:1]
    tickers = tuple(dict.fromkeys(t for ts in groups.values() for t in ts))

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
avail = {g: [t for t in ts if t in sub.columns] for g, ts in groups.items()}
color = {t: PALETTE[i % len(PALETTE)] for i, t in enumerate(sub.columns)}


def total_ret(t: str) -> float:
    return float(returns[t].dropna().iloc[-1])


def make_fig(cols, bold=(), height=420):
    fig = go.Figure()
    for t in cols:
        y = sub[t] / base[t] * 100 if log_scale else returns[t]
        fig.add_trace(go.Scatter(
            x=sub.index, y=y, name=t, mode="lines",
            line=dict(width=3.5 if t in bold else 1.8, color=color[t])))
    fig.update_layout(yaxis_title="wartość (start = 100)" if log_scale else "%",
                      hovermode="x unified", height=height,
                      margin=dict(l=10, r=10, t=10, b=10),
                      legend=dict(orientation="h", y=-0.2))
    if log_scale:
        fig.update_yaxes(type="log")
    return fig


def best_caption(cols, what):
    if not cols:
        return
    best = max(cols, key=total_ret)
    st.caption(f"{what}: najlepszy w okresie to {best} ({total_ret(best):+.1f}%).")


# ---------------------------------------------------------------- układ
st.title("Giełda czy aktywa bezpieczne?")
st.caption(f"Zakres: {sub.index[0]:%Y-%m-%d} - {sub.index[-1]:%Y-%m-%d} "
           f"(data końcowa: {end:%Y-%m-%d}). "
           f"Ostatnie dostępne notowanie w danych: {data_max:%Y-%m-%d}.")

# 1) benchmark vs złoto i obligacje
bench = avail[G_BENCH][0] if avail[G_BENCH] else None
safe = avail[G_SAFE]
st.subheader("Benchmark vs złoto i obligacje")
if bench and safe:
    st.plotly_chart(make_fig([bench] + safe, bold=(bench,)), width="stretch")
    r_bench = total_ret(bench)
    best_safe = max(safe, key=total_ret)
    r_safe = total_ret(best_safe)
    safe_txt = ", ".join(f"{t} {total_ret(t):+.1f}%" for t in safe)
    if r_bench > r_safe:
        st.success(f"📈 **Wygrała giełda.** {bench}: {r_bench:+.1f}% vs najlepsze "
                   f"aktywo bezpieczne {best_safe}: {r_safe:+.1f}% ({safe_txt}).")
    else:
        st.warning(f"🛡️ **Wygrały aktywa bezpieczne.** Najlepsze: {best_safe} "
                   f"{r_safe:+.1f}% vs {bench}: {r_bench:+.1f}% ({safe_txt}).")
    st.caption("Reguła: giełda wygrywa, jeśli zwrot benchmarku w wybranym okresie "
               "jest wyższy niż zwrot najlepszego z aktywów bezpiecznych.")
else:
    st.info("Brak danych dla benchmarku lub aktywów bezpiecznych. "
            "Sprawdź tickery w panelu bocznym.")

# 2) dwa wykresy obok siebie
left, right = st.columns(2)
with left:
    st.subheader("Indeksy akcyjne")
    if avail[G_EQ]:
        st.plotly_chart(make_fig(avail[G_EQ]), width="stretch")
        best_caption(avail[G_EQ], "Akcje")
    else:
        st.info("Brak danych dla indeksów akcyjnych.")
with right:
    st.subheader("Złoto i obligacje")
    if safe:
        st.plotly_chart(make_fig(safe), width="stretch")
        best_caption(safe, "Aktywa bezpieczne")
    else:
        st.info("Brak danych dla złota i obligacji.")

# ---------------------------------------------------------------- tabela
group_of = {}
for g, ts in avail.items():
    for t in ts:
        group_of.setdefault(t, g)
rows = []
for c in sub.columns:
    s = sub[c].dropna()
    full = prices[c].dropna()
    last = full.asof(end)
    row = {
        "Ticker": c,
        "Grupa": group_of.get(c, "-"),
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