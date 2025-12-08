# ============================================================
# PART 1 — Imports / Globals / Utility / Config
# ============================================================

import re
import io
import os
import json
import html
import math
import time
import uuid
import urllib.parse
import datetime
from dataclasses import dataclass
from collections import Counter
from typing import Any, Dict, Optional

import requests
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup

from pymarc import Record, Field, Subfield, MARCWriter

# ---------------------------
# Streamlit global settings
# ---------------------------
st.set_page_config(page_title="KORMARC 자동 생성기", layout="wide")

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

OPENAI_CHAT_COMPLETIONS = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"

# ---------------------------
# Debug message buffer
# ---------------------------
CURRENT_DEBUG_LINES = []
def dbg(*msg):
    CURRENT_DEBUG_LINES.append(" ".join(str(x) for x in msg))

def dbg_err(*msg):
    CURRENT_DEBUG_LINES.append("[ERROR] " + " ".join(str(x) for x in msg))


# ============================================================
# Part 1-2 — Normalization Helpers
# ============================================================

def normalize_text(s: str) -> str:
    """Remove HTML, whitespace, and unify text cleanly."""
    if not s:
        return ""
    s = html.unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


# KORMARC Region → Code Mapping
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

COUNTRY_FIXED = "ulk"
LANG_FIXED = "kor"


# ============================================================
# Part 1-3 — 008 Builder (from original code)
# ============================================================

def _pad(s: str, n: int, fill=" "):
    s = "" if s is None else str(s)
    return (s[:n] + fill * n)[:n]


def extract_year_from_aladin_pubdate(pubdate_str: str) -> str:
    m = re.search(r"(19|20)\d{2}", pubdate_str or "")
    return m.group(0) if m else "19uu"


def guess_country3_from_place(place_str: str) -> str:
    if not place_str:
        return COUNTRY_FIXED
    for key, code in KR_REGION_TO_CODE.items():
        if key in place_str:
            return code
    return COUNTRY_FIXED


def detect_illus4(text: str) -> str:
    keys = []
    if re.search(r"삽화|삽도|일러스트|그림|illustration", text, re.I):
        keys.append("a")
    if re.search(r"도표|표|차트|그래프|chart|graph", text, re.I):
        keys.append("d")
    if re.search(r"사진|포토|화보|photo|photograph", text, re.I):
        keys.append("o")

    out = []
    for k in keys:
        if k not in out:
            out.append(k)
    return "".join(out)[:4]


def detect_index(text: str) -> str:
    return "1" if re.search(r"색인|찾아보기|index", text, re.I) else "0"


def detect_lit_form(title: str, category: str, extra: str = "") -> str:
    blob = f"{title} {category} {extra}"
    if re.search(r"서간집|편지|letters?", blob, re.I):
        return "i"
    if re.search(r"기행|여행기|수기|일기|travel|diary", blob, re.I):
        return "m"
    if re.search(r"시집|poem|poetry", blob, re.I):
        return "p"
    if re.search(r"소설|novel|fiction", blob, re.I):
        return "f"
    if re.search(r"에세이|수필|essay", blob, re.I):
        return "e"
    return " "


def detect_bio(text: str) -> str:
    if re.search(r"자서전|회고록|autobiograph", text, re.I):
        return "a"
    if re.search(r"전기|평전|biograph", text, re.I):
        return "b"
    if re.search(r"전기적|자전적|회고|회상", text, re.I):
        return "d"
    return " "


def build_008_kormarc_bk(
        date_entered,
        date1,
        country3,
        lang3,
        date2="",
        illus4="",
        has_index="0",
        lit_form=" ",
        bio=" ",
        type_of_date="s",
        modified_record=" ",
        cataloging_src="a",
):
    if len(date_entered) != 6:
        raise ValueError("date_entered must be YYMMDD")
    if len(date1) != 4:
        raise ValueError("date1 must be 4 chars")

    body = "".join([
        date_entered,
        _pad(type_of_date, 1),
        date1,
        _pad(date2, 4),
        _pad(country3, 3),
        _pad(illus4, 4),
        " " * 4,
        " " * 2,
        _pad(modified_record, 1),
        "0",
        "0",
        has_index,
        _pad(cataloging_src, 1),
        _pad(lit_form, 1),
        _pad(bio, 1),
        _pad(lang3, 3),
        " " * 2,
    ])
    return body


def build_008_from_isbn(
        isbn,
        *,
        aladin_pubdate="",
        aladin_title="",
        aladin_category="",
        aladin_desc="",
        aladin_toc="",
        source_300_place="",
        override_country3=None,
        override_lang3=None,
        cataloging_src="a",
):
    today = datetime.datetime.now().strftime("%y%m%d")
    date1 = extract_year_from_aladin_pubdate(aladin_pubdate)

    if override_country3:
        country3 = override_country3
    elif source_300_place:
        country3 = guess_country3_from_place(source_300_place)
    else:
        country3 = COUNTRY_FIXED

    lang3 = override_lang3 or LANG_FIXED

    bigtext = " ".join([aladin_title, aladin_desc, aladin_toc])
    illus4 = detect_illus4(bigtext)
    has_index = detect_index(bigtext)
    lit_form = detect_lit_form(aladin_title, aladin_category, bigtext)
    bio = detect_bio(bigtext)

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
# ============================================================
# PART 2 — GPT Master: 041 / 546 / Original Title 생성 (1회 호출)
# ============================================================

def call_gpt_master_for_lang_and_original(
    title: str,
    description: str,
    toc: str,
    isbn: str,
    model="gpt-4o"
):
    """
    GPT 1회 호출로 다음 3가지를 동시에 생성:
      - 041 KORMARC 서브필드 ($a 본문언어 / $h 원작언어)
      - 546 주기문
      - originalTitle (원제)
    """
    system_prompt = (
        "너는 KORMARC 041/546 전문가이다. "
        "주어진 도서 정보(title, description, toc)를 바탕으로 "
        "① 본문 언어(iso-639-2) ② 원작 언어(있을 시) "
        "③ 원제(original title)를 판단하고, "
        "아래 JSON 형식으로만 출력하라.\n\n"
        "반드시 다음 key만 포함된 JSON으로 출력:\n"
        "{\n"
        '  "041": "$akor" 또는 "$akor$heng" 같은 형태,\n'
        '  "546": "한국어로 씀" 또는 "영어 원작을 한국어로 번역",\n'
        '  "originalTitle": "원제가 없으면 빈 문자열"\n'
        "}\n"
    )

    user_prompt = {
        "title": title,
        "description": description,
        "toc": toc,
        "isbn": isbn
    }

    try:
        rsp = requests.post(
            OPENAI_CHAT_COMPLETIONS,
            headers={
                "Authorization": f"Bearer {st.secrets['openai']['api_key']}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)}
                ],
                "temperature": 0.0,
            },
            timeout=40,
        )
        rsp.raise_for_status()
        txt = rsp.json()["choices"][0]["message"]["content"].strip()
        result = json.loads(txt)
        return result
    except Exception as e:
        dbg_err(f"[GPT-MASTER ERROR] {e}")
        return {
            "041": "",
            "546": "",
            "originalTitle": ""
        }


# ============================================================
# PART 2-2 — 041/546 마무리 빌더
# ============================================================

def _as_mrk_041(plain: str) -> str:
    """
    GPT 결과에서 건네받은 "041": "$akor$heng" 같은 문자열을
    MRK 표기 "=041  0\$akor$heng" 으로 변환
    """
    if not plain:
        return ""
    return f"=041  0\\{plain}"


def _as_mrk_546(plain: str) -> str:
    if not plain:
        return ""
    return f"=546  \\\\$a{plain}"


# ============================================================
# PART 2-3 — 최종 호출 함수: get_kormarc_tags()
#   → generate_all_oneclick() 내부에서 이 함수만 부르면 됨
# ============================================================

def get_kormarc_tags(isbn: str):
    """
    ISBN으로 알라딘 메타 불러온 뒤,
    GPT-1회 호출로 041 / 546 / originalTitle 생성.
    반환값: (041_mrk_str, 546_mrk_str, original_title_str)
    """
    # --- 알라딘에서 제목/설명/목차 불러오기 ---
    item = fetch_aladin_item(isbn)
    if not item:
        dbg_err(f"[get_kormarc_tags] 알라딘 item 없음: {isbn}")
        return None, None, ""

    title = item.get("title", "") or ""
    desc = item.get("description", "") or ""
    toc  = ((item.get("subInfo") or {}).get("toc")) or ""

    # --- GPT Master 호출 ---
    out = call_gpt_master_for_lang_and_original(
        title=title,
        description=desc,
        toc=toc,
        isbn=isbn,
        model="gpt-4o",    # ★ 요청대로 gpt-4o 강제 적용
    )

    raw_041 = out.get("041") or ""
    raw_546 = out.get("546") or ""
    original = out.get("originalTitle") or ""

    # MRK 변환
    mrk041 = _as_mrk_041(raw_041) if raw_041 else None
    mrk546 = _as_mrk_546(raw_546) if raw_546 else None

    return mrk041, mrk546, original


# ============================================================
# PART 2-4 — 알라딘 item wrapper (fetch_aladin_item)
# ============================================================

def fetch_aladin_item(isbn: str):
    """
    기존 코드에 흩어져 있던 알라딘 ItemLookUp 호출을 통합.
    description, toc 포함한 완전한 item dict 리턴.
    """
    try:
        ttb = st.secrets["aladin"]["ttbkey"]
    except Exception:
        dbg_err("알라딘 TTB key 없음")
        return None

    url = "https://www.aladin.co.kr/ttb/api/ItemLookUp.aspx"
    params = {
        "ttbkey": ttb,
        "itemIdType": "ISBN",
        "ItemId": isbn,
        "output": "js",
        "Version": "20131101",
        "OptResult": "subInfo,authors,categoryName,fulldescription,toc"
    }
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        js = r.json()
        item = (js.get("item") or [{}])[0]
        return item
    except Exception as e:
        dbg_err(f"[fetch_aladin_item error] {e}")
        return None
# ============================================================
# PART 3 — 020 / 653 / 490 / 830 / 300
# ============================================================

# -----------------------------
# 020 Builder (가격 + 부가기호)
# -----------------------------
def fetch_additional_code_from_nlk(isbn: str) -> dict:
    """
    국립중앙도서관 SearchApi에서 부가기호(EA_ADD_CODE), SET_ISBN, 가격(PRE_PRICE)
    """
    endpoints = [
        "https://seoji.nl.go.kr/landingPage/SearchApi.do",
        "https://www.nl.go.kr/seoji/SearchApi.do",
    ]

    params = {
        "cert_key": st.secrets["nlk"]["cert_key"],
        "result_style": "json",
        "page_no": 1,
        "page_size": 1,
        "isbn": isbn.replace("-", "").strip(),
    }

    for url in endpoints:
        try:
            r = requests.get(url, params=params, timeout=12)
            r.raise_for_status()
            js = r.json()
            docs = js.get("docs") or js.get("doc") or []
            if not docs:
                continue
            d = docs[0]
            return {
                "add_code": (d.get("EA_ADD_CODE") or "").strip(),
                "set_isbn": (d.get("SET_ISBN") or "").strip(),
                "price": (d.get("PRE_PRICE") or "").strip(),
            }
        except Exception:
            continue

    return {"add_code": "", "set_isbn": "", "price": ""}


def _extract_price_kr(item: dict, isbn: str) -> str:
    """
    가격 추출 우선순위:
    1) 알라딘 priceStandard
    2) NLK PRE_PRICE
    3) 알라딘 상세페이지 크롤링 가격
    """
    raw = str((item or {}).get("priceStandard", "") or "").strip()
    if raw:
        return re.sub(r"[^\d]", "", raw)

    try:
        nlk = fetch_additional_code_from_nlk(isbn)
        if nlk and nlk.get("price"):
            return re.sub(r"[^\d]", "", nlk["price"])
    except:
        pass

    # fallback: 알라딘 상세 페이지 가격 크롤링
    try:
        url = f"https://www.aladin.co.kr/shop/wproduct.aspx?ISBN={isbn}"
        r = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        price = soup.select_one("span.price2")
        if price:
            t = price.text.strip().replace("정가 :", "").replace("원", "")
            return re.sub(r"[^\d]", "", t)
    except:
        pass

    return ""


def _build_020_from_item_and_nlk(isbn: str, item: dict) -> str:
    nlk = fetch_additional_code_from_nlk(isbn)
    add_code = nlk.get("add_code", "")
    price = _extract_price_kr(item, isbn)

    out = f"=020  \\\\$a{isbn}"
    if add_code:
        out += f"$g{add_code}"
    if price:
        out += f":$c{price}"
    return out


# ============================================================
# PART 3-2 — GPT 기반 653 생성기
# ============================================================

def _clean_author_str(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[·/,;]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _norm(text: str) -> str:
    if not text:
        return ""
    import unicodedata
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\s\uac00-\ud7a3]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _build_forbidden_set(title: str, authors: str) -> set:
    t_norm = _norm(title)
    a_norm = _norm(authors)

    forb = set()
    if t_norm:
        forb.update(t_norm.split())
        forb.add(t_norm.replace(" ", ""))
    if a_norm:
        forb.update(a_norm.split())
        forb.add(a_norm.replace(" ", ""))
    return {x for x in forb if len(x) >= 2}


def _should_keep_keyword(kw: str, forbidden: set) -> bool:
    n = _norm(kw)
    if not n or len(n.replace(" ", "")) < 2:
        return False
    for f in forbidden:
        if n in f or f in n:
            return False
    return True


def generate_653_with_gpt(category, title, authors, desc, toc, max_keywords=7):
    system = (
        "너는 MARC 653 전문가이다. 모든 키워드는 '붙여쓰기 명사'로만 생성하라.\n"
        "출력 형식은 반드시: $a키워드1 $a키워드2 ...\n"
        "금지: 제목/저자/출판사명, 너무 일반적인 단어(연구, 방법, 사례, 의미 등), "
        "구체적 주제가 아닌 메타표현.\n"
    )

    user = (
        f"분류: {category}\n"
        f"제목: {title}\n"
        f"저자: {authors}\n"
        f"설명: {desc}\n"
        f"목차: {toc}\n"
        f"최대 {max_keywords}개 키워드 생성."
    )

    try:
        rsp = requests.post(
            OPENAI_CHAT_COMPLETIONS,
            headers={
                "Authorization": f"Bearer {st.secrets['openai']['api_key']}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                "temperature": 0.2,
                "max_tokens": 200,
            },
            timeout=40,
        )
        rsp.raise_for_status()
        raw = rsp.json()["choices"][0]["message"]["content"].strip()

        # $a 키워드 분리
        kws = re.findall(r"\$a([^$]+)", raw)
        kws = [k.strip().replace(" ", "") for k in kws if k.strip()]

        forb = _build_forbidden_set(title, authors)
        kws = [k for k in kws if _should_keep_keyword(k, forb)]

        # 중복 제거 + 최대 7개
        out = []
        seen = set()
        for w in kws:
            if w not in seen:
                seen.add(w)
                out.append(w)
            if len(out) >= max_keywords:
                break

        return "=653  \\\\" + "".join(f"$a{x}" for x in out)

    except Exception as e:
        dbg_err(f"[653 GPT ERROR] {e}")
        return None


def _parse_653_keywords(tag_653: str | None) -> list:
    if not tag_653:
        return []
    s = re.sub(r"^=653\s+\\\\", "", tag_653.strip())
    kws = re.findall(r"\$a([^$]+)", s)
    return [k.strip() for k in kws if k.strip()][:7]


# ============================================================
# PART 3-3 — 490 + 830 (총서)
# ============================================================

def build_490_830_mrk_from_item(item):
    si = None
    if isinstance(item, dict):
        si = item.get("seriesInfo") or (item.get("subInfo") or {}).get("seriesInfo")

    if isinstance(si, list):
        cand = si
    elif isinstance(si, dict):
        cand = [si]
    else:
        cand = []

    series_name, vol = "", ""
    for ent in cand:
        if not isinstance(ent, dict):
            continue
        name = (ent.get("seriesName") or ent.get("name") or "").strip()
        v = (ent.get("volume") or ent.get("vol") or "").strip()
        if name:
            series_name, vol = name, v
            break

    if not series_name:
        return "", ""

    disp = f"{series_name} {vol}".strip()
    tag_490 = f"=490  10$a{disp}"
    tag_830 = f"=830  \\0$a{disp}"
    return tag_490, tag_830


# ============================================================
# PART 3-4 — 300 형태사항 생성기
# ============================================================

def detect_illustrations(text: str):
    if not text:
        return False, None

    groups = {
        "삽화": ["삽화", "일러스트", "illustration", "그림"],
        "사진": ["사진", "photo", "포토", "화보"],
        "도표": ["도표", "차트", "그래프"],
    }

    found = []
    for label, keys in groups.items():
        if any(k in text for k in keys):
            found.append(label)

    if found:
        return True, ", ".join(found)
    return False, None


def parse_aladin_physical_book_info(html):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one("span.Ere_bo_title")
    sub = soup.select_one("span.Ere_sub1_title")
    desc = soup.select_one("div.Ere_prod_mconts_R")

    t = title.get_text(strip=True) if title else ""
    t2 = sub.get_text(strip=True) if sub else ""
    d = desc.get_text(" ", strip=True) if desc else ""

    combined = " ".join([t, t2, d])

    form = soup.select_one("div.conts_info_list1")
    a_part = ""
    b_part = ""
    c_part = ""

    page_value = None
    size_value = None

    if form:
        items = [x.strip() for x in form.stripped_strings]
        for it in items:
            if re.search(r"(쪽|p)\s*$", it):
                m = re.search(r"\d+", it)
                if m:
                    page_value = int(m.group())
                    a_part = f"{m.group()} p."
            if "mm" in it:
                m = re.search(r"(\d+)\s*[xX]\s*(\d+)", it)
                if m:
                    w, h = int(m.group(1)), int(m.group(2))
                    size_value = f"{w}x{h}mm"
                    c_part = f"{math.ceil(h/10)} cm"

    illus, label = detect_illustrations(combined)
    if illus:
        b_part = label

    subfields = []
    mrk_parts = []

    if a_part:
        chunk = f"$a{a_part}"
        if b_part:
            chunk += f" :$b{b_part}"
        mrk_parts.append(chunk)
        subfields.append(Subfield("a", a_part))
        if b_part:
            subfields.append(Subfield("b", b_part))
    elif b_part:
        mrk_parts.append(f"$b{b_part}")
        subfields.append(Subfield("b", b_part))

    if c_part:
        mrk_parts.append(f"; $c {c_part}")
        subfields.append(Subfield("c", c_part))

    if not mrk_parts:
        mrk_parts = ["$a1책."]
        subfields = [Subfield("a", "1책.")]

    mrk = "=300  \\\\" + " ".join(mrk_parts)

    return {
        "300": mrk,
        "300_subfields": subfields,
        "page_value": page_value,
        "size_value": size_value,
        "illustration_possibility": label if label else "없음",
    }


def search_aladin_detail_page(link):
    try:
        r = requests.get(link, timeout=12)
        r.raise_for_status()
        return parse_aladin_physical_book_info(r.text), None
    except Exception as e:
        return {
            "300": "=300  \\\\$a1책. [파싱 실패]",
            "300_subfields": [Subfield("a", "1책.")],
        }, str(e)


def build_300_from_aladin_detail(item: dict):
    link = (item or {}).get("link", "")
    if not link:
        fallback = "=300  \\\\$a1책."
        return fallback, Field("300", [" ", " "], [Subfield("a", "1책.")])

    parsed, err = search_aladin_detail_page(link)
    mrk = parsed.get("300")
    subs = parsed.get("300_subfields")

    f = Field("300", [" ", " "], subs)
    return mrk, f
# ============================================================
# PART 4 — Publisher / Place / Country-code / 260 Builder
# ============================================================

from oauth2client.service_account import ServiceAccountCredentials
import gspread


# ------------------------------------------------------------
# 구글시트 DB 로드 (출판사명–주소 / 발행국명–부호 / 임프린트 목록)
# ------------------------------------------------------------
@st.cache_data(ttl=3600)
def load_publisher_db():
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        st.secrets["gspread"],
        [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    client = gspread.authorize(creds)
    sh = client.open("출판사 DB")

    # ① 출판사명–주소
    pub_rows = sh.worksheet("발행처명–주소 연결표").get_all_values()[1:]
    pub_data = pd.DataFrame(
        [(r[1], r[2]) for r in pub_rows],
        columns=["출판사명", "주소"],
    )

    # ② 발행국 명–부호
    region_rows = sh.worksheet("발행국명–발행국부호 연결표").get_all_values()[1:]
    region_data = pd.DataFrame(
        [(r[0], r[1]) for r in region_rows],
        columns=["발행국", "발행국 부호"],
    )

    # ③ 임프린트 호출 (여러 시트)
    imprints = []
    for ws in sh.worksheets():
        if ws.title.startswith("발행처-임프린트 연결표"):
            rows = ws.get_all_values()[1:]
            for r in rows:
                if r:
                    imprints.append(r[0])
    imprint_data = pd.DataFrame(imprints, columns=["임프린트"])

    return pub_data, region_data, imprint_data


# ------------------------------------------------------------
# 문자열 정규화
# ------------------------------------------------------------
def normalize_publisher_name(name):
    return re.sub(r"\s|\(.*?\)|주식회사|㈜|도서출판|출판사", "", name or "").lower()


def split_publisher_aliases(name):
    if not name:
        return "", []

    # (부가정보) 제거 → 대표명과 alias 둘 다 확보
    aliases = []
    inside = re.findall(r"\((.*?)\)", name)
    for c in inside:
        for part in re.split(r"[,/]", c):
            part = part.strip()
            if part:
                aliases.append(part)
    base = re.sub(r"\(.*?\)", "", name).strip()

    # '/' 로 여러 브랜드가 걸쳐져 있는 경우
    if "/" in base:
        parts = [p.strip() for p in base.split("/") if p.strip()]
        return parts[0], parts[1:]
    return base, aliases


def normalize_publisher_location_for_display(addr: str):
    if not addr or addr in ("출판지 미상", "예외 발생"):
        return addr

    addr = addr.strip()
    major = ["서울", "인천", "대전", "광주", "울산", "대구", "부산", "세종"]
    for city in major:
        if city in addr:
            return city

    # 도 단위는 두 글자만 표시
    p = addr.split()
    if len(p) >= 2:
        return p[1].replace("시", "")
    return p[0]


# ------------------------------------------------------------
# KPIPA 사이트 검색
# ------------------------------------------------------------
def get_publisher_name_from_isbn_kpipa(isbn):
    url = "https://bnk.kpipa.or.kr/home/v3/addition/search"
    params = {
        "ST": isbn,
        "PG": 1,
        "PG2": 1,
        "DSF": "Y",
        "SO": "weight",
        "DT": "A",
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        link = soup.select_one("a.book-grid-item")
        if not link:
            return None, None, "❌ KPIPA 검색 결과 없음"

        detail = "https://bnk.kpipa.or.kr" + link.get("href")
        r2 = requests.get(detail, headers=HEADERS, timeout=12)
        soup2 = BeautifulSoup(r2.text, "html.parser")

        dt = soup2.find("dt", string="출판사 / 임프린트")
        if not dt:
            return None, None, "❌ KPIPA 상세 정보 없음"
        dd = dt.find_next_sibling("dd")
        if not dd:
            return None, None, "❌ KPIPA dd 없음"

        full = dd.text.strip()
        base = full.split("/")[0].strip()
        return full, normalize_publisher_name(base), None
    except Exception as e:
        return None, None, f"KPIPA 오류: {e}"


# ------------------------------------------------------------
# KPIPA 출판사명 → 주소 검색 (구글시트)
# ------------------------------------------------------------
def search_publisher_location_with_alias(name, pub_data):
    if not name:
        return "출판지 미상", ["❌ 입력값 없음"]

    norm = normalize_publisher_name(name)
    df = pub_data[pub_data["출판사명"].apply(lambda x: normalize_publisher_name(x) == norm)]
    if not df.empty:
        addr = df.iloc[0]["주소"]
        return addr, [f"✓ KPIPA-DB 매칭: {name} → {addr}"]
    return "출판지 미상", [f"❌ KPIPA-DB 매칭 실패: {name}"]


# ------------------------------------------------------------
# 임프린트 → 본사 매핑
# ------------------------------------------------------------
def find_main_publisher_from_imprints(rep_name, imprint_data, pub_data):
    norm_rep = normalize_publisher_name(rep_name)
    for line in imprint_data["임프린트"]:
        if "/" in line:
            base, imp = [x.strip() for x in line.split("/", 1)]
        else:
            base, imp = line.strip(), None

        if not imp:
            continue
        if normalize_publisher_name(imp) == norm_rep:
            addr, log = search_publisher_location_with_alias(base, pub_data)
            return addr, log
    return None, ["❌ 임프린트 매칭 없음"]


# ------------------------------------------------------------
# 문화부(MCST) 검색 (보조)
# ------------------------------------------------------------
def get_mcst_address(name: str):
    url = "https://book.mcst.go.kr/html/searchList.php"
    params = {
        "search_area": "전체",
        "search_state": "1",
        "search_kind": "1",
        "search_type": "1",
        "search_word": name,
    }
    logs = []
    try:
        r = requests.get(url, params=params, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.select("table.board tbody tr")
        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) >= 4:
                status = tds[3].text.strip()
                if status == "영업":
                    addr = tds[2].text.strip()
                    logs.append("✓ MCST: match 1건")
                    return addr, logs
        logs.append("❌ MCST 결과 없음")
        return None, logs
    except Exception as e:
        return None, [f"MCST 오류: {e}"]


# ------------------------------------------------------------
# 발행국 부호(AACR 지역 코드)
# ------------------------------------------------------------
def get_country_code_by_region(region_name, region_df):
    if not region_name:
        return "   "
    try:
        def _norm(r):
            r = (r or "").strip()
            if r.startswith(("전라", "충청", "경상")):
                return r[0] + (r[2] if len(r) > 2 else "")
            return r[:2]

        target = _norm(region_name)
        for _, row in region_df.iterrows():
            if _norm(row["발행국"]) == target:
                return row["발행국 부호"].strip() or "   "
        return "   "
    except:
        return "   "


# ------------------------------------------------------------
# 메인: 출판지·국가코드 번들 생성
# ------------------------------------------------------------
def build_pub_location_bundle(isbn, publisher_raw):
    logs = []
    try:
        pub_data, region_data, imprint_data = load_publisher_db()
        logs.append("✓ Google Sheet 로드 성공")

        full, norm, err = get_publisher_name_from_isbn_kpipa(isbn)
        if err:
            logs.append(err)

        rep, aliases = split_publisher_aliases(full or publisher_raw or "")
        logs.append(f"대표 출판사명: {rep}, alias={aliases}")

        # 1) KPIPA-DB
        place, lg = search_publisher_location_with_alias(rep, pub_data)
        logs += lg
        source = "KPIPA-DB"

        # 2) 임프린트
        if place in ("출판지 미상", None):
            place2, lg2 = find_main_publisher_from_imprints(rep, imprint_data, pub_data)
            logs += lg2
            if place2:
                place = place2
                source = "IMPRINT → KPIPA"

        # 3) MCST
        if place in ("출판지 미상", None):
            addr, lg3 = get_mcst_address(rep)
            logs += lg3
            if addr:
                place = addr
                source = "MCST"

        if not place or place in ("출판지 미상", None):
            place = "출판지 미상"
            source = "FALLBACK"
            logs.append("⚠️ 모든 경로 실패 → 출판지 미상")

        disp = normalize_publisher_location_for_display(place)
        country = get_country_code_by_region(place, region_data)

        return {
            "place_raw": place,
            "place_display": disp,
            "country_code": country,
            "resolved_publisher": rep,
            "source": source,
            "debug": logs,
        }

    except Exception as e:
        return {
            "place_raw": "발행지 미상",
            "place_display": "발행지 미상",
            "country_code": "   ",
            "resolved_publisher": publisher_raw,
            "source": "ERROR",
            "debug": [f"예외: {e}"],
        }


# ------------------------------------------------------------
# 260 Builder
# ------------------------------------------------------------
def build_260(place_display: str, publisher_name: str, pubyear: str):
    place = place_display or "발행지 미상"
    pub = publisher_name or "발행처 미상"
    y = pubyear or ""
    return f"=260  \\\\$a{place} :$b{pub},$c{y}"
# ============================================================
# PART 5 — 056: KDC 분류 생성기 (GPT-4o 기반)
# ============================================================

@dataclass
class BookInfo:
    title: str = ""
    author: str = ""
    pub_date: str = ""
    publisher: str = ""
    isbn13: str = ""
    category: str = ""
    description: str = ""
    toc: str = ""
    extra: Optional[Dict[str, Any]] = None
    marc041: str = ""   # 041 MRK 전체 저장


# -------------------------------------------
# 텍스트 정규화 도우미
# -------------------------------------------
def clean_text(s: Optional[str]):
    if not s:
        return ""
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def strip_tags(html_text: str) -> str:
    return re.sub(r"<[^>]+>", " ", html_text or "")


def first_match_number(text: str) -> Optional[str]:
    """본문에서 연속된 숫자(1~3자리) 또는 소수점 포함 번호 추출"""
    if not text:
        return None
    m = re.search(r"\b([0-9]{1,3}(?:\.[0-9]+)?)\b", text)
    return m.group(1) if m else None


def normalize_kdc_3digit(code: Optional[str]) -> Optional[str]:
    """
    '813.7' → '813'
    '5' → '5'
    '005' → '005'
    """
    if not code:
        return None
    m = re.search(r"(\d{1,3})", code)
    return m.group(1) if m else None


# -------------------------------------------
# 알라딘 API → BookInfo 로 흡수
# -------------------------------------------
def aladin_lookup_by_api(isbn13: str, ttbkey: str) -> Optional[BookInfo]:
    if not ttbkey:
        return None

    params = {
        "ttbkey": ttbkey,
        "itemIdType": "ISBN13",
        "ItemId": isbn13,
        "output": "js",
        "Version": "20131101",
        "OptResult": "authors,categoryName,fulldescription,toc",
    }
    try:
        r = requests.get(
            "https://www.aladin.co.kr/ttb/api/ItemLookUp.aspx",
            params=params,
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        js = r.json()
        items = js.get("item", [])
        if not items:
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
        dbg_err(f"[aladin_lookup_by_api ERROR] {e}")
        return None


# -------------------------------------------
# 알라딘 웹 스크레이핑 (API 부재 시)
# -------------------------------------------
def aladin_lookup_by_web(isbn13: str) -> Optional[BookInfo]:
    try:
        params = {"SearchTarget": "Book", "SearchWord": f"isbn:{isbn13}"}
        sr = requests.get("https://www.aladin.co.kr/search/wsearchresult.aspx",
                          params=params, headers=HEADERS, timeout=15)
        sr.raise_for_status()
        soup = BeautifulSoup(sr.text, "html.parser")

        link = soup.select_one("a.bo3")
        if not link:
            return None
        item_url = urllib.parse.urljoin("https://www.aladin.co.kr", link["href"])

        pr = requests.get(item_url, headers=HEADERS, timeout=15)
        pr.raise_for_status()
        psoup = BeautifulSoup(pr.text, "html.parser")

        # 제목/설명 파싱
        og_title = psoup.select_one('meta[property="og:title"]')
        og_desc = psoup.select_one('meta[property="og:description"]')

        title = clean_text(og_title["content"]) if og_title else ""
        desc  = clean_text(og_desc["content"]) if og_desc else ""
        body  = clean_text(psoup.get_text(" "))[:3000]

        description = desc or body

        # 저자/출판사 추출(약식)
        text = clean_text(psoup.get_text(" "))
        aut = ""
        pub = ""
        date = ""

        ma = re.search(r"(저자|지은이)\s*:\s*([^\n|·/]+)", text)
        if ma:
            aut = clean_text(ma.group(2))
        mp = re.search(r"(출판사)\s*:\s*([^\n|·/]+)", text)
        if mp:
            pub = clean_text(mp.group(2))
        md = re.search(r"(출간일|출판일)\s*:\s*([0-9]{4}\.[0-9]{1,2}\.[0-9]{1,2})", text)
        if md:
            date = clean_text(md.group(2))

        # 카테고리
        crumbs = psoup.select(".location, .path, .breadcrumb")
        cat = clean_text(" > ".join(c.get_text(" ") for c in crumbs)) if crumbs else ""

        return BookInfo(
            title=title,
            author=aut,
            publisher=pub,
            pub_date=date,
            isbn13=isbn13,
            category=cat,
            description=description,
            toc="",   # 스크레이핑으로 toc는 불안정하므로 생략
        )
    except Exception as e:
        dbg_err(f"[aladin_lookup_by_web ERROR] {e}")
        return None


# -------------------------------------------
# 041 원작 언어($h) → 문학계열 보정
# -------------------------------------------
def _parse_marc_041_original(marc041: str):
    if not marc041:
        return None
    s = str(marc041).lower()
    m = re.search(r"\$h([a-z]{3})", s)
    return m.group(1) if m else None


def _lang3_to_kdc_lit_base(lang3: str):
    if not lang3:
        return None
    l = lang3.lower()
    if l == "kor": return "810"
    if l == "chi" or l == "zho": return "820"
    if l == "jpn": return "830"
    if l == "eng": return "840"
    if l == "ger" or l == "deu": return "850"
    if l == "fre": return "860"
    if l == "spa" or l == "por": return "870"
    if l == "ita": return "880"
    return "890"


def _rebase_8xx_with_language(code: str, marc041: str):
    """
    8xx 문학번호가 있을 때 041 $h 원작언어에 따라 문학계열 앞 2자리만 교체.
    예: 코드=813, 원작=eng → 843
    """
    if not code or not code[0] == "8":
        return code

    orig = _parse_marc_041_original(marc041)
    if not orig:
        return code

    base = _lang3_to_kdc_lit_base(orig)
    if not base:
        return code

    m = re.match(r"^(\d{3})(\..+)?$", code)
    if not m:
        return code

    head = m.group(1)
    tail = m.group(2) or ""

    genre = head[2]   # 세 번째 자리(1=시, 3=소설…)
    new3 = base[:2] + genre
    return new3 + tail


# -------------------------------------------
# GPT 호출 → KDC 판단
# -------------------------------------------
def ask_llm_for_kdc(book: BookInfo, api_key: str, model: str = "gpt-4o",
                    keywords_hint=None) -> Optional[str]:

    # 긴 텍스트는 안전하게 축약
    def clip(s, n):
        s = s or ""
        return s if len(s) <= n else s[:n] + "…"

    payload = {
        "title": clip(book.title, 160),
        "author": clip(book.author, 120),
        "publisher": book.publisher,
        "pub_date": book.pub_date,
        "isbn13": book.isbn13,
        "category": clip(book.category, 160),
        "description": clip(book.description, 1200),
        "toc": clip(book.toc, 1200),
    }

    sys = (
        "너는 한국십진분류(KDC) 전문가이다. "
        "도서의 중심 주제를 고려하여 반드시 **3자리 정수(KDC 상위)**만 결정하라.\n"
        "출력 규칙:\n"
        " - 예: 813 / 823 / 325 / 181\n"
        " - 이유, 설명, 단위표기 금지.\n"
        " - 판단 곤란하면 정확히 '직접분류추천' 네 글자만 출력.\n"
        " - 힌트(653 keywords)가 주어져도 설명/목차가 우선.\n"
    )

    hint_str = ", ".join(keywords_hint or [])

    user = (
        f"도서 정보(JSON):\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        f"참고용 653 키워드: {hint_str or '(없음)'}\n"
        "정답 예시: 813 / 823 / 325 / 181 / 직접분류추천"
    )

    # 응답 파서
    def parse_resp(s):
        if not s:
            return None
        s = s.strip()
        if "직접분류추천" in s:
            return "직접분류추천"
        m = re.search(r"\b(\d{1,3})\b", s)
        if not m:
            return None
        return m.group(1).zfill(3)

    # LLM 호출
    try:
        rsp = requests.post(
            OPENAI_CHAT_COMPLETIONS,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": sys},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.0,
                "max_tokens": 15,
            },
            timeout=45,
        )
        rsp.raise_for_status()
        text = rsp.json()["choices"][0]["message"]["content"]
        code = parse_resp(text)
        if not code:
            return None

        # 문학 재정렬(813→843 등)
        code2 = _rebase_8xx_with_language(code, book.marc041 or "")
        return code2

    except Exception as e:
        dbg_err(f"[ask_llm_for_kdc ERROR] {e}")
        return None


# -------------------------------------------
# KDC 종합 호출
# -------------------------------------------
def get_kdc_from_isbn(isbn, ttbkey, openai_key, model, keywords_hint=None):
    info = aladin_lookup_by_api(isbn, ttbkey)
    if not info:
        info = aladin_lookup_by_web(isbn)
    if not info:
        dbg_err("KDC: 알라딘에서 정보가 없음")
        return None

    # 041 정보를 BookInfo 에 입력 (문학 재정렬용)
    # generate_all_oneclick() 내부에서 marc041 값을 info.marc041 로 주입한다.
    # 여기서는 placeholder 유지.

    code = ask_llm_for_kdc(info, openai_key, model=model, keywords_hint=keywords_hint)

    if code and re.fullmatch(r"\d{1,3}", code):
        return code
    return None
# ============================================================
# PART 6 — 메인 엔진: generate_all_oneclick / run_and_export
# ============================================================

def generate_all_oneclick(
    isbn: str,
    reg_mark: str = "",
    reg_no: str = "",
    copy_symbol: str = "",
    use_ai_940: bool = True,
):
    """
    ISBN 하나로 **모든 MARC 태그**를 자동 생성하는 핵심 엔진.
    - 041, 546 : GPT-4o 1회 호출 (get_kormarc_tags)
    - 245/246/700 : 알라딘 + NLK 메타 기반
    - 020 : 가격 + 부가기호
    - 260 : 출판지/발행국/출판사 자동 정규화
    - 300 : 알라딘 상세페이지 크롤링 기반 형태사항 파서
    - 490/830 : 총서 처리
    - 653 : GPT 기반 주제어
    - 056 : GPT 기반 KDC
    - 940 : AI 또는 Rule 기반 서명핀
    - 최종적으로 Record 객체 + 바이너리 .mrc + 텍스트 .mrk 동시 출력
    """

    # 메타 준비
    marc_rec = Record(to_unicode=True, force_utf8=True)
    meta = {"debug_lines": [], "notes": []}
    global CURRENT_DEBUG_LINES
    CURRENT_DEBUG_LINES = []

    # 알라딘 Item
    item = fetch_aladin_item(isbn)

    # --------------------------------------------
    # 1) 041 / 546 / originalTitle (GPT master 1회 호출)
    # --------------------------------------------
    tag_041_text, tag_546_text, original_title = get_kormarc_tags(isbn)
    origin_lang = None
    if tag_041_text:
        m = re.search(r"\$h([a-z]{3})", tag_041_text, flags=re.I)
        if m:
            origin_lang = m.group(1).lower()

    # --------------------------------------------
    # 2) 245 (서명) + 246 (이형서명) + 700 (저자) 생성
    # --------------------------------------------
    author_raw, _ = fetch_nlk_author_only(isbn)

    marc245 = build_245_with_people_from_sources(item, author_raw, prefer="aladin")
    f_245 = mrk_str_to_field(marc245)

    marc246 = build_246_from_aladin_item(item)
    f_246 = mrk_str_to_field(marc246)

    # 저자 700
    mrk_700 = build_700_people_pref_aladin(
        author_raw,
        item,
        origin_lang_code=origin_lang,
    ) or []

    # --------------------------------------------
    # 3) 90010 LOD 기반 원어명
    # --------------------------------------------
    people = extract_people_from_aladin(item) if item else {}
    mrk_90010 = build_90010_from_wikidata(people, include_translator=False)

    # --------------------------------------------
    # 4) 940 : 서명핀 생성
    # --------------------------------------------
    a_out, n = parse_245_a_n(marc245)
    mrk_940 = build_940_from_title_a(
        a_out,
        use_ai=use_ai_940,
        disable_number_reading=bool(n),
    )

    # --------------------------------------------
    # 5) 260 : 출판지/출판사/발행연도
    # --------------------------------------------
    pub_raw = (item or {}).get("publisher", "")
    pub_date = (item or {}).get("pubDate", "") or ""
    pub_year = pub_date[:4] if len(pub_date) >= 4 else ""

    bundle = build_pub_location_bundle(isbn, pub_raw)

    tag_260 = build_260(
        place_display=bundle["place_display"],
        publisher_name=pub_raw,
        pubyear=pub_year,
    )
    f_260 = mrk_str_to_field(tag_260)

    # --------------------------------------------
    # 6) 008 (통합)
    # --------------------------------------------
    lang3_override = _lang3_from_tag041(tag_041_text) if tag_041_text else None

    data_008 = build_008_from_isbn(
        isbn,
        aladin_pubdate=pub_date,
        aladin_title=(item or {}).get("title", ""),
        aladin_category=(item or {}).get("categoryName", ""),
        aladin_desc=(item or {}).get("description", ""),
        aladin_toc=((item or {}).get("subInfo", {}) or {}).get("toc", ""),
        override_country3=bundle["country_code"],
        override_lang3=lang3_override,
        cataloging_src="a",
    )
    field_008 = Field(tag="008", data=data_008)

    # --------------------------------------------
    # 7) 007 (책 = ta)
    # --------------------------------------------
    field_007 = Field("007", data="ta")

    # --------------------------------------------
    # 8) 020 가격/부가기호 + set ISBN
    # --------------------------------------------
    tag_020 = _build_020_from_item_and_nlk(isbn, item)
    f_020 = mrk_str_to_field(tag_020)

    nlk_extra = fetch_additional_code_from_nlk(isbn)
    set_isbn = nlk_extra.get("set_isbn", "").strip()

    # --------------------------------------------
    # 9) 653 GPT 기반 주제어
    # --------------------------------------------
    tag_653 = generate_653_with_gpt(
        (item or {}).get("categoryName", ""),
        (item or {}).get("title", ""),
        author_raw or "",
        (item or {}).get("description", ""),
        ((item or {}).get("subInfo", {}) or {}).get("toc", ""),
        max_keywords=7,
    )
    f_653 = mrk_str_to_field(tag_653) if tag_653 else None

    # 653 힌트 추출
    try:
        kw_hint = _parse_653_keywords(tag_653)
    except:
        kw_hint = []

    # --------------------------------------------
    # 10) 056 KDC (GPT-4o)
    # --------------------------------------------
    kdc_code = get_kdc_from_isbn(
        isbn,
        ttbkey=ALADIN_TTB_KEY,
        openai_key=openai_key,
        model="gpt-4o",
        keywords_hint=kw_hint,
    )
    tag_056 = f"=056  \\\\$a{kdc_code}$26" if kdc_code else None
    f_056 = mrk_str_to_field(tag_056)

    # --------------------------------------------
    # 11) 490 / 830 (총서)
    # --------------------------------------------
    tag_490, tag_830 = build_490_830_mrk_from_item(item)
    f_490 = mrk_str_to_field(tag_490)
    f_830 = mrk_str_to_field(tag_830)

    # --------------------------------------------
    # 12) 300 형태사항
    # --------------------------------------------
    tag_300, f_300 = build_300_from_aladin_detail(item)

    # --------------------------------------------
    # 13) 950 (가격)
    # --------------------------------------------
    tag_950 = build_950_from_item_and_price(item, isbn)
    f_950 = mrk_str_to_field(tag_950)

    # --------------------------------------------
    # 14) 049 (등록기호)
    # --------------------------------------------
    tag_049 = build_049(reg_mark, reg_no, copy_symbol)
    f_049 = mrk_str_to_field(tag_049)

    # ----------------------------------------------------
    # 15) 최종 조립 (MARC 필드 순서 보장)
    # ----------------------------------------------------
    pieces = []

    pieces.append((field_008, f"=008  {data_008}"))
    pieces.append((field_007, "=007  ta"))
    if f_020: pieces.append((f_020, tag_020))
    if set_isbn:
        tag_020_1 = f"=020  1\\$a{set_isbn} (set)"
        pieces.append((mrk_str_to_field(tag_020_1), tag_020_1))

    # 번역서는 041 반드시 포함
    if tag_041_text:
        f_041 = mrk_str_to_field(tag_041_text)
        pieces.append((f_041, tag_041_text))

    if f_056: pieces.append((f_056, tag_056))
    if f_245: pieces.append((f_245, marc245))
    if f_246: pieces.append((f_246, marc246))
    if f_260: pieces.append((f_260, tag_260))
    if f_300: pieces.append((f_300, tag_300))
    if f_490: pieces.append((f_490, tag_490))

    if tag_546_text:
        f_546 = mrk_str_to_field(tag_546_text)
        pieces.append((f_546, tag_546_text))

    if f_653: pieces.append((f_653, tag_653))

    for m in mrk_700:
        f = mrk_str_to_field(m)
        pieces.append((f, m))

    for m in mrk_90010:
        pieces.append((mrk_str_to_field(m), m))

    for m in mrk_940:
        pieces.append((mrk_str_to_field(m), m))

    if f_830: pieces.append((f_830, tag_830))
    if f_950: pieces.append((f_950, tag_950))
    if f_049: pieces.append((f_049, tag_049))

    # 최종 MRK 조립
    mrk_strings = [m for _, m in pieces]
    mrk_text = "\n".join(mrk_strings)

    # MRC 조립
    for f, _ in pieces:
        marc_rec.add_field(f)

    # 메타 저장
    meta = {
        "041": tag_041_text,
        "546": tag_546_text,
        "020": tag_020,
        "056": tag_056,
        "653": tag_653,
        "kdc_code": kdc_code,
        "Publisher_raw": pub_raw,
        "Place_display": bundle.get("place_display"),
        "CountryCode_008": bundle.get("country_code"),
        "Candidates": get_candidate_names_for_isbn(isbn),
        "mrk_preview": "\n".join(mrk_strings[:12]),
        "debug_lines": CURRENT_DEBUG_LINES.copy(),
    }

    return marc_rec, marc_rec.as_marc(), mrk_text, meta


# ============================================================
# PART 6-2 — run_and_export
# ============================================================

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
        st.success("📦 MRC/MRK 파일 생성 완료!")
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
# ============================================================
# PART 7 — Streamlit UI (중복 key 완전 제거 버전)
# ============================================================

st.header("📚 ISBN → MARC 자동 생성기 (KORMARC)")

# ------------------------------------------
# UI 설정: 중복 방지를 위해 모든 key 를 ui_ 접두어로 통일
# ------------------------------------------

use_ai_940 = st.checkbox(
    "🧠 940 생성에 OpenAI 활용",
    value=True,
    key="ui_use_ai_940"
)

# --------------------------
# 입력 폼
# --------------------------
with st.form(key="ui_isbn_form", clear_on_submit=False):
    st.text_input(
        "🔹 단일 ISBN 입력",
        placeholder="예: 9788937462849",
        key="ui_single_isbn"
    )

    st.file_uploader(
        "📁 CSV 업로드 (UTF-8, 열: ISBN, 등록기호, 등록번호, 별치기호)",
        type=["csv"],
        key="ui_csv"
    )

    submitted = st.form_submit_button("🚀 변환 실행", use_container_width=True)

# --------------------------
# 제출 후 처리
# --------------------------

if submitted:
    single = (st.session_state.get("ui_single_isbn") or "").strip()
    csvfile = st.session_state.get("ui_csv")

    jobs = []

    # 단일 ISBN
    if single:
        jobs.append([single, "", "", ""])

    # CSV
    if csvfile:
        try:
            df = load_uploaded_csv(csvfile)
            required = {"ISBN", "등록기호", "등록번호", "별치기호"}
            if not required.issubset(df.columns):
                st.error("❌ CSV에 필요한 열이 없습니다: ISBN, 등록기호, 등록번호, 별치기호")
                st.stop()

            rows = df[["ISBN", "등록기호", "등록번호", "별치기호"]]\
                    .dropna(subset=["ISBN"])\
                    .copy()

            rows["별치기호"] = rows["별치기호"].fillna("")

            jobs.extend(rows.values.tolist())

        except Exception as e:
            st.error(f"CSV 읽기 오류: {e}")
            st.stop()

    if not jobs:
        st.warning("ISBN을 입력하거나 CSV를 업로드 해주세요.")
        st.stop()

    # ------------------------------
    # 실제 변환 실행
    # ------------------------------

    st.write(f"총 {len(jobs)}건 처리 중…")
    prog = st.progress(0)

    results = []
    all_mrk_list = []

    for i, (isbn, reg_mark, reg_no, copy_symbol) in enumerate(jobs, start=1):

        record, marc_bytes, mrk_text, meta = run_and_export(
            isbn,
            reg_mark=reg_mark,
            reg_no=reg_no,
            copy_symbol=copy_symbol,
            use_ai_940=use_ai_940,
            save_dir="./output",
            preview_in_streamlit=True,
        )

        # 요약 표시
        cand = ", ".join(meta.get("Candidates", [])) if meta else "-"
        st.caption(
            f"ISBN: **{isbn}** | 후보저자: {cand} | "
            f"700={meta.get('700_count','-')} / "
            f"90010={meta.get('90010_count',0)} / "
            f"940={meta.get('940_count',0)}"
        )

        st.write(f"[DEBUG] MRK length={len(mrk_text)}")
        st.code(mrk_text or "(MRK 생성 실패)", language="text")

        with st.expander(f"🧭 메타 정보 보기 ({isbn})"):
            safe_meta = {k: v for k, v in meta.items() if k != "debug_lines"}
            st.json(safe_meta)

            dbg_lines = meta.get("debug_lines") or []
            if dbg_lines:
                st.text("\n".join(str(x) for x in dbg_lines))
            else:
                st.caption("표시할 디버그 로그 없음")

        all_mrk_list.append(mrk_text)
        results.append((record, isbn, mrk_text, meta))

        prog.progress(i / len(jobs))

    # ------------------------------------
    # 전체 MRK 텍스트 다운로드
    # ------------------------------------
    combined = "\n\n".join(all_mrk_list).encode("utf-8-sig")
    st.download_button(
        label="📦 전체 MARC(MRK) 텍스트 다운로드",
        data=combined,
        file_name="marc_output.txt",
        mime="text/plain",
        key="ui_dl_all_mrk",
    )

    # ------------------------------------
    # 전체 MRC 바이너리 다운로드
    # ------------------------------------
    buf = io.BytesIO()
    writer = MARCWriter(buf)

    for record_obj, isbn, _, _ in results:
        if isinstance(record_obj, Record):
            writer.write(record_obj)

    buf.seek(0)

    st.download_button(
        label="📥 전체 MRC 파일 다운로드",
        data=buf,
        file_name="marc_output.mrc",
        mime="application/octet-stream",
        key="ui_dl_all_mrc",
    )

    st.session_state["ui_last_results"] = results


# -------------------------------------------------------------
# 사용 팁
# -------------------------------------------------------------
with st.expander("⚙️ 사용 팁"):
    st.markdown(
        """
- 저자명: **NLK SearchApi(JSON)** → 역할어 제거 후 `=700` 자동 생성  
- 서명: **알라딘 title/subTitle** → 245 자동  
- 형태사항: **알라딘 상세페이지 크롤링** → 페이지·삽화·크기 자동 추출  
- KDC: **GPT-4o 1회 호출 + 원작언어 기반 문학 재배치(813→843 등)**  
- 041/546: **GPT Master 1회 호출로 동시 생성**
        """
    )

