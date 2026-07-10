"""
test_cashflow.py — DART 현금흐름 엔진 라이브 검증 (인증키 필요)

실행 (PowerShell):
    $env:DART_API_KEY='발급받은키'; python test_cashflow.py
    $env:DART_API_KEY='발급받은키'; python test_cashflow.py 카카오   # 회사명 지정

또는 인자로 키 전달:
    python test_cashflow.py 삼성전자 발급받은키

DART_API_KEY 환경변수 또는 두 번째 인자로 인증키를 준다.
회사명 기본값은 삼성전자.
"""

import os
import sys

# 콘솔이 cp949여도 한글 출력되도록
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import dart_engine as de


def fmt_won(v):
    if v is None:
        return "N/A"
    a = abs(v)
    s = f"{a/1e12:.2f}조" if a >= 1e12 else (f"{a/1e8:.0f}억" if a >= 1e8 else f"{a:,}원")
    return ("-" + s) if v < 0 else s


def main():
    args = [a for a in sys.argv[1:]]
    company = "삼성전자"
    key = os.environ.get("DART_API_KEY", "")
    # 인자 파싱: 첫 번째=회사명(선택), 두 번째=키(선택)
    if args:
        company = args[0]
    if len(args) >= 2:
        key = args[1]

    if not key:
        print("✗ DART 인증키가 없습니다. DART_API_KEY 환경변수나 인자로 주세요.")
        print("  예: $env:DART_API_KEY='키'; python test_cashflow.py")
        return

    log = lambda m: print("  ·", m)

    print(f"\n[1] 회사 목록 로드 + '{company}' 검색...")
    de.load_corp_list(key, log_fn=log)
    hits = de.search_company(company)
    if not hits:
        print(f"✗ '{company}' 검색 결과 없음")
        return
    corp = hits[0]
    print(f"    → {corp['corp_name']} ({corp['corp_code']})  [검색결과 {len(hits)}건 중 첫 번째]")

    end_year = "2024"  # 최근 확정 사업연도 기준 (필요시 조정)
    print(f"\n[2] 핵심재무 + 현금흐름 3개년 조회 (기준연도 {end_year})...")
    key_3y = de.get_key_financials_3y(key, corp["corp_code"], end_year, log_fn=log)
    cf_3y = de.get_cashflow_3y(key, corp["corp_code"], end_year, log_fn=log)
    metrics = de.calculate_cashflow_metrics(key_3y, cf_3y)

    print(f"\n[3] 현금창출 지표 — {corp['corp_name']}")
    years = [m["year"] for m in metrics]
    print(f"    {'항목':<18}" + "".join(f"{y+'년':>14}" for y in years))
    print("    " + "-" * (18 + 14 * len(years)))
    rows = [
        ("영업활동현금흐름", "영업활동현금흐름", fmt_won),
        ("CapEx(유형취득)", "CapEx", fmt_won),
        ("잉여현금흐름(FCF)", "잉여현금흐름", fmt_won),
        ("FCF마진", "FCF마진", lambda v: "N/A" if v is None else f"{v:.1f}%"),
        ("이익의질(CFO/영업익)", "이익의질", lambda v: "N/A" if v is None else f"{v:.2f}x"),
        ("CapEx강도(/매출)", "CapEx강도", lambda v: "N/A" if v is None else f"{v:.1f}%"),
        ("투자활동현금흐름", "투자활동현금흐름", fmt_won),
        ("재무활동현금흐름", "재무활동현금흐름", fmt_won),
    ]
    for label, dkey, f in rows:
        cells = "".join(f"{f(m.get(dkey)):>14}" for m in metrics)
        print(f"    {label:<18}{cells}")

    # 원자료 확인용
    print("\n[4] 참고: 핵심재무 매출/영업이익")
    for k in key_3y:
        print(f"    {k['year']}년  매출 {fmt_won(k.get('매출액'))}  영업이익 {fmt_won(k.get('영업이익'))}")

    all_none = all(m["영업활동현금흐름"] is None for m in metrics)
    print("\n" + ("✗ 현금흐름이 전부 N/A — 파싱/계정명 확인 필요" if all_none
                  else "✓ 현금흐름 데이터 정상 수신"))


if __name__ == "__main__":
    main()
