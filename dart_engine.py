import re
import io
import os
import html
import zipfile
import xml.etree.ElementTree as ET
import requests


_CORP_CODE_URL = 'https://opendart.fss.or.kr/api/corpCode.xml'
_LIST_URL = 'https://opendart.fss.or.kr/api/list.json'
_DOC_URL = 'https://opendart.fss.or.kr/api/document.xml'
_FINANCIALS_URL = 'https://opendart.fss.or.kr/api/fnlttSinglAcnt.json'
_DIVIDEND_URL = 'https://opendart.fss.or.kr/api/alotMatter.json'

_VALID_ENTITY = re.compile(r'&(?:\#\d+|\#x[\da-fA-F]+|amp|lt|gt|quot|apos);')
_TAG_START = re.compile(r'</?[A-Za-z_!][\w:.-]*')


def load_corp_list(api_key, cache_path='CORPCODE.xml', log_fn=None):
    """
    DART 전체 회사 목록을 반환한다.
    cache_path 파일이 없으면 다운로드 후 저장, 있으면 캐시 사용.
    반환값: [{"corp_code": "...", "corp_name": "...", "stock_code": "..."}, ...]
    stock_code는 상장사만 6자리, 비상장사는 ''.
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    if not os.path.exists(cache_path):
        log("회사 목록 다운로드 중...")
        resp = requests.get(_CORP_CODE_URL, params={'crtfc_key': api_key})
        if not resp.content.startswith(b'PK'):
            raise RuntimeError(f"corpCode 다운로드 실패: {resp.text[:200]}")
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            z.extractall(os.path.dirname(cache_path) or '.')
        log(f"저장 완료: {cache_path}")
    else:
        log(f"캐시 사용: {cache_path}")

    tree = ET.parse(cache_path)
    corps = [
        {
            'corp_code': item.findtext('corp_code', ''),
            'corp_name': item.findtext('corp_name', ''),
            'stock_code': (item.findtext('stock_code', '') or '').strip(),
        }
        for item in tree.getroot().findall('list')
    ]
    log(f"회사 목록 로드 완료: {len(corps):,}건")
    return corps


_KO_TO_EN = {
    '에스케이': 'SK',
    '엘지': 'LG',
    '씨제이': 'CJ',
    '케이티': 'KT',
    '지에스': 'GS',
    '에이치디': 'HD',
    '디엘': 'DL',
}

# 'KT&G' → '케이티앤지' 처럼 &가 낀 사명을 한글 등록명으로 되돌릴 때만 쓰는 알파벳 표기
_EN_LETTER_TO_KO = {
    'G': '지', 'B': '비', 'F': '에프', 'S': '에스', 'T': '티', 'C': '씨', 'M': '엠',
}


def search_company(corp_list, keyword):
    """
    keyword가 corp_name에 포함된 항목을 반환한다 (부분일치, 대소문자 무시).
    한글↔영문 표기(에스케이 ↔ SK 등)를 양방향 변환해 원래 키워드와 합산, 중복 제거.
    DART는 회사에 따라 'SK하이닉스'처럼 영문으로, '케이티앤지'처럼 한글로 등록한다.
    반환값: [{"corp_code": "...", "corp_name": "...", "stock_code": "..."}, ...]
    """
    def _match(kw, corp_name_upper):
        return kw.upper() in corp_name_upper

    keyword = html.unescape(keyword).strip()      # 'KT&amp;G' → 'KT&G'

    to_en = keyword
    for ko, en in _KO_TO_EN.items():
        to_en = to_en.replace(ko, en)

    to_ko = keyword.upper()
    for ko, en in sorted(_KO_TO_EN.items(), key=lambda kv: -len(kv[1])):
        to_ko = to_ko.replace(en, ko)
    if '&' in to_ko:
        # 'KT&G' → '케이티&G' → '케이티앤G' → '케이티앤지' (DART 등록명)
        to_ko = to_ko.replace('&', '앤')
        for en, ko in _EN_LETTER_TO_KO.items():
            to_ko = to_ko.replace(en, ko)

    keywords = list(dict.fromkeys([keyword, to_en, to_ko]))

    seen = set()
    results = []
    for c in corp_list:
        name_upper = c['corp_name'].upper()
        if c['corp_code'] not in seen and any(_match(kw, name_upper) for kw in keywords):
            seen.add(c['corp_code'])
            results.append(c)
    return results


def list_disclosures(api_key, corp_code, bgn_de, end_de, report_types=None, log_fn=None):
    """
    정기공시(pblntf_ty=A) 목록을 조회해 반환한다.
    report_types: ["사업보고서", "반기보고서", "분기보고서"] 같은 리스트.
                  None이면 필터 없이 전체 반환.
    정정본("정정"이 report_nm에 포함)은 항상 제외한다.
    반환값: [{"rcept_no": "...", "report_nm": "...", "rcept_dt": "..."}, ...]
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    params = {
        'crtfc_key': api_key,
        'corp_code': corp_code,
        'bgn_de': bgn_de,
        'end_de': end_de,
        'pblntf_ty': 'A',
        'page_count': 100,
    }
    resp = requests.get(_LIST_URL, params=params)
    data = resp.json()

    if data.get('status') != '000':
        raise RuntimeError(f"list.json 오류: {data.get('status')} {data.get('message')}")

    items = data.get('list', [])
    log(f"공시 목록 수신: {len(items)}건 (전체 {data.get('total_count')}건)")

    items = [i for i in items if '정정' not in i['report_nm']]

    if report_types:
        items = [i for i in items if any(rt in i['report_nm'] for rt in report_types)]

    log(f"필터 후: {len(items)}건")
    if len(items) == 0:
        log("이 회사는 정기공시(사업/반기/분기보고서) 제출 이력이 없습니다. 비상장 외감법인은 감사보고서만 제출하는 경우가 많습니다.")

    return [
        {
            'rcept_no': i['rcept_no'],
            'report_nm': i['report_nm'],
            'rcept_dt': i['rcept_dt'],
        }
        for i in items
    ]


def download_document(api_key, rcept_no, save_dir, log_fn=None):
    """
    rcept_no에 해당하는 공시 문서를 save_dir에 다운로드·압축해제한다.
    이미 .done 마커가 있으면 건너뛴다.
    반환값: {"status": "성공"|"건너뜀"|"실패", "files": [...]}
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    done_marker = os.path.join(save_dir, '.done')
    if os.path.exists(done_marker):
        files = [f for f in os.listdir(save_dir) if f != '.done']
        log(f"[건너뜀] {rcept_no} (이미 존재)")
        return {'status': '건너뜀', 'files': files}

    os.makedirs(save_dir, exist_ok=True)

    resp = requests.get(_DOC_URL, params={'crtfc_key': api_key, 'rcept_no': rcept_no})
    if not resp.content.startswith(b'PK'):
        msg = resp.text[:200]
        log(f"[실패] {rcept_no}: {msg}")
        return {'status': '실패', 'files': [], 'error': msg}

    zip_path = os.path.join(save_dir, f"{rcept_no}.zip")
    with open(zip_path, 'wb') as f:
        f.write(resp.content)

    with zipfile.ZipFile(zip_path) as z:
        extracted = z.namelist()
        z.extractall(save_dir)

    open(done_marker, 'w').close()
    log(f"[성공] {rcept_no} → {len(extracted)}개 파일")
    return {'status': '성공', 'files': extracted}


_FIN_TARGETS = {
    '매출액': ['매출액', '수익(매출액)', '영업수익'],
    '영업이익': ['영업이익'],
    '당기순이익': ['당기순이익'],
    '자산총계': ['자산총계'],
    '부채총계': ['부채총계'],
    '자본총계': ['자본총계'],
}


def _parse_amount(raw):
    """콤마 제거 후 정수 변환. 빈 값이면 None."""
    if not raw or raw.strip() == '':
        return None
    try:
        return int(raw.replace(',', '').replace(' ', ''))
    except ValueError:
        return None


def _find_account(items, keywords):
    """
    keywords 순서대로 account_nm 부분일치 검색.
    여러 키워드 중 앞 키워드를 먼저 시도하고, 같은 키워드 내에서는
    정확일치 → 시작일치 → 포함 순으로 우선한다.
    """
    for kw in keywords:
        exact = [i for i in items if i['account_nm'] == kw]
        starts = [i for i in items if i['account_nm'].startswith(kw) and i not in exact]
        contains = [i for i in items if kw in i['account_nm'] and i not in exact and i not in starts]
        for group in (exact, starts, contains):
            if group:
                return group[0]
    return None


def get_key_financials(api_key, corp_code, bsns_year, reprt_code='11011', log_fn=None):
    """
    DART 주요계정(fnlttSinglAcnt)에서 핵심재무 6개 항목을 반환한다.
    연결(CFS) 우선, 없으면 별도(OFS) 사용.
    반환값: {
        "fs_div": "CFS" | "OFS",
        "매출액": int | None,
        "영업이익": int | None,
        "당기순이익": int | None,
        "자산총계": int | None,
        "부채총계": int | None,
        "자본총계": int | None,
        "currency": str,
        "unit": str,      # DART 원문 단위 (보통 "원")
    }
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    resp = requests.get(_FINANCIALS_URL, params={
        'crtfc_key': api_key,
        'corp_code': corp_code,
        'bsns_year': bsns_year,
        'reprt_code': reprt_code,
    })
    data = resp.json()

    if data.get('status') != '000':
        raise RuntimeError(f"fnlttSinglAcnt 오류: {data.get('status')} {data.get('message')}")

    all_items = data.get('list', [])
    log(f"주요계정 수신: {len(all_items)}건 (연도={bsns_year}, 보고서={reprt_code})")

    cfs = [i for i in all_items if i.get('fs_div') == 'CFS']
    ofs = [i for i in all_items if i.get('fs_div') == 'OFS']
    items = cfs if cfs else ofs
    fs_div = 'CFS' if cfs else 'OFS'
    log(f"재무제표 구분: {fs_div} ({len(items)}건)")

    result = {'fs_div': fs_div}
    for label, keywords in _FIN_TARGETS.items():
        row = _find_account(items, keywords)
        if row:
            result[label] = _parse_amount(row.get('thstrm_amount', ''))
        else:
            result[label] = None
            log(f"  ※ '{label}' 항목 없음")

    sample = items[0] if items else {}
    result['currency'] = sample.get('currency', 'KRW')
    result['unit'] = '원'

    return result


def get_key_financials_3y(api_key, corp_code, end_year, reprt_code='11011', log_fn=None):
    """
    end_year 포함 직전 2개년까지 총 3개년 핵심재무를 반환한다.
    반환값: [{"year": "2022", ...}, {"year": "2023", ...}, {"year": "2024", ...}]
    연도 오름차순 정렬. 조회 실패한 연도는 None 값 딕셔너리로 채운다.
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    years = [str(int(end_year) - i) for i in range(2, -1, -1)]
    results = []
    for yr in years:
        log(f"{yr}년 조회 중...")
        try:
            row = get_key_financials(api_key, corp_code, yr, reprt_code, log_fn=log_fn)
            row['year'] = yr
        except Exception as e:
            log(f"  {yr}년 오류: {e}")
            row = {
                'year': yr,
                'fs_div': None,
                '매출액': None,
                '영업이익': None,
                '당기순이익': None,
                '자산총계': None,
                '부채총계': None,
                '자본총계': None,
                'currency': 'KRW',
                'unit': '원',
            }
        results.append(row)
    return results


_DIV_ITEMS = [
    ('주당배당금(원)', '주당 현금배당금', '보통주', 'int'),
    ('배당성향(%)', '현금배당성향', None, 'float'),
    ('시가배당률(%)', '현금배당수익률', '보통주', 'float'),
    ('현금배당총액(백만원)', '현금배당금총액', None, 'int'),
]


def _parse_div(raw, val_type):
    """'-' 또는 빈 값은 None, 나머지는 int/float 변환."""
    if not raw or raw.strip() in ('-', ''):
        return None
    clean = raw.replace(',', '').strip()
    try:
        return float(clean) if val_type == 'float' else int(clean)
    except ValueError:
        return None


def _find_div(items, se_kw, stock_filter, col):
    """se 부분일치 + stock_knd 필터로 항목 찾아 해당 연도 컬럼 값 반환.

    우선주가 없는 기업(KB금융 등)은 stock_knd를 '보통주'가 아니라 '-'로 신고한다.
    따라서 종류 일치 항목이 없으면 종류 미표기('-'/공백) 항목으로 폴백한다.
    같은 se가 여러 줄일 수 있어(값이 '-'인 빈 줄 포함) 실제 값이 있는 줄을 고른다.
    """
    cands = [i for i in items if se_kw in i.get('se', '')]
    if stock_filter:
        exact = [i for i in cands if i.get('stock_knd') == stock_filter]
        cands = exact or [i for i in cands
                          if (i.get('stock_knd') or '').strip() in ('-', '')]

    for item in cands:
        raw = item.get(col, '')
        if raw and raw.strip() not in ('-', ''):
            return raw
    return cands[0].get(col, '') if cands else ''


def get_dividend_info(api_key, corp_code, bsns_year, reprt_code='11011', log_fn=None):
    """
    단일 연도 배당 정보를 반환한다.
    반환값: {"주당배당금(원)": int|None, "배당성향(%)": float|None,
             "시가배당률(%)": float|None, "현금배당총액(백만원)": int|None}
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    resp = requests.get(_DIVIDEND_URL, params={
        'crtfc_key': api_key,
        'corp_code': corp_code,
        'bsns_year': bsns_year,
        'reprt_code': reprt_code,
    })
    data = resp.json()

    if data.get('status') != '000':
        raise RuntimeError(f"alotMatter 오류: {data.get('status')} {data.get('message')}")

    items = data.get('list', [])
    log(f"배당 수신: {len(items)}건 (연도={bsns_year})")

    result = {}
    for key, se_kw, stock_filter, val_type in _DIV_ITEMS:
        raw = _find_div(items, se_kw, stock_filter, 'thstrm')
        result[key] = _parse_div(raw, val_type)
    return result


def get_dividend_info_3y(api_key, corp_code, end_year, reprt_code='11011', log_fn=None):
    """
    end_year 포함 직전 2개년까지 총 3개년 배당 정보를 반환한다.
    alotMatter는 1회 호출로 3개년(thstrm/frmtrm/lwfr)을 제공하므로 API 1번만 호출한다.
    반환값: [{"year": "2022", ...}, {"year": "2023", ...}, {"year": "2024", ...}]
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    log(f"배당 3개년 조회 중 (기준연도={end_year})...")
    resp = requests.get(_DIVIDEND_URL, params={
        'crtfc_key': api_key,
        'corp_code': corp_code,
        'bsns_year': end_year,
        'reprt_code': reprt_code,
    })
    data = resp.json()

    if data.get('status') != '000':
        raise RuntimeError(f"alotMatter 오류: {data.get('status')} {data.get('message')}")

    items = data.get('list', [])
    log(f"배당 수신: {len(items)}건")

    year_col = [
        (str(int(end_year) - 2), 'lwfr'),
        (str(int(end_year) - 1), 'frmtrm'),
        (str(int(end_year)), 'thstrm'),
    ]

    results = []
    for yr, col in year_col:
        row = {'year': yr}
        for key, se_kw, stock_filter, val_type in _DIV_ITEMS:
            raw = _find_div(items, se_kw, stock_filter, col)
            row[key] = _parse_div(raw, val_type)
        results.append(row)
    return results


def calculate_financial_ratios(financials_3y, extended_3y=None):
    """
    get_key_financials_3y() + (선택) get_extended_financials_3y() 결과로 연도별 재무비율을 계산한다.
    반환값: [{"year": "2022", "영업이익률": float|None, ...}, ...]
    """
    def safe_pct(numerator, denominator):
        if numerator is None or denominator is None or denominator == 0:
            return None
        return numerator / denominator * 100

    def yoy(cur, prev):
        # 전년대비 성장률(%). 전년이 0 이하이면 부호 왜곡되므로 None.
        if cur is None or prev is None or prev <= 0:
            return None
        return (cur - prev) / prev * 100

    ext_by_year = {}
    if extended_3y:
        for row in extended_3y:
            ext_by_year[row['year']] = row

    results = []
    prev = {}
    for row in financials_3y:
        rev = row.get('매출액')
        op = row.get('영업이익')
        ni = row.get('당기순이익')
        ta = row.get('자산총계')
        tl = row.get('부채총계')
        eq = row.get('자본총계')
        yr = row['year']
        ext = ext_by_year.get(yr, {})
        gp = ext.get('매출총이익')
        cogs = ext.get('매출원가')
        ci = ext.get('총포괄이익')

        ratio = {
            'year': yr,
            '영업이익률': safe_pct(op, rev),
            '순이익률': safe_pct(ni, rev),
            '부채비율': safe_pct(tl, eq),
            'ROE': safe_pct(ni, eq),
            'ROA': safe_pct(ni, ta),
            '매출총이익률': safe_pct(gp, rev),
            '매출원가율': safe_pct(cogs, rev),
            '총포괄이익률': safe_pct(ci, rev),
            # 성장성 (전년대비)
            '매출성장률': yoy(rev, prev.get('rev')),
            '영업이익성장률': yoy(op, prev.get('op')),
            '순이익성장률': yoy(ni, prev.get('ni')),
        }
        results.append(ratio)
        prev = {'rev': rev, 'op': op, 'ni': ni}
    return results


_EXT_FIN_URL = 'https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json'

_EXT_TARGETS = [
    ('매출원가', '매출원가'),
    ('매출총이익', '매출총이익'),
    ('총포괄이익', '총포괄이익'),
]


def _ext_find(cis_items, keyword):
    """CIS 항목에서 keyword 부분일치 첫 번째 결과 반환."""
    for item in cis_items:
        if keyword in item.get('account_nm', ''):
            return item
    return None


def _ext_parse(raw):
    if not raw or raw.strip() in ('-', ''):
        return None
    try:
        return int(raw.replace(',', '').strip())
    except ValueError:
        return None


def get_extended_financials(api_key, corp_code, bsns_year, reprt_code='11011', log_fn=None):
    """
    fnlttSinglAcntAll에서 매출원가·매출총이익·총포괄이익을 반환한다.
    CFS 우선, CIS 항목 없으면 OFS 재시도.
    반환값: {"매출원가": int|None, "매출총이익": int|None, "총포괄이익": int|None, "fs_div": str}
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    for fs in ('CFS', 'OFS'):
        resp = requests.get(_EXT_FIN_URL, params={
            'crtfc_key': api_key,
            'corp_code': corp_code,
            'bsns_year': bsns_year,
            'reprt_code': reprt_code,
            'fs_div': fs,
        })
        data = resp.json()

        if data.get('status') != '000':
            raise RuntimeError(f"fnlttSinglAcntAll 오류: {data.get('status')} {data.get('message')}")

        cis = [i for i in data.get('list', []) if i.get('sj_div') == 'CIS']
        if not cis:
            continue
        log(f"확장재무 CIS {len(cis)}건 수신 ({fs}, 연도={bsns_year})")

        result = {'fs_div': fs}
        for key, kw in _EXT_TARGETS:
            row = _ext_find(cis, kw)
            result[key] = _ext_parse(row.get('thstrm_amount', '') if row else '')
        return result

    log(f"확장재무: CIS 항목 없음 (연도={bsns_year})")
    return {'fs_div': None, '매출원가': None, '매출총이익': None, '총포괄이익': None}


def get_extended_financials_3y(api_key, corp_code, end_year, reprt_code='11011', log_fn=None):
    """
    fnlttSinglAcntAll는 thstrm/frmtrm/bfefrmtrm 3열을 한 번에 제공하므로 1회 호출로 3개년 반환.
    반환값: [{"year":"2022",...}, {"year":"2023",...}, {"year":"2024",...}]  (오름차순)
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    log(f"확장재무 3개년 조회 중 (기준연도={end_year})...")
    for fs in ('CFS', 'OFS'):
        resp = requests.get(_EXT_FIN_URL, params={
            'crtfc_key': api_key,
            'corp_code': corp_code,
            'bsns_year': end_year,
            'reprt_code': reprt_code,
            'fs_div': fs,
        })
        data = resp.json()

        if data.get('status') != '000':
            raise RuntimeError(f"fnlttSinglAcntAll 오류: {data.get('status')} {data.get('message')}")

        cis = [i for i in data.get('list', []) if i.get('sj_div') == 'CIS']
        if not cis:
            continue
        log(f"확장재무 CIS {len(cis)}건 수신 ({fs})")

        year_col = [
            (str(int(end_year) - 2), 'bfefrmtrm_amount'),
            (str(int(end_year) - 1), 'frmtrm_amount'),
            (str(int(end_year)), 'thstrm_amount'),
        ]

        results = []
        for yr, col in year_col:
            row_data = {'year': yr, 'fs_div': fs}
            for key, kw in _EXT_TARGETS:
                item = _ext_find(cis, kw)
                row_data[key] = _ext_parse(item.get(col, '') if item else '')
            results.append(row_data)
        return results

    years = [str(int(end_year) - i) for i in range(2, -1, -1)]
    return [
        {'year': y, 'fs_div': None, '매출원가': None, '매출총이익': None, '총포괄이익': None}
        for y in years
    ]


# ── 현금흐름(현금창출능력) ─────────────────────────────────────────────────
# fnlttSinglAcntAll(_EXT_FIN_URL)에서 sj_div='CF'(현금흐름표) 항목을 사용한다.
# (target label, [account_nm 부분일치 키워드 우선순위])
_CF_TARGETS = (
    ('영업활동현금흐름', ['영업활동현금흐름', '영업활동으로 인한 현금흐름', '영업활동']),
    ('투자활동현금흐름', ['투자활동현금흐름', '투자활동으로 인한 현금흐름', '투자활동']),
    ('재무활동현금흐름', ['재무활동현금흐름', '재무활동으로 인한 현금흐름', '재무활동']),
    ('CapEx', ['유형자산의 취득', '유형자산의취득', '유형자산의 증가']),
)


def _cf_find(cf_items, keywords):
    """CF 항목에서 keywords(우선순위)로 account_nm 부분일치 첫 결과 반환."""
    for kw in keywords:
        for item in cf_items:
            if kw in item.get('account_nm', ''):
                return item
    return None


def get_cashflow_3y(api_key, corp_code, end_year, reprt_code='11011', log_fn=None):
    """
    fnlttSinglAcntAll의 현금흐름표(CF)에서 3개년 현금흐름을 반환한다.
    thstrm/frmtrm/bfefrmtrm 3열을 한 번에 제공하므로 1회 호출로 3개년.
    CFS 우선, CF 항목 없으면 OFS 재시도.
    반환값: [{"year":str, "fs_div":str, "영업활동현금흐름":int|None,
             "투자활동현금흐름":int|None, "재무활동현금흐름":int|None,
             "CapEx":int|None(음수=유출)}, ...]  (오름차순)
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    log(f"현금흐름 3개년 조회 중 (기준연도={end_year})...")
    for fs in ('CFS', 'OFS'):
        resp = requests.get(_EXT_FIN_URL, params={
            'crtfc_key': api_key,
            'corp_code': corp_code,
            'bsns_year': end_year,
            'reprt_code': reprt_code,
            'fs_div': fs,
        })
        data = resp.json()

        if data.get('status') != '000':
            raise RuntimeError(f"fnlttSinglAcntAll 오류: {data.get('status')} {data.get('message')}")

        cf = [i for i in data.get('list', []) if i.get('sj_div') == 'CF']
        if not cf:
            continue
        log(f"현금흐름 CF {len(cf)}건 수신 ({fs})")

        year_col = [
            (str(int(end_year) - 2), 'bfefrmtrm_amount'),
            (str(int(end_year) - 1), 'frmtrm_amount'),
            (str(int(end_year)), 'thstrm_amount'),
        ]

        results = []
        for yr, col in year_col:
            row_data = {'year': yr, 'fs_div': fs}
            for key, kws in _CF_TARGETS:
                item = _cf_find(cf, kws)
                row_data[key] = _ext_parse(item.get(col, '') if item else '')
            results.append(row_data)
        return results

    years = [str(int(end_year) - i) for i in range(2, -1, -1)]
    return [
        {'year': y, 'fs_div': None, '영업활동현금흐름': None,
         '투자활동현금흐름': None, '재무활동현금흐름': None, 'CapEx': None}
        for y in years
    ]


def calculate_cashflow_metrics(key_3y, cashflow_3y):
    """
    핵심재무(key_3y: 매출액·영업이익 포함)와 현금흐름(cashflow_3y)을 결합해
    연도별 현금창출 지표를 계산한다.
    반환값: [{"year":str, "영업활동현금흐름":int|None, "CapEx":int|None(양수=유출액),
             "잉여현금흐름":int|None, "FCF마진":float|None, "이익의질":float|None,
             "CapEx강도":float|None, "투자활동현금흐름":int|None,
             "재무활동현금흐름":int|None}, ...]  (오름차순)
    이익의질 = CFO/영업이익(배수), FCF마진·CapEx강도 = %(매출 대비).
    """
    key_by_year = {r['year']: r for r in (key_3y or [])}
    out = []
    for cf in cashflow_3y:
        yr = cf['year']
        k = key_by_year.get(yr, {})
        revenue = k.get('매출액')
        op_income = k.get('영업이익')
        cfo = cf.get('영업활동현금흐름')
        capex_raw = cf.get('CapEx')
        capex_abs = None if capex_raw is None else abs(capex_raw)
        fcf = None if (cfo is None or capex_abs is None) else cfo - capex_abs

        def pct(a, b):
            if a is None or b is None or b == 0:
                return None
            return a / b * 100.0

        out.append({
            'year': yr,
            '영업활동현금흐름': cfo,
            'CapEx': capex_abs,
            '잉여현금흐름': fcf,
            'FCF마진': pct(fcf, revenue),
            '이익의질': (None if (cfo is None or not op_income) else cfo / op_income),
            'CapEx강도': pct(capex_abs, revenue),
            '투자활동현금흐름': cf.get('투자활동현금흐름'),
            '재무활동현금흐름': cf.get('재무활동현금흐름'),
        })
    return out


_EQUITY_URL = 'https://opendart.fss.or.kr/api/otrCprInvstmntSttus.json'


def get_equity_investments(api_key, corp_code, bsns_year, reprt_code='11011', log_fn=None):
    """
    타법인 출자현황을 반환한다. 지분율 내림차순 정렬.
    반환값: [{"법인명": str, "최초취득일": str, "지분율": float|None,
              "기말장부가액": int|None}, ...]
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    resp = requests.get(_EQUITY_URL, params={
        'crtfc_key': api_key,
        'corp_code': corp_code,
        'bsns_year': bsns_year,
        'reprt_code': reprt_code,
    })
    data = resp.json()

    if data.get('status') != '000':
        raise RuntimeError(f"otrCprInvstmntSttus 오류: {data.get('status')} {data.get('message')}")

    items = data.get('list', [])
    log(f"타법인출자 수신: {len(items)}건 (연도={bsns_year})")

    def _parse_float(raw):
        if not raw or raw.strip() in ('-', ''):
            return None
        try:
            return float(raw.replace(',', ''))
        except ValueError:
            return None

    def _parse_int(raw):
        if not raw or raw.strip() in ('-', ''):
            return None
        try:
            return int(raw.replace(',', ''))
        except ValueError:
            return None

    results = []
    for item in items:
        results.append({
            '법인명': item.get('inv_prm', ''),
            '최초취득일': item.get('frst_acqs_de', ''),
            '지분율': _parse_float(item.get('trmend_blce_qota_rt', '')),
            '기말장부가액': _parse_int(item.get('trmend_blce_acntbk_amount', '')),
        })

    results.sort(key=lambda x: x['지분율'] if x['지분율'] is not None else -1, reverse=True)
    return results


_AUDIT_URL = 'https://opendart.fss.or.kr/api/accnutAdtorNmNdAdtOpinion.json'


def get_audit_opinion_3y(api_key, corp_code, end_year, reprt_code='11011', log_fn=None):
    """
    3개년 감사인·감사의견·핵심감사사항을 반환한다.
    반환값: [{"year":str, "감사인":str, "감사의견":str, "강조사항":str, "핵심감사사항":str}, ...]
    연도당 복수 보고서(연결/별도 등)가 있을 경우 연결재무제표 언급 항목 우선, 없으면 첫 항목.
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    def _best(items):
        """연결재무제표 언급 항목 우선, 없으면 핵심감사 가장 긴 항목."""
        cfs = [i for i in items if '연결재무제표' in (i.get('core_adt_matter') or '')]
        pool = cfs if cfs else items
        return max(pool, key=lambda i: len(i.get('core_adt_matter') or ''), default=items[0])

    def _clean(text):
        if not text or text.strip() in ('-', '해당사항 없음', ''):
            return '해당사항 없음'
        import re
        return re.sub(r'[ \t]+', ' ', text.strip())

    results = []
    years = [str(int(end_year) - i) for i in range(2, -1, -1)]
    for year in years:
        resp = requests.get(_AUDIT_URL, params={
            'crtfc_key': api_key,
            'corp_code': corp_code,
            'bsns_year': year,
            'reprt_code': reprt_code,
        })
        data = resp.json()

        if data.get('status') != '000':
            log(f"감사의견 조회 실패 ({year}): {data.get('message')}")
            results.append({
                'year': year,
                '감사인': 'N/A',
                '감사의견': 'N/A',
                '강조사항': '',
                '핵심감사사항': '',
            })
            continue

        items = data.get('list', [])
        log(f"감사의견 {len(items)}건 수신 (연도={year})")
        if not items:
            results.append({
                'year': year,
                '감사인': 'N/A',
                '감사의견': 'N/A',
                '강조사항': '',
                '핵심감사사항': '',
            })
            continue

        row = _best(items)
        results.append({
            'year': year,
            '감사인': row.get('adtor', '').replace('\n', '').strip(),
            '감사의견': row.get('adt_opinion', '').strip(),
            '강조사항': _clean(row.get('emphs_matter', '')),
            '핵심감사사항': _clean(row.get('core_adt_matter', '')),
        })
    return results


_SHAREHOLDER_URL = 'https://opendart.fss.or.kr/api/hyslrSttus.json'


def get_major_shareholder(api_key, corp_code, bsns_year, reprt_code='11011', log_fn=None):
    """
    최대주주 및 특수관계인 현황을 반환한다.
    반환값: [{"주주명":str, "관계":str, "주식종류":str, "기말주식수":int|None, "지분율":float|None}, ...]
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    resp = requests.get(_SHAREHOLDER_URL, params={
        'crtfc_key': api_key,
        'corp_code': corp_code,
        'bsns_year': bsns_year,
        'reprt_code': reprt_code,
    })
    data = resp.json()

    if data.get('status') != '000':
        raise RuntimeError(f"hyslrSttus 오류: {data.get('status')} {data.get('message')}")

    items = data.get('list', [])
    log(f"최대주주 현황 {len(items)}건 수신 (연도={bsns_year})")

    def _parse_float(raw):
        try:
            return float(raw.replace(',', ''))
        except Exception:
            return None

    def _parse_int(raw):
        try:
            return int(raw.replace(',', ''))
        except Exception:
            return None

    results = []
    for item in items:
        results.append({
            '주주명': item.get('nm', '').strip(),
            '관계': item.get('relate', '').strip(),
            '주식종류': item.get('stock_knd', '').strip(),
            '기말주식수': _parse_int(item.get('trmend_posesn_stock_co', '')),
            '지분율': _parse_float(item.get('trmend_posesn_stock_qota_rt', '')),
        })
    return results


_EMP_URL = 'https://opendart.fss.or.kr/api/empSttus.json'


def get_employee_status(api_key, corp_code, bsns_year, reprt_code='11011', log_fn=None):
    """
    직원 현황을 반환한다. 남/녀 행을 집계해 합산 결과와 성별 세부를 함께 반환.
    반환값: {
      "총직원": int, "정규직": int, "계약직": int,
      "평균근속연수": float|None,   # 가중평균
      "1인평균급여": int|None,      # 연간 원화
      "성별": [{"성별":str, "직원수":int, "정규직":int, "계약직":int,
                "평균근속연수":float|None, "1인평균급여":int|None}, ...]
    }
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    resp = requests.get(_EMP_URL, params={
        'crtfc_key': api_key,
        'corp_code': corp_code,
        'bsns_year': bsns_year,
        'reprt_code': reprt_code,
    })
    data = resp.json()

    if data.get('status') != '000':
        raise RuntimeError(f"empSttus 오류: {data.get('status')} {data.get('message')}")

    items = data.get('list', [])
    log(f"직원 현황 {len(items)}건 수신 (연도={bsns_year})")

    def _int(raw):
        try:
            return int(raw.replace(',', ''))
        except Exception:
            return None

    def _float(raw):
        try:
            return float(raw.strip())
        except Exception:
            return None

    gender_rows = []
    for item in items:
        sm = _int(item.get('sm', ''))
        rgllbr = _int(item.get('rgllbr_co', ''))
        cnttk = _int(item.get('cnttk_co', ''))
        tenure = _float(item.get('avrg_cnwk_sdytrn', ''))
        salary = _int(item.get('jan_salary_am', ''))
        gender_rows.append({
            '성별': item.get('sexdstn', '').strip(),
            '직원수': sm,
            '정규직': rgllbr,
            '계약직': cnttk,
            '평균근속연수': tenure,
            '1인평균급여': salary,
        })

    total_sm = sum(r['직원수'] or 0 for r in gender_rows) or None
    total_reg = sum(r['정규직'] or 0 for r in gender_rows) or None
    total_cnt = sum(r['계약직'] or 0 for r in gender_rows) or None

    wt_tenure = None
    if total_sm:
        parts = [(r['평균근속연수'] or 0) * (r['직원수'] or 0) for r in gender_rows]
        wt_tenure = sum(parts) / total_sm

    avg_salary = None
    if total_sm:
        total_pay = sum((r['1인평균급여'] or 0) * (r['직원수'] or 0) for r in gender_rows)
        avg_salary = int(total_pay / total_sm) if total_pay else None

    return {
        '총직원': total_sm,
        '정규직': total_reg,
        '계약직': total_cnt,
        '평균근속연수': round(wt_tenure, 1) if wt_tenure is not None else None,
        '1인평균급여': avg_salary,
        '성별': gender_rows,
    }


_ISSU_URL = 'https://opendart.fss.or.kr/api/irdsSttus.json'
_TREASURY_URL = 'https://opendart.fss.or.kr/api/tesstkAcqsDspsSttus.json'


def get_capital_changes(api_key, corp_code, bsns_year, reprt_code='11011', log_fn=None):
    """
    증자(감자) 현황과 자기주식 취득/처분 현황을 반환한다.
    반환값: {
      "증자감자": [{"발행일":str, "발행형태":str, "주식종류":str,
                    "수량":str, "액면가":str, "발행가":str}, ...],
      "자기주식": [{"주식종류":str, "취득방법":str, "기초수량":str,
                    "취득":str, "처분":str, "소각":str, "기말수량":str}, ...]
    }
    내역이 없으면 빈 리스트.
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    def _has(raw):
        return raw and raw.strip() not in ('-', '')

    resp1 = requests.get(_ISSU_URL, params={
        'crtfc_key': api_key,
        'corp_code': corp_code,
        'bsns_year': bsns_year,
        'reprt_code': reprt_code,
    })
    d1 = resp1.json()
    if d1.get('status') != '000':
        raise RuntimeError(f"irdsSttus 오류: {d1.get('status')} {d1.get('message')}")

    issu_items = d1.get('list', [])
    log(f"증자감자 {len(issu_items)}건 수신 (연도={bsns_year})")

    issu_result = []
    for item in issu_items:
        if not (_has(item.get('isu_dcrs_de')) or _has(item.get('isu_dcrs_stle'))):
            continue
        issu_result.append({
            '발행일': item.get('isu_dcrs_de', '-').strip(),
            '발행형태': item.get('isu_dcrs_stle', '-').strip(),
            '주식종류': item.get('isu_dcrs_stock_knd', '-').strip(),
            '수량': item.get('isu_dcrs_qy', '-').strip(),
            '액면가': item.get('isu_dcrs_mstvdv_fval_amount', '-').strip(),
            '발행가': item.get('isu_dcrs_mstvdv_amount', '-').strip(),
        })

    resp2 = requests.get(_TREASURY_URL, params={
        'crtfc_key': api_key,
        'corp_code': corp_code,
        'bsns_year': bsns_year,
        'reprt_code': reprt_code,
    })
    d2 = resp2.json()
    if d2.get('status') != '000':
        raise RuntimeError(f"tesstkAcqsDspsSttus 오류: {d2.get('status')} {d2.get('message')}")

    treas_items = d2.get('list', [])
    log(f"자기주식 {len(treas_items)}건 수신 (연도={bsns_year})")

    treas_result = []
    for item in treas_items:
        if item.get('acqs_mth2') != '총계':
            continue
        vals = [
            item.get('bsis_qy'),
            item.get('change_qy_acqs'),
            item.get('change_qy_dsps'),
            item.get('trmend_qy'),
        ]
        if not any(_has(v) for v in vals):
            continue
        treas_result.append({
            '주식종류': item.get('stock_knd', '-').strip(),
            '취득방법': item.get('acqs_mth2', '-').strip(),
            '기초수량': item.get('bsis_qy', '-').strip(),
            '취득': item.get('change_qy_acqs', '-').strip(),
            '처분': item.get('change_qy_dsps', '-').strip(),
            '소각': item.get('change_qy_incnr', '-').strip(),
            '기말수량': item.get('trmend_qy', '-').strip(),
        })

    return {'증자감자': issu_result, '자기주식': treas_result}


def fix_xml(xml_text):
    """
    DART XML에서 발생하는 두 가지 오염을 보정한다:
      - 텍스트/속성값 내 날것 & → &amp;
      - 텍스트 내 비태그 < → &lt;
    유효한 entity 및 정상 태그는 그대로 유지한다.
    """
    result = []
    i = 0
    n = len(xml_text)
    while i < n:
        c = xml_text[i]
        if c == '<':
            if xml_text[i:i + 9] == '<![CDATA[':
                end = xml_text.find(']]>', i + 9)
                if end != -1:
                    result.append(xml_text[i:end + 3])
                    i = end + 3
                    continue
            if xml_text[i:i + 4] == '<!--':
                end = xml_text.find('-->', i + 4)
                if end != -1:
                    result.append(xml_text[i:end + 3])
                    i = end + 3
                    continue
            if xml_text[i:i + 2] == '<?':
                end = xml_text.find('?>', i + 2)
                if end != -1:
                    result.append(xml_text[i:end + 2])
                    i = end + 2
                    continue
            m = _TAG_START.match(xml_text, i)
            if m:
                i, tag_str = _parse_tag(xml_text, i, n)
                result.append(tag_str)
                continue
            result.append('&lt;')
            i += 1
        elif c == '&':
            m = _VALID_ENTITY.match(xml_text, i)
            if m:
                result.append(m.group())
                i = m.end()
            else:
                result.append('&amp;')
                i += 1
        else:
            result.append(c)
            i += 1
    return ''.join(result)


def _parse_tag(s, i, n):
    """태그 내부를 순회하며 속성값 안의 & 만 보정. (end_pos, fixed_str) 반환"""
    result = []
    in_quote = None
    while i < n:
        c = s[i]
        if in_quote:
            if c == in_quote:
                result.append(c)
                in_quote = None
                i += 1
            elif c == '&':
                m = _VALID_ENTITY.match(s, i)
                if m:
                    result.append(m.group())
                    i = m.end()
                else:
                    result.append('&amp;')
                    i += 1
            else:
                result.append(c)
                i += 1
        else:
            if c in ('"', "'"):
                in_quote = c
                result.append(c)
                i += 1
            elif c == '>':
                result.append('>')
                i += 1
                break
            else:
                result.append(c)
                i += 1
    return i, ''.join(result)
