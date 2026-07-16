"""
us_report.py — 미국 기업 재무분석 CLI 데모

데이터원 2가지를 선택할 수 있다:
    --edgar   SEC EDGAR 공식 XBRL (기본) — 정확·안정, 미국 국내기업(10-K)
    --yahoo   yfinance(Yahoo) — 빠르고 외국기업(20-F, 예: TSM)도 커버

사용법:
    python us_report.py NVDA               # 단일 종목 상세 (기본: EDGAR)
    python us_report.py NVDA MSFT AVGO     # 여러 종목 각각
    python us_report.py --screen           # AI 밸류체인 기본 유니버스 현금창출 랭킹
    python us_report.py --screen MU AVGO   # 지정 종목 랭킹
    python us_report.py --yahoo TSM        # Yahoo 소스로 조회

수익성·성장성·안정성·배당·밸류에이션을 기본으로, 현금흐름 분석을 함께 보여준다.
"""

import sys

# 어느 컴퓨터에서나 한글이 깨지지 않도록 표준출력을 UTF-8로 (Windows cp949 대응)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import us_engine as ue
import sec_engine as se


# ── 포맷 헬퍼 ────────────────────────────────────────────────────────────────

_CUR_SYMBOL = {"USD": "$", "TWD": "NT$", "KRW": "₩", "EUR": "€", "JPY": "¥", "GBP": "£"}


def cur_symbol(code):
    if not code:
        return "$"
    return _CUR_SYMBOL.get(code.upper(), code.upper() + " ")


def money(v, cur="$"):
    """큰 금액을 조/십억/백만 단위로. (달러 기준)"""
    if v is None:
        return "N/A"
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e12:
        return f"{sign}{cur}{a/1e12:.2f}T"
    if a >= 1e9:
        return f"{sign}{cur}{a/1e9:.2f}B"
    if a >= 1e6:
        return f"{sign}{cur}{a/1e6:.1f}M"
    return f"{sign}{cur}{a:,.0f}"


def pct(v, dp=1):
    return "N/A" if v is None else f"{v:.{dp}f}%"


def num(v, dp=2):
    return "N/A" if v is None else f"{v:.{dp}f}"


def mult(v, dp=2):
    return "N/A" if v is None else f"{v:.{dp}f}x"


def _cols(header, rows, aligns=None):
    """간단한 표 렌더러. rows: list[list[str]]. 열폭 자동."""
    ncol = len(header)
    widths = [len(str(header[i])) for i in range(ncol)]
    for r in rows:
        for i in range(ncol):
            widths[i] = max(widths[i], len(str(r[i])))
    aligns = aligns or ["<"] * ncol

    def fmt(r):
        return "  ".join(f"{str(r[i]):{aligns[i]}{widths[i]}}" for i in range(ncol))

    line = "  ".join("-" * widths[i] for i in range(ncol))
    out = [fmt(header), line]
    out += [fmt(r) for r in rows]
    return "\n".join(out)


# ── 단일 종목 리포트 ─────────────────────────────────────────────────────────

def report(ticker, eng=se):
    a = eng.analyze(ticker, log_fn=lambda m: None)
    if not a["ok"]:
        print(f"\n[{ticker.upper()}] ✗ {a['error']}")
        return

    ov, val, g = a["overview"], a["valuation"], a["growth"]
    cur = cur_symbol(ov["currency"])

    print("\n" + "=" * 72)
    print(f"  {ov['name']}  ({a['ticker']})")
    sub = " · ".join(x for x in [ov["sector"], ov["industry"]] if x)
    if sub:
        print(f"  {sub}")
    print(f"  데이터원: {a.get('source', 'Yahoo Finance')}")
    print("=" * 72)

    print(f"  현재가 {money(ov['price'], cur) if ov['price'] and ov['price']<1e6 else num(ov['price'])}"
          f"    시가총액 {money(ov['market_cap'], cur)}")
    print(f"  PER {mult(val['per'])}  선행PER {mult(val['forward_per'])}  "
          f"PBR {mult(val['pbr'])}  PSR {mult(val['psr'])}  "
          f"EV/EBITDA {mult(val['ev_ebitda'])}")
    print(f"  FCF수익률 {pct(val['fcf_yield'])}   배당수익률 {pct(val['dividend_yield'])}")
    if ov["currency_mismatch"]:
        print(f"  ※ 재무 보고통화={ov['currency']} / 주가통화={ov['trade_currency']} "
              f"→ 금액은 {ov['currency']} 기준, FCF수익률은 통화 불일치로 생략")

    yrs = a["years"]
    ann = a["annual"]

    header = ["지표"] + yrs

    # 수익성
    print("\n  ▸ 수익성")
    rows = [
        ["매출액"]     + [money(r["revenue"], cur) for r in ann],
        ["영업이익"]   + [money(r["operating_income"], cur) for r in ann],
        ["순이익"]     + [money(r["net_income"], cur) for r in ann],
        ["매출총이익률"] + [pct(r["gross_margin"]) for r in ann],
        ["영업이익률"] + [pct(r["operating_margin"]) for r in ann],
        ["순이익률"]   + [pct(r["net_margin"]) for r in ann],
        ["ROE"]        + [pct(r["roe"]) for r in ann],
        ["ROA"]        + [pct(r["roa"]) for r in ann],
        ["ROIC"]       + [pct(r["roic"]) for r in ann],
    ]
    print("  " + _cols(header, rows, ["<"] + [">"] * len(yrs)).replace("\n", "\n  "))

    # 성장성 (전년대비, 연도별)
    def yoy(cur_v, prev_v):
        if cur_v is None or prev_v is None or prev_v <= 0:
            return None
        return (cur_v - prev_v) / prev_v * 100.0

    def grow_row(key):
        out = []
        for i, r in enumerate(ann):
            out.append(pct(yoy(r.get(key), ann[i - 1].get(key))) if i > 0 else "-")
        return out
    print("\n  ▸ 성장성")
    rows = [
        ["매출성장률"]   + grow_row("revenue"),
        ["영업이익성장률"] + grow_row("operating_income"),
        ["순이익성장률"] + grow_row("net_income"),
        ["EPS성장률"]    + grow_row("diluted_eps"),
    ]
    print("  " + _cols(header, rows, ["<"] + [">"] * len(yrs)).replace("\n", "\n  "))
    print(f"    (매출 3년 CAGR {pct(g['revenue_cagr'])})")

    # 안정성
    print("\n  ▸ 안정성")
    rows = [
        ["부채비율(D/E)"] + [mult(r["debt_to_equity"]) for r in ann],
        ["유동비율"]      + [mult(r["current_ratio"]) for r in ann],
        ["이자보상배율"]  + [mult(r["interest_coverage"]) for r in ann],
        ["순부채"]        + [money(r["net_debt"], cur) for r in ann],
    ]
    print("  " + _cols(header, rows, ["<"] + [">"] * len(yrs)).replace("\n", "\n  "))

    # 배당
    def ps(v):
        return "N/A" if v is None else f"${v:.2f}"
    print("\n  ▸ 배당")
    rows = [
        ["주당배당금(DPS)"] + [ps(r.get("dps")) for r in ann],
        ["총현금배당"]      + [money(r.get("dividends_paid"), cur) for r in ann],
        ["배당성향"]        + [pct(r.get("payout_ratio")) for r in ann],
    ]
    print("  " + _cols(header, rows, ["<"] + [">"] * len(yrs)).replace("\n", "\n  "))

    # 현금창출 (보조 지표 — 맨 마지막)
    print("\n  ▸ 현금창출능력")
    rows = [
        ["영업현금흐름(CFO)"] + [money(r["cfo"], cur) for r in ann],
        ["CapEx"]           + [money(r["capex"], cur) for r in ann],
        ["잉여현금흐름(FCF)"] + [money(r["fcf"], cur) for r in ann],
        ["FCF 마진"]         + [pct(r["fcf_margin"]) for r in ann],
        ["이익의 질(CFO/영업이익)"] + [mult(r["earnings_quality"]) for r in ann],
        ["CapEx 강도(/매출)"] + [pct(r["capex_intensity"]) for r in ann],
    ]
    print("  " + _cols(header, rows, ["<"] + [">"] * len(yrs)).replace("\n", "\n  "))


# ── 스크리너 (현금창출 랭킹) ─────────────────────────────────────────────────

def screen(tickers, eng=se):
    src = "SEC EDGAR" if eng is se else "Yahoo Finance"
    print(f"\n현금창출 스크리닝 ({len(tickers)}개 종목, 데이터원: {src})...\n")
    rows = eng.screen(tickers, log_fn=lambda m: print(f"  · {m}"))

    print("\n" + "=" * 72)
    print("  AI 밸류체인 · 현금창출 랭킹 (최근 회계연도, FCF마진 내림차순)")
    print("=" * 72)
    header = ["#", "티커", "시총", "FCF", "FCF마진", "이익의질", "ROIC", "FCF수익률", "매출CAGR"]
    table = []
    rank = 0
    for r in rows:
        if not r["ok"]:
            table.append(["-", r["ticker"], "조회실패", "", "", "", "", "", ""])
            continue
        rank += 1
        sym = cur_symbol(r.get("currency"))
        tk = r["ticker"] + ("*" if r.get("currency_mismatch") else "")
        table.append([
            str(rank), tk, money(r["market_cap"]), money(r["fcf"], sym),
            pct(r["fcf_margin"]), mult(r["earnings_quality"]), pct(r["roic"]),
            pct(r["fcf_yield"]), pct(r["revenue_cagr"]),
        ])
    aligns = ["<", "<", ">", ">", ">", ">", ">", ">", ">"]
    print(_cols(header, table, aligns))
    if any(r.get("currency_mismatch") for r in rows if r["ok"]):
        print("\n* 재무 보고통화가 시총 통화와 달라(예: TSM=TWD) FCF는 보고통화 기준,"
              " FCF수익률은 생략됨. 시총은 USD.")
    print("※ 참고: 과거 재무 기준 스크리닝입니다. 미래 예측이 아니라 후보 압축용입니다.")


# ── 엔트리 ───────────────────────────────────────────────────────────────────

def main(argv):
    args = argv[1:]
    # 데이터원 선택 플래그
    eng = se  # 기본: SEC EDGAR
    if "--yahoo" in args:
        eng = ue
        args = [a for a in args if a != "--yahoo"]
    if "--edgar" in args:
        eng = se
        args = [a for a in args if a != "--edgar"]

    if not args:
        print(__doc__)
        return
    if args[0] in ("--screen", "-s"):
        tickers = args[1:] or ue.DEFAULT_UNIVERSE
        screen(tickers, eng)
    else:
        for tk in args:
            report(tk, eng)


if __name__ == "__main__":
    main(sys.argv)
