"""
sec_engine.py — 미국 상장기업 펀더멘털 엔진 (SEC EDGAR 공식 데이터)

us_engine.py(yfinance)의 '승격' 버전. 재무제표 원자료를 야후가 아니라
SEC EDGAR의 XBRL companyfacts API에서 직접 가져온다 → 공식·무료·안정적.

analyze(ticker) / screen(tickers) 는 us_engine과 **동일한 반환 구조**를 가져
us_report.py 등에서 그대로 재사용할 수 있다. 지표 계산식도 us_engine의
순수 헬퍼를 재사용한다(일관성).

주의:
- EDGAR는 펀더멘털만 제공한다(주가·시가총액 없음). 밸류에이션(PER·PBR·FCF수익률
  등)은 EDGAR 재무 + 경량 현재가 조회(yfinance fast_info, 실패 시 생략)로 계산한다.
- 미국 국내 신고자(10-K) 위주. 외국기업(20-F, 예: TSM)은 us-gaap XBRL이
  부실해 데이터가 없을 수 있다 → 그 경우 us_engine(yfinance) 사용 권장.
- SEC 정책상 연락처가 담긴 User-Agent가 필수다(아래 _UA). 요청은 10건/초 이하로 제한.
"""

import os
import json
import time
import datetime as _dt

import requests

# us_engine의 순수 계산 헬퍼 재사용 (I/O 없음)
from us_engine import (
    _num, _safe_div, _pct, _yoy, _cagr,
    _cash_metrics, _profitability, _stability,
    DEFAULT_UNIVERSE,
)

# SEC 요구: 실제 앱/연락처가 담긴 User-Agent
_UA = {"User-Agent": "my-first-project stock analyzer (bsjang91@gmail.com)"}
_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"

_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sec_cache")
_MIN_INTERVAL = 0.15          # 요청 간 최소 간격(초) — 10건/초 정책 준수
_last_req = [0.0]
_ticker_map = None            # {TICKER: (cik_int, title)}
_facts_cache = {}             # cik10 -> facts dict (프로세스 내)


# ── 저수준: HTTP + 캐시 ──────────────────────────────────────────────────────

def _throttle():
    dt = time.time() - _last_req[0]
    if dt < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - dt)
    _last_req[0] = time.time()


def _get_json(url, timeout=30):
    _throttle()
    r = requests.get(url, headers=_UA, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _cache_path(name):
    return os.path.join(_CACHE_DIR, name)


def _load_ticker_map(log=lambda m: None):
    global _ticker_map
    if _ticker_map is not None:
        return _ticker_map
    os.makedirs(_CACHE_DIR, exist_ok=True)
    p = _cache_path("company_tickers.json")
    if os.path.exists(p):
        data = json.load(open(p, encoding="utf-8"))
    else:
        log("SEC 티커 목록 다운로드 중...")
        data = _get_json(_SEC_TICKERS_URL)
        json.dump(data, open(p, "w", encoding="utf-8"))
    _ticker_map = {v["ticker"].upper(): (v["cik_str"], v.get("title", ""))
                   for v in data.values()}
    return _ticker_map


def _get_facts(cik10, log=lambda m: None):
    if cik10 in _facts_cache:
        return _facts_cache[cik10]
    os.makedirs(_CACHE_DIR, exist_ok=True)
    p = _cache_path(f"CIK{cik10}.json")
    if os.path.exists(p):
        facts = json.load(open(p, encoding="utf-8"))
    else:
        log(f"EDGAR companyfacts 다운로드 중 (CIK{cik10})...")
        facts = _get_json(_SEC_FACTS_URL.format(cik10=cik10))
        json.dump(facts, open(p, "w", encoding="utf-8"))
    _facts_cache[cik10] = facts
    return facts


def resolve_cik(query, log=lambda m: None):
    """티커 또는 회사명으로 (CIK10, title, ticker_symbol) 반환. 못 찾으면 None."""
    m = _load_ticker_map(log)
    q = query.strip().upper()
    # 1) 정확한 티커
    hit = m.get(q)
    if hit is not None:
        return (f"{hit[0]:010d}", hit[1], q)
    # 2) 회사명(title) 부분일치 — 가장 짧은(가장 정확한) 것 우선
    cands = [(tk, cik, title) for tk, (cik, title) in m.items() if q in (title or '').upper()]
    if cands:
        cands.sort(key=lambda x: len(x[2]))
        tk, cik, title = cands[0]
        return (f"{cik:010d}", title, tk)
    return None


# ── XBRL 개념 추출 ───────────────────────────────────────────────────────────

_ANNUAL_FORMS = ("10-K", "20-F", "40-F")


def _is_annual_form(form):
    return any(form.startswith(f) for f in _ANNUAL_FORMS)


def _pick_unit(concept, prefer="USD"):
    """개념의 units dict에서 사용할 단위 키를 고른다."""
    units = concept.get("units", {})
    if not units:
        return None
    if prefer in units:
        return prefer
    if prefer == "shares":
        for k in units:
            if "shares" in k.lower():
                return k
    return next(iter(units))


def _days(a, b):
    try:
        da = _dt.date.fromisoformat(a)
        db = _dt.date.fromisoformat(b)
        return (db - da).days
    except (TypeError, ValueError):
        return None


def _annual_duration(gaap, concepts, unit="USD", priority=False):
    """
    연간 기간항목(매출·현금흐름 등) → {연도(int): 값}.
    10-K/20-F 등 연간보고서의 FY, 기간≈1년 자료만. 종료일 연도로 키.
    폴백 체인의 모든 개념을 합쳐서(태그 마이그레이션 대응) 연도별 최신 신고분 우선.

    priority=True면 개념 순서를 우선순위로 취급해, 앞선 개념이 값을 준 연도는
    뒤 개념으로 덮어쓰지 않는다. 한 기업이 여러 개념을 동시에 신고하고 그중
    하나가 부분집합일 때(예: capex의 PP&E vs 기타 유형자산) 작은 쪽이 잡혀
    금액이 과소계상되는 것을 막는다.
    """
    best = {}  # year -> (filed, val)
    for name in concepts:
        c = gaap.get(name)
        if not c:
            continue
        ukey = _pick_unit(c, unit)
        if ukey is None:
            continue
        for f in c["units"][ukey]:
            if not _is_annual_form(f.get("form", "")):
                continue
            if f.get("fp") != "FY":
                continue
            d = _days(f.get("start"), f.get("end"))
            if d is None or d < 340 or d > 380:
                continue
            end = f.get("end")
            val = _num(f.get("val"))
            if end is None or val is None:
                continue
            year = int(end[:4])
            filed = f.get("filed", "")
            if year in best:
                # 우선순위 모드: 이미 상위 개념이 채운 연도는 건드리지 않는다.
                if priority and best[year][2] != name:
                    continue
                if filed <= best[year][0]:
                    continue
            best[year] = (filed, val, name)
    return {y: v for y, (_, v, _n) in best.items()}


def _annual_instant(gaap, concepts, unit="USD"):
    """
    연간 시점항목(자산·자본 등) → {연도(int): 값}.
    연간보고서 기준 회계연도말 잔액. 종료일 연도로 키.
    폴백 체인의 모든 개념을 합쳐서 연도별 최신 신고분 우선.
    """
    best = {}
    for name in concepts:
        c = gaap.get(name)
        if not c:
            continue
        ukey = _pick_unit(c, unit)
        if ukey is None:
            continue
        for f in c["units"][ukey]:
            if not _is_annual_form(f.get("form", "")):
                continue
            end = f.get("end")
            val = _num(f.get("val"))
            if end is None or val is None:
                continue
            year = int(end[:4])
            filed = f.get("filed", "")
            if year not in best or filed > best[year][0]:
                best[year] = (filed, val)
    return {y: v for y, (_, v) in best.items()}


# 개념 폴백 체인
_C = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "tax": ["IncomeTaxExpenseBenefit"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestAndDebtExpense"],
    "dna": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
            "DepreciationAndAmortization"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    # 앞쪽이 우선(priority=True). 통신사는 2019년경 Other~로, 리츠는 자본적개선(capital
    # improvements)으로 태그가 갈린다. 리츠의 부동산 '취득'은 성장투자라 capex에서 제외.
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
              "PaymentsToAcquireOtherProductiveAssets", "PaymentsForCapitalImprovements"],
    "dps": ["CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid"],
    "div_paid": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends", "PaymentsOfDividendsCommon",
                 "PaymentsOfOrdinaryDividends"],
    "total_assets": ["Assets"],
    "equity": ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "ltd_noncurrent": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "ltd_current": ["LongTermDebtCurrent", "DebtCurrent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "shares": ["EntityCommonStockSharesOutstanding"],
}


def _build_series(gaap, dei):
    """모든 개념을 연도별로 뽑아 dict of {year: val} 로 반환."""
    def dur(keys):
        return _annual_duration(gaap, _C[keys])

    def ins(keys):
        return _annual_instant(gaap, _C[keys])

    s = {
        "revenue": dur("revenue"), "gross_profit": dur("gross_profit"),
        "operating_income": dur("operating_income"), "net_income": dur("net_income"),
        "pretax": dur("pretax"), "tax": dur("tax"),
        "interest_expense": dur("interest_expense"), "dna": dur("dna"),
        "cfo": dur("cfo"), "capex": _annual_duration(gaap, _C["capex"], priority=True),
        "dps": dur("dps"),
        "div_paid": _annual_duration(gaap, _C["div_paid"], priority=True),
        "eps_diluted": _annual_duration(gaap, _C["eps_diluted"], unit="USD/shares"),
        "total_assets": ins("total_assets"), "equity": ins("equity"),
        "current_assets": ins("current_assets"), "current_liabilities": ins("current_liabilities"),
        "ltd_noncurrent": ins("ltd_noncurrent"), "ltd_current": ins("ltd_current"),
        "cash": ins("cash"),
        "shares": _annual_instant(dei, _C["shares"], unit="shares") if dei else {},
    }
    return s


def _year_row(s, year):
    """한 연도의 us_engine 호환 'y' dict 구성."""
    def g(k):
        return s[k].get(year)

    revenue = g("revenue")
    op_income = g("operating_income")
    ebit = op_income               # EDGAR 근사: EBIT ≈ 영업이익
    dna = g("dna")
    ebitda = None if (ebit is None or dna is None) else ebit + dna
    ltd_n, ltd_c = g("ltd_noncurrent"), g("ltd_current")
    total_debt = None
    if ltd_n is not None or ltd_c is not None:
        total_debt = (ltd_n or 0) + (ltd_c or 0)
    equity = g("equity")
    cash = g("cash")
    net_debt = None if (total_debt is None or cash is None) else total_debt - cash
    invested_capital = None
    if equity is not None or total_debt is not None:
        invested_capital = (equity or 0) + (total_debt or 0)
    cfo = g("cfo")
    capex = g("capex")
    capex_abs = None if capex is None else abs(capex)
    fcf = None if (cfo is None or capex_abs is None) else cfo - capex_abs
    return {
        "revenue": revenue, "gross_profit": g("gross_profit"), "operating_income": op_income,
        "net_income": g("net_income"), "pretax": g("pretax"), "tax": g("tax"),
        "ebit": ebit, "ebitda": ebitda, "interest_expense": g("interest_expense"),
        "diluted_eps": g("eps_diluted"),
        "total_assets": g("total_assets"), "equity": equity, "total_debt": total_debt,
        "net_debt": net_debt, "invested_capital": invested_capital,
        "current_assets": g("current_assets"), "current_liabilities": g("current_liabilities"),
        "cfo": cfo, "capex": capex_abs, "fcf": fcf,
    }


# ── 경량 현재가 (밸류에이션용, 선택) ─────────────────────────────────────────

def _fetch_price(ticker):
    """yfinance fast_info로 현재가만 가볍게 조회. 실패 시 None. yfinance 소음 로그는 억제."""
    try:
        import logging
        import yfinance as yf
        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        fi = yf.Ticker(ticker).fast_info
        price = _num(getattr(fi, "last_price", None))
        shares = _num(getattr(fi, "shares", None))
        return price, shares
    except Exception:  # noqa: BLE001
        return None, None


# ── 공개 API ─────────────────────────────────────────────────────────────────

def analyze(ticker, log_fn=None, with_price=True):
    """
    한 종목의 종합 재무분석(EDGAR)을 us_engine.analyze와 동일 구조로 반환.
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    ticker = ticker.strip().upper()
    result = {"ticker": ticker, "ok": False, "error": None}

    try:
        cik = resolve_cik(ticker, log)
    except Exception as e:  # noqa: BLE001
        result["error"] = f"티커 목록 조회 실패: {e}"
        return result
    if cik is None:
        result["error"] = "SEC EDGAR에서 티커/회사명을 찾지 못했습니다 (미국 상장 여부 확인)."
        return result
    cik10, title, symbol = cik
    result["ticker"] = symbol      # 입력이 회사명이어도 실제 티커로 정규화

    try:
        facts = _get_facts(cik10, log)
    except Exception as e:  # noqa: BLE001
        result["error"] = f"EDGAR 데이터 조회 실패: {e}"
        return result

    gaap = facts.get("facts", {}).get("us-gaap", {})
    dei = facts.get("facts", {}).get("dei", {})
    if not gaap:
        result["error"] = "us-gaap XBRL 데이터가 없습니다 (외국기업 20-F 등일 수 있음 → us_engine 사용 권장)."
        return result

    s = _build_series(gaap, dei)
    if not s["revenue"]:
        result["error"] = "연간 매출 데이터를 찾지 못했습니다."
        return result

    years = sorted(s["revenue"].keys())[-4:]     # 최근 4개년 오름차순
    log(f"[{ticker}] EDGAR {len(years)}개 회계연도")

    annual = []
    for y in years:
        raw = _year_row(s, y)
        row = {"year": str(y)}
        row.update(raw)
        row.update(_cash_metrics(raw))
        row.update(_profitability(raw))
        row.update(_stability(raw))
        # 배당
        row['dps'] = s['dps'].get(y)
        dp = s['div_paid'].get(y)
        row['dividends_paid'] = None if dp is None else abs(dp)
        row['payout_ratio'] = _pct(row['dividends_paid'], row['net_income'])
        annual.append(row)

    def ser(key):
        return [r[key] for r in annual]

    rev = ser("revenue")
    n = len(annual)
    growth = {
        "revenue_yoy": _yoy(rev[-1], rev[-2]) if n >= 2 else None,
        "revenue_cagr": _cagr(rev[0], rev[-1], n - 1) if n >= 2 else None,
        "operating_income_yoy": _yoy(ser("operating_income")[-1], ser("operating_income")[-2]) if n >= 2 else None,
        "net_income_yoy": _yoy(ser("net_income")[-1], ser("net_income")[-2]) if n >= 2 else None,
        "cfo_yoy": _yoy(ser("cfo")[-1], ser("cfo")[-2]) if n >= 2 else None,
        "fcf_yoy": _yoy(ser("fcf")[-1], ser("fcf")[-2]) if n >= 2 else None,
        "eps_yoy": _yoy(ser("diluted_eps")[-1], ser("diluted_eps")[-2]) if n >= 2 else None,
    }

    latest = annual[-1]
    # 밸류에이션: EDGAR 펀더멘털 + (선택) 경량 현재가
    price, shares = (_fetch_price(symbol) if with_price else (None, None))
    if shares is None:
        shares = s["shares"].get(years[-1])
    market_cap = None if (price is None or shares is None) else price * shares
    latest_dps = s["dps"].get(years[-1])
    valuation = {
        "per": _safe_div(price, latest["diluted_eps"]),
        "forward_per": None,     # EDGAR엔 추정치 없음
        "pbr": _safe_div(market_cap, latest["equity"]),
        "psr": _safe_div(market_cap, latest["revenue"]),
        "ev_ebitda": _safe_div(
            None if market_cap is None else market_cap + (latest["total_debt"] or 0) - (s["cash"].get(years[-1]) or 0),
            latest["ebitda"]),
        "fcf_yield": _pct(latest["fcf"], market_cap),
        "dividend_yield": _pct(latest_dps, price),
    }

    result.update({
        "ok": True,
        "overview": {
            "name": facts.get("entityName") or title or ticker,
            "sector": None, "industry": None,     # EDGAR엔 업종 분류(SIC)만 있어 생략
            "currency": "USD", "trade_currency": "USD", "currency_mismatch": False,
            "price": price, "market_cap": market_cap,
        },
        "valuation": valuation,
        "years": [str(y) for y in years],
        "annual": annual,
        "growth": growth,
        "latest": latest,
        "source": "SEC EDGAR",
    })
    return result


def screen(tickers=None, log_fn=None, with_price=True):
    """여러 종목 현금창출 비교 요약(EDGAR). us_engine.screen과 동일 구조."""
    def log(msg):
        if log_fn:
            log_fn(msg)

    if tickers is None:
        tickers = DEFAULT_UNIVERSE

    rows = []
    for tk in tickers:
        a = analyze(tk, log_fn=log_fn, with_price=with_price)
        if not a["ok"]:
            rows.append({"ticker": tk.upper(), "name": tk.upper(), "ok": False,
                         "error": a["error"]})
            continue
        latest = a["latest"] or {}
        rows.append({
            "ticker": a["ticker"], "name": a["overview"]["name"], "ok": True,
            "currency": a["overview"]["currency"],
            "currency_mismatch": a["overview"]["currency_mismatch"],
            "market_cap": a["overview"]["market_cap"],
            "cfo": latest.get("cfo"), "fcf": latest.get("fcf"),
            "fcf_margin": latest.get("fcf_margin"),
            "earnings_quality": latest.get("earnings_quality"),
            "roic": latest.get("roic"), "fcf_yield": a["valuation"]["fcf_yield"],
            "revenue_cagr": a["growth"]["revenue_cagr"], "error": None,
        })

    rows.sort(key=lambda r: (r["ok"] is False,
                             -(r.get("fcf_margin") if r.get("fcf_margin") is not None else -1e9)))
    return rows
