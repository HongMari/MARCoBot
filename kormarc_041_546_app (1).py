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
from typing import Optional, Dict, Any
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
        if "nlk" in st.secrets and "cert_key" in st.secrets["nlk"]:
            return st.secrets["nlk"]["cert_key"]

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
# PART 2 — 008 생성기 / 지역·국가코드 / Detect 유틸
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

    if len(date_entered) != 6:
        raise ValueError("date_entered YYMMDD 오류")

    if len(date1) != 4:
        raise ValueError("date1(출판연도)은 4자리여야 합니다.")

    body = "".join([
        date_entered,
        pad(type_of_date,1),
        date1,
        pad(date2,4),
        pad(country3,3),
        pad(illus4,4),
        " " * 4,
        " " * 2,
        pad(modified_record,1),
        "0",
        "0",
        has_index if has_index in ("0","1") else "0",
        pad(cataloging_src,1),
        pad(lit_form,1),
        pad(bio,1),
        pad(lang3,3),
        " " * 2
    ])

    if len(body) != 40:
        raise AssertionError(f"008 length mismatch: {len(body)}")

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



# =====================================================
# 삽화/도표/사진 감지
# =====================================================
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


# =====================================================
# 색인 감지
# =====================================================
def detect_index(text: str) -> str:
    return "1" if re.search(r"색인|찾아보기|index", text, re.I) else "0"


# =====================================================
# 문학 형태 감지
# =====================================================
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


# =====================================================
# 전기 요소 감지
# =====================================================
def detect_bio(text: str) -> str:
    if re.search(r"자서전|회고록|autobiograph", text, re.I):
        return "a"
    if re.search(r"전기|평전|biograph", text, re.I):
        return "b"
    if re.search(r"전기적|자전적|회고", text, re.I):
        return "d"
    return " "


# =====================================================
# 발행지 미상 판단
# =====================================================
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
# 최종: ISBN 기반 008 필드 구성
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

    # ---------- country3 ----------
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
# 알라딘 ItemLookUp (API) — Safe Patch + 캐싱
# ------------------------------------------------------
@st.cache_data(ttl=3600)
def aladin_lookup_by_api(isbn13: str, ttbkey: str) -> "BookInfo | None":
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

        # BookInfo dataclass에 맞게 반환
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
# 알라딘 웹 스크레이핑 (백업) — Safe Patch + 캐싱
# ------------------------------------------------------
@st.cache_data(ttl=3600)
def aladin_lookup_by_web(isbn13: str) -> "BookInfo | None":
    try:
        params = {"SearchTarget": "Book", "SearchWord": f"isbn:{isbn13}"}
        sr = requests.get(ALADIN_SEARCH_URL, params=params, headers=HEADERS, timeout=15)
        sr.raise_for_status()
        soup = BeautifulSoup(sr.text, "html.parser")

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

        author, publisher, pub_date, category = "", "", "", ""
        info_box = psoup.select_one("#Ere_prod_allwrap")

        if info_box:
            text = clean_text(info_box.get_text(" "))
            ma = re.search(r"(저자|지은이)\s*:\s*([^\|·/]+)", text)
            mp = re.search(r"(출판사)\s*:\s*([^\|·/]+)", text)
            md = re.search(r"(출간일)\s*:\s*[0-9]{4}\.[0-9]{1,2}\.[0-9]{1,2}", text)

            if ma: author = clean_text(ma.group(2))
            if mp: publisher = clean_text(mp.group(2))
            if md: pub_date = clean_text(md.group(0))

        crumbs = psoup.select(".location, .path, .breadcrumb")
        if crumbs:
            category = clean_text(" > ".join(c.get_text(" ") for c in crumbs))

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
# 기본 텍스트 기반 1차 언어 감지 — Safe Patch
# (빈 문자열 / 특수문자 처리 안정화)
# ------------------------------------------------------
def detect_language(text):
    if not text:
        return 'und'

    text = re.sub(r'[\s\W_]+', '', text or "")
    if not text:
        return 'und'
    
    ch = text[0]

    # 한글
    if '\uac00' <= ch <= '\ud7a3':
        return 'kor'
    # 일본어 히라가나/가타카나
    if '\u3040' <= ch <= '\u30ff':
        return 'jpn'
    # 중국 한자
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
# 최종 546 생성기 — Safe Patch
# ------------------------------------------------------
def generate_546_from_041_kormarc(marc_041: str) -> str:
    """
    041의 $a, $h 분석해서 자연어 문장 생성
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
# 041 문자열에서 $a → 언어코드 추출
# ------------------------------------------------------
def _lang3_from_tag041(tag_041: str | None) -> str | None:
    if not tag_041:
        return None
    m = re.search(r"\$a([a-z]{3})", tag_041, flags=re.I)
    return m.group(1).lower() if m else None


# ------------------------------------------------------
# 041 원작언어($h) 파싱 (문학 8xx 후처리에 사용)
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

    if l == "kor": return "810"
    if l in ("chi","zho"): return "820"
    if l == "jpn": return "830"
    if l == "eng": return "840"
    if l in ("ger","deu"): return "850"
    if l in ("fre","fra"): return "860"
    if l in ("spa","por"): return "870"
    if l == "ita": return "880"
    return "890"


def _rebase_8xx_with_language(code: str, marc041: str) -> str:
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
    genre = head3[2]

    new_head = base[:2] + genre
    return new_head + tail


# ------------------------------------------------------
# =041 / =546 MRK 변환기 (Safe Patch)
# ------------------------------------------------------
def _as_mrk_041(s: str | None) -> str:
    if not s:
        return None
    return s if s.startswith("=041") else f"=041  \\\\{s}"

def _as_mrk_546(s: str | None) -> str:
    if not s:
        return None
    return s if s.startswith("=546") else f"=546  \\\\{s}"



# ============================================
# PART 5 — GPT 기반 653 생성기 + 금칙어 필터링 (Safe Patch)
# ============================================

import openai

def _call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 256):
    """
    GPT 호출 — Safe Patch
    - 예외 발생 시 None
    - prompt 안전성 개선
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
# 금칙어 정의
# ---------------------------------------
FORBIDDEN_WORDS = {
    "책", "도서", "소설", "작품", "저자", "출판", "출판사",
    "이야기", "내용", "문학", "문학작품", "대상", "독자",
    "장편소설", "단편소설", "글", "산문", "브랜드",
    "시리즈", "총서", "권", "편", "chapter", "index",
}


# ---------------------------------------
# 키워드 정규화 (Safe Patch)
# ---------------------------------------
def _normalize_keyword(k: str):
    if not k:
        return ""
    k = k.strip().lower()
    k = re.sub(r"[^0-9a-z가-힣·\- ]+", "", k)
    return k


# ---------------------------------------
# GPT 반환 키워드 → 리스트
# ---------------------------------------
def _extract_keywords_from_gpt(raw: str) -> list[str]:
    if not raw:
        return []

    tokens = re.split(r"[,;\n]|·|\t|\|", raw)
    out = []

    for t in tokens:
        t = _normalize_keyword(t)
        if len(t) < 2:
            continue
        if t in FORBIDDEN_WORDS:
            continue
        out.append(t)

    uniq = []
    for x in out:
        if x not in uniq:
            uniq.append(x)

    return uniq[:7]


# ---------------------------------------
# GPT → 653 MRK 변환
# ---------------------------------------
def _keywords_to_653_mrk(keywords: list[str]):
    if not keywords:
        return None

    parts = [f"$a{w}" for w in keywords]
    return "=653  \\\\" + "".join(parts)


# ---------------------------------------
# 653 자동 생성기 (GPT)
# ---------------------------------------
def _build_653_via_gpt(item):
    if not item:
        return None

    # BookInfo dataclass로 안전하게 접근
    title = item.title or ""
    desc  = item.description or ""
    cate  = item.category or ""
    toc   = item.toc or ""

    text_blob = (
        f"제목: {title}\n"
        f"카테고리: {cate}\n"
        f"내용요약: {desc[:800]}\n"
        f"목차: {toc[:500]}"
    )

    sys_prompt = (
        "너는 대한민국 공공도서관의 주제전문 사서다.\n"
        "입력된 도서정보를 분석해 KORMARC 653$a에 넣을 **구체적·실질적** 주제 키워드 3~6개만 산출하라.\n"
        "출력은 쉼표 구분 (예: 인공지능, 기계학습, 데이터과학)."
    )

    raw = _call_llm(sys_prompt, text_blob, max_tokens=80)
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
# KDC 분류 입력 Payload 구성 — Safe Patch
# ------------------------------------------------------
def _build_kdc_payload(info, keywords_hint):
    return {
        "title": info.title or "",
        "author": info.author or "",
        "publisher": info.publisher or "",
        "category": info.category or "",
        "description": info.description or "",
        "toc": clean_text(info.toc or ""),
        "keywords_hint": keywords_hint or [],
    }


# ------------------------------------------------------
# GPT 시스템 프롬프트 (KDC 전문가 모드)
# ------------------------------------------------------
KDC_SYSTEM_PROMPT = """
너는 대한민국 공공도서관 분류전문 사서이며, KDC 제6판 규칙을 엄격히 준수한다.

임무:
1) 제공된 도서정보(title, author, category, description, toc, keywords_hint)를 분석해
2) 가장 적합한 **KDC 3자리 정수 1개**만 산출한다 (예: 370, 004, 823)
3) 판단이 어려우면 '직접분류추천'만 출력한다.

출력 형식:
- 불필요한 설명 없이 **정수 3자리 또는 직접분류추천**만 출력.
"""


# ------------------------------------------------------
# GPT 기반 KDC 코드 생성기 — Safe Patch
# ------------------------------------------------------
def ask_llm_for_kdc(info: 'BookInfo', api_key: str, model: str, keywords_hint=None):
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
# ISBN 기반 전체 KDC 처리 파이프라인 — Safe Patch
# ------------------------------------------------------
def get_kdc_from_isbn(isbn13: str, ttbkey: str, openai_key: str, model: str,
                      keywords_hint: list[str] | None = None) -> str | None:

    # ① 알라딘 기본 정보 확보
    info = aladin_lookup_by_api(isbn13, ttbkey) if ttbkey else None
    if not info:
        info = aladin_lookup_by_web(isbn13)

    if not info:
        st.warning("❌ 알라딘에서 도서 정보 조회 실패")
        return None

    # ② GPT 호출
    code = ask_llm_for_kdc(info, api_key=openai_key, model=model, keywords_hint=keywords_hint)

    if not code:
        return None

    if code == "직접분류추천":
        return "직접분류추천"

    # 숫자 여부 검증
    if re.fullmatch(r"\d{1,3}", code):
        return code.zfill(3)

    return None
# ============================================
# PART 7 — MARC 빌더 (300 / 020 / 245 / 246 / 700 / 490 / 830 / 940 / 950 / 049 …)
# ============================================

# =============================================================
# BookInfo Dataclass (최종 정상 정의본)
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
# 300 필드 — 알라딘 상세페이지 기반 형사항 파싱
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

    combined = " ".join([title_text, subtitle_text, description])
    has_illus, illus_label = detect_illustrations(combined)
    if has_illus:
        b_part = illus_label

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

    subfields = []
    if a_part: subfields.append(Subfield("a", a_part))
    if b_part: subfields.append(Subfield("b", b_part))
    if c_part: subfields.append(Subfield("c", c_part))

    return {
        "300": mrk,
        "300_subfields": subfields,
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


def build_300_from_aladin_detail(item: dict | BookInfo):
    """ item.extra.get("link") 기반 """
    try:
        extra = item.extra if isinstance(item, BookInfo) else (item.get("extra") or {})
        link = extra.get("link", "")
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
# 총서 490 / 830
# =============================================================
def build_490_830_mrk_from_item(item):
    si = None
    if isinstance(item, BookInfo):
        si = item.extra.get("seriesInfo") if item.extra else None
        if si is None:
            si = item.extra.get("subInfo", {}).get("seriesInfo") if item.extra else None
    else:
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
# 가격 / ISBN → 020
# =============================================================
def _extract_price_kr(item, isbn):
    price = 0
    try:
        extra = item.extra if isinstance(item,BookInfo) else (item.get("extra") or {})
        if "priceStandard" in extra:
            price = int(extra["priceStandard"])
        elif "priceSales" in extra:
            price = int(extra["priceSales"])
    except:
        pass
    return price


def _build_020_from_item_and_nlk(isbn, item):
    price = _extract_price_kr(item, isbn)
    if price:
        return f"=020  \\\\$a{isbn} :$c{price}"
    return f"=020  \\\\$a{isbn}"


# =============================================================
# 950 (가격)
# =============================================================
def build_950_from_item_and_price(item, isbn):
    price = _extract_price_kr(item, isbn)
    if price:
        return f"=950  \\\\$a{price}"
    return "=950  \\\\$a미상"



# =============================================================
# 245 서명 (책제목·부제·책임표시)
# =============================================================
def build_245_with_people_from_sources(item, nlk_author_raw, prefer="aladin"):
    title = clean_text(item.title)
    subtitle = ""
    if isinstance(item, BookInfo):
        if item.extra and "subInfo" in item.extra:
            subtitle = clean_text(item.extra.get("subInfo", {}).get("subTitle") or "")
    else:
        subtitle = clean_text((item.get("subInfo") or {}).get("subTitle") or "")

    author  = clean_text(item.author)
    year    = clean_text(item.pub_date)[:4]

    c_part = author
    if year:
        c_part += f" ({year})"

    out = "=245  00"

    if subtitle:
        out += f"$a{title} :$b{subtitle}"
    else:
        out += f"$a{title}"

    if c_part:
        out += f" /$c{c_part}"

    return out



# =============================================================
# 246 — 원제(대등서명)
# =============================================================
def build_246_from_aladin_item(item):
    orig = None
    if isinstance(item, BookInfo):
        orig = (item.extra or {}).get("originalTitle")
    else:
        orig = (item.get("extra") or {}).get("originalTitle")

    if not orig:
        return ""
    orig = clean_text(orig)

    return f"=246  31$a{orig}"



# =============================================================
# 700 — 인명 접근점
# =============================================================
def build_700_people_pref_aladin(nlk_author_raw, item, origin_lang_code=None):
    authors = clean_text(nlk_author_raw or item.author or "")
    if not authors:
        return []

    tokens = re.split(r",|;|/|·|\s", authors)
    tokens = [t.strip() for t in tokens if t.strip()]

    out = []
    for t in tokens:
        if not t:
            continue

        if origin_lang_code in ("eng", "fre", "ger", "spa", "rus", "ita"):
            parts = t.split()
            if len(parts) >= 2:
                lname = parts[-1]
                fname = " ".join(parts[:-1])
                name_form = f"{lname}, {fname}"
            else:
                name_form = t
        else:
            name_form = t

        out.append(f"=700  1\\$a{name_form}")

    return out



# =============================================================
# 940 — 제목 기반 분류기
# =============================================================
def parse_245_a_n(marc245: str):
    if not marc245:
        return "", None
    m = re.search(r"\$a([^$]+)", marc245)
    a = clean_text(m.group(1)) if m else ""
    n = re.search(r"\b(\d+)\b", a)
    return a, (n.group(1) if n else None)


def build_940_from_title_a(title_a: str, use_ai=True, disable_number_reading=False):
    if disable_number_reading:
        title_clean = re.sub(r"\d+", "", title_a)
    else:
        title_clean = title_a

    if not title_clean:
        return []

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
# MRK 문자열 → pymarc Field 변환기
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
# 메인 엔진 — 단일 ISBN 기반 전체 MARC 생성
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
    # ③ 041 / 546
    # --------------------------
    original_title = item.extra.get("originalTitle") if item.extra else ""
    lang_main = detect_language(item.title)
    lang_orig = detect_language(original_title) if original_title else None

    if original_title:
        tag_041_text = f"$a{lang_main}$h{lang_orig}"
    else:
        tag_041_text = f"$a{lang_main}"

    tag_546_text = generate_546_from_041_kormarc(tag_041_text)

    f_041 = mrk_str_to_field(_as_mrk_041(tag_041_text))
    f_546 = mrk_str_to_field(_as_mrk_546(tag_546_text))

    if f_041:
        pieces.append((f_041, _as_mrk_041(tag_041_text)))
    if f_546:
        pieces.append((f_546, _as_mrk_546(tag_546_text)))

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
    # ⑥ 300
    # --------------------------
    tag_300, f_300 = build_300_from_aladin_detail(item)

    # --------------------------
    # ⑦ 발행지 + 260
    # --------------------------
    publisher_raw = item.publisher or ""
    pubdate       = item.pub_date or ""
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
        aladin_title=item.title,
        aladin_category=item.category,
        aladin_desc=item.description,
        aladin_toc=item.toc,
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
    # ⑪ 653 (GPT)
    # --------------------------
    tag_653 = _build_653_via_gpt(item)
    f_653 = mrk_str_to_field(tag_653) if tag_653 else None

    # --------------------------
    # ⑫ 056 (GPT-KDC)
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
    # ⑬ 940
    # --------------------------
    a_out, n = parse_245_a_n(marc245)
    mrk_940 = build_940_from_title_a(a_out, use_ai=use_ai_940, disable_number_reading=bool(n))

    # --------------------------
    # ⑭ 049
    # --------------------------
    tag_049 = build_049(reg_mark, reg_no, copy_symbol)
    f_049 = mrk_str_to_field(tag_049) if tag_049 else None

    # ------------------------------------------------------
    # 조립
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

    # 700/940/830/950/049
    for m in mrk_700:
        add(mrk_str_to_field(m), m)
    for m in mrk_940:
        add(mrk_str_to_field(m), m)
    add(f_830, tag_830)
    add(f_950, tag_950)
    add(f_049, tag_049)

    # ------------------------------------------------------
    # MRK 텍스트
    # ------------------------------------------------------
    mrk_strings = [m for _, m in pieces]
    mrk_text = "\n".join(mrk_strings)

    # pymarc record 조립
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
# run_and_export (파일 저장 + Streamlit 미리보기)
# ------------------------------------------------------
def save_marc_files(record: Record, save_dir: str, base_filename: str):
    import os
    os.makedirs(save_dir, exist_ok=True)

    mrc_path = os.path.join(save_dir, f"{base_filename}.mrc")
    mrk_path = os.path.join(save_dir, f"{base_filename}.mrk")

    with open(mrc_path, "wb") as f:
        f.write(record.as_marc())

    mrk_text = record_to_mrk_from_record(record)
    with open(mrk_path, "w", encoding="utf-8") as f:
        f.write(mrk_text)

    return mrc_path, mrk_path



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

st.header("📚 ISBN → MARC 자동 생성기 (Safe Patch Version)")

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

    # 전체 MRC 묶음
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
