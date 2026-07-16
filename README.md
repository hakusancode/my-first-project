# 기업 재무분석 도구 (corp-financial-analysis)

한국(DART)·미국(SEC EDGAR·Yahoo) 상장기업의 **재무·성장성·안정성·배당·현금흐름**을
한 화면에서 분석하는 데스크톱 GUI 앱입니다.

- **한국**: DART(금융감독원 전자공시, [opendart.fss.or.kr](https://opendart.fss.or.kr)) — 정기공시 원문 다운로드 + 9개 분석 탭
- **미국**: SEC EDGAR 공식 XBRL(기본) / Yahoo — 티커·회사명으로 재무분석 (인증키 불필요)
- **언어/런타임**: Python 3.12+ · **GUI**: CustomTkinter (다크 테마)

> 이 저장소의 `.py` 소스는 원래 배포된 `dart_downloader.exe`(PyInstaller 번들)를
> 바이트코드 역어셈블로 복원한 뒤, 미국 분석·현금흐름 등을 추가·발전시킨 것입니다.

## 실행 (어느 컴퓨터에서나)

**가장 쉬운 방법 — 자동 설치 런처** (가상환경 생성 + 패키지 설치 + 실행 자동):

- **Windows**: `run.bat` 더블클릭
- **macOS / Linux**: 터미널에서 `chmod +x run.sh && ./run.sh`

**수동 실행:**
```bash
pip install -r requirements.txt
python dart_gui.py
```

> 실행 후 상단 **🇰🇷 한국 / 🇺🇸 미국 / 💰 배당 스크리너** 토글로 화면을 고릅니다.
> 한국 분석·다운로드에는 [OpenDART 인증키](https://opendart.fss.or.kr/)(무료)가 필요하고,
> 미국 분석은 인증키 없이 바로 됩니다.
> **💰 배당 스크리너** 탭에서는 우측 패널의 컨트롤(시장·최소 배당률·상위 개수·정밀검증)로
> 고배당주를 걸러 등급을 매깁니다 — CLI `dividend_screener.py`와 동일 엔진입니다.

## 주요 기능

**1. 공시 원문 다운로드**
- 회사명 검색 (한글 그룹명 자동 변환: 에스케이→SK, 엘지→LG 등)
- 시작/종료 연도 및 보고서 유형(사업/반기/분기) 선택 후 정기공시 원문(XML) 일괄 다운로드
- 정정본 자동 제외, `.done` 마커로 중복 다운로드 스킵

**2. 기업분석 9개 탭** (회사 선택 시 백그라운드 조회, 현금흐름은 맨 마지막 탭)

| 탭 | 내용 | DART API |
|---|---|---|
| 핵심재무 | 3개년 매출/영업이익/순이익/자산·부채·자본 (연결 우선) | `fnlttSinglAcnt` |
| **현금흐름** | 영업활동현금흐름·CapEx·**FCF**·FCF마진·**이익의 질**(CFO/영업이익)·CapEx강도 | `fnlttSinglAcntAll`(CF) |
| 재무지표 | 영업이익률·순이익률·ROA·매출총이익률·매출원가율 등 (계산) | — |
| 배당 | 주당배당금·배당성향·시가배당률·현금배당총액 3개년 | `alotMatter` |
| 타법인출자 | 법인명·취득일·지분율·장부가액 | `otrCprInvstmntSttus` |
| 감사 | 감사인·감사의견·핵심감사사항 | `accnutAdtorNmNdAdtOpinion` |
| 최대주주 | 주주명·관계·지분율 | `hyslrSttus` |
| 직원 | 총직원/정규직·계약직/평균근속/1인평균급여 | `empSttus` |
| 자본변동 | 증자(감자)·자기주식 취득/처분 | `irdsSttus`, `tesstkAcqsDspsSttus` |

## 미국주식 분석 (프로토타입, `us_engine.py` / `us_report.py`)

> **GUI 통합**: `python dart_gui.py` 실행 후 상단 **🇰🇷 한국 / 🇺🇸 미국** 토글로 미국 종목도
> 같은 화면에서 분석할 수 있습니다. 미국 모드에서는 검색창에 **티커 또는 회사명**(예: `NVDA`,
> `NVIDIA`)을 입력하면 EDGAR 기반 현금창출·수익성·안정성·**배당**·밸류에이션이 표시됩니다.
> (미국 분석은 DART 인증키가 필요 없습니다.)

한국(DART)에 더해 **미국 상장기업 재무분석**을 제공하는 프로토타입입니다.
**수익성**(마진·ROE·ROA·ROIC)·**성장성**(매출·영업이익·순이익 성장률)·
**안정성**(부채비율·유동비율·이자보상배율)·**배당**·**밸류에이션**(PER·PBR·PSR·EV/EBITDA)을
기본으로 하고, 여기에 **현금흐름 분석**(영업현금흐름·FCF·FCF마진·이익의 질·CapEx강도)을 더했습니다.

**데이터원 2가지** (플래그로 선택):

| 소스 | 플래그 | 성격 |
|---|---|---|
| **SEC EDGAR** (`sec_engine.py`) | `--edgar` (기본) | 공식 XBRL, 정확·안정. 미국 국내기업(10-K). 예: NVDA FY2023 영업이익을 GAAP 공식값으로 정확히 반영 |
| **Yahoo/yfinance** (`us_engine.py`) | `--yahoo` | 빠르고 외국기업(20-F, 예: TSM)도 커버. 비공식 |

```bash
python us_report.py NVDA              # 단일 상세 (기본: EDGAR)
python us_report.py NVDA MSFT AVGO    # 여러 종목 각각
python us_report.py --screen          # 기본 유니버스 12종목 현금창출 랭킹 (EDGAR)
python us_report.py --screen MU AVGO  # 지정 종목 랭킹
python us_report.py --yahoo TSM       # 외국기업은 Yahoo 소스로
```

### 고배당주 스크리너 (`dividend_screener.py`)

배당수익률만 높은 종목을 나열하는 대신, **배당 함정**(주가가 빠져서, 혹은 벌지도 못하는 돈을
나눠줘서 배당률이 높아 보이는 종목)을 걸러냅니다. 배당수익률과 함께 **배당성향**(순이익 대비),
**FCF 커버리지**(잉여현금흐름 ÷ 현금배당총액), **3년 연속 배당** 여부를 종합해
**○ 양호 / △ 주의 / × 위험** 등급을 매깁니다.

```bash
# 미국 (yfinance + SEC EDGAR, 인증키 불필요)
python dividend_screener.py                       # 기본 유니버스(대형주 91종목)
python dividend_screener.py --min-yield 4 --top 20
python dividend_screener.py KO PG XOM O           # 지정 티커
python dividend_screener.py --no-deep             # 1단계만(빠름, 안전성 평가 생략)

# 한국 (DART alotMatter + 현금흐름, DART_API_KEY 필요)
DART_API_KEY=키 python dividend_screener.py --kr --min-yield 3
DART_API_KEY=키 python dividend_screener.py --kr 삼성전자 'KT&G' 005930 --csv out.csv
```

한국은 **DART 공시 시가배당률**(결산 시점 주가 기준)과 **현재가 기준 배당률**(최근 DPS ÷ yfinance
현재가)을 나란히 보여줍니다. 조회는 2단계로 나눠, 무거운 재무제표 조회는 배당률 조건을 통과한
종목에만 수행합니다.

**업종별 예외** — 지표를 그대로 적용하면 오탐이 나는 업종은 기준을 바꿉니다:

| 업종 | 문제 | 처리 |
|---|---|---|
| 리츠 | 감가상각이 커서 순이익 배당성향이 구조적으로 100% 초과(실제로는 FFO로 배당) | 배당성향 대신 현금흐름으로 판정 |
| 금융(은행·보험·증권) | 대출·예금이 영업활동현금흐름에 섞여 FCF가 무의미(기업은행 −23.6x) | 현금흐름 대신 배당성향으로 판정 |
| 할부금융 연결 제조사 | 금융자산 증가로 CFO가 마이너스(현대차 −4.4x) | 배당성향이 낮으면 위험이 아닌 **주의** |

예(미국): KO는 배당성향 67%로 멀쩡해 보이지만 FCF 커버리지 0.6x → **위험**.
예(한국): KT 배당성향 104%(순이익 초과) → **위험**, 한국가스공사 3년 중 1년만 배당 → **주의**.

> 과거 재무 기준의 **스크리닝(후보 압축)** 도구입니다 — 미래 예측이 아닙니다.
> EDGAR는 펀더멘털만 제공하므로 주가·시가총액·밸류에이션은 경량 현재가 조회로 보완합니다.
> 외국기업(20-F)은 us-gaap XBRL이 없어 EDGAR에서 조회 실패할 수 있습니다 → `--yahoo` 사용.
> Yahoo 소스에서 보고통화≠시총통화(예: TSM=TWD)인 종목은 금액을 보고통화로 표시하고 FCF수익률은 생략합니다.

## 파일 구성

| 파일 | 설명 |
|---|---|
| `dart_engine.py` | DART API 호출·응답 파싱 로직 (17개 공개 함수) |
| `dart_gui.py` | CustomTkinter GUI (`DartApp` 클래스) |
| `us_engine.py` | 미국 재무분석 엔진 (yfinance, `analyze`/`screen`) |
| `sec_engine.py` | 미국 재무분석 엔진 (SEC EDGAR 공식, `us_engine`과 동일 인터페이스) |
| `us_report.py` | 미국 분석 CLI 리포트·스크리너 데모 (`--edgar`/`--yahoo`) |
| `dividend_screener.py` | 한·미 고배당 스크리너 (배당 함정 필터: 배당성향·FCF커버리지·연속배당) |
| `requirements.txt` | 의존성 (customtkinter, requests, yfinance, pandas) |
| `dart_downloader.exe` | 원본 배포 실행파일 (참고용) |

## 참고

- 인증키는 소스에 하드코딩되어 있지 않으며, 실행 시 사용자가 직접 입력합니다.
- 다운로드 원문·`CORPCODE.xml` 캐시는 `.gitignore`로 버전관리에서 제외됩니다.
- 비상장 외감법인 등 XBRL 재무데이터를 제공하지 않는 회사는 재무 탭이 비어 있을 수 있습니다.
