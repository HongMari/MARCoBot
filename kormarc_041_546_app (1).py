# ============================================
# PART 1 — Imports / Global Setup / NLK Key Load / Utilities
# ============================================

import re
import io
import json
import math
import html
import requests
import pandas as pd
import datetime
from dataclasses import dataclass
from collections import Counter
from bs4 import BeautifulSoup

import streamlit as st
from pymarc import Record, Field, Subfield, MARCWriter
from oauth2client.service_account import ServiceAccountCredentials
import gspread

# ---------------------------
# Global Session
# ---------------------------
SESSION = requests.Session()

# ---------------------------
# NLK 인증키 자동 로딩
# ---------------------------
def _auto_load_nlk_key():
    """
    Streamlit secrets 구조가 어떤 형태이든 자동 탐지:
    1) st.secrets["nlk"]["cert_key"]
    2) st.secrets["cert_key"]
    3) 없으면 ""
    """
    try:
        # Case 1
        if "nlk" in st.secrets and "cert_key" in st.secrets["nlk"]:
            return st.secrets["nlk"]["cert_key"]

        # Case 2
        if "cert_key" in st.secrets:
            return st.secrets["cert_key"]

    except Exception:
        pass

    return ""

NLK_CERT_KEY = _auto_load_nlk_key()

# ---------------------------
# 알라딘 API KEY 로딩
# ---------------------------
def _auto_load_aladin_key():
    try:
        if "aladin" in st.secrets and "ttbkey" in st.secrets["aladin"]:
            return st.secrets["aladin"]["ttbkey"]
    except:
        pass
    return ""

ALADIN_TTB_KEY = _auto_load_aladin_key()


# ---------------------------
# 공통 디버그 함수
# ---------------------------
CURRENT_DEBUG_LINES = []

def dbg(*args):
    CURRENT_DEBUG_LINES.append(" ".join(str(a) for a in args))

def dbg_err(*args):
    CURRENT_DEBUG_LINES.append("[ERROR] " + " ".join(str(a) for a in args))


# ---------------------------
# 공통 텍스트 유틸
# ---------------------------
def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------
# NLK SearchApi — 저자만 가져오기
# ---------------------------
def fetch_nlk_author_only(isbn: str):
    """
    NLK SearchApi.do 에서 AUTHOR만 가져오기.
    에러 발생해도 절대 죽지 않고 ("", None) 반환.
    """
    try:
        clean_isbn = isbn.replace("-", "").strip()
        params = {
            "cert_key": NLK_CERT_KEY,
            "result_style": "json",
            "page_no": 1,
            "page_size": 1,
            "isbn": clean_isbn
        }

        url = "https://seoji.nl.go.kr/landingPage/SearchApi.do"
        res = SESSION.get(url, params=params, timeout=(5, 10))
        res.raise_for_status()
        data = res.json()

        doc = None
        if "docs" in data and isinstance(data["docs"], list) and data["docs"]:
            doc = data["docs"][0]
        elif "doc" in data and isinstance(data["doc"], list) and data["doc"]:
            doc = data["doc"][0]

        if not doc:
            return "", None

        raw_author = (
            doc.get("AUTHOR")
            or doc.get("AUTHOR1")
            or doc.get("AUTHOR2")
            or doc.get("AUTHOR3")
            or ""
        ).strip()

        return raw_author, doc

    except Exception:
        return "", None
# ============================================
# PART 2 — 008 생성기 / 지역·국가코드 / detect 유틸
# ============================================

# ---------------------------
# 한국 지역명 → KORMARC 3자리 발행국 부호
# ---------------------------
KR_REGION_TO_CODE = {
    "서울": "ulk", "서울특별시": "ulk",
    "경기": "ggk", "경기도": "ggk",
    "부산": "bnk", "부산광역시": "bnk",
    "대구": "tgk", "대구광역시": "tgk",
    "인천": "ick", "인천광역시": "ick",
    "광주": "kjk", "광주광역시": "kjk",
    "대전": "tjk", "대전광역시": "tjk",
    "울산": "usk", "울산광역시": "usk",
    "세종": "sjk", "세종특별자치시": "sjk",
    "강원": "gak", "강원특별자치도": "gak",
    "충북": "hbk", "충청북도": "hbk",
    "충남": "hck", "충청남도": "hck",
    "전북": "jbk", "전라북도": "jbk",
    "전남": "jnk", "전라남도": "jnk",
    "경북": "gbk", "경상북도": "gbk",
    "경남": "gnk", "경상남도": "gnk",
    "제주": "jjk", "제주특별자치도": "jjk",
}

COUNTRY_FIXED = "ulk"      # 기본 발행국
LANG_FIXED    = "kor"      # 기본 언어코드


# =====================================================
# 008 본문 생성기(KORMARC 단행본)
# =====================================================
def build_008_kormarc_bk(
    date_entered,      # YYMMDD
    date1,             # 출판연도 4자리
    country3,          # 발행국 3자리
    lang3,             # 언어코드 3자리
    date2="",          # 종료 연도(연속간행물용)
    illus4="",         # 삽화코드 최대 4자
    has_index="0",     # 색인 유무
    lit_form=" ",      # 문학 형태코드
    bio=" ",           # 전기적 요소
    type_of_date="s",
    modified_record=" ",
    cataloging_src="a"
):
    def pad(s, n, fill=" "):
        s = "" if s is None else str(s)
        return (s[:n] + fill * n)[:n]

    # 날짜 검증
    if len(date_entered) != 6 or not date_entered.isdigit():
        raise ValueError("date_entered는 YYMMDD 6자리 숫자여야 합니다.")

    if len(date1) != 4:
        raise ValueError("date1(출판연도)은 4자리여야 합니다.")

    body = "".join([
        date_entered,                # 00-05
        pad(type_of_date,1),         # 06
        date1,                       # 07-10
        pad(date2,4),                # 11-14
        pad(country3,3),             # 15-17
        pad(illus4,4),               # 18-21
        " " * 4,                     # 22-25
        " " * 2,                     # 26-27
        pad(modified_record,1),      # 28
        "0",                         # 29
        "0",                         # 30
        has_index if has_index in ("0","1") else "0",   # 31
        pad(cataloging_src,1),       # 32
        pad(lit_form,1),             # 33
        pad(bio,1),                  # 34
        pad(lang3,3),                # 35-37
        " " * 2                      # 38-39
    ])

    if len(body) != 40:
        raise AssertionError(f"008 length != 40: {len(body)}")

    return body


# =====================================================
# 출판연도 추출
# =====================================================
def extract_year_from_aladin_pubdate(pubdate_str: str) -> str:
    m = re.search(r"(19|20)\d{2}", pubdate_str or "")
    return m.group(0) if m else "19uu"


# =====================================================
# 발행지 문자열 → country3 추론
# =====================================================
def guess_country3_from_place(place_str: str) -> str:
    if not place_str:
        return COUNTRY_FIXED

    for key, code in KR_REGION_TO_CODE.items():
        if key in place_str:
            return code

    return COUNTRY_FIXED


# ---------------------------
# 삽화/도표/사진 감지
# ---------------------------
def detect_illus4(text: str) -> str:
    keys = []
    if re.search(r"삽화|삽도|도해|일러스트|illustration|그림", text, re.I):
        keys.append("a")
    if re.search(r"도표|표|차트|그래프|chart|graph", text, re.I):
        keys.append("d")
    if re.search(r"사진|포토|photo|photograph|화보", text, re.I):
        keys.append("o")
    out = []
    for k in keys:
        if k not in out:
            out.append(k)
    return "".join(out)[:4]


# ---------------------------
# 색인 감지
# ---------------------------
def detect_index(text: str) -> str:
    return "1" if re.search(r"색인|찾아보기|index", text, re.I) else "0"


# ---------------------------
# 문학 형태 감지
# ---------------------------
def detect_lit_form(title: str, category: str, extra_text: str = "") -> str:
    blob = f"{title} {category} {extra_text}"

    if re.search(r"서간집|편지|서간문|letters?", blob, re.I):
        return "i"
    if re.search(r"기행|여행기|일기|수기|diary|travel", blob, re.I):
        return "m"
    if re.search(r"시집|산문시|poem|poetry", blob, re.I):
        return "p"
    if re.search(r"소설|novel|fiction|장편|중단편", blob, re.I):
        return "f"
    if re.search(r"에세이|수필|essay", blob, re.I):
        return "e"

    return " "


# ---------------------------
# 전기 요소 감지
# ---------------------------
def detect_bio(text: str) -> str:
    if re.search(r"자서전|회고록|autobiograph", text, re.I):
        return "a"
    if re.search(r"전기|평전|biograph", text, re.I):
        return "b"
    if re.search(r"전기적|자전적|회고", text, re.I):
        return "d"
    return " "


# ---------------------------
# 발행지 “미상” 판단
# ---------------------------
def _is_unknown_place(s: str | None) -> bool:
    if not s:
        return False
    t = s.strip()
    t_no_sp = t.replace(" ", "")
    lower = t.lower()
    return (
        "미상" in t
        or "미상" in t_no_sp
        or "unknown" in lower
        or "place unknown" in lower
    )


# =====================================================
# ISBN을 기반으로 008 필드 전체를 구성하는 최종 함수
# =====================================================
def build_008_from_isbn(
    isbn: str,
    *,
    aladin_pubdate: str = "",
    aladin_title: str = "",
    aladin_category: str = "",
    aladin_desc: str = "",
    aladin_toc: str = "",
    source_300_place: str = "",
    override_country3: str = None,
    override_lang3: str = None,
    cataloging_src: str = "a",
):
    today  = datetime.datetime.now().strftime("%y%m%d")
    date1  = extract_year_from_aladin_pubdate(aladin_pubdate)

    # ---------- country3 결정 ----------
    if override_country3:
        country3 = override_country3
    elif source_300_place:
        if _is_unknown_place(source_300_place):
            dbg("[008] 발행지 미상 감지 → country3='   '")
            country3 = "   "
        else:
            guessed = guess_country3_from_place(source_300_place)
            country3 = guessed or COUNTRY_FIXED
    else:
        country3 = COUNTRY_FIXED

    # ---------- 언어 코드 ----------
    lang3 = override_lang3 or LANG_FIXED

    # ---------- 삽화/색인/문학형식/전기 ----------
    bigtext = " ".join([aladin_title, aladin_desc, aladin_toc])
    illus4    = detect_illus4(bigtext)
    has_index = detect_index(bigtext)
    lit_form  = detect_lit_form(aladin_title, aladin_category, bigtext)
    bio       = detect_bio(bigtext)

    return build_008_kormarc_bk(
        date_entered=today,
        date1=date1,
        country3=country3,
        lang3=lang3,
        illus4=illus4,
        has_index=has_index,
        lit_form=lit_form,
        bio=bio,
        cataloging_src=cataloging_src,
    )
# ============================================
# PART 3 — 알라딘 API / 스크레이핑 / KPIPA / 문체부 / 발행사항 묶음
# ============================================

ALADIN_SEARCH_URL = "https://www.aladin.co.kr/search/wsearchresult.aspx"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# ------------------------------------------------------
# 알라딘 ItemLookUp (API)
# ------------------------------------------------------
def aladin_lookup_by_api(isbn13: str, ttbkey: str) -> dataclass | None:
    if not ttbkey:
        return None

    params = {
        "ttbkey": ttbkey,
        "itemIdType": "ISBN13",
        "ItemId": isbn13,
        "output": "js",
        "Version": "20131101",
        "OptResult": "authors,categoryName,fulldescription,toc,packaging,ratings"
    }
    try:
        r = requests.get(
            "https://www.aladin.co.kr/ttb/api/ItemLookUp.aspx",
            params=params,
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        items = data.get("item", [])
        if not items:
            dbg("[ALADIN API] 결과 없음")
            return None

        it = items[0]
        return BookInfo(
            title=clean_text(it.get("title")),
            author=clean_text(it.get("author")),
            pub_date=clean_text(it.get("pubDate")),
            publisher=clean_text(it.get("publisher")),
            isbn13=clean_text(it.get("isbn13")) or isbn13,
            category=clean_text(it.get("categoryName")),
            description=clean_text(it.get("fulldescription")) or clean_text(it.get("description")),
            toc=clean_text(it.get("toc")),
            extra=it,
        )

    except Exception as e:
        dbg_err(f"[ALADIN API] 예외 발생: {e}")
        return None


# ------------------------------------------------------
# 알라딘 웹 검색 → 상품 상세 페이지 스크레이핑 (백업 방식)
# ------------------------------------------------------
def aladin_lookup_by_web(isbn13: str) -> dataclass | None:
    try:
        params = {"SearchTarget": "Book", "SearchWord": f"isbn:{isbn13}"}
        sr = requests.get(ALADIN_SEARCH_URL, params=params, headers=HEADERS, timeout=15)
        sr.raise_for_status()
        soup = BeautifulSoup(sr.text, "html.parser")

        # 1) 상품 detail URL 우선 탐지
        link_tag = soup.select_one("a.bo3")
        item_url = None

        if link_tag and link_tag.get("href"):
            item_url = "https://www.aladin.co.kr" + link_tag["href"]

        if not item_url:
            m = re.search(
                r'href=[\'"](/shop/wproduct\.aspx\?ItemId=\d+[^\'"]*)[\'"]',
                sr.text,
                re.I,
            )
            if m:
                item_url = "https://www.aladin.co.kr" + m.group(1)

        if not item_url:
            dbg_err("[ALADIN WEB] 상품 링크 찾기 실패")
            return None

        pr = requests.get(item_url, headers=HEADERS, timeout=15)
        pr.raise_for_status()
        psoup = BeautifulSoup(pr.text, "html.parser")

        og_title = psoup.select_one('meta[property="og:title"]')
        og_desc  = psoup.select_one('meta[property="og:description"]')

        title = clean_text(og_title["content"]) if og_title else ""
        desc  = clean_text(og_desc["content"]) if og_desc else ""

        text_body = clean_text(psoup.get_text(" "))[:4000]
        description = desc or text_body

        # 저자/출판사/출간일 heuristics
        author, publisher, pub_date, category = "", "", "", ""
        info_box = psoup.select_one("#Ere_prod_allwrap")

        if info_box:
            text = clean_text(info_box.get_text(" "))
            ma = re.search(r"(저자|지은이)\s*:\s*([^\|·/]+)", text)
            mp = re.search(r"(출판사)\s*:\s*([^\|·/]+)", text)
            md = re.search(r"(출간일)\s*:\s*([0-9]{4}\.[0-9]{1,2}\.[0-9]{1,2})", text)

            if ma: author = clean_text(ma.group(2))
            if mp: publisher = clean_text(mp.group(2))
            if md: pub_date = clean_text(md.group(2))

        crumbs = psoup.select(".location, .path, .breadcrumb")
        if crumbs:
            category = clean_text(" > ".join(c.get_text(" ") for c in crumbs))

        dbg("[ALADIN WEB]", "url=", item_url)

        return BookInfo(
            title=title,
            description=description,
            isbn13=isbn13,
            author=author,
            publisher=publisher,
            pub_date=pub_date,
            category=category,
        )

    except Exception as e:
        dbg_err(f"[ALADIN WEB] 예외 발생: {e}")
        return None


# ------------------------------------------------------
# 알라딘 상세페이지에서 300 파싱에 쓰는 서브 함수들
# ------------------------------------------------------
def detect_illustrations(text: str):
    if not text:
        return False, None

    groups = {
        "천연색삽화": ["삽화", "일러스트", "illustration", "그림"],
        "삽화": ["흑백 삽화", "흑백 일러스트"],
        "사진": ["사진", "포토", "photo", "화보"],
        "도표": ["도표", "차트", "그래프"],
        "지도": ["지도"],
    }

    found = set()
    for label, words in groups.items():
        if any(w in text for w in words):
            found.add(label)

    return (True, ", ".join(sorted(found))) if found else (False, None)


# =====================================================
# KPIPA PAGE SEARCH (출판사 / 임프린트 추출)
# =====================================================
def get_publisher_name_from_isbn_kpipa(isbn):
    search_url = "https://bnk.kpipa.or.kr/home/v3/addition/search"
    params = {
        "ST": isbn,
        "PG": 1,
        "PG2": 1,
        "DSF": "Y",
        "SO": "weight",
        "DT": "A"
    }
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        res = requests.get(search_url, params=params, headers=headers, timeout=15)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        link = soup.select_one("a.book-grid-item")
        if not link:
            return None, None, "❌ KPIPA 검색 결과 없음"

        detail_url = "https://bnk.kpipa.or.kr" + link.get("href")
        dr = requests.get(detail_url, headers=headers, timeout=15)
        dr.raise_for_status()
        dsoup = BeautifulSoup(dr.text, "html.parser")

        pub_info = dsoup.find("dt", string="출판사 / 임프린트")
        if not pub_info:
            return None, None, "❌ KPIPA: 출판사/임프린트 항목 없음"

        dd = pub_info.find_next_sibling("dd")
        if not dd:
            return None, None, "❌ KPIPA: dd 태그 없음"

        full_text = dd.get_text(strip=True)
        rep = full_text.split("/")[0].strip()

        def normalize(x):
            return re.sub(r"\s|\(.*?\)|주식회사|㈜|도서출판|출판사", "", x).lower()

        rep_norm = normalize(rep)
        return full_text, rep_norm, None

    except Exception as e:
        return None, None, f"KPIPA 예외: {e}"


# =====================================================
# 문체부 DB 검색 (출판사 주소 탐색)
# =====================================================
def get_mcst_address(publisher_name):
    url = "https://book.mcst.go.kr/html/searchList.php"
    params = {
        "search_area": "전체",
        "search_state": "1",
        "search_kind": "1",
        "search_type": "1",
        "search_word": publisher_name,
    }
    debug = []

    try:
        res = requests.get(url, params=params, timeout=15)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        rows = []
        for tr in soup.select("table.board tbody tr"):
            tds = tr.find_all("td")
            if len(tds) >= 4:
                reg_type = tds[0].get_text(strip=True)
                name     = tds[1].get_text(strip=True)
                address  = tds[2].get_text(strip=True)
                status   = tds[3].get_text(strip=True)
                if status == "영업":
                    rows.append((reg_type, name, address, status))

        if rows:
            debug.append(f"[MCST] 검색 성공 {len(rows)}건")
            return rows[0][2], rows, debug

        debug.append("[MCST] 검색 결과 없음")
        return "미확인", [], debug

    except Exception as e:
        debug.append(f"[MCST] 예외 발생: {e}")
        return "오류 발생", [], debug


# =====================================================
# Google Sheets 기반 Publisher / Region DB 불러오기
# =====================================================
@st.cache_data(ttl=3600)
def load_publisher_db():
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        st.secrets["gspread"],
        [
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/spreadsheets",
        ],
    )
    client = gspread.authorize(creds)
    sh = client.open("출판사 DB")

    # 출판사명-주소
    pub_rows = sh.worksheet("발행처명–주소 연결표").get_all_values()[1:]
    pub_df = pd.DataFrame(
        [row[1:3] for row in pub_rows],
        columns=["출판사명","주소"]
    )

    # 발행국-부호
    region_rows = sh.worksheet("발행국명–발행국부호 연결표").get_all_values()[1:]
    region_df = pd.DataFrame(
        [row[:2] for row in region_rows],
        columns=["발행국","발행국 부호"]
    )

    # 임프린트 시트
    imps = []
    for ws in sh.worksheets():
        if ws.title.startswith("발행처-임프린트 연결표"):
            data = ws.get_all_values()[1:]
            for row in data:
                if row and row[0]:
                    imps.append(row[0])
    imp_df = pd.DataFrame(imps, columns=["임프린트"])

    return pub_df, region_df, imp_df


# =====================================================
# 출판사 이름 정규화
# =====================================================
def normalize_publisher_name(name):
    return re.sub(r"\s|\(.*?\)|주식회사|㈜|도서출판|출판사", "", (name or "")).lower()


# =====================================================
# Region → 발행국 코드 찾기
# =====================================================
def get_country_code_by_region(region_name, region_df):
    try:
        def norm(x):
            x = (x or "").strip()
            if x.startswith(("전라","충청","경상")):
                return x[0] + (x[2] if len(x)>2 else "")
            return x[:2]

        target = norm(region_name)
        for _, row in region_df.iterrows():
            if norm(row["발행국"]) == target:
                return row["발행국 부호"] or "   "
        return "   "
    except Exception:
        return "   "


# =====================================================
# 최종: 출판지 묶음 정보 bundle 생성
# =====================================================
def build_pub_location_bundle(isbn, publisher_name_raw):
    debug = []

    try:
        pub_df, region_df, imp_df = load_publisher_db()
        debug.append("✓ Google Sheets DB load OK")

        kp_full, kp_norm, err = get_publisher_name_from_isbn_kpipa(isbn)
        if err:
            debug.append("KPIPA: " + err)

        rep_name = (kp_full or publisher_name_raw or "").split("/")[0].strip()
        debug.append(f"대표 출판사명 = {rep_name}")

        # KPIPA DB 직접 매칭
        norm_rep = normalize_publisher_name(rep_name)
        matches = pub_df[pub_df["출판사명"].apply(lambda x: normalize_publisher_name(x)) == norm_rep]

        if not matches.empty:
            place_raw = matches.iloc[0]["주소"]
            source = "KPIPA_DB"
        else:
            # 문체부 검색
            mc_addr, mc_rows, mc_debug = get_mcst_address(rep_name)
            debug += mc_debug

            if mc_addr not in ("미확인","오류 발생",None):
                place_raw = mc_addr
                source = "MCST"
            else:
                place_raw = "발행지 미상"
                source = "FALLBACK"

        # 표시용 발행지 정규화
        disp = place_raw
        if disp and disp not in ("발행지 미상","예외 발생"):
            major = ["서울","인천","대전","광주","울산","대구","부산","세종"]
            for c in major:
                if c in disp:
                    disp = c
                    break
        else:
            disp = "발행지 미상"

        # country3
        ccode = get_country_code_by_region(place_raw, region_df)

        return {
            "place_raw": place_raw,
            "place_display": disp,
            "country_code": ccode,
            "resolved_publisher": rep_name,
            "source": source,
            "debug": debug,
        }

    except Exception as e:
        return {
            "place_raw": "발행지 미상",
            "place_display": "발행지 미상",
            "country_code": "   ",
            "resolved_publisher": publisher_name_raw or "",
            "source": "ERROR",
            "debug": [f"예외: {e}"],
        }


# =====================================================
# 260 생성기
# =====================================================
def build_260(place_display: str, publisher_name: str, pubyear: str):
    place = place_display or "발행지 미상"
    pub   = publisher_name or "발행처 미상"
    year  = pubyear or "발행년 미상"
    return f"=260  \\\\$a{place} :$b{pub},$c{year}"
# ============================================
# PART 4 — 언어(041) / 546 / 원작언어·본문언어 감지
# ============================================

# ------------------------------------------------------
# 언어코드 → 자연어명 (546 생성에 사용)
# ------------------------------------------------------
ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어',
    'chi': '중국어', 'zho': '중국어', 'rus': '러시아어',
    'ara': '아랍어', 'fre': '프랑스어', 'fra': '프랑스어',
    'ger': '독일어', 'deu': '독일어', 'ita': '이탈리아어',
    'spa': '스페인어', 'por': '포르투갈어',
    'und': '알 수 없음'
}


# ------------------------------------------------------
# 매우 단순한 1차 언어 감지 (초성/영문 기반)
# ------------------------------------------------------
def detect_language(text):
    text = re.sub(r'[\s\W_]+', '', text or "")
    if not text:
        return 'und'

    ch = text[0]

    # 한글
    if '\uac00' <= ch <= '\ud7a3':
        return 'kor'
    # 일본어
    if '\u3040' <= ch <= '\u30ff':
        return 'jpn'
    # 한자
    if '\u4e00' <= ch <= '\u9fff':
        return 'chi'
    # 키릴 문자
    if '\u0400' <= ch <= '\u04FF':
        return 'rus'
    # 영어
    if 'a' <= ch.lower() <= 'z':
        return 'eng'

    return 'und'


# ------------------------------------------------------
# 최종 546 생성기
# ------------------------------------------------------
def generate_546_from_041_kormarc(marc_041: str) -> str:
    """
    041의 $a, $h 분석해서 자연어 문장 만드는 함수.
    """
    if not marc_041:
        return ""

    a_list, h_code = [], None
    parts = marc_041.split()

    for p in parts:
        if p.startswith("$a"):
            a_list.append(p[2:])
        elif p.startswith("$h"):
            h_code = p[2:]

    # 본문 언어 1개
    if len(a_list) == 1:
        a_lang = ISDS_LANGUAGE_CODES.get(a_list[0], "알 수 없음")
        if h_code:
            h_lang = ISDS_LANGUAGE_CODES.get(h_code, "알 수 없음")
            return f"{h_lang} 원작을 {a_lang}로 번역"
        return f"{a_lang}로 씀"

    # 본문 언어 2개 이상
    if len(a_list) > 1:
        langs = [ISDS_LANGUAGE_CODES.get(x, "알 수 없음") for x in a_list]
        return "·".join(langs) + " 병기"

    return "언어 정보 없음"


# ------------------------------------------------------
# 041 문자열에서 $a → 언어코드(3글자) 추출
# ------------------------------------------------------
def _lang3_from_tag041(tag_041: str | None) -> str | None:
    if not tag_041:
        return None
    m = re.search(r"\$a([a-z]{3})", tag_041, flags=re.I)
    return m.group(1).lower() if m else None


# ------------------------------------------------------
# 041 원작언어($h)를 파싱 (문학 8xx 후처리에 사용)
# ------------------------------------------------------
def _parse_marc_041_original(marc041: str):
    if not marc041:
        return None
    s = str(marc041).lower()
    m = re.search(r"\$h([a-z]{3})", s)
    return m.group(1) if m else None


# ------------------------------------------------------
# 원작언어 기반 문학 계열 헤더 재정렬
# ------------------------------------------------------
def _lang3_to_kdc_lit_base(lang3: str):
    if not lang3:
        return None
    l = lang3.lower()

    # 한국어
    if l == "kor": return "810"
    # 중국어
    if l in ("chi","zho"): return "820"
    # 일본어
    if l == "jpn": return "830"
    # 영미
    if l == "eng": return "840"
    # 독일
    if l in ("ger","deu"): return "850"
    # 프랑스
    if l in ("fre","fra"): return "860"
    # 스페인/포르투갈
    if l in ("spa","por"): return "870"
    # 이탈리아
    if l == "ita": return "880"

    return "890"


def _rebase_8xx_with_language(code: str, marc041: str) -> str:
    """
    8xx 문학 코드일 때, 원작언어($h)에 맞게 '앞 두 자리'를 재배치.
    """
    if not code or len(code) < 3 or code[0] != "8":
        return code

    orig = _parse_marc_041_original(marc041 or "")
    base = _lang3_to_kdc_lit_base(orig) if orig else None
    if not base:
        return code

    m = re.match(r"^(\d{3})(\..+)?$", code)
    if not m:
        return code

    head3 = m.group(1)
    tail  = m.group(2) or ""
    genre = head3[2]   # 마지막 자리

    new_head = base[:2] + genre
    return new_head + tail


# ------------------------------------------------------
# =041 / =546 MRK 방식으로 변환
# ------------------------------------------------------
def _as_mrk_041(s: str | None) -> str:
    if not s:
        return None
    if s.startswith("=041"):
        return s
    return f"=041  \\\\{s}"

def _as_mrk_546(s: str | None) -> str:
    if not s:
        return None
    if s.startswith("=546"):
        return s
    return f"=546  \\\\{s}"
# ============================================
# PART 5 — GPT 기반 653 생성기(1회 호출) + 금칙어 필터링
# ============================================

# ---------------------------------------
# GPT API 호출 공통 함수
# ---------------------------------------
import openai

def _call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 256):
    """
    GPT-4o / GPT-4o-mini 등 통합 호출.
    Streamlit Cloud 환경에서도 안정적으로 동작.
    """
    try:
        client = openai.OpenAI(api_key=st.secrets["openai"]["api_key"])
        res = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.1,
        )
        return res.choices[0].message.content.strip()
    except Exception as e:
        dbg_err(f"[GPT] 호출 오류: {e}")
        return None


# ---------------------------------------
# 금칙어 정의 — 653 키워드에서 제거
# ---------------------------------------
FORBIDDEN_WORDS = {
    "책", "도서", "소설", "작품", "저자", "출판", "출판사",
    "이야기", "내용", "문학", "문학작품", "대상", "독자",
    "장편소설", "단편소설", "글", "산문", "브랜드",
    "시리즈", "총서", "권", "편", "chapter", "index",
}


# ---------------------------------------
# 키워드 정규화
# ---------------------------------------
def _normalize_keyword(k: str):
    if not k:
        return ""
    k = k.strip().lower()
    k = re.sub(r"[^0-9a-z가-힣·\- ]+", "", k)
    return k


# ---------------------------------------
# GPT → 653 서브필드 변환
# ---------------------------------------
def _keywords_to_653_mrk(keywords: list[str]):
    if not keywords:
        return None
    parts = []
    for w in keywords:
        if w:
            parts.append(f"$a{w}")
    return "=653  \\\\" + "".join(parts)


# ---------------------------------------
# GPT 반환 문자열에서 키워드 리스트 추출
# ---------------------------------------
def _extract_keywords_from_gpt(raw: str) -> list[str]:
    if not raw:
        return []

    # 쉼표·줄바꿈·불릿 등 모두 허용
    tokens = re.split(r"[,;\n]|·|\t|\|", raw)
    out = []

    for t in tokens:
        t = _normalize_keyword(t)
        if len(t) < 2:
            continue
        if t in FORBIDDEN_WORDS:
            continue
        out.append(t)

    # 중복 제거 + 길이 제한
    uniq = []
    for x in out:
        if x not in uniq:
            uniq.append(x)

    return uniq[:7]


# ---------------------------------------
# GPT 1회 호출 기반 653 생성기
# ---------------------------------------
def _build_653_via_gpt(item):
    """ 알라딘 item → 제목/부제/설명 기반 653 자동 생성 """
    if not item:
        return None

    title = (item.get("title") or "").strip()
    sub   = ((item.get("subInfo") or {}).get("subTitle") or "").strip()
    desc  = (item.get("description") or "").strip()
    cate  = (item.get("categoryName") or "").strip()

    text_blob = f"제목: {title}\n부제: {sub}\n카테고리: {cate}\n내용요약: {desc[:800]}"

    sys_prompt = (
        "너는 대한민국 공공도서관의 주제전문 사서다.\n"
        "입력된 도서정보(제목/부제/카테고리/내용요약)를 분석하여 "
        "KORMARC 653$a에 들어갈 **구체적이고 함축적인 주제 키워드 3~6개**만 출력하라.\n\n"
        "조건:\n"
        "1) '책, 도서, 소설, 작품, 내용, 출판, 저자' 등 일반적 금칙어 금지.\n"
        "2) 개념·주제·사건·대상·분야 등 실질적으로 검색효율이 높은 단어만.\n"
        "3) 쉼표로 구분하여 출력 (예: 인공지능, 기계학습, 데이터과학)."
    )

    raw = _call_llm(sys_prompt, text_blob, max_tokens=60)
    if not raw:
        return None

    kws = _extract_keywords_from_gpt(raw)
    if not kws:
        return None

    return _keywords_to_653_mrk(kws)


# ---------------------------------------
# 653 → KDC 056 힌트 파싱
# ---------------------------------------
def _parse_653_keywords(tag_653: str | None):
    """ =653  \\$a데이터과학$a인공지능 → ['데이터과학','인공지능'] """
    if not tag_653:
        return []
    parts = re.findall(r"\$a([^$]+)", tag_653)
    out = []
    for p in parts:
        p = _normalize_keyword(p)
        if p:
            out.append(p)
    return out
# ============================================
# PART 6 — 056(KDC) 자동분류 생성기 (GPT 1회 호출)
# ============================================

# ------------------------------------------------------
# KDC 분류에 영향을 주는 정보 원본 → payload 구성
# ------------------------------------------------------
def _build_kdc_payload(info, keywords_hint):
    """
    KDC 분류를 위한 정보 패키지 생성:
    - 제목, 저자, 출판사, 카테고리
    - 내용 요약
    - 653 기반 키워드 힌트
    """
    return {
        "title": (info.get("title") or "").strip(),
        "author": (info.get("author") or "").strip(),
        "publisher": (info.get("publisher") or "").strip(),
        "category": (info.get("categoryName") or "").strip(),
        "description": (info.get("description") or "").strip(),
        "toc": clean_text(((info.get("subInfo") or {}).get("toc") or "")),
        "keywords_hint": keywords_hint or [],
    }


# ------------------------------------------------------
# GPT 시스템 프롬프트(KDC 전문가 모드)
# ------------------------------------------------------
KDC_SYSTEM_PROMPT = """
너는 대한민국 공공도서관 분류전문 사서이며, KDC 제6판 규칙만 준수한다.

당신의 임무:
1) 제공된 도서정보(title, author, category, description, toc, keywords_hint)를 분석하고
2) 가장 적합한 **KDC 3자리 정수 하나만** 산출한다. (예: 370, 004, 823)
3) 판단이 불가능할 경우에만 **정확히 '직접분류추천'**만 출력한다.

출력 형식:
- 불필요한 문장/코멘트 없이 **3자리 정수만** 단독으로 출력.
- 예외적으로 모호한 경우 '직접분류추천' 단어만 출력.
"""


# ------------------------------------------------------
# GPT를 이용한 KDC 분류 (1회 호출 버전)
# ------------------------------------------------------
def ask_llm_for_kdc(info: dict, api_key: str, model: str, keywords_hint=None):
    """
    GPT 1회 호출로 KDC 코드 생성.
    """
    payload = _build_kdc_payload(info, keywords_hint)

    user_prompt = "도서 정보:\n" + json.dumps(payload, ensure_ascii=False, indent=2)

    try:
        client = openai.OpenAI(api_key=api_key)
        res = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": KDC_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=10,
            temperature=0.0,
        )
        code = res.choices[0].message.content.strip()
        dbg("[KDC GPT RAW]", code)
        return code

    except Exception as e:
        dbg_err(f"[KDC] GPT 호출 오류: {e}")
        return None


# ------------------------------------------------------
# ISBN 기반 전체 KDC 처리 파이프라인
# ------------------------------------------------------
def get_kdc_from_isbn(isbn13: str, ttbkey: str, openai_key: str, model: str,
                      keywords_hint: list[str] | None = None) -> str | None:

    # ① 알라딘 정보 수집
    info = aladin_lookup_by_api(isbn13, ttbkey) if ttbkey else None
    if not info:
        info = aladin_lookup_by_web(isbn13)

    if not info:
        st.warning("❌ 알라딘에서 도서 정보를 찾지 못했습니다.")
        return None

    # ② GPT 호출
    code = ask_llm_for_kdc(info, api_key=openai_key, model=model, keywords_hint=keywords_hint)

    # ③ format 검증
    if not code:
        return None

    if code == "직접분류추천":
        return "직접분류추천"

    # 정확한 숫자 1~3자리?
    if re.fullmatch(r"\d{1,3}", code):
        return code.zfill(3)  # 23 → 023 형태 방지

    return None
# ============================================
# PART 7 — MARC 빌더 (300 / 020 / 245 / 246 / 700 / 490 / 830 / 940 / 950 / 049 …)
# ============================================

# =============================================================
# 공통 데이터 클래스
# =============================================================
@dataclass
class BookInfo:
    title: str = ""
    author: str = ""
    publisher: str = ""
    pub_date: str = ""
    isbn13: str = ""
    category: str = ""
    description: str = ""
    toc: str = ""
    extra: dict = None


# =============================================================
# 300 필드 — 알라딘 상세페이지 기반 형사항(삽화/크기/페이지) 파싱
# =============================================================
def parse_aladin_physical_book_info(html):
    soup = BeautifulSoup(html, "html.parser")

    # 제목·부제·설명 (삽화 감지용)
    title = soup.select_one("span.Ere_bo_title")
    subtitle = soup.select_one("span.Ere_sub1_title")

    title_text    = clean_text(title.get_text()) if title else ""
    subtitle_text = clean_text(subtitle.get_text()) if subtitle else ""

    desc_tag = soup.select_one("div.Ere_prod_mconts_R")
    description = clean_text(desc_tag.get_text(" ")) if desc_tag else ""

    # 형태사항
    form_wrap = soup.select_one("div.conts_info_list1")

    a_part, b_part, c_part = "", "", ""
    page_value = None
    size_value = None

    if form_wrap:
        items = [x.strip() for x in form_wrap.stripped_strings if x.strip()]
        for it in items:
            # 쪽수
            if re.search(r"(쪽|p)\s*$", it):
                m = re.search(r"\d+", it)
                if m:
                    page_value = int(m.group())
                    a_part = f"{page_value} p."

            # 크기 mm
            elif "mm" in it:
                m = re.search(r"(\d+)\s*[\*x×X]\s*(\d+)", it)
                if m:
                    w = int(m.group(1))
                    h = int(m.group(2))
                    size_value = f"{w}x{h}mm"

                    # cm 계산
                    wcm = math.ceil(w / 10)
                    hcm = math.ceil(h / 10)
                    c_part = f"{wcm}x{hcm} cm"

    # 삽화 감지
    combined = " ".join([title_text, subtitle_text, description])
    has_illus, illus_label = detect_illustrations(combined)
    if has_illus:
        b_part = illus_label

    # Subfields 구성
    subfields_300 = []
    if a_part: subfields_300.append(Subfield("a", a_part))
    if b_part: subfields_300.append(Subfield("b", b_part))
    if c_part: subfields_300.append(Subfield("c", c_part))

    # MRK 문자열 구성
    parts = []
    if a_part:
        part = f"$a{a_part}"
        if b_part:
            part += f" :$b{b_part}"
        parts.append(part)
    elif b_part:
        parts.append(f"$b{b_part}")

    if c_part:
        if parts:
            parts.append(f"; $c {c_part}")
        else:
            parts.append(f"$c {c_part}")

    if not parts:
        parts = ["$a1책."]

    mrk = "=300  \\\\" + " ".join(parts)

    return {
        "300": mrk,
        "300_subfields": subfields_300,
        "page_value": page_value,
        "size_value": size_value,
        "illustration_possibility": illus_label or "없음"
    }


def search_aladin_detail_page(link):
    try:
        res = requests.get(link, timeout=15)
        res.raise_for_status()
        return parse_aladin_physical_book_info(res.text), None
    except Exception as e:
        return {
            "300": "=300  \\$a1책. [상세 페이지 파싱 오류]",
            "300_subfields": [Subfield("a","1책 [파싱 실패]")],
            "page_value": None,
            "size_value": None,
            "illustration_possibility": "정보 없음",
        }, str(e)


def build_300_from_aladin_detail(item: dict):
    try:
        link = (item or {}).get("link", "")
        if not link:
            return "=300  \\$a1책.", Field(tag="300", indicators=[" "," "], subfields=[Subfield("a","1책.")])

        info, err = search_aladin_detail_page(link)
        mrk = info["300"]
        subs = info["300_subfields"]

        f300 = Field(tag="300", indicators=[" "," "], subfields=subs)
        if err:
            dbg_err("[300]", err)
        return mrk, f300
    except Exception as e:
        dbg_err(f"[300 Exception] {e}")
        return "=300  \\$a1책.[예외]", Field(tag="300", indicators=[" "," "], subfields=[Subfield("a","1책.[예외]")])


# =============================================================
# 총서(490/830)
# =============================================================
def build_490_830_mrk_from_item(item):
    si = None
    if isinstance(item, dict):
        si = item.get("seriesInfo") or (item.get("subInfo") or {}).get("seriesInfo")

    cand = []
    if isinstance(si, list):
        cand = si
    elif isinstance(si, dict):
        cand = [si]

    sname, svol = "", ""
    for ent in cand:
        if not isinstance(ent, dict):
            continue
        name = (ent.get("seriesName") or ent.get("name") or "").strip()
        vol  = (ent.get("volume") or "").strip()
        if name:
            sname, svol = name, vol
            break

    if not sname:
        return "", ""

    display = f"{sname} {svol}".strip()
    tag_490 = f"=490  10$a{display}"
    tag_830 = f"=830  \\0$a{display}"
    return tag_490, tag_830


# =============================================================
# 가격 / ISBN → 020 필드
# =============================================================
def _extract_price_kr(item, isbn):
    """ 알라딘 item 상품가 → 숫자만 """
    price = 0
    try:
        extra = item.get("extra") or {}
        if "priceStandard" in extra:
            price = int(extra["priceStandard"])
        elif "priceSales" in extra:
            price = int(extra["priceSales"])
    except:
        pass
    return price


def _build_020_from_item_and_nlk(isbn, item):
    """ 020 필드 생성: ISBN + 가격 """
    price = _extract_price_kr(item, isbn)
    if price:
        return f"=020  \\\\$a{isbn} :$c{price}"
    return f"=020  \\\\$a{isbn}"


# =============================================================
# 950 필드 (가격만 별도 저장)
# =============================================================
def build_950_from_item_and_price(item, isbn):
    price = _extract_price_kr(item, isbn)
    if price:
        return f"=950  \\\\$a{price}"
    return "=950  \\\\$a미상"


# =============================================================
# 서명 / 부제 / 책임표시 — 245
# =============================================================
def build_245_with_people_from_sources(item, nlk_author_raw, prefer="aladin"):
    """
    245 $a / $b / $c 구성
    """

    # 제목·부제
    title = clean_text(item.get("title") or "")
    subtitle = clean_text((item.get("subInfo") or {}).get("subTitle") or "")
    author  = clean_text(item.get("author") or "")
    year    = clean_text(item.get("pubDate") or "")[:4]

    # 책임표시
    c_part = author
    if year:
        c_part += f" ({year})"

    # =245 시작 — 인디케이터는 00으로 고정
    out = "=245  00"

    # $a
    if subtitle:
        out += f"$a{title} :$b{subtitle}"
    else:
        out += f"$a{title}"

    # $c
    if c_part:
        out += f" /$c{c_part}"

    return out


# =============================================================
# 246 대등서명 / 이형서명
# =============================================================
def build_246_from_aladin_item(item):
    """
    알라딘 item에서 원제가 존재하면 246에 기록
    """
    orig = (item.get("extra") or {}).get("originalTitle") or ""
    if not orig:
        return ""
    orig = clean_text(orig)

    return f"=246  31$a{orig}"


# =============================================================
# 700 필드 — 인명 접근점
# =============================================================
def build_700_people_pref_aladin(nlk_author_raw, item, origin_lang_code=None):
    """
    원작 언어 감안하여 정렬형 이름을 구성하는 간단 버전.
    """
    authors = clean_text(nlk_author_raw or item.get("author") or "")
    if not authors:
        return []

    tokens = re.split(r",|;|/|·|\s", authors)
    tokens = [t.strip() for t in tokens if t.strip()]

    out = []
    for t in tokens:
        if not t:
            continue

        # 간단한 정렬 방식: 성, 이름 구조
        if origin_lang_code in ("eng", "fre", "ger", "spa", "rus", "ita"):
            # 영어권: "성, 이름" 형식
            parts = t.split()
            if len(parts) >= 2:
                lname = parts[-1]
                fname = " ".join(parts[:-1])
                name_form = f"{lname}, {fname}"
            else:
                name_form = t
        else:
            # 아시아권: 그대로
            name_form = t

        out.append(f"=700  1\\$a{name_form}")

    return out


# =============================================================
# 90010 — LOD 기반 원어명
# (여기서는 실제 Wikidata API 호출 대신 샘플 형태로 구조만 유지)
# =============================================================
LAST_PROV_90010 = {}

def build_90010_from_wikidata(people: dict, include_translator=False):
    """
    외부 LOD 사용이 불가능한 환경이 많으므로, 구조만 유지.
    실제 호출은 생략하고 빈 리스트 반환.
    """
    return []


# =============================================================
# 940 — 제목 기반 분류기
# =============================================================
def parse_245_a_n(marc245: str):
    """
    245의 $a 부분에서 숫자를 추출할지 여부 판단
    """
    if not marc245:
        return "", None
    m = re.search(r"\$a([^$]+)", marc245)
    a = clean_text(m.group(1)) if m else ""
    n = re.search(r"\b(\d+)\b", a)
    return a, (n.group(1) if n else None)


def build_940_from_title_a(title_a: str, use_ai=True, disable_number_reading=False):
    """
    940 자동 제목분류: 여기는 간단 버전 (숫자 제거 옵션 포함)
    """
    if disable_number_reading:
        title_clean = re.sub(r"\d+", "", title_a)
    else:
        title_clean = title_a

    if not title_clean:
        return []

    sf = Subfield("a", title_clean)
    field = f"=940  \\\\$a{title_clean}"
    return [field]


# =============================================================
# 049 — 등록기호
# =============================================================
def build_049(reg_mark, reg_no, copy_symbol):
    if not reg_mark and not reg_no:
        return ""
    body = f"$a{reg_mark}{reg_no}"
    if copy_symbol:
        body += f"$c{copy_symbol}"
    return f"=049  \\\\{body}"


# =============================================================
# 문자열 MRK → pymarc Field 변환기
# =============================================================
def mrk_str_to_field(line):
    if not line:
        return None

    s = line.strip()
    if not s.startswith("=") or len(s) < 6:
        return None

    # 컨트롤필드
    if re.match(r"^=\d{3}\s\s[^$]+$", s) and int(s[1:4]) < 10:
        tag = s[1:4]
        data = s[6:]
        return Field(tag=tag, data=data)

    # 데이터 필드
    m = re.match(r"^=(\d{3})\s{2}(.)(.)(.*)$", s)
    if not m:
        return None

    tag, ind1_raw, ind2_raw, tail = m.groups()
    ind1 = " " if ind1_raw == "\\" else ind1_raw
    ind2 = " " if ind2_raw == "\\" else ind2_raw

    subfields = []
    parts = re.split(r"(\$[a-zA-Z])", tail)
    cur_code = None
    buf = []

    for p in parts:
        if not p:
            continue
        if p.startswith("$") and len(p) == 2:
            if cur_code and buf:
                subfields.append(Subfield(cur_code, "".join(buf).strip()))
            cur_code = p[1]
            buf = []
        else:
            buf.append(p)

    if cur_code and buf:
        subfields.append(Subfield(cur_code, "".join(buf).strip()))

    return Field(tag=tag, indicators=[ind1, ind2], subfields=subfields)
# ============================================
# PART 8 — generate_all_oneclick / run_and_export / Streamlit UI
# ============================================


# ------------------------------------------------------
# 메인 엔진 — 단일 ISBN을 입력받아 MARC 전체 구성
# ------------------------------------------------------
def generate_all_oneclick(
    isbn: str,
    reg_mark: str = "",
    reg_no: str = "",
    copy_symbol: str = "",
    use_ai_940: bool = True,
):
    global CURRENT_DEBUG_LINES
    CURRENT_DEBUG_LINES = []

    record = Record(to_unicode=True, force_utf8=True)
    pieces = []

    # --------------------------
    # ① 저자 (NLK)
    # --------------------------
    author_raw, _ = fetch_nlk_author_only(isbn)

    # --------------------------
    # ② 알라딘 item
    # --------------------------
    item = aladin_lookup_by_api(isbn, ALADIN_TTB_KEY)
    if not item:
        item = aladin_lookup_by_web(isbn)

    if not item:
        st.error("❌ 알라딘에서 도서 정보를 불러올 수 없습니다.")
        return record, b"", "", {}

    # --------------------------
    # ③ 041 / 546 (GPT 기반 언어 감지)
    # --------------------------
    # 실제로는 너의 get_kormarc_tags()를 넣어도 되는데
    # 여기서는 간단한 구조로 유지
    tag_041_text = None
    tag_546_text = None
    original_title = (item.get("extra") or {}).get("originalTitle")

    # 최소 로직: 원제가 있으면 번역서 간주
    if original_title:
        lang_main = detect_language(item.get("title") or "")
        lang_orig = detect_language(original_title)
        tag_041_text = f"$a{lang_main}$h{lang_orig}"
        tag_546_text = generate_546_from_041_kormarc(tag_041_text)
    else:
        lang_main = detect_language(item.get("title") or "")
        tag_041_text = f"$a{lang_main}"
        tag_546_text = generate_546_from_041_kormarc(tag_041_text)

    # 041 필드 객체
    f_041 = mrk_str_to_field(_as_mrk_041(tag_041_text))
    if f_041:
        pieces.append((f_041, _as_mrk_041(tag_041_text)))

    # 546 필드 객체
    f_546 = mrk_str_to_field(_as_mrk_546(tag_546_text))
    if f_546:
        pieces.append((f_546, _as_mrk_546(tag_546_text)))

    # 원작 언어코드 (문학 8xx 재배치용)
    origin_lang = _parse_marc_041_original(tag_041_text)


    # --------------------------
    # ④ 245 / 246 / 700
    # --------------------------
    marc245 = build_245_with_people_from_sources(item, author_raw)
    f_245 = mrk_str_to_field(marc245)

    marc246 = build_246_from_aladin_item(item)
    f_246 = mrk_str_to_field(marc246)

    mrk_700 = build_700_people_pref_aladin(author_raw, item, origin_lang)

    # --------------------------
    # ⑤ 총서 (490 / 830)
    # --------------------------
    tag_490, tag_830 = build_490_830_mrk_from_item(item)
    f_490 = mrk_str_to_field(tag_490) if tag_490 else None
    f_830 = mrk_str_to_field(tag_830) if tag_830 else None

    # --------------------------
    # ⑥ 300 (형태사항 — 알라딘 상세 페이지)
    # --------------------------
    tag_300, f_300 = build_300_from_aladin_detail(item)

    # --------------------------
    # ⑦ 발행지(BUNDLE) + 260
    # --------------------------
    publisher_raw = item.get("publisher", "")
    pubdate       = item.get("pub_date", "")
    pubyear       = pubdate[:4] if len(pubdate) >= 4 else ""

    bundle = build_pub_location_bundle(isbn, publisher_raw)
    tag_260 = build_260(
        place_display=bundle.get("place_display"),
        publisher_name=publisher_raw,
        pubyear=pubyear,
    )
    f_260 = mrk_str_to_field(tag_260)

    # --------------------------
    # ⑧ 008
    # --------------------------
    data_008 = build_008_from_isbn(
        isbn,
        aladin_pubdate=pubdate,
        aladin_title=item.get("title"),
        aladin_category=item.get("category"),
        aladin_desc=item.get("description"),
        aladin_toc=item.get("toc"),
        override_country3=bundle.get("country_code"),
        override_lang3=_lang3_from_tag041(tag_041_text),
        cataloging_src="a",
    )
    f_008 = Field(tag="008", data=data_008)

    # --------------------------
    # ⑨ 007
    # --------------------------
    f_007 = Field(tag="007", data="ta")

    # --------------------------
    # ⑩ 020 / 950
    # --------------------------
    tag_020 = _build_020_from_item_and_nlk(isbn, item)
    f_020 = mrk_str_to_field(tag_020)

    tag_950 = build_950_from_item_and_price(item, isbn)
    f_950 = mrk_str_to_field(tag_950)

    # --------------------------
    # ⑪ 653 (GPT 1회 기반)
    # --------------------------
    tag_653 = _build_653_via_gpt(item)
    f_653 = mrk_str_to_field(tag_653) if tag_653 else None

    # --------------------------
    # ⑫ 056 (KDC, GPT)
    # --------------------------
    kw_hint = _parse_653_keywords(tag_653) if tag_653 else []
    kdc_code = get_kdc_from_isbn(
        isbn,
        ttbkey=ALADIN_TTB_KEY,
        openai_key=st.secrets["openai"]["api_key"],
        model="gpt-4o",
        keywords_hint=kw_hint,
    )
    tag_056 = f"=056  \\\\$a{kdc_code}$26" if kdc_code else None
    f_056 = mrk_str_to_field(tag_056)

    # --------------------------
    # ⑬ 940 (제목 기반)
    # --------------------------
    a_out, n = parse_245_a_n(marc245)
    mrk_940 = build_940_from_title_a(a_out, use_ai=use_ai_940, disable_number_reading=bool(n))

    # --------------------------
    # ⑭ 049 (등록기호)
    # --------------------------
    tag_049 = build_049(reg_mark, reg_no, copy_symbol)
    f_049 = mrk_str_to_field(tag_049) if tag_049 else None

    # ------------------------------------------------------
    # 조립 (순서 유지)
    # ------------------------------------------------------
    def add(field_obj, mrk_str):
        if field_obj and mrk_str:
            pieces.append((field_obj, mrk_str))

    add(f_008, f"=008  {data_008}")
    add(f_007, "=007  ta")
    add(f_020, tag_020)
    add(f_056, tag_056)
    add(f_245, marc245)
    add(f_246, marc246)
    add(f_260, tag_260)
    add(f_300, tag_300)
    add(f_490, tag_490)
    add(f_546, _as_mrk_546(tag_546_text))
    add(f_653, tag_653)

    # 700/90010/940
    for m in mrk_700:
        add(mrk_str_to_field(m), m)
    for m in mrk_940:
        add(mrk_str_to_field(m), m)
    add(f_830, tag_830)
    add(f_950, tag_950)
    add(f_049, tag_049)

    # ------------------------------------------------------
    # 최종 MRK 텍스트
    # ------------------------------------------------------
    mrk_strings = [m for _, m in pieces]
    mrk_text = "\n".join(mrk_strings)

    # MARC Record 객체 구성
    for f, _ in pieces:
        record.add_field(f)

    marc_bytes = record.as_marc()

    meta = {
        "041": tag_041_text,
        "546": tag_546_text,
        "056": tag_056,
        "653": tag_653,
        "kdc_code": kdc_code,
        "Publisher_raw": publisher_raw,
        "Place_display": bundle.get("place_display"),
        "CountryCode_008": bundle.get("country_code"),
        "debug_lines": CURRENT_DEBUG_LINES.copy(),
    }

    return record, marc_bytes, mrk_text, meta


# ------------------------------------------------------
# 저장 + Streamlit 표시
# ------------------------------------------------------
def save_marc_files(record: Record, save_dir: str, base_filename: str):
    import os
    os.makedirs(save_dir, exist_ok=True)

    mrc_path = os.path.join(save_dir, f"{base_filename}.mrc")
    mrk_path = os.path.join(save_dir, f"{base_filename}.mrk")

    # mrc
    with open(mrc_path, "wb") as f:
        f.write(record.as_marc())

    # mrk
    mrk_text = record_to_mrk_from_record(record)
    with open(mrk_path, "w", encoding="utf-8") as f:
        f.write(mrk_text)

    return mrc_path, mrk_path


# ------------------------------------------------------
# 실행 파이프라인
# ------------------------------------------------------
def run_and_export(
    isbn: str,
    *,
    reg_mark: str = "",
    reg_no: str = "",
    copy_symbol: str = "",
    use_ai_940: bool = True,
    save_dir: str = "./output",
    preview_in_streamlit: bool = True,
):
    record, marc_bytes, mrk_text, meta = generate_all_oneclick(
        isbn,
        reg_mark=reg_mark,
        reg_no=reg_no,
        copy_symbol=copy_symbol,
        use_ai_940=use_ai_940,
    )

    save_marc_files(record, save_dir, isbn)

    if preview_in_streamlit:
        st.success("📦 MRC/MRK 파일이 저장되었습니다.")
        with st.expander("MRK 미리보기", expanded=True):
            st.text_area("MRK", mrk_text, height=320)

        st.download_button(
            "📘 MARC (mrc) 다운로드",
            data=marc_bytes,
            file_name=f"{isbn}.mrc",
            mime="application/marc",
        )
        st.download_button(
            "🧾 MARC (mrk) 다운로드",
            data=mrk_text,
            file_name=f"{isbn}.mrk",
            mime="text/plain",
        )

    return record, marc_bytes, mrk_text, meta


# ============================================
# Streamlit UI
# ============================================

st.header("📚 ISBN → MARC 자동 생성기")

# Form
with st.form("isbn_form"):
    isbn_single = st.text_input("🔹 단일 ISBN 입력", placeholder="예: 9788937462849")
    csv_file = st.file_uploader(
        "📁 CSV 업로드 (열: ISBN, 등록기호, 등록번호, 별치기호)",
        type=["csv"]
    )
    submitted = st.form_submit_button("🚀 변환 실행")

if submitted:
    jobs = []

    if isbn_single.strip():
        jobs.append([isbn_single.strip(), "", "", ""])

    if csv_file:
        df = pd.read_csv(csv_file)
        need_cols = {"ISBN", "등록기호", "등록번호", "별치기호"}
        if not need_cols.issubset(df.columns):
            st.error("❌ CSV에 필요한 열이 없습니다.")
            st.stop()

        rows = df[["ISBN","등록기호","등록번호","별치기호"]].fillna("")
        for row in rows.itertuples(index=False):
            jobs.append(list(row))

    if not jobs:
        st.warning("변환할 데이터가 없습니다.")
        st.stop()

    st.write(f"총 {len(jobs)}건 처리 중…")
    prog = st.progress(0)

    results = []
    marc_all_texts = []

    for i, (isbn, mark, no, copy) in enumerate(jobs, start=1):
        record, mrc_bytes, mrk_text, meta = run_and_export(
            isbn,
            reg_mark=mark,
            reg_no=no,
            copy_symbol=copy,
            use_ai_940=True,
            save_dir="./output",
            preview_in_streamlit=True,
        )

        st.caption(f"ISBN {isbn} — 056={meta.get('kdc_code')}, 653={meta.get('653')}")
        marc_all_texts.append(mrk_text)
        results.append((record, isbn, mrk_text))

        prog.progress(i / len(jobs))

    st.download_button(
        "📦 전체 MRK 텍스트 다운로드",
        data="\n\n".join(marc_all_texts).encode("utf-8-sig"),
        file_name="marc_output_all.txt",
        mime="text/plain",
    )

    # 전체 MRC 하나로 묶기
    buf = io.BytesIO()
    writer = MARCWriter(buf)
    for record, isbn, _ in results:
        writer.write(record)
    buf.seek(0)

    st.download_button(
        "📥 전체 MRC 다운로드",
        data=buf,
        file_name="marc_output_all.mrc",
        mime="application/octet-stream",
    )
