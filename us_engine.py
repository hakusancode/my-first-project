"""
us_engine.py — 미국 상장기업 재무분석 엔진 (yfinance 기반)

dart_engine.py(한국/DART)의 미국 버전. 현금창출능력을 중심에 두고
수익성·성장성·안정성·밸류에이션 지표를 함께 계산한다.

핵심 진입점:
    analyze(ticker)            → 한 종목의 종합 분석 dict
    screen(tickers)            → 여러 종목을 현금창출 중심으로 비교하는 요약 리스트

반환 dict는 순수 파이썬 값(float/str/None)만 담으므로 CLI·GUI 어디서든 재사용 가능.
금액 단위는 모두 원화가 아닌 '보고 통화'(대개 USD) 기준 원값(원 단위 아님, 달러 원값).
"""

import math
import yfinance as yf


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _num(v):
    """yfinance/pandas 값을 안전한 float 또는 None으로 변환. NaN → None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _get(df, keys, col):
    """
    재무제표 DataFrame에서 행(keys) × 열(col 위치)을 안전 조회.
    keys는 문자열 또는 대체 행이름 리스트(회사마다 계정명이 다름).
    col은 열 위치 인덱스(0 = 최신 회계연도).
    """
    if df is None or getattr(df, "empty", True):
        return None
    if isinstance(keys, str):
        keys = [keys]
    for k in keys:
        if k in df.index:
            try:
                return _num(df.loc[k].iloc[col])
            except (IndexError, KeyError):
                continue
    return None


def _safe_div(a, b):
    """0/None 안전 나눗셈."""
    if a is None or b is None or b == 0:
        return None
    return a / b


def _pct(a, b):
    """비율(%) = a/b*100. 안전."""
    r = _safe_div(a, b)
    return None if r is None else r * 100.0


def _yoy(cur, prev):
    """전년대비 증가율(%). prev가 음수/0이면 부호 왜곡되므로 None."""
    if cur is None or prev is None or prev <= 0:
        return None
    return (cur - prev) / prev * 100.0


def _cagr(first, last, periods):
    """연평균성장률(%). first(과거)→last(현재), periods년."""
    if first is None or last is None or first <= 0 or last <= 0 or periods <= 0:
        return None
    return ((last / first) ** (1.0 / periods) - 1.0) * 100.0


# ── 연도별 원자료 추출 ───────────────────────────────────────────────────────

def _year_labels(*dfs, limit=4):
    """가장 열이 많은 재무제표의 컬럼(회계연도 종료일)에서 연도 라벨 생성. 최신순 위치 유지."""
    best = None
    for df in dfs:
        if df is not None and not getattr(df, "empty", True):
            if best is None or len(df.columns) > len(best):
                best = df.columns
    if best is None:
        return []
    labels = []
    for c in best[:limit]:
        try:
            labels.append(str(c.year))
        except AttributeError:
            labels.append(str(c))
    return labels


def _extract_year(inc, bs, cf, col):
    """열 위치 col(0=최신)의 손익/재무상태/현금흐름 원자료를 dict로 뽑는다."""
    revenue = _get(inc, ["Total Revenue", "Operating Revenue"], col)
    gross = _get(inc, "Gross Profit", col)
    op_income = _get(inc, ["Operating Income", "Total Operating Income As Reported"], col)
    net_income = _get(inc, ["Net Income", "Net Income Common Stockholders"], col)
    pretax = _get(inc, "Pretax Income", col)
    tax = _get(inc, "Tax Provision", col)
    ebit = _get(inc, "EBIT", col)
    ebitda = _get(inc, ["EBITDA", "Normalized EBITDA"], col)
    interest_exp = _get(inc, ["Interest Expense", "Interest Expense Non Operating"], col)
    diluted_eps = _get(inc, "Diluted EPS", col)

    total_assets = _get(bs, "Total Assets", col)
    equity = _get(bs, ["Stockholders Equity", "Common Stock Equity",
                       "Total Equity Gross Minority Interest"], col)
    total_debt = _get(bs, "Total Debt", col)
    net_debt = _get(bs, "Net Debt", col)
    invested_capital = _get(bs, "Invested Capital", col)
    cur_assets = _get(bs, "Current Assets", col)
    cur_liab = _get(bs, "Current Liabilities", col)

    cfo = _get(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"], col)
    capex = _get(cf, ["Capital Expenditure", "Purchase Of PPE"], col)  # 보통 음수
    fcf_row = _get(cf, "Free Cash Flow", col)

    # FCF: yfinance 'Free Cash Flow' 우선, 없으면 CFO + CapEx(음수) 로 계산
    if fcf_row is not None:
        fcf = fcf_row
    elif cfo is not None and capex is not None:
        fcf = cfo + capex
    else:
        fcf = None

    capex_abs = None if capex is None else abs(capex)

    return {
        "revenue": revenue, "gross_profit": gross, "operating_income": op_income,
        "net_income": net_income, "pretax": pretax, "tax": tax, "ebit": ebit,
        "ebitda": ebitda, "interest_expense": interest_exp, "diluted_eps": diluted_eps,
        "total_assets": total_assets, "equity": equity, "total_debt": total_debt,
        "net_debt": net_debt, "invested_capital": invested_capital,
        "current_assets": cur_assets, "current_liabilities": cur_liab,
        "cfo": cfo, "capex": capex_abs, "fcf": fcf,
    }


# ── 파생 지표 계산 ───────────────────────────────────────────────────────────

def _cash_metrics(y):
    """현금창출 지표: FCF마진·이익의 질·CapEx강도."""
    return {
        "fcf_margin": _pct(y["fcf"], y["revenue"]),
        "cfo_margin": _pct(y["cfo"], y["revenue"]),
        # 이익의 질: CFO / 영업이익 (>1 이면 이익이 현금으로 잘 전환)
        "earnings_quality": _safe_div(y["cfo"], y["operating_income"]),
        # CapEx 강도: CapEx / 매출
        "capex_intensity": _pct(y["capex"], y["revenue"]),
        # FCF / 순이익 (현금 전환 배수)
        "fcf_to_ni": _safe_div(y["fcf"], y["net_income"]),
    }


def _profitability(y):
    """수익성 지표: 마진·ROE·ROA·ROIC."""
    tax_rate = _safe_div(y["tax"], y["pretax"])
    if tax_rate is None or tax_rate < 0 or tax_rate > 1:
        tax_rate = 0.21  # 미국 법인세 기본값 fallback
    nopat = None if y["ebit"] is None else y["ebit"] * (1.0 - tax_rate)
    return {
        "gross_margin": _pct(y["gross_profit"], y["revenue"]),
        "operating_margin": _pct(y["operating_income"], y["revenue"]),
        "net_margin": _pct(y["net_income"], y["revenue"]),
        "roe": _pct(y["net_income"], y["equity"]),
        "roa": _pct(y["net_income"], y["total_assets"]),
        "roic": _pct(nopat, y["invested_capital"]),
    }


def _stability(y):
    """안정성 지표: 부채비율·유동비율·이자보상배율."""
    return {
        "debt_to_equity": _safe_div(y["total_debt"], y["equity"]),
        "current_ratio": _safe_div(y["current_assets"], y["current_liabilities"]),
        # 이자보상배율: EBIT / |이자비용|
        "interest_coverage": _safe_div(
            y["ebit"], None if y["interest_expense"] is None else abs(y["interest_expense"])),
        "net_debt": y["net_debt"],
    }


# ── 공개 API ─────────────────────────────────────────────────────────────────

def analyze(ticker, log_fn=None):
    """
    한 종목의 종합 재무분석을 반환한다.
    반환 dict:
      {
        "ticker": str, "ok": bool, "error": str|None,
        "overview": {name, sector, industry, currency, price, market_cap, ...},
        "valuation": {per, forward_per, pbr, psr, ev_ebitda, fcf_yield, dividend_yield},
        "years": ["2023","2024","2025"...]        # 오름차순
        "annual": [ {year, ...원자료..., **현금/수익성/안정성 지표}, ... ],  # 오름차순
        "growth": {revenue_yoy, revenue_cagr, operating_income_yoy,
                   net_income_yoy, cfo_yoy, fcf_yoy, eps_yoy},
        "latest": {...가장 최근 연도 지표 요약...},
      }
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    ticker = ticker.strip().upper()
    result = {"ticker": ticker, "ok": False, "error": None}
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        inc = t.income_stmt
        bs = t.balance_sheet
        cf = t.cashflow
    except Exception as e:  # noqa: BLE001  (네트워크/파싱 등 광범위 오류)
        result["error"] = f"데이터 조회 실패: {e}"
        return result

    if (inc is None or getattr(inc, "empty", True)):
        result["error"] = "재무제표 데이터가 없습니다 (티커 확인 또는 상장폐지/ETF 등)."
        return result

    labels = _year_labels(inc, bs, cf, limit=4)   # 최신순 위치
    n = len(labels)
    log(f"[{ticker}] {n}개 회계연도 수신")

    # 열 위치 0..n-1 (0=최신) 을 오름차순(과거→현재)으로 재배열
    order = list(range(n))[::-1]           # 예: [3,2,1,0]
    years_asc = labels[::-1]

    annual = []
    for pos in order:
        raw = _extract_year(inc, bs, cf, pos)
        row = {"year": labels[pos]}
        row.update(raw)
        row.update(_cash_metrics(raw))
        row.update(_profitability(raw))
        row.update(_stability(raw))
        annual.append(row)

    # 성장성 (과거→현재)
    def series(key):
        return [r[key] for r in annual]

    rev = series("revenue")
    growth = {
        "revenue_yoy": _yoy(rev[-1], rev[-2]) if len(rev) >= 2 else None,
        "revenue_cagr": _cagr(rev[0], rev[-1], len(rev) - 1) if len(rev) >= 2 else None,
        "operating_income_yoy": _yoy(series("operating_income")[-1],
                                     series("operating_income")[-2]) if n >= 2 else None,
        "net_income_yoy": _yoy(series("net_income")[-1],
                               series("net_income")[-2]) if n >= 2 else None,
        "cfo_yoy": _yoy(series("cfo")[-1], series("cfo")[-2]) if n >= 2 else None,
        "fcf_yoy": _yoy(series("fcf")[-1], series("fcf")[-2]) if n >= 2 else None,
        "eps_yoy": _yoy(series("diluted_eps")[-1],
                        series("diluted_eps")[-2]) if n >= 2 else None,
    }

    market_cap = _num(info.get("marketCap"))
    # 보고 통화(financialCurrency)와 거래 통화(currency)가 다르면(예: TSM=TWD 보고 / USD 거래)
    # 재무제표 금액과 시가총액의 통화가 달라 FCF수익률 등이 왜곡되므로 표시하지 않는다.
    fin_cur = (info.get("financialCurrency") or info.get("currency") or "USD").upper()
    trade_cur = (info.get("currency") or fin_cur).upper()
    currency_mismatch = fin_cur != trade_cur
    latest_fcf = annual[-1]["fcf"] if annual else None
    overview = {
        "name": info.get("shortName") or info.get("longName") or ticker,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": fin_cur,             # 재무제표 금액의 통화
        "trade_currency": trade_cur,     # 주가/시총의 통화
        "currency_mismatch": currency_mismatch,
        "price": _num(info.get("currentPrice") or info.get("regularMarketPrice")),
        "market_cap": market_cap,
    }
    valuation = {
        "per": _num(info.get("trailingPE")),
        "forward_per": _num(info.get("forwardPE")),
        "pbr": _num(info.get("priceToBook")),
        "psr": _num(info.get("priceToSalesTrailing12Months")),
        "ev_ebitda": _num(info.get("enterpriseToEbitda")),
        # FCF 수익률 = 최근 연간 FCF / 시가총액 (통화 불일치 시 생략)
        "fcf_yield": None if currency_mismatch else _pct(latest_fcf, market_cap),
        "dividend_yield": _num(info.get("dividendYield")),
    }

    result.update({
        "ok": True,
        "overview": overview,
        "valuation": valuation,
        "years": years_asc,
        "annual": annual,
        "growth": growth,
        "latest": annual[-1] if annual else None,
        "source": "Yahoo Finance",
    })
    return result


# 미국 AI 밸류체인 기본 유니버스 (프로토타입용 예시 — 자유롭게 수정)
AI_UNIVERSE = [
    "NVDA",  # GPU
    "MSFT",  # 클라우드/코파일럿
    "GOOGL", # 클라우드/제미나이
    "META",  # AI 인프라/광고
    "AMZN",  # AWS
    "AVGO",  # 커스텀 AI 칩/네트워킹
    "AMD",   # GPU/CPU
    "TSM",   # 파운드리(ADR)
    "MU",    # HBM 메모리
    "ORCL",  # AI 클라우드
    "PLTR",  # AI 소프트웨어
    "ANET",  # AI 데이터센터 네트워킹
]


def screen(tickers=None, log_fn=None):
    """
    여러 종목을 현금창출 중심으로 비교하기 위한 요약 리스트를 반환한다.
    각 원소: {ticker, name, ok, market_cap, cfo, fcf, fcf_margin,
              earnings_quality, roic, fcf_yield, revenue_cagr, error}
    FCF 마진 내림차순 정렬(데이터 없는 종목은 뒤로).
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    if tickers is None:
        tickers = AI_UNIVERSE

    rows = []
    for tk in tickers:
        a = analyze(tk, log_fn=log_fn)
        if not a["ok"]:
            rows.append({"ticker": tk.upper(), "name": tk.upper(), "ok": False,
                         "error": a["error"]})
            continue
        latest = a["latest"] or {}
        rows.append({
            "ticker": a["ticker"],
            "name": a["overview"]["name"],
            "ok": True,
            "currency": a["overview"]["currency"],
            "currency_mismatch": a["overview"]["currency_mismatch"],
            "market_cap": a["overview"]["market_cap"],
            "cfo": latest.get("cfo"),
            "fcf": latest.get("fcf"),
            "fcf_margin": latest.get("fcf_margin"),
            "earnings_quality": latest.get("earnings_quality"),
            "roic": latest.get("roic"),
            "fcf_yield": a["valuation"]["fcf_yield"],
            "revenue_cagr": a["growth"]["revenue_cagr"],
            "error": None,
        })

    rows.sort(key=lambda r: (r["ok"] is False,
                             -(r.get("fcf_margin") if r.get("fcf_margin") is not None else -1e9)))
    return rows
