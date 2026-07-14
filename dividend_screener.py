"""
dividend_screener.py — 한국·미국 고배당주 스크리너

단순히 배당수익률만 높은 종목을 나열하지 않는다. 배당수익률이 높은 이유가
'주가가 빠져서'이거나 '벌지도 못하는 돈을 나눠줘서'인 경우(= 배당 함정)를
걸러내기 위해, 배당의 지속가능성을 함께 평가한다.

  · 배당수익률  — 얼마나 주는가
  · 배당성향    — 순이익 대비 얼마나 무리해서 주는가 (100% 초과 = 적자 배당)
  · FCF 커버리지 — 잉여현금흐름으로 배당을 몇 배 감당하는가 (1배 미만 = 빚내서 배당)
  · 연속 배당   — 3년 내내 배당했는가, 늘렸는가

  → 이를 종합해 안전등급(양호 / 주의 / 위험)을 매긴다.

데이터원
  · 한국: DART alotMatter(배당) + fnlttSinglAcntAll(현금흐름). 배당수익률은
          ① DART 공시 시가배당률(결산 시점 주가 기준)과
          ② 현재가 기준 재계산치(최근 DPS ÷ yfinance 현재가)를 함께 표시한다.
  · 미국: yfinance(배당·주가) + SEC EDGAR(FCF·배당총액)

2단계 조회로 속도를 아낀다: 1단계에서 배당수익률로 후보를 압축하고,
무거운 재무제표 조회(2단계)는 살아남은 종목에만 수행한다.

사용법:
    python dividend_screener.py                      # 미국 기본 유니버스
    python dividend_screener.py --kr                 # 한국 기본 유니버스(시총 상위)
    python dividend_screener.py --kr --min-yield 4   # 배당률 4% 이상만
    python dividend_screener.py --kr 삼성전자 KT&G 005930    # 지정 종목(이름/종목코드)
    python dividend_screener.py KO PG XOM            # 지정 티커
    python dividend_screener.py --top 15 --csv out.csv
    python dividend_screener.py --no-deep            # 1단계만(빠름, 안전성 평가 생략)

한국 모드는 DART 인증키가 필요하다:  $env:DART_API_KEY='발급키'
"""

import concurrent.futures as _cf
import csv
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ── 기본 유니버스 (시총 상위 + 배당 관련 섹터 위주) ──────────────────────────

# 미국: S&P 대형주 중 배당 관련성이 높은 섹터(에너지·유틸리티·통신·금융·리츠·
# 필수소비재·헬스케어) 위주 + 무배당 대조군(NVDA 등) 일부
_US_UNIVERSE = [
    # 테크
    "AAPL", "MSFT", "NVDA", "AVGO", "CSCO", "ORCL", "IBM", "TXN", "QCOM", "ADI", "INTC", "HPQ",
    # 통신·미디어
    "T", "VZ", "CMCSA",
    # 에너지
    "XOM", "CVX", "COP", "EOG", "SLB", "PSX", "VLO", "MPC", "KMI", "WMB", "OKE",
    # 유틸리티
    "NEE", "DUK", "SO", "D", "AEP", "EXC", "XEL", "ED", "PEG", "WEC",
    # 금융
    "JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "USB", "PNC", "TFC", "AXP", "CB", "MET", "PRU",
    # 필수소비재
    "PG", "KO", "PEP", "PM", "MO", "CL", "KMB", "GIS", "K", "HSY", "SYY", "KHC", "ADM",
    # 헬스케어
    "JNJ", "PFE", "MRK", "ABBV", "AMGN", "BMY", "GILD", "CVS", "UNH", "MDT",
    # 산업재
    "CAT", "MMM", "HON", "LMT", "RTX", "GD", "UPS", "EMR", "ITW",
    # 리츠
    "O", "VICI", "SPG", "PLD", "AMT", "CCI", "IRM", "WPC",
    # 경기소비재
    "MCD", "HD", "SBUX", "TGT", "LOW", "F", "GM",
]

# 한국: (종목코드, 시장) — 시장은 yfinance 접미사(KS=코스피, KQ=코스닥)
# 회사명은 CORPCODE.xml에서 종목코드로 정확 매칭해 가져온다.
_KR_UNIVERSE = [
    # 시총 상위 (코스피)
    ("005930", "KS"), ("000660", "KS"), ("373220", "KS"), ("207940", "KS"), ("005380", "KS"),
    ("000270", "KS"), ("068270", "KS"), ("005490", "KS"), ("051910", "KS"), ("006400", "KS"),
    ("035420", "KS"), ("035720", "KS"), ("012330", "KS"), ("028260", "KS"), ("066570", "KS"),
    ("009150", "KS"), ("010130", "KS"), ("018260", "KS"), ("051900", "KS"), ("097950", "KS"),
    # 금융 (전통적 고배당)
    ("105560", "KS"), ("055550", "KS"), ("086790", "KS"), ("316140", "KS"), ("138040", "KS"),
    ("024110", "KS"), ("032830", "KS"), ("000810", "KS"), ("005830", "KS"), ("001450", "KS"),
    ("088350", "KS"), ("071050", "KS"), ("006800", "KS"), ("016360", "KS"), ("029780", "KS"),
    # 통신·유틸리티
    ("017670", "KS"), ("030200", "KS"), ("032640", "KS"), ("015760", "KS"), ("036460", "KS"),
    # 에너지·화학·소재
    ("010950", "KS"), ("096770", "KS"), ("011170", "KS"), ("004020", "KS"), ("009830", "KS"),
    # 지주·기타 고배당 후보
    ("033780", "KS"), ("034730", "KS"), ("003550", "KS"), ("001040", "KS"), ("000880", "KS"),
    ("267250", "KS"), ("021240", "KS"), ("086280", "KS"), ("161390", "KS"), ("011200", "KS"),
    # 소비재·유통·제약
    ("271560", "KS"), ("004370", "KS"), ("139480", "KS"), ("069960", "KS"), ("023530", "KS"),
    ("282330", "KS"), ("007070", "KS"), ("090430", "KS"), ("000100", "KS"), ("128940", "KS"),
    # 산업재·조선·방산·건설
    ("009540", "KS"), ("010140", "KS"), ("042660", "KS"), ("012450", "KS"), ("047810", "KS"),
    ("000720", "KS"), ("006360", "KS"), ("047040", "KS"), ("034020", "KS"), ("241560", "KS"),
    ("267260", "KS"), ("003490", "KS"),
    # 코스닥
    ("247540", "KQ"), ("086520", "KQ"), ("196170", "KQ"), ("293490", "KQ"), ("041510", "KQ"),
]


# ── 공통 유틸 ────────────────────────────────────────────────────────────────

def _num(v):
    """None/NaN/빈값을 None으로 정규화."""
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f          # NaN 방어


def _safe_div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def pct(v, nd=2):
    return "N/A" if v is None else f"{v:.{nd}f}%"


def mult(v):
    return "N/A" if v is None else f"{v:.1f}x"


_FINANCIAL_SECTORS = ("Financial Services", "Financial")


def is_reit(row):
    return (row.get("sector") or "") == "Real Estate"


def is_financial(row):
    return (row.get("sector") or "") in _FINANCIAL_SECTORS


def grade(row):
    """배당 안전등급을 매긴다. (등급, 사유리스트) 반환.

    위험: 배당성향 100% 초과(못 버는 돈을 배당) 또는 FCF 커버리지 1배 미만(현금 부족)
    주의: 배당성향 80% 초과, FCF 커버리지 1.5배 미만, 또는 배당 중단 이력
    양호: 위 항목 모두 통과
    미평가: 판단할 데이터가 없음 (--no-deep 이거나 조회 실패)

    업종별 예외 — 지표를 그대로 적용하면 오탐이 나는 두 업종은 기준을 바꾼다:
      · 리츠: 감가상각이 커서 순이익 기준 배당성향이 구조적으로 100%를 넘는다
              (실제로는 FFO로 배당). → 배당성향 대신 현금흐름으로 판정.
      · 금융(은행·보험·증권): 대출·예금·보험료가 영업활동현금흐름에 섞여 FCF가
              의미를 잃는다(기업은행 −23.6x 등). → 현금흐름 대신 배당성향으로 판정.
    """
    payout = row.get("payout_ratio")          # %
    cover = row.get("fcf_coverage")           # 배수
    streak = row.get("div_streak")            # 3년 중 배당한 연수
    reit, fin = is_reit(row), is_financial(row)

    use_payout = payout is not None and not reit
    use_cover = cover is not None and not fin

    dangers, cautions, notes = [], [], []

    if reit and payout is not None:
        notes.append(f"리츠(배당성향 {payout:.0f}%는 감가상각 탓, 현금흐름으로 판정)")
    if fin and cover is not None:
        notes.append("금융업(FCF는 무의미, 배당성향으로 판정)")

    # 회계상 적자·현금흐름 부족이 동시에 오면 진짜 배당 함정이지만, 한쪽만 나쁜 경우는
    # 대개 일회성 손상(비현금) 또는 연결 금융부문 탓이다. 둘을 교차로 확인해 등급을 낮춘다.
    cash_covers = use_cover and cover >= 1

    if use_payout:
        if payout < 0:
            if cash_covers:
                cautions.append(f"회계상 적자이나 현금흐름은 배당을 감당({cover:.1f}x, "
                                f"일회성 손상 가능)")
            else:
                dangers.append("적자 중 배당")
        elif payout > 100:
            dangers.append(f"배당성향 {payout:.0f}%(순이익 초과)")
        elif payout > 80:
            cautions.append(f"배당성향 {payout:.0f}%(높음)")

    if use_cover:
        if cover < 1:
            # 이익 대비 배당이 낮은데 현금흐름만 나쁜 경우는 배당 함정과 다르다.
            # 할부금융 자회사를 연결하는 제조사(현대차 등)는 금융자산 증가가 영업활동
            # 현금흐름을 갉아먹어 FCF가 마이너스로 나온다. → 위험이 아니라 확인 대상.
            if use_payout and 0 <= payout <= 60:
                cautions.append(f"FCF 커버리지 {cover:.2f}x이나 배당성향 {payout:.0f}%로 낮음"
                                f"(연결 금융부문 등 확인 필요)")
            else:
                dangers.append(f"FCF 커버리지 {cover:.2f}x(현금흐름 미달)")
        elif cover < 1.5:
            cautions.append(f"FCF 커버리지 {cover:.2f}x(빠듯)")

    if streak is not None and streak < 3:
        cautions.append(f"3년 중 {streak}년만 배당")

    # 심각한 사유가 먼저 오게 한다 — 표에는 첫 사유만 보이므로 판정 근거가 가려지면 안 된다.
    reasons = dangers + cautions + notes

    if not use_payout and not use_cover:
        return "미평가", reasons
    if dangers:
        return "위험", reasons
    if cautions:
        return "주의", reasons
    return "양호", reasons or ["배당성향·현금흐름 안정"]


def _rank(rows, top=None):
    """배당수익률 내림차순 정렬. 수익률 없는 종목은 뒤로."""
    rows.sort(key=lambda r: (r.get("div_yield") is None, -(r.get("div_yield") or 0)))
    return rows if top is None else rows[:top]


# ── 미국 ─────────────────────────────────────────────────────────────────────

def _us_quick(ticker):
    """1단계: yfinance info 1회로 배당수익률·배당성향·주가 등 확보 (가볍다)."""
    import logging
    import yfinance as yf
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)

    out = {"ticker": ticker, "name": ticker, "sector": None, "ok": False, "error": None,
           "price": None, "market_cap": None, "dps": None, "div_yield": None,
           "payout_ratio": None, "fcf_coverage": None, "div_streak": None}
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as e:  # noqa: BLE001
        out["error"] = f"조회 실패: {e}"
        return out

    price = _num(info.get("currentPrice") or info.get("regularMarketPrice"))
    # 연간 주당배당금(달러)에서 직접 수익률을 계산한다. info["dividendYield"]는
    # yfinance 버전에 따라 비율(0.025)/퍼센트(2.5)가 섞여 나와 신뢰할 수 없다.
    rate = _num(info.get("trailingAnnualDividendRate")) or _num(info.get("dividendRate"))
    out.update({
        "name": info.get("shortName") or info.get("longName") or ticker,
        "sector": info.get("sector"),
        "price": price,
        "market_cap": _num(info.get("marketCap")),
        "dps": rate,
        "div_yield": _safe_div(rate, price) and _safe_div(rate, price) * 100,
        "ok": True,
    })
    po = _num(info.get("payoutRatio"))        # 비율(0.35) → %
    out["payout_ratio"] = None if po is None else po * 100
    return out


def _us_deep(row, log_fn=None):
    """2단계: EDGAR(실패 시 Yahoo) 재무제표로 FCF 커버리지·연속배당 확인."""
    ticker = row["ticker"]
    try:
        import sec_engine
        a = sec_engine.analyze(ticker, log_fn=log_fn)
        if not a["ok"]:
            import us_engine
            a = us_engine.analyze(ticker, log_fn=log_fn)
        if not a["ok"]:
            return row
    except Exception:  # noqa: BLE001
        return row

    annual = a.get("annual") or []
    if not annual:
        return row

    latest = annual[-1]
    fcf = latest.get("fcf")
    paid = latest.get("dividends_paid")
    # 리츠는 부동산 '취득'을 capex 태그로 신고하지 않는 곳이 많아 FCF가 비는데(VICI·WPC),
    # 취득은 성장투자라 배당 감당 능력은 CFO로 보는 게 맞다(AFFO 대용).
    if fcf is None and is_reit(row):
        fcf = latest.get("cfo")
        row["cover_basis"] = "CFO"
    row["fcf_coverage"] = _safe_div(fcf, paid)
    # 배당성향은 EDGAR 실적 기준값을 우선 채택(1단계 yfinance 값보다 정확)
    if latest.get("payout_ratio") is not None:
        row["payout_ratio"] = latest["payout_ratio"]
    # 배당총액을 한 해도 못 읽었으면 '배당 안 했다'가 아니라 '알 수 없다'로 둔다.
    paid3 = [r.get("dividends_paid") for r in annual[-3:]]
    row["div_streak"] = (None if all(v is None for v in paid3)
                         else sum(1 for v in paid3 if (v or 0) > 0))
    row["div_years"] = len(paid3)
    return row


def screen_us(tickers, min_yield=0.0, deep=True, workers=6, log_fn=None):
    def log(m):
        if log_fn:
            log_fn(m)

    log(f"1단계: 배당 정보 조회 ({len(tickers)}개)...")
    rows = []
    with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_us_quick, tickers):
            rows.append(r)

    cands = [r for r in rows if (r.get("div_yield") or 0) >= min_yield and r["ok"]]
    log(f"  → 배당률 {min_yield}% 이상: {len(cands)}개")

    if deep and cands:
        log(f"2단계: 배당 지속가능성 검증 ({len(cands)}개)...")
        with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
            cands = list(ex.map(lambda r: _us_deep(r), cands))
    return _rank(cands)


# ── 한국 ─────────────────────────────────────────────────────────────────────

def _kr_price(stock_code, market):
    """yfinance로 한국 종목 현재가 조회 (005930.KS 형식). 실패 시 None.

    시장(KS/KQ)을 모르면 둘 다 시도한다. FastInfo.get()은 항상 None을 반환하므로
    속성 접근을 쓴다.
    """
    import logging
    import yfinance as yf
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    for suffix in ([market] if market else ["KS", "KQ"]):
        try:
            p = _num(getattr(yf.Ticker(f"{stock_code}.{suffix}").fast_info, "last_price", None))
            if p:
                return p
        except Exception:  # noqa: BLE001
            continue
    return None


def _kr_quick(api_key, corp, end_year):
    """1단계: DART 배당 API 1회 + 현재가 1회."""
    import dart_engine as de

    out = {"corp_code": corp["corp_code"], "stock_code": corp.get("stock_code", ""),
           "market": corp.get("market"), "name": corp["corp_name"], "ok": False, "error": None,
           "price": None, "dps": None, "div_yield": None, "dart_yield": None,
           "payout_ratio": None, "fcf_coverage": None, "div_streak": None}
    try:
        div3 = de.get_dividend_info_3y(api_key, corp["corp_code"], end_year)
    except Exception as e:  # noqa: BLE001
        out["error"] = f"배당 조회 실패: {e}"
        return out

    latest = div3[-1]
    dps = latest.get("주당배당금(원)")
    dps3 = [r.get("주당배당금(원)") for r in div3]
    out.update({
        "ok": True,
        "dps": dps,
        "dart_yield": latest.get("시가배당률(%)"),      # 공시값(결산 시점 주가 기준)
        "payout_ratio": latest.get("배당성향(%)"),
        "div_total": latest.get("현금배당총액(백만원)"),
        # 한 해도 못 읽었으면 '무배당'이 아니라 '알 수 없음'
        "div_streak": (None if all(v is None for v in dps3)
                       else sum(1 for v in dps3 if (v or 0) > 0)),
        "div_years": len(dps3),
    })

    price = _kr_price(out["stock_code"], out["market"]) if out["stock_code"] else None
    out["price"] = price
    # 현재가 기준 배당률. 현재가를 못 구하면 공시 시가배당률로 폴백한다.
    cur = _safe_div(dps, price)
    out["div_yield"] = cur * 100 if cur is not None else out["dart_yield"]
    return out


def _kr_sector(stock_code, market):
    """yfinance로 업종 조회 (금융·리츠 판정용). 실패 시 None."""
    import logging
    import yfinance as yf
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    for suffix in ([market] if market else ["KS", "KQ"]):
        try:
            info = yf.Ticker(f"{stock_code}.{suffix}").info or {}
            if info.get("sector"):
                return info["sector"]
        except Exception:  # noqa: BLE001
            continue
    return None


def _kr_deep(api_key, row, end_year):
    """2단계: 현금흐름표로 FCF 커버리지 확인 (DART 2회 호출) + 업종 판별."""
    import dart_engine as de
    if row.get("stock_code"):
        row["sector"] = _kr_sector(row["stock_code"], row.get("market"))
    try:
        key3 = de.get_key_financials_3y(api_key, row["corp_code"], end_year)
        cf3 = de.get_cashflow_3y(api_key, row["corp_code"], end_year)
        metrics = de.calculate_cashflow_metrics(key3, cf3)
    except Exception:  # noqa: BLE001
        return row

    if not metrics:
        return row
    fcf = metrics[-1].get("잉여현금흐름")          # 원
    total_mn = row.get("div_total")                # 백만원
    total = None if total_mn is None else total_mn * 1_000_000
    row["fcf_coverage"] = _safe_div(fcf, total)
    row["fcf"] = fcf
    return row


def _resolve_kr(api_key, targets, log_fn=None):
    """종목코드/회사명 목록을 corp 레코드로 해석한다.

    targets 항목: (종목코드, 시장) 튜플 또는 문자열(6자리 종목코드 또는 회사명).
    """
    import dart_engine as de
    corp_list = de.load_corp_list(api_key, log_fn=log_fn)
    by_stock = {c["stock_code"]: c for c in corp_list if c.get("stock_code")}

    resolved = []
    for t in targets:
        market = None
        if isinstance(t, tuple):
            code, market = t
        else:
            code = t.strip()

        if code.isdigit() and len(code) == 6:
            corp = by_stock.get(code)
            if not corp:
                if log_fn:
                    log_fn(f"  ! 종목코드 {code}: DART 목록에 없음(비상장/폐지)")
                continue
        else:
            hits = [h for h in de.search_company(corp_list, code) if h.get("stock_code")]
            if not hits:
                if log_fn:
                    log_fn(f"  ! '{code}': 상장사 검색 결과 없음")
                continue
            # 정확일치 > 이름이 키워드로 시작 > 짧은 이름 순. '현대차'가 '현대차증권'에
            # 걸리는 식의 오매칭이 조용히 넘어가지 않도록, 정확일치가 아니면 알린다.
            exact = [h for h in hits if h["corp_name"] == code]
            if exact:
                corp = exact[0]
            else:
                hits.sort(key=lambda h: (not h["corp_name"].startswith(code),
                                         len(h["corp_name"])))
                corp = hits[0]
                if log_fn:
                    others = f" (후보 {len(hits)}개)" if len(hits) > 1 else ""
                    log_fn(f"  ! '{code}' → '{corp['corp_name']}'"
                           f"[{corp['stock_code']}]로 해석{others}. 정확하지 않으면 종목코드로 지정하세요.")

        resolved.append({**corp, "market": market})
    return resolved


def screen_kr(api_key, targets, end_year=2024, min_yield=0.0, deep=True, workers=4, log_fn=None):
    def log(m):
        if log_fn:
            log_fn(m)

    corps = _resolve_kr(api_key, targets, log_fn=log)
    log(f"1단계: 배당 정보 조회 ({len(corps)}개)...")

    rows = []
    with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(lambda c: _kr_quick(api_key, c, end_year), corps):
            rows.append(r)

    cands = [r for r in rows if r["ok"] and (r.get("div_yield") or 0) >= min_yield]
    log(f"  → 배당률 {min_yield}% 이상: {len(cands)}개")

    if deep and cands:
        log(f"2단계: 배당 지속가능성 검증 ({len(cands)}개)...")
        with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
            cands = list(ex.map(lambda r: _kr_deep(api_key, r, end_year), cands))
    return _rank(cands)


# ── 출력 ─────────────────────────────────────────────────────────────────────

_GRADE_MARK = {"양호": "○", "주의": "△", "위험": "×", "미평가": "-"}


def print_table(rows, market, end_year=None):
    is_kr = market == "kr"
    title = (f"[한국] 고배당 스크리너 (DART {end_year} 사업연도 배당)" if is_kr
             else "[미국] 고배당 스크리너 (yfinance + SEC EDGAR)")
    width = 100
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)

    if is_kr:
        head = (f"  {'#':<3}{'회사':<16}{'배당률':>7}{'공시':>7}{'DPS':>9}"
                f"{'배당성향':>8}{'FCF커버':>8}{'연속':>6}  {'등급':<5} 비고")
    else:
        head = (f"  {'#':<3}{'티커':<7}{'회사':<20}{'배당률':>7}{'DPS':>8}"
                f"{'배당성향':>8}{'FCF커버':>8}{'연속':>6}  {'등급':<5} 비고")
    print(head)
    print("  " + "-" * (width - 4))

    for i, r in enumerate(rows, 1):
        g, reasons = grade(r)
        note = reasons[0] if reasons else ""
        streak = (f"{r['div_streak']}/{r.get('div_years', 3)}"
                  if r.get("div_streak") is not None else "N/A")
        mark = f"{_GRADE_MARK[g]} {g}"

        if is_kr:
            dps = "N/A" if r.get("dps") is None else f"{r['dps']:,.0f}"
            print(f"  {i:<3}{r['name'][:15]:<16}{pct(r.get('div_yield'), 2):>7}"
                  f"{pct(r.get('dart_yield'), 1):>7}{dps:>9}"
                  f"{pct(r.get('payout_ratio'), 0):>8}{mult(r.get('fcf_coverage')):>8}"
                  f"{streak:>6}  {mark:<5} {note}")
        else:
            dps = "N/A" if r.get("dps") is None else f"${r['dps']:.2f}"
            print(f"  {i:<3}{r['ticker']:<7}{(r['name'] or '')[:19]:<20}"
                  f"{pct(r.get('div_yield'), 2):>7}{dps:>8}"
                  f"{pct(r.get('payout_ratio'), 0):>8}{mult(r.get('fcf_coverage')):>8}"
                  f"{streak:>6}  {mark:<5} {note}")

    print()
    if is_kr:
        print("  · 배당률 = 최근 DPS ÷ 현재가(yfinance).  공시 = DART 시가배당률(결산 시점 주가 기준).")
    print("  · FCF커버 = 잉여현금흐름 ÷ 현금배당총액. 1배 미만이면 벌어들인 현금보다 많이 배당한 것.")
    print("  · 연속 = 최근 3개 사업연도 중 배당한 횟수.")
    print("  · 등급: ○ 양호 / △ 주의 / × 위험(배당 함정 의심) / - 미평가")
    print("  ※ 공시된 과거 배당 기준입니다. 미래 배당을 보장하지 않습니다.")


def write_csv(rows, path, market):
    is_kr = market == "kr"
    cols = (["name", "stock_code", "div_yield", "dart_yield", "dps", "payout_ratio",
             "fcf_coverage", "div_streak", "price", "grade", "note"] if is_kr else
            ["ticker", "name", "sector", "div_yield", "dps", "payout_ratio",
             "fcf_coverage", "div_streak", "price", "market_cap", "grade", "note"])
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            g, reasons = grade(r)
            w.writerow({**r, "grade": g, "note": "; ".join(reasons)})
    print(f"  CSV 저장: {path}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def _pop_opt(args, name, cast=str, default=None):
    """--name value 형식 옵션을 args에서 꺼낸다."""
    if name not in args:
        return default
    i = args.index(name)
    if i + 1 >= len(args):
        raise SystemExit(f"{name} 옵션에 값이 필요합니다.")
    val = args[i + 1]
    del args[i:i + 2]
    return cast(val)


def main(argv):
    args = argv[1:]
    is_kr = "--kr" in args
    deep = "--no-deep" not in args
    args = [a for a in args if a not in ("--kr", "--no-deep")]

    min_yield = _pop_opt(args, "--min-yield", float, 0.0)
    top = _pop_opt(args, "--top", int, None)
    csv_path = _pop_opt(args, "--csv", str, None)
    year = _pop_opt(args, "--year", int, 2024)

    log = lambda m: print(f"  · {m}")  # noqa: E731

    if is_kr:
        key = os.environ.get("DART_API_KEY", "")
        if not key:
            print("한국(--kr) 모드는 DART 인증키가 필요합니다.")
            print("  예: $env:DART_API_KEY='키'; python dividend_screener.py --kr")
            return
        targets = args or _KR_UNIVERSE
        print(f"\n[한국] 고배당 스크리닝 ({len(targets)}개 종목, {year} 사업연도)...\n")
        rows = screen_kr(key, targets, end_year=year, min_yield=min_yield,
                         deep=deep, log_fn=log)
        rows = rows[:top] if top else rows
        print_table(rows, "kr", end_year=year)
    else:
        tickers = [a.upper() for a in args] or _US_UNIVERSE
        print(f"\n[미국] 고배당 스크리닝 ({len(tickers)}개 종목)...\n")
        rows = screen_us(tickers, min_yield=min_yield, deep=deep, log_fn=log)
        rows = rows[:top] if top else rows
        print_table(rows, "us")

    if csv_path:
        write_csv(rows, csv_path, "kr" if is_kr else "us")


if __name__ == "__main__":
    main(sys.argv)
