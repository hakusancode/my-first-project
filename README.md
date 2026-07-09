# DART 공시 다운로더 & 기업분석 (dart_downloader)

DART(금융감독원 전자공시시스템, [opendart.fss.or.kr](https://opendart.fss.or.kr)) OpenAPI를 이용해
한국 상장기업의 **정기공시 원문을 내려받고**, **재무·배당·지배구조 등을 한눈에 분석**하는 데스크톱 GUI 앱입니다.

- **언어/런타임**: Python 3.12+
- **GUI**: CustomTkinter (다크 테마)
- **구성**: `dart_engine.py`(API·데이터 로직) + `dart_gui.py`(화면)

> 이 저장소의 `.py` 소스는 배포된 `dart_downloader.exe`(PyInstaller 번들)를
> 바이트코드 역어셈블을 통해 **원본과 동작이 동일하도록 복원**한 것입니다.

## 준비물

1. **DART OpenAPI 인증키** — [OpenDART](https://opendart.fss.or.kr/) 가입 후 무료 발급.
2. **패키지 설치**
   ```bash
   pip install -r requirements.txt
   ```

## 실행

```bash
python dart_gui.py
```

실행 후 화면 상단에 발급받은 **인증키**를 입력하고, 저장 폴더를 지정한 뒤 사용합니다.

## 주요 기능

**1. 공시 원문 다운로드**
- 회사명 검색 (한글 그룹명 자동 변환: 에스케이→SK, 엘지→LG 등)
- 시작/종료 연도 및 보고서 유형(사업/반기/분기) 선택 후 정기공시 원문(XML) 일괄 다운로드
- 정정본 자동 제외, `.done` 마커로 중복 다운로드 스킵

**2. 기업분석 8개 탭** (회사 선택 시 백그라운드 조회)

| 탭 | 내용 | DART API |
|---|---|---|
| 핵심재무 | 3개년 매출/영업이익/순이익/자산·부채·자본 (연결 우선) | `fnlttSinglAcnt` |
| 재무지표 | 영업이익률·순이익률·ROA·매출총이익률·매출원가율 등 (계산) | — |
| 배당 | 주당배당금·배당성향·시가배당률·현금배당총액 3개년 | `alotMatter` |
| 타법인출자 | 법인명·취득일·지분율·장부가액 | `otrCprInvstmntSttus` |
| 감사 | 감사인·감사의견·핵심감사사항 | `accnutAdtorNmNdAdtOpinion` |
| 최대주주 | 주주명·관계·지분율 | `hyslrSttus` |
| 직원 | 총직원/정규직·계약직/평균근속/1인평균급여 | `empSttus` |
| 자본변동 | 증자(감자)·자기주식 취득/처분 | `irdsSttus`, `tesstkAcqsDspsSttus` |

## 파일 구성

| 파일 | 설명 |
|---|---|
| `dart_engine.py` | DART API 호출·응답 파싱 로직 (17개 공개 함수) |
| `dart_gui.py` | CustomTkinter GUI (`DartApp` 클래스) |
| `requirements.txt` | 의존성 (customtkinter, requests) |
| `dart_downloader.exe` | 원본 배포 실행파일 (참고용) |

## 참고

- 인증키는 소스에 하드코딩되어 있지 않으며, 실행 시 사용자가 직접 입력합니다.
- 다운로드 원문·`CORPCODE.xml` 캐시는 `.gitignore`로 버전관리에서 제외됩니다.
- 비상장 외감법인 등 XBRL 재무데이터를 제공하지 않는 회사는 재무 탭이 비어 있을 수 있습니다.
