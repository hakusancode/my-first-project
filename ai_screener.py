"""
ai_screener.py — 기업 사업설명 기반 'AI 노출도' 자동 탐지 + 재무 결합 랭킹

수동으로 AI 종목 리스트를 만드는 대신, 각 기업이 스스로 공시한 사업설명
(business description) 텍스트에서 AI 관련 키워드를 분석해 'AI 노출도 점수'를
자동 계산한다. 여기에 현금창출·성장성 지표를 결합해
"AI에 노출돼 있으면서 재무도 좋은" 기업을 걸러낸다.

- 미국: yfinance의 longBusinessSummary(영문) 사용 (인증키 불필요)
- 재무 결합: sec_engine(EDGAR) 우선, 실패 시 us_engine(Yahoo)

주의: 과거·현재 공시 기준의 후보 압축 도구다. 미래 예측이 아니다.

사용법:
    python ai_screener.py                    # 기본 유니버스(AI+비AI 혼합) 랭킹
    python ai_screener.py NVDA MSFT KO       # 지정 종목
    python ai_screener.py --no-fin NVDA KO   # 재무 결합 없이 AI 점수만(빠름)
"""

import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# (정규식 패턴, 표시 라벨, 가중치) — 소문자 기준으로 매칭
_AI_TERMS = [
    # 강한 신호 (3)
    (r"artificial intelligence", "artificial intelligence", 3),
    (r"generative ai", "generative AI", 3),
    (r"machine learning", "machine learning", 3),
    (r"deep learning", "deep learning", 3),
    (r"large language model", "LLM", 3),
    (r"\bllms?\b", "LLM", 3),
    (r"neural network", "neural network", 3),
    (r"\bgpus?\b", "GPU", 3),
    (r"\bhbm\b", "HBM", 3),
    (r"ai infrastructure", "AI infrastructure", 3),
    (r"ai accelerator", "AI accelerator", 3),
    (r"accelerated computing", "accelerated computing", 3),
    (r"foundation model", "foundation model", 3),
    (r"\binference\b", "inference", 3),
    (r"agentic", "agentic", 3),
    # 중간 신호 (2)
    (r"data center", "data center", 2),
    (r"computer vision", "computer vision", 2),
    (r"natural language", "natural language", 2),
    (r"autonomous", "autonomous", 2),
    (r"\bcopilot\b", "copilot", 2),
    (r"chatbot", "chatbot", 2),
    (r"supercomput", "supercomputing", 2),
    (r"high[- ]performance computing", "HPC", 2),
    (r"predictive analytics", "predictive analytics", 2),
    # 약한/일반 신호 (1)
    (r"\bai\b", "AI", 1),
    (r"\bml\b", "ML", 1),
    (r"algorithm", "algorithm", 1),
    (r"analytics", "analytics", 1),
    (r"automation", "automation", 1),
    (r"semiconductor", "semiconductor", 1),
    (r"\bcloud\b", "cloud", 1),
    (r"\bchips?\b", "chip", 1),
    (r"\bcompute\b", "compute", 1),
]


def score_text(text):
    """사업설명 텍스트의 AI 노출도 점수와 매칭 키워드를 반환.
    반환: (score: float, matched: [(label, count, weight), ...])"""
    if not text:
        return 0.0, []
    t = text.lower()
    score = 0.0
    agg = {}  # label -> (count, weight)
    for pat, label, w in _AI_TERMS:
        n = len(re.findall(pat, t))
        if n:
            score += w * min(n, 3)   # 과다 반복 상한
            c, _ = agg.get(label, (0, w))
            agg[label] = (c + n, w)
    matched = [(label, c, w) for label, (c, w) in agg.items()]
    matched.sort(key=lambda x: (-x[2], -x[1]))   # 가중치·빈도 순
    return score, matched


def business_summary(ticker):
    """yfinance에서 사업설명·회사명·섹터 조회."""
    import logging
    import yfinance as yf
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    info = yf.Ticker(ticker).info or {}
    name = info.get("shortName") or info.get("longName") or ticker
    return info.get("longBusinessSummary", "") or "", name, info.get("sector")


def analyze_ai(ticker, with_financials=True, log_fn=None):
    """한 종목의 AI 노출도(+선택적 재무)를 반환."""
    ticker = ticker.strip().upper()
    summary, name, sector = business_summary(ticker)
    score, matched = score_text(summary)
    out = {
        "ticker": ticker, "name": name, "sector": sector,
        "ai_score": score, "matched": matched, "has_summary": bool(summary),
        "market_cap": None, "fcf_margin": None, "roic": None, "revenue_cagr": None,
    }
    if with_financials:
        try:
            import sec_engine
            a = sec_engine.analyze(ticker, log_fn=log_fn)
            if not a["ok"]:
                import us_engine
                a = us_engine.analyze(ticker, log_fn=log_fn)
            if a["ok"]:
                latest = a["latest"] or {}
                out["market_cap"] = a["overview"]["market_cap"]
                out["fcf_margin"] = latest.get("fcf_margin")
                out["roic"] = latest.get("roic")
                out["revenue_cagr"] = a["growth"]["revenue_cagr"]
        except Exception:  # noqa: BLE001
            pass
    return out


def screen_ai(tickers, with_financials=True, log_fn=None):
    """여러 종목을 AI 노출도 내림차순으로 랭킹."""
    rows = []
    for t in tickers:
        if log_fn:
            log_fn(f"{t} 분석 중...")
        rows.append(analyze_ai(t, with_financials, log_fn=None))
    rows.sort(key=lambda r: -r["ai_score"])
    return rows


# 기본 유니버스: AI 밸류체인 + 대조군(비AI) 혼합 → 판별력 확인용
_DEFAULT = ["NVDA", "MSFT", "GOOGL", "META", "AMZN", "AVGO", "AMD", "PLTR",
            "ORCL", "ANET", "MU", "PG", "KO", "WMT", "XOM"]


def _fmt_usd(v):
    if v is None:
        return "N/A"
    a = abs(v)
    if a >= 1e12:
        return f"${a/1e12:.2f}T"
    if a >= 1e9:
        return f"${a/1e9:.0f}B"
    return f"${a/1e6:.0f}M"


def _pct(v):
    return "N/A" if v is None else f"{v:.1f}%"


def main(argv):
    args = argv[1:]
    with_fin = "--no-fin" not in args
    args = [a for a in args if a != "--no-fin"]
    tickers = args or _DEFAULT

    print(f"\nAI 노출도 자동 탐지 ({len(tickers)}개 종목)"
          f"{' + 재무 결합' if with_fin else ''}...\n")
    rows = screen_ai(tickers, with_fin, log_fn=lambda m: print(f"  · {m}"))

    print("\n" + "=" * 78)
    print("  AI 노출도 랭킹 (사업설명 키워드 기반)")
    print("=" * 78)
    print(f"  {'#':<3}{'티커':<7}{'AI점수':>6}  {'FCF마진':>8}{'ROIC':>7}{'매출CAGR':>9}   주요 키워드")
    print("  " + "-" * 74)
    for i, r in enumerate(rows, 1):
        kws = ", ".join(f"{lbl}×{c}" if c > 1 else lbl for lbl, c, w in r["matched"][:5])
        if not r["has_summary"]:
            kws = "(사업설명 없음)"
        print(f"  {i:<3}{r['ticker']:<7}{r['ai_score']:>6.0f}  "
              f"{_pct(r['fcf_margin']):>8}{_pct(r['roic']):>7}{_pct(r['revenue_cagr']):>9}   {kws}")
    print("\n  ※ 사업설명(공시) 기준 AI 노출도입니다. 미래 예측이 아니라 후보 압축용입니다.")
    print("     AI 점수 높고 FCF마진·ROIC·성장률이 좋은 기업이 'AI로 현금 버는' 후보입니다.")


if __name__ == "__main__":
    main(sys.argv)
