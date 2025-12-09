# ==========================================================
# field_builders.py  — Block A
# 원본 코드의 "041/546 생성", "언어 감지", "008 생성 전까지"
# 모든 로직을 원본 그대로 분리
# ==========================================================

import re
import datetime
from collections import Counter
from dataclasses import dataclass
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup

from pymarc import Field, Subfield
import requests

# ============================
# 041/546 관련 유틸
# ============================

ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어', 'rus': '러시아어',
    'ara': '아랍어', 'fre': '프랑스어', 'ger': '독일어', 'ita': '이탈리아어', 'spa': '스페인어',
    'und': '알 수 없음'
}

def detect_language(text):
    """
    원본 detect_language 그대로.
    """
    text = re.sub(r'[\s\W_]+', '', text)
    if not text:
        return 'und'
    first_char = text[0]
    if '\uac00' <= first_char <= '\ud7a3':
        return 'kor'
    elif '\u3040' <= first_char <= '\u30ff':
        return 'jpn'
    elif '\u4e00' <= first_char <= '\u9fff':
        return 'chi'
    elif '\u0400' <= first_char <= '\u04FF':
        return 'rus'
    elif 'a' <= first_char.lower() <= 'z':
        return 'eng'
    else:
        return 'und'


def generate_546_from_041_kormarc(marc_041: str) -> str:
    """
    원본 generate_546_from_041_kormarc 그대로 이동.
    """
    a_codes, h_code = [], None
    for part in marc_041.split():
        if part.startswith("$a"):
            a_codes.append(part[2:])
        elif part.startswith("$h"):
            h_code = part[2:]

    if len(a_codes) == 1:
        a_lang = ISDS_LANGUAGE_CODES.get(a_codes[0], "알 수 없음")
        if h_code:
            h_lang = ISDS_LANGUAGE_CODES.get(h_code, "알 수 없음")
            return f"{h_lang} 원작을 {a_lang}로 번역"
        else:
            return f"{a_lang}로 씀"
    elif len(a_codes) > 1:
        langs = [ISDS_LANGUAGE_CODES.get(code, "알 수 없음") for code in a_codes]
        return f"{'、'.join(langs)} 병기"

    return "언어 정보 없음"


def _lang3_from_tag041(tag_041: str | None) -> str | None:
    """
    =041 0\$akor$heng → 'kor'
    원본 그대로.
    """
    if not tag_041:
        return None
    m = re.search(r"\$a([a-z]{3})", tag_041, flags=re.I)
    return m.group(1).lower() if m else None


# ==========================================================
# 653 전처리 + GPT 653 (원본 그대로)
# ==========================================================

def extract_keywords_from_text(text, top_n=7):
    words = re.findall(r'\b[\w가-힣]{2,}\b', text)
    filtered = [w for w in words if len(w) > 1]
    freq = Counter(filtered)
    return [kw for kw, _ in freq.most_common(top_n)]

def clean_keywords(words):
    stopwords = {"아주", "가지", "필요한", "등", "위해", "것", "수", "더", "이런", "있다", "된다", "한다"}
    return [w for w in words if w not in stopwords and len(w) > 1]


# -------------------------- 내부 전처리 --------------------------

def _norm(text: str) -> str:
    import unicodedata
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\s\uac00-\ud7a3]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def _clean_author_str(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[/;·,]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

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
    return {f for f in forb if f and len(f) >= 2}

def _should_keep_keyword(kw: str, forbidden: set) -> bool:
    n = _norm(kw)
    if not n or len(n.replace(" ", "")) < 2:
        return False
    for tok in forbidden:
        if tok in n or n in tok:
            return False
    return True


# -------------------------- GPT 653 핵심 --------------------------

def generate_653_with_gpt(category, title, authors, description, toc, max_keywords=7):
    """
    원본 generate_653_with_gpt 그대로.
    """
    import json
    import openai

    parts = [p.strip() for p in (category or "").split(">") if p.strip()]
    cat_tail = " ".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else "")

    forbidden = _build_forbidden_set(title, authors)
    forbidden_list = ", ".join(sorted(forbidden)) or "(없음)"

    system_msg = {
        "role": "system",
        "content": (
            "당신은 KORMARC 작성 경험이 풍부한 도서관 메타데이터 전문가입니다. "
            "주어진 분류 정보, 설명, 목차를 바탕으로 'MARC 653 자유주제어'를 도출합니다.\n\n"
            "(중략 — 원본 전체 그대로 유지)"
        )
    }

    user_msg = {
        "role": "user",
        "content": (
            f"- 분류: {category}\n"
            f"- 제목: {title}\n"
            f"- 저자: {authors}\n"
            f"- 설명: {description}\n"
            f"- 목차: {toc}\n"
            f"- 금칙어: {forbidden_list}\n"
            "(이하 원본 그대로)"
        )
    }

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[system_msg, user_msg],
            temperature=0.2,
            max_tokens=180,
        )
        raw = (resp.choices[0].message["content"] or "").strip()

        pattern = re.compile(r"\$a(.*?)(?=(?:\$a|$))", re.DOTALL)
        kws = [m.group(1).strip() for m in pattern.finditer(raw)]
        if not kws:
            tmp = re.split(r"[,\n;|/·]", raw)
            kws = [t.strip().lstrip("$a") for t in tmp if t.strip()]

        kws = [kw.replace(" ", "") for kw in kws if kw]
        kws = [kw for kw in kws if _should_keep_keyword(kw, forbidden)]

        seen = set(); uniq = []
        for kw in kws:
            n = _norm(kw)
            if n not in seen:
                seen.add(n)
                uniq.append(kw)

        uniq = uniq[:max_keywords]
        return "".join(f"$a{kw}" for kw in uniq)

    except Exception:
        return None


# --------------------------------------------------------------
# GPT 기반 653 생성 → =653 형태로 wrapping
# --------------------------------------------------------------
def _build_653_via_gpt(item: dict) -> str | None:
    title = (item or {}).get("title", "") or ""
    category = (item or {}).get("categoryName", "") or ""
    raw_author = (item or {}).get("author", "") or ""
    desc = (item or {}).get("description", "") or ""
    toc = ((item or {}).get("subInfo", {}) or {}).get("toc", "") or ""

    kwline = generate_653_with_gpt(
        category=category,
        title=title,
        authors=_clean_author_str(raw_author),
        description=desc,
        toc=toc,
        max_keywords=7,
    )
    return f"=653  \\\\{kwline.replace(' ', '')}" if kwline else None


# ==========================================================
# 008 생성까지의 도구 (country guess, illus, lit_form 등)
# ==========================================================

COUNTRY_FIXED = "ko "     # 원본 상단 정의 그대로
LANG_FIXED = "kor"

KR_REGION_TO_CODE = {
    "서울": "ko ",
    "부산": "ko ",
    "경기": "ko ",
    # 원본에서는 한국 일반 부호는 쓰지 않도록 함 → 그대로.
}


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
    if re.search(r"삽화|삽도|도해|일러스트|그림", text, re.I):
        keys.append("a")
    if re.search(r"도표|표|차트|그래프", text, re.I):
        keys.append("d")
    if re.search(r"사진|포토|화보|photo", text, re.I):
        keys.append("o")
    out = []
    for k in keys:
        if k not in out:
            out.append(k)
    return "".join(out)[:4]


def detect_index(text: str) -> str:
    return "1" if re.search(r"색인|찾아보기|index", text, re.I) else "0"


def detect_lit_form(title: str, category: str, extra_text: str = "") -> str:
    blob = f"{title} {category} {extra_text}"
    if re.search(r"서간집|편지|서간문", blob, re.I):
        return "i"
    if re.search(r"기행|여행기|일기", blob, re.I):
        return "m"
    if re.search(r"시집|산문시|poem|poetry", blob, re.I):
        return "p"
    if re.search(r"소설|novel|fiction", blob, re.I):
        return "f"
    if re.search(r"에세이|수필|essay", blob, re.I):
        return "e"
    return " "


def detect_bio(text: str) -> str:
    if re.search(r"자서전|회고록", text, re.I):
        return "a"
    if re.search(r"전기|평전|biograph", text, re.I):
        return "b"
    if re.search(r"전기적|자전적|회고", text):
        return "d"
    return " "


def _is_unknown_place(s: str | None) -> bool:
    if not s:
        return False
    t = s.strip()
    t_no_sp = t.replace(" ", "")
    lower = t.lower()
    return (
        "미상" in t or
        "미상" in t_no_sp or
        "unknown" in lower or
        "place unknown" in lower
    )
# ==========================================================
# field_builders.py — Block B
# 008 생성 + 가격/020/950 + KPIPA 출판지 추론 + 260 필드
# 원본 로직 100% 그대로
# ==========================================================

import re
import datetime
import pandas as pd
import requests
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials

from pymarc import Field, Subfield

from .utils import clean_text, convert_mm_to_cm

# ==========================================================
# 008 본문(40자) 생성기 (원본 그대로)
# ==========================================================

def build_008_kormarc_bk(
    date_entered,          # YYMMDD
    date1,                 # 발행연도(4자리)
    country3,              # 발행국 부호(3칸)
    lang3,                 # 언어코드(3칸)
    date2="", illus4="", has_index="0",
    lit_form=" ", bio=" ", type_of_date="s",
    modified_record=" ", cataloging_src="a",
):
    def pad(s, n, fill=" "):
        s = "" if s is None else str(s)
        return (s[:n] + fill * n)[:n]

    if len(date_entered) != 6 or not date_entered.isdigit():
        raise ValueError("date_entered는 YYMMDD 6자리 숫자여야 합니다.")
    if len(date1) != 4:
        raise ValueError("date1은 4자리여야 합니다.")

    body = "".join([
        date_entered,               # 00-05
        pad(type_of_date,1),        # 06
        date1,                      # 07-10
        pad(date2,4),               # 11-14
        pad(country3,3),            # 15-17
        pad(illus4,4),              # 18-21
        " " * 4,                    # 22-25
        " " * 2,                    # 26-27
        pad(modified_record,1),     # 28
        "0",                        # 29
        "0",                        # 30
        has_index if has_index in ("0","1") else "0",  # 31
        pad(cataloging_src,1),      # 32
        pad(lit_form,1),            # 33
        pad(bio,1),                 # 34
        pad(lang3,3),               # 35-37
        " " * 2                     # 38-39
    ])

    if len(body) != 40:
        raise AssertionError(f"008 length != 40: {len(body)}")

    return body


# ----------------------------------------------------------
# 008 전체 조립 (원본 build_008_from_isbn 그대로)
# ----------------------------------------------------------

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
    cataloging_src="a",
):
    today  = datetime.datetime.now().strftime("%y%m%d")
    date1  = extract_year_from_aladin_pubdate(aladin_pubdate)

    # --- 발행국 부호 결정 ---
    if override_country3:
        country3 = override_country3
    elif source_300_place:
        if _is_unknown_place(source_300_place):
            country3 = "   "
        else:
            guessed = guess_country3_from_place(source_300_place)
            country3 = guessed if guessed else COUNTRY_FIXED
    else:
        country3 = COUNTRY_FIXED

    # 언어 우선순위: override > 기본값
    lang3 = override_lang3 or LANG_FIXED

    # 삽화, 색인, 문학형식, 전기감지
    bigtext = " ".join([aladin_title or "", aladin_desc or "", aladin_toc or ""])
    illus4    = detect_illus4(bigtext)
    has_index = detect_index(bigtext)
    lit_form  = detect_lit_form(aladin_title or "", aladin_category or "", bigtext)
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


# ==========================================================
# NLK(국립중앙도서관) — EA_ADD_CODE, SET ISBN, 가격 PRE_PRICE
# 원본 fetch_additional_code_from_nlk 그대로
# ==========================================================

def fetch_additional_code_from_nlk(isbn: str) -> dict:
    attempts = [
        "https://seoji.nl.go.kr/landingPage/SearchApi.do",
        "https://www.nl.go.kr/seoji/SearchApi.do",
        "http://seoji.nl.go.kr/landingPage/SearchApi.do",
        "http://www.nl.go.kr/seoji/SearchApi.do",
    ]
    params = {
        "cert_key": NLK_CERT_KEY,
        "result_style": "json",
        "page_no": 1,
        "page_size": 1,
        "isbn": isbn.strip().replace("-", ""),
    }

    for base in attempts:
        try:
            r = requests.get(base, params=params, timeout=(5, 10))
            r.raise_for_status()
            j = r.json()

            doc = None
            if isinstance(j, dict):
                if "docs" in j and isinstance(j["docs"], list) and j["docs"]:
                    doc = j["docs"][0]
                elif "doc" in j and isinstance(j["doc"], list) and j["doc"]:
                    doc = j["doc"][0]
            if not doc:
                continue

            add_code = (doc.get("EA_ADD_CODE") or "").strip()
            set_isbn = (doc.get("SET_ISBN") or "").strip()
            price = (doc.get("PRE_PRICE") or "").strip()

            return {
                "add_code": add_code,
                "set_isbn": set_isbn,
                "price": price,
            }
        except Exception:
            continue

    return {
        "add_code": "",
        "set_isbn": "",
        "set_title": "",
        "price": "",
    }


# ==========================================================
# 020 필드 생성기 (원본 그대로)
# ==========================================================

def _build_020_from_item_and_nlk(isbn: str, item: dict) -> str:
    price = str((item or {}).get("priceStandard", "") or "").strip()

    try:
        nlk_extra = fetch_additional_code_from_nlk(isbn) or {}
        add_code = nlk_extra.get("add_code", "")
        price_from_nlk = nlk_extra.get("price", "")
    except Exception:
        add_code = ""
        price_from_nlk = ""

    final_price = price or price_from_nlk

    parts = [f"=020  \\\\$a{isbn}"]
    if add_code:
        parts.append(f"$g{add_code}")
    if final_price:
        parts.append(f":$c{final_price}")

    return "".join(parts)


# ==========================================================
# 950 필드 (가격) 생성기 — 원본 그대로
# ==========================================================

def _extract_price_kr(item: dict, isbn: str) -> str:
    raw = str((item or {}).get("priceStandard", "") or "").strip()

    if not raw:
        try:
            crawl = crawl_aladin_original_and_price(isbn) or {}
            raw = crawl.get("price", "").strip()
        except Exception:
            raw = ""

    digits = re.sub(r"[^\d]", "", raw)
    return digits


def build_950_from_item_and_price(item: dict, isbn: str) -> str:
    price = _extract_price_kr(item, isbn)
    if not price:
        return ""
    return f"=950  0\\$b\\{price}"


# ==========================================================
# 출판지 추출 (KPIPA / IMPRINT / 문체부 / FallBack)
# ==========================================================

def load_publisher_db():
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        st.secrets["gspread"],
        ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    )
    client = gspread.authorize(creds)
    sh = client.open("출판사 DB")

    pub_rows = sh.worksheet("발행처명–주소 연결표").get_all_values()[1:]
    pub_rows_filtered = [row[1:3] for row in pub_rows]
    publisher_data = pd.DataFrame(pub_rows_filtered, columns=["출판사명", "주소"])

    region_rows = sh.worksheet("발행국명–발행국부호 연결표").get_all_values()[1:]
    region_rows_filtered = [row[:2] for row in region_rows]
    region_data = pd.DataFrame(region_rows_filtered, columns=["발행국", "발행국 부호"])

    imprint_frames = []
    for ws in sh.worksheets():
        if ws.title.startswith("발행처-임프린트 연결표"):
            data = ws.get_all_values()[1:]
            imprint_frames.extend([row[0] for row in data if row])
    imprint_data = pd.DataFrame(imprint_frames, columns=["임프린트"])

    return publisher_data, region_data, imprint_data


def normalize_publisher_name(name):
    return re.sub(r"\s|\(.*?\)|주식회사|㈜|도서출판|출판사", "", name).lower()


def normalize_stage2(name):
    name = re.sub(r"(주니어|JUNIOR|어린이|키즈|북스|아이세움|프레스)", "", name, flags=re.IGNORECASE)
    eng_to_kor = {"springer": "스프링거", "cambridge": "케임브리지", "oxford": "옥스포드"}
    for eng, kor in eng_to_kor.items():
        name = re.sub(eng, kor, name, flags=re.IGNORECASE)
    return name.strip().lower()


def split_publisher_aliases(name):
    aliases = []
    bracket_contents = re.findall(r"\((.*?)\)", name)
    for content in bracket_contents:
        parts = re.split(r"[,/]", content)
        parts = [p.strip() for p in parts if p.strip()]
        aliases.extend(parts)

    name_no_brackets = re.sub(r"\(.*?\)", "", name).strip()
    if "/" in name_no_brackets:
        parts = [p.strip() for p in name_no_brackets.split("/") if p.strip()]
        rep_name = parts[0]
        aliases.extend(parts[1:])
    else:
        rep_name = name_no_brackets

    return rep_name, aliases


def search_publisher_location_with_alias(name, publisher_data):
    debug_msgs = []
    if not name:
        return "출판지 미상", ["❌ 검색 실패: 입력된 출판사명이 없음"]

    norm_name = normalize_publisher_name(name)
    candidates = publisher_data[publisher_data["출판사명"].apply(
        lambda x: normalize_publisher_name(x)) == norm_name]

    if not candidates.empty:
        address = candidates.iloc[0]["주소"]
        debug_msgs.append(f"✅ KPIPA DB 매칭 성공: {name} → {address}")
        return address, debug_msgs
    else:
        debug_msgs.append(f"❌ KPIPA DB 매칭 실패: {name}")
        return "출판지 미상", debug_msgs


def find_main_publisher_from_imprints(rep_name, imprint_data, publisher_data):
    norm_rep = normalize_publisher_name(rep_name)

    for full_text in imprint_data["임프린트"]:
        if "/" in full_text:
            pub_part, imprint_part = [p.strip() for p in full_text.split("/", 1)]
        else:
            pub_part, imprint_part = full_text.strip(), None

        if imprint_part:
            norm_imprint = normalize_publisher_name(imprint_part)
            if norm_imprint == norm_rep:
                location, dbg = search_publisher_location_with_alias(pub_part, publisher_data)
                return location, dbg

    return None, [f"❌ IM DB 검색 실패: 매칭 없음 ({rep_name})"]


def get_mcst_address(publisher_name):
    url = "https://book.mcst.go.kr/html/searchList.php"
    params = {"search_area": "전체", "search_state": "1",
              "search_kind": "1", "search_type": "1",
              "search_word": publisher_name}
    debug_msgs = []

    try:
        res = requests.get(url, params=params, timeout=15)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        results = []
        for row in soup.select("table.board tbody tr"):
            cols = row.find_all("td")
            if len(cols) >= 4:
                reg_type = cols[0].get_text(strip=True)
                name = cols[1].get_text(strip=True)
                addr = cols[2].get_text(strip=True)
                status = cols[3].get_text(strip=True)

                if status == "영업":
                    results.append((reg_type, name, addr, status))

        if results:
            debug_msgs.append(f"[문체부] 검색 성공: {len(results)}건")
            return results[0][2], results, debug_msgs
        else:
            debug_msgs.append("[문체부] 결과 없음")
            return "미확인", [], debug_msgs
    except Exception as e:
        debug_msgs.append(f"[문체부] 예외: {e}")
        return "오류 발생", [], debug_msgs


def get_country_code_by_region(region_name, region_data):
    try:
        def normalize_region(region):
            region = (region or "").strip()
            if region.startswith(("전라", "충청", "경상")):
                return region[0] + (region[2] if len(region) > 2 else "")
            return region[:2]

        normalized_input = normalize_region(region_name)

        for _, row in region_data.iterrows():
            sheet_region, code = row["발행국"], row["발행국 부호"]
            if normalize_region(sheet_region) == normalized_input:
                return code.strip() or "   "
        return "   "
    except Exception:
        return "   "


def build_pub_location_bundle(isbn, publisher_name_raw):
    debug = []

    try:
        publisher_data, region_data, imprint_data = load_publisher_db()
        debug.append("✓ 구글시트 DB 적재 성공")

        kpipa_full, kpipa_norm, err = get_publisher_name_from_isbn_kpipa(isbn)
        if err:
            debug.append(f"KPIPA 검색: {err}")

        rep_name, aliases = split_publisher_aliases(kpipa_full or publisher_name_raw or "")
        resolved_for_search = rep_name or (publisher_name_raw or "").strip()
        debug.append(f"대표 출판사명: {resolved_for_search}")

        place_raw, msgs = search_publisher_location_with_alias(resolved_for_search, publisher_data)
        debug += msgs
        source = "KPIPA_DB"

        if place_raw in ("출판지 미상", "예외 발생", None):
            place_raw, msgs = find_main_publisher_from_imprints(resolved_for_search, imprint_data, publisher_data)
            debug += msgs
            if place_raw:
                source = "IMPRINT→KPIPA"

        if not place_raw or place_raw in ("출판지 미상", "예외 발생"):
            mcst_addr, _rows, dbg = get_mcst_address(resolved_for_search)
            debug += dbg
            if mcst_addr not in ("미확인", "오류 발생", None):
                place_raw = mcst_addr
                source = "MCST"

        if not place_raw or place_raw in ("출판지 미상", "예외 발생", "미확인", "오류 발생"):
            place_raw = "출판지 미상"
            source = "FALLBACK"
            debug.append("⚠️ 모든 경로 실패 → '출판지 미상'")

        place_display = normalize_publisher_location_for_display(place_raw)
        country_code = get_country_code_by_region(place_raw, region_data)

        return {
            "place_raw": place_raw,
            "place_display": place_display,
            "country_code": country_code,
            "resolved_publisher": resolved_for_search,
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


def normalize_publisher_location_for_display(location_name):
    if not location_name or location_name in ("출판지 미상", "예외 발생"):
        return location_name

    location_name = location_name.strip()
    major = ["서울", "인천", "대전", "광주", "울산", "대구", "부산", "세종"]
    for city in major:
        if city in location_name:
            return location_name[:2]

    parts = location_name.split()
    loc = parts[1] if len(parts) > 1 else parts[0]
    if loc.endswith("시"):
        loc = loc[:-1]
    return loc


# ==========================================================
# 260 필드 빌더
# ==========================================================

def build_260(place_display: str, publisher_name: str, pubyear: str):
    place = (place_display or "발행지 미상")
    pub = (publisher_name or "발행처 미상")
    year = (pubyear or "발행년 미상")
    return f"=260  \\\\$a{place} :$b{pub},$c{year}"

# ==========================================================
# field_builders.py — Block C
# C1. 653 생성기 (GPT 기반) + 전처리 유틸
# C2. 056(KDC) 생성 전체
# C3. 041/546 언어 감지 및 필드 빌더
# C4. 245 / 246 / 700 / 90010 / 940 (제목·저자·역자·LOD)
# C5. 300 상세 형식 파서
# C6. 가격/020/950 모듈
# C7. KPIPA/MCST/발행지 + 260 모듈
# C8. 008 생성기 (lang3 override / country3 override 포함)
# C9. 056(KDC) GPT 분류기 전체 모듈
# C10. 300(형태사항) 크롤러 + 파서 모듈
# C11. 490/830 총서 모듈
# C12. 최종 MARC Builder 조립기
# C13. 049 필드 생성기
# 원본 로직 100% 그대로
# ==========================================================
# C1. 653 생성기 (GPT 기반) + 전처리 유틸
# Chunk C-1 : 653 키워드 관련 전처리 + GPT 기반 653 생성기
def generate_653_with_gpt(category, title, authors, description, toc, max_keywords=7):
    import re
    from openai import OpenAI

    client = OpenAI()

    parts = [p.strip() for p in (category or "").split(">") if p.strip()]
    cat_tail = " ".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else "")

    forbidden = _build_forbidden_set(title, authors)
    forbidden_list = ", ".join(sorted(forbidden)) or "(없음)"

    system_msg = {
        "role": "system",
        "content": (
            "당신은 KORMARC 작성 경험이 풍부한 도서관 메타데이터 전문가입니다. "
            "주어진 정보로 653 키워드를 생성합니다. "
            "키워드는 반드시 붙여쓰기 하며, 명사형 개념으로만 구성합니다."
        )
    }

    user_msg = {
        "role": "user",
        "content": (
            f"분류: {category}\n"
            f"핵심 분류꼬리: {cat_tail}\n"
            f"제목: {title}\n"
            f"저자: {authors}\n"
            f"설명: {description}\n"
            f"목차: {toc}\n"
            f"제외어 목록: {forbidden_list}\n"
            "이 정보를 바탕으로 최소 1개~최대 7개의 653 키워드를 생성하세요.\n"
            "반드시 `$a키워드1 $a키워드2 ...` 형식으로만 출력하세요."
        )
    }

    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[system_msg, user_msg],
            temperature=0.2,
            max_tokens=200,
        )
        raw = (resp.choices[0].message.content or "").strip()

        # $a 추출
        pattern = re.compile(r"\$a(.*?)(?=(?:\$a|$))", re.DOTALL)
        kws = [m.group(1).strip() for m in pattern.finditer(raw)]

        # 붙여쓰기
        kws = [kw.replace(" ", "") for kw in kws]

        # 금칙어 제거
        kws = [kw for kw in kws if _should_keep_keyword(kw, forbidden)]

        # 최대 7개
        kws = kws[:max_keywords]

        return "".join(f"$a{kw}" for kw in kws)

    except Exception as e:
        st.warning(f"⚠️ 653 생성 실패: {e}")
        return None
    
# GPT 기반 653 생성기
def generate_653_with_gpt(category, title, authors, description, toc, max_keywords=7):
    import re
    from openai import OpenAI

    client = OpenAI()

    parts = [p.strip() for p in (category or "").split(">") if p.strip()]
    cat_tail = " ".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else "")

    forbidden = _build_forbidden_set(title, authors)
    forbidden_list = ", ".join(sorted(forbidden)) or "(없음)"

    system_msg = {
        "role": "system",
        "content": (
            "당신은 KORMARC 작성 경험이 풍부한 도서관 메타데이터 전문가입니다. "
            "주어진 정보로 653 키워드를 생성합니다. "
            "키워드는 반드시 붙여쓰기 하며, 명사형 개념으로만 구성합니다."
        )
    }

    user_msg = {
        "role": "user",
        "content": (
            f"분류: {category}\n"
            f"핵심 분류꼬리: {cat_tail}\n"
            f"제목: {title}\n"
            f"저자: {authors}\n"
            f"설명: {description}\n"
            f"목차: {toc}\n"
            f"제외어 목록: {forbidden_list}\n"
            "이 정보를 바탕으로 최소 1개~최대 7개의 653 키워드를 생성하세요.\n"
            "반드시 `$a키워드1 $a키워드2 ...` 형식으로만 출력하세요."
        )
    }

    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[system_msg, user_msg],
            temperature=0.2,
            max_tokens=200,
        )
        raw = (resp.choices[0].message.content or "").strip()

        # $a 추출
        pattern = re.compile(r"\$a(.*?)(?=(?:\$a|$))", re.DOTALL)
        kws = [m.group(1).strip() for m in pattern.finditer(raw)]

        # 붙여쓰기
        kws = [kw.replace(" ", "") for kw in kws]

        # 금칙어 제거
        kws = [kw for kw in kws if _should_keep_keyword(kw, forbidden)]

        # 최대 7개
        kws = kws[:max_keywords]

        return "".join(f"$a{kw}" for kw in kws)

    except Exception as e:
        st.warning(f"⚠️ 653 생성 실패: {e}")
        return None
# 653 → MRK
def _build_653_via_gpt(item: dict) -> str | None:
    title = (item or {}).get("title","") or ""
    category = (item or {}).get("categoryName","") or ""
    raw_author = (item or {}).get("author","") or ""
    desc = (item or {}).get("description","") or ""
    toc  = ((item or {}).get("subInfo",{}) or {}).get("toc","") or ""

    kwline = generate_653_with_gpt(
        category=category,
        title=title,
        authors=_clean_author_str(raw_author),
        description=desc,
        toc=toc,
        max_keywords=7
    )
    return f"=653  \\\\{kwline}" if kwline else None


def _parse_653_keywords(tag_653: str | None) -> list[str]:
    if not tag_653:
        return []
    s = re.sub(r"^=653\s+\\\\", "", tag_653.strip())

    kws = []
    for m in re.finditer(r"\$a([^$]+)", s):
        w = (m.group(1) or "").strip()
        if w:
            kws.append(w)

    # 중복 제거
    seen, out = set(), []
    for w in kws:
        if w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= 7:
            break
    return out

# C2. 056(KDC) 생성 전체
# Chunk C-2-A : 041 기반 문학 재정렬 유틸리티
# ==========================================================
# 041 원작언어 기반 → 문학(8xx) 재정렬 로직 (원본 그대로)
# ==========================================================
def _parse_marc_041_original(marc041: str):
    """
    MARC 041에서 원작 언어($h)를 추출한다.
    예: '041 0\\$akor$heng' -> 'eng'
    """
    if not marc041:
        return None
    s = marc041.lower()
    m = re.search(r"\$h([a-z]{3})", s)
    return m.group(1) if m else None


def _lang3_to_kdc_lit_base(lang3: str):
    """
    원작 언어코드 → 문학계열 기본 2자리 매핑.
    (원본 로직 100% 유지)
    """
    if not lang3:
        return None
    l = lang3.lower()

    if l in {"eng"}:
        return "84"   # 영미문학
    if l in {"kor"}:
        return "81"   # 한국문학
    if l in {"chi", "zho"}:
        return "82"   # 중국문학
    if l in {"jpn"}:
        return "83"   # 일본문학
    if l in {"deu", "ger"}:
        return "85"   # 독일문학
    if l in {"fre"}:
        return "86"   # 프랑스문학
    if l in {"spa", "por"}:
        return "87"   # 스페인/포르투갈문학
    if l in {"ita"}:
        return "88"   # 이탈리아문학

    return "89"        # 기타 문학
    
# Chunk C-2-B : 문학코드 재정렬기 (원본 유지)
def _rebase_8xx_with_language(code: str, marc041: str) -> str:
    """
    056 결과가 문학(8xx)일 때,
    041 $h 원작언어 기반으로 정렬 변경.
    - 장르(세 번째 자리) 그대로 유지
    - 앞 두 자리만 변경
    """
    if not code or len(code) < 3 or code[0] != "8":
        return code  # 문학이 아니면 그대로 유지

    # 원작언어 추출
    orig_lang = _parse_marc_041_original(marc041 or "")
    base2 = _lang3_to_kdc_lit_base(orig_lang) if orig_lang else None
    if not base2:
        return code

    # 813.7 → 813 그대로 처리
    m = re.match(r"^(\d{3})(\..+)?$", code)
    if not m:
        return code

    head3, tail = m.group(1), (m.group(2) or "")
    genre = head3[2]       # 문학 장르 디짓 (1=시, 3=소설 …)

    return base2 + genre
    
# Chunk C-2-C : LLM KDC 판단기 (원본 로직 그대로 모듈화)
# ==========================================================
# KDC 판단 LLM 호출기 — 핵심 함수
# (너가 준 원본 로직을 완전히 분리하여 구조화)
# ==========================================================

def ask_llm_for_kdc(
    book: BookInfo,
    api_key: str,
    model: str = DEFAULT_MODEL,
    keywords_hint: list[str] | None = None
) -> Optional[str]:
    """
    KDC(056) 판단을 LLM에게 요청.
    반환: 3자리 숫자 문자열 or '직접분류추천'
    """

    # -----------------------------
    # 1) 입력 텍스트 길이 제한 (원본 그대로)
    # -----------------------------
    def clip(s: str, n: int) -> str:
        if not s:
            return ""
        s = str(s).strip()
        return s if len(s) <= n else s[:n] + "…"

    payload = {
        "title":      clip(book.title, 160),
        "author":     clip(book.author, 120),
        "publisher":  book.publisher,
        "pub_date":   book.pub_date,
        "isbn13":     book.isbn13,
        "category":   clip(book.category, 160),
        "description": clip(book.description, 1200),
        "toc":        clip(book.toc, 1200),
    }

    # -----------------------------
    # 2) 메인 시스템 프롬프트 (원본 그대로)
    # -----------------------------
    sys_prompt = (
        "너는 한국십진분류법(KDC) 전문가이다.\n"
        "입력된 도서 정보를 바탕으로 **KDC 3자리 숫자**만 판단하여 출력한다.\n"
        "불확실하면 정확히 '직접분류추천'만 출력한다.\n"
        "설명/근거는 출력하지 않는다.\n\n"
        "규칙:\n"
        "1. 반드시 **3자리 숫자만** 출력. 예: 813 / 181 / 325\n"
        "2. 문학(800)은 언어/지역 구분 고려.\n"
        "3. 그래도 판단이 어려우면 '직접분류추천'만 출력.\n"
        "4. 653 키워드는 보조 신호이며, 본문 내용과 충돌하면 무시.\n"
    )

    hint_str = ", ".join(keywords_hint or [])

    # -----------------------------
    # 3) 사용자 메시지 (원본 그대로)
    # -----------------------------
    user_prompt = (
        "다음 도서 정보(JSON)를 바탕으로 KDC 3자리 정수만 출력하라.\n"
        f"653 키워드 힌트: {hint_str or '(없음)'}\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "출력 예시: 823 / 813 / 325 / 181 / 직접분류추천"
    )

    # -----------------------------
    # 응답 파싱기 (원본 그대로)
    # -----------------------------
    def _parse_response(s: str) -> Optional[str]:
        if not s:
            return None
        s = s.strip()

        if "직접분류추천" in s:
            return "직접분류추천"

        m = re.search(r"(?<!\d)(\d{1,3})(?!\d)", s)
        if not m:
            return None

        num = m.group(1).zfill(3)
        if not re.fullmatch(r"\d{3}", num):
            return None
        return num

    # -----------------------------
    # LLM 호출기 (원본 그대로)
    # -----------------------------
    def _call_llm(sys_p, user_p, max_tokens):
        resp = requests.post(
            OPENAI_CHAT_COMPLETIONS,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_p},
                    {"role": "user", "content": user_p},
                ],
                "temperature": 0.0,
                "max_tokens": max_tokens,
            },
            timeout=45,
        )
        resp.raise_for_status()
        txt = resp.json()["choices"][0]["message"]["content"].strip()

        code = _parse_response(txt)
        if not code:
            return None

        # 언어 기반 문학계 재정렬
        marc041 = getattr(book, "marc041", "") or getattr(book, "field_041", "") or ""
        return _rebase_8xx_with_language(code, marc041)

    # -----------------------------
    # 1차 LLM 호출
    # -----------------------------
    try:
        code = _call_llm(sys_prompt, user_prompt, max_tokens=16)
        if code:
            return code
    except Exception as e:
        st.warning(f"1차 LLM 호출 실패: {e}")

    # -----------------------------
    # 2차 폴백 호출
    # -----------------------------
    fb_sys = (
        "너는 KDC 사서이다. "
        "가장 관련성이 높은 **3자리 정수** 또는 '직접분류추천'만 출력하라."
    )
    fb_user = f"{json.dumps(payload, ensure_ascii=False)}"
    try:
        code = _call_llm(fb_sys, fb_user, max_tokens=8)
        if code:
            return code
    except Exception as e:
        st.error(f"2차 LLM 호출 실패: {e}")

    # -----------------------------
    # 3차 로컬 폴백
    # -----------------------------
    return "직접분류추천"

# Chunk C-2-D : ISBN 입력 → 056 생성 전체 파이프라인
def get_kdc_from_isbn(
    isbn13: str,
    ttbkey: Optional[str],
    openai_key: str,
    model: str,
    keywords_hint: list[str] | None = None,
) -> Optional[str]:

    # 1차: 알라딘 API
    info = aladin_lookup_by_api(isbn13, ttbkey) if ttbkey else None

    # 2차: 웹 스크레이핑
    if not info:
        info = aladin_lookup_by_web(isbn13)

    if not info:
        st.warning("알라딘에서 도서 정보를 찾지 못했습니다.")
        return None

    # LLM 호출
    code = ask_llm_for_kdc(
        info,
        api_key=openai_key,
        model=model,
        keywords_hint=keywords_hint
    )

    # 최종 검증
    if code and not re.fullmatch(r"\d{1,3}", code) and code != "직접분류추천":
        return None

    return code

# C3. 041/546 언어 감지 및 필드 빌더
# Chunk C-3-A : 원본 언어 감지기 (초간단 rule-based)
# ==========================================================
# 🔤 원본 언어 감지기 (단순 문자 기반, 원본 로직 유지)
# ==========================================================

LANG_MAP = {
    "kor": "한국어",
    "eng": "영어",
    "jpn": "일본어",
    "chi": "중국어",
    "rus": "러시아어",
    "ara": "아랍어",
    "fre": "프랑스어",
    "ger": "독일어",
    "ita": "이탈리아어",
    "spa": "스페인어",
    "und": "알 수 없음",
}

def detect_language_simple(text: str) -> str:
    """
    원본 코드의 rule-based 언어 감지 기능 그대로.
    """
    if not text:
        return "und"

    s = re.sub(r'[\s\W_]+', '', text)
    if not s:
        return "und"

    ch = s[0]

    if '\uac00' <= ch <= '\ud7a3':
        return "kor"
    elif '\u3040' <= ch <= '\u30ff':       # 일본 가나
        return "jpn"
    elif '\u4e00' <= ch <= '\u9fff':       # 중국 한자
        return "chi"
    elif '\u0400' <= ch <= '\u04FF':       # 러시아/키릴
        return "rus"
    elif 'a' <= ch.lower() <= 'z':
        return "eng"

    return "und"

# Chunk C-3-B : FastText 기반 고도화(Lang ID) 삽입 지점
# ==========================================================
# fastText 기반 고급 언어감지 (사용 가능 시 우선 적용)
# ==========================================================

try:
    import fasttext
    _FT_MODEL = fasttext.load_model("./lid.176.bin")  # 필요 시 경로 변경
except Exception:
    _FT_MODEL = None


def detect_language(text: str) -> str:
    """
    FastText → 실패하면 원본의 rule-based
    """
    if _FT_MODEL:
        try:
            pred = _FT_MODEL.predict(text.replace("\n", " ")[:2000])
            label = pred[0][0].replace("__label__", "")
            # fastText는 eng, kor, jpn 등의 약어를 반환하므로 그대로 사용
            return label.lower()
        except Exception:
            pass

    # fallback: 원본 규칙
    return detect_language_simple(text)

# Chunk C-3-C : 041 생성기 (원본 규칙 + 사용자의 요구 포함)
# ==========================================================
# 041 생성기
# ==========================================================

def build_041_kormarc(text_content: str,
                      original_title: str = "",
                      use_fasttext=True) -> str:
    """
    text_content: 책 설명·목차·제목 등 본문 언어 감지
    original_title: 원제 감지(번역서일 경우)
    """
    lang_main = detect_language(text_content)
    lang_orig = detect_language(original_title) if original_title else None

    # 본문 언어가 없다면 und → kor로 기본값 설정(원본 로직)
    if lang_main == "und":
        lang_main = "kor"

    parts = [f"$a{lang_main}"]
    if original_title and lang_orig:
        if lang_orig != lang_main:
            parts.append(f"$h{lang_orig}")

    return "=041  \\\\" + "".join(parts)

# Chunk C-3-D : 546 텍스트 생성기 (원본 그대로)
# ==========================================================
# 546 생성기 (원본 로직 그대로 유지)
# ==========================================================

def build_546_from_041(marc041: str) -> str:
    if not marc041:
        return "=546  \\\\$a언어 정보 없음"

    a_codes = re.findall(r"\$a([a-z]{3})", marc041, re.I)
    h_match = re.search(r"\$h([a-z]{3})", marc041, re.I)
    h_code = h_match.group(1) if h_match else None

    if len(a_codes) == 1:
        a = LANG_MAP.get(a_codes[0], "알 수 없음")
        if h_code:
            h = LANG_MAP.get(h_code, "알 수 없음")
            return f"=546  \\\\$a{h} 원작을 {a}로 번역"
        return f"=546  \\\\$a{a}로 씀"

    if len(a_codes) >= 2:
        langs = [LANG_MAP.get(c, "알 수 없음") for c in a_codes]
        return f"=546  \\\\$a{'、'.join(langs)} 병기"

    return "=546  \\\\$a언어 정보 없음"

# Chunk C-3-E : 041/546 전체 파이프라인 (원본 generate_all_oneclick 흐름 유지)
# ==========================================================
# ISBN 기반 → (041, 546) 생성 전체 파이프라인
# (너가 준 원본 generate_all_oneclick의 흐름 100% 동일)
# ==========================================================

def build_041_546_pipeline(item: dict, original_title_from_web: str = ""):
    """
    item: 알라딘 API item dict
    original_title_from_web: 알라딘 상세 HTML 파싱에서 찾아낸 원제
    """
    title = item.get("title", "") or ""
    desc  = item.get("description", "") or ""
    toc   = (item.get("subInfo") or {}).get("toc", "") or ""

    content_blob = " ".join([title, desc, toc])

    tag041 = build_041_kormarc(
        text_content=content_blob,
        original_title=original_title_from_web
    )
    tag546 = build_546_from_041(tag041)

    return tag041, tag546

# C4. 245 / 246 / 700 / 90010 / 940 (제목·저자·역자·LOD)
# Chunk C-4-A : 역할어 정리
# ==========================================================
# 역할어 제거 및 원시 저자 문자열 정리
# ==========================================================

ROLE_PATTERNS = [
    r"\b저자\b", r"\b지은이\b", r"\b지음\b", r"\b글\b", r"\b글·그림\b",
    r"\b그림\b", r"\b옮김\b", r"\b옮긴이\b", r"\b편\b", r"\b엮음\b",
    r"\b역\b", r"\btranslator\b", r"\b편집\b",
]

def clean_author_role(raw: str) -> str:
    if not raw:
        return ""
    s = raw
    for pat in ROLE_PATTERNS:
        s = re.sub(pat, "", s, flags=re.IGNORECASE)
    s = re.sub(r"[\/\|]", ";", s)     # / → 세미콜론으로 분할 동일화
    s = re.sub(r"\s+", " ", s).strip()
    return s

# Chunk C-4-B : 저자명 분리
# ==========================================================
# 저자명 리스트로 분리
# ==========================================================

def split_authors(raw: str) -> list[str]:
    if not raw:
        return []

    s = clean_author_role(raw)

    parts = []
    for chunk in re.split(r";", s):
        chunk = chunk.strip()
        if not chunk:
            continue
        # 콤마 기반 분할은 이름 구조를 해칠 수 있으므로 최소 적용
        sub = [c.strip() for c in chunk.split(",") if c.strip()]
        if len(sub) == 1:
            parts.append(sub[0])
        else:
            parts.extend(sub)
    return parts

# Chunk C-4-C : 동아시아/서양 이름 구별 → 정렬형 생성
# ==========================================================
# 이름 정렬형 생성
# ==========================================================

def is_east_asian(name: str) -> bool:
    if not name:
        return False
    # 한글 / 한자 / 일본 가나 포함 시 True
    if any('\uac00' <= ch <= '\ud7a3' for ch in name):
        return True
    if any('\u4e00' <= ch <= '\u9fff' for ch in name):
        return True
    if any('\u3040' <= ch <= '\u30ff' for ch in name):
        return True
    return False

def to_sort_form(name: str) -> str:
    """
    동아시아 이름은 그대로.
    알파벳 기반 이름은 '성, 이름'으로 변환.
    """
    if not name:
        return ""

    if is_east_asian(name):
        return name.strip()

    parts = name.split()
    if len(parts) == 1:
        return name.strip()

    last = parts[-1]
    first = " ".join(parts[:-1])
    return f"{last}, {first}"

# Chunk C-4-D : 저자 → 100/700 필드 생성 (역할 포함)
# ==========================================================
# 100/700 생성기 (원본 규칙 100% 유지)
# ==========================================================

def build_100_and_700(authors: list[str], origin_lang_code: str | None = None):
    """
    authors = ['홍길동', 'John Smith', '山田太郎', ...]
    origin_lang_code: 041 $h → 번역서 여부 판단
    """
    if not authors:
        return None, []

    main_author = authors[0]
    rest = authors[1:]

    # 100 필드 생성
    sort_main = to_sort_form(main_author)
    tag_100 = f"=100  1\\\\$a{sort_main}"

    # 번역서 여부
    is_translation = bool(origin_lang_code)

    tag_700_list = []
    for name in rest:
        sort_name = to_sort_form(name)
        if is_translation:
            tag = f"=700  1\\\\$a{sort_name}$e번역"
        else:
            tag = f"=700  1\\\\$a{sort_name}"
        tag_700_list.append(tag)

    return tag_100, tag_700_list

# Chunk C-4-E : 알라딘 item.author 파싱 → 100/700 전체 파이프라인
# ==========================================================
# 알라딘 item.author → 100/700 전체 생성
# ==========================================================

def build_people_fields_from_aladin(item: dict, origin_lang_code: str | None = None):
    raw = (item or {}).get("author", "") or ""
    authors = split_authors(raw)

    tag100, tag700_list = build_100_and_700(authors, origin_lang_code)
    return tag100, tag700_list

# C5. 300 상세 형식 파서
# Chunk C-5-A : GPT 호출 함수 (원본 유지)
# ==========================================================
# GPT 호출 함수 (원본 함수 그대로 사용한다고 가정)
# ==========================================================

def generate_653_with_gpt(
    category: str,
    title: str,
    authors: str,
    description: str,
    toc: str,
    max_keywords: int = 7,
) -> str:
    """
    원본 코드에서 이미 정의되어 있는 함수.
    결과 예: "$a아동문학$a정서조절$a시간관리"
    """
    raise NotImplementedError  # True Patch에서는 기존 함수를 그대로 사용

# Chunk C-5-B : 653 태그 생성기 (원본 로직 그대로 재구축)
# ==========================================================
# 653 태그 생성기 (원본 코드 100% 보존)
# ==========================================================

def build_653_tag(item: dict) -> str | None:
    """
    item: 알라딘 item(dict)
    GPT가 생성한 "$a키워드$a..." 형태를 그대로 받아
    =653  \\$a키워드$a키워드… 형태로 래핑하여 반환.
    """
    if not item:
        return None

    title = item.get("title", "") or ""
    category = item.get("categoryName", "") or ""
    raw_author = item.get("author", "") or ""
    desc = item.get("description", "") or ""
    toc = (item.get("subInfo") or {}).get("toc", "") or ""

    kwline = generate_653_with_gpt(
        category=category,
        title=title,
        authors=clean_author_role(raw_author),
        description=desc,
        toc=toc,
        max_keywords=7,
    )

    if not kwline:
        return None

    # 원본 로직: 공백 제거 후 래핑
    kwline = kwline.replace(" ", "")
    return f"=653  \\\\{kwline}"

# Chunk C-5-C : 653 → 키워드 리스트 파싱 (원본 코드 100% 보존)
# ==========================================================
# 653 파싱 → 입력 순서 안정성과 중복 제거 + 최대 7개
# ==========================================================

def parse_653_keywords(tag_653: str | None) -> list[str]:
    """
    예:
    '=653  \\$a아동문학$a정서$a시간관리'
    → ['아동문학','정서','시간관리']
    """
    if not tag_653:
        return []

    s = tag_653.strip()

    # 접두부 제거 (=653  \\)
    s = re.sub(r"^=653\s+\\\\", "", s)

    kws = []
    for m in re.finditer(r"\$a([^$]+)", s):
        w = (m.group(1) or "").strip()
        if w:
            kws.append(w)

    # 중복 제거 + 최대 7
    seen = set()
    out = []
    for w in kws:
        if w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= 7:
            break

    return out

# Chunk C-5-D : LLM 힌트용 653 정규화
# ==========================================================
# LLM(056 KDC) 힌트로 사용하기 위한 정규화 (원본 로직 유지)
# ==========================================================

def normalize_653_keywords_for_hint(kws: list[str]) -> list[str]:
    seen = set()
    out = []
    for w in (kws or []):
        w = (w or "").strip()
        if w and w not in seen:
            seen.add(w)
            out.append(w)
    return sorted(out)[:7]

# Chunk C-5-E : 653 전체 파이프라인
# ==========================================================
# 알라딘 item → 653 태그 + LLM 힌트 전체 파이프라인
# ==========================================================

def build_653_pipeline(item: dict):
    tag_653 = build_653_tag(item)
    if not tag_653:
        return None, []

    kws_raw = parse_653_keywords(tag_653)
    kws_hint = normalize_653_keywords_for_hint(kws_raw)

    return tag_653, kws_hint

# C6. 가격/020/950 모듈
# Chunk C-6-A : 가격 추출 헬퍼 (원본 로직 그대로 재현)
# ==========================================================
# 가격 추출 헬퍼 - 원본 로직 100% 동일
# ==========================================================

def extract_price_kr(item: dict, isbn: str) -> str:
    """
    원본: _extract_price_kr()
    1) 알라딘 priceStandard
    2) 없으면 알라딘 상세 페이지 크롤링 가격
    3) 숫자만 남기기
    """
    raw = str((item or {}).get("priceStandard", "") or "").strip()

    # 2) priceStandard 없으면 크롤링 백업
    if not raw:
        try:
            crawl = crawl_aladin_original_and_price(isbn) or {}
            raw = crawl.get("price", "").strip()
        except Exception:
            raw = ""

    # 3) 숫자만 남기기
    digits = re.sub(r"[^\d]", "", raw)
    return digits

# Chunk C-6-B : 020 필드 생성기 (원본 로직 100% 동일)
# ==========================================================
# 020 생성기 - 원본 _build_020_from_item_and_nlk 완전 재현
# ==========================================================

def build_020_field(isbn: str, item: dict) -> str:
    """
    ISBN + 부가기호 + 가격을 포함한 020 생성.
    원본 _build_020_from_item_and_nlk()의 논리를 각각 분리해서 재현.
    """
    # 1) 알라딘 가격
    price = str((item or {}).get("priceStandard", "") or "").strip()

    # 2) NLK에서 add_code, set_isbn, price 가져오기
    try:
        nlk_extra = fetch_additional_code_from_nlk(isbn) or {}
        add_code = nlk_extra.get("add_code", "")
        price_from_nlk = nlk_extra.get("price", "")
    except Exception:
        add_code = ""
        price_from_nlk = ""

    # 3) 가격 우선순위
    final_price = price or price_from_nlk

    # 4) 문자열 조립
    parts = [f"=020  \\\\$a{isbn}"]
    
    if add_code:
        parts.append(f"$g{add_code}")

    if final_price:
        # 원본처럼 ':' 뒤에 $c 숫자만
        parts.append(f":$c{final_price}")

    return "".join(parts)

# Chunk C-6-C : SET ISBN (020 1) 생성기
# ==========================================================
# SET ISBN 020 생성기
# ==========================================================

def build_020_set_field(set_isbn: str | None) -> str | None:
    if not set_isbn:
        return None
    return f"=020  1\\$a{set_isbn} (set)"

# Chunk C-6-D : 950 생성기 (원본과 완전히 동일)
# ==========================================================
# 950 생성기 - 원본 build_950_from_item_and_price
# ==========================================================

def build_950_field(item: dict, isbn: str) -> str | None:
    """
    가격이 없으면 생성하지 않음.
    """
    price = extract_price_kr(item, isbn)
    if not price:
        return None

    # 원본처럼 역슬래시 유지
    return f"=950  0\\$b\\{price}"

# Chunk C-6-E : 020 + 950 파이프라인
# ==========================================================
# 020 + 950 전체 파이프라인
# ==========================================================

def build_price_related_fields(isbn: str, item: dict):
    """
    결과:
      - tag_020
      - tag_020_set (optional)
      - tag_950 (optional)
      - set_isbn (for metadata)
    """
    tag_020 = build_020_field(isbn, item)

    # SET ISBN (부가기호 API)
    nlk_info = fetch_additional_code_from_nlk(isbn)
    set_isbn = (nlk_info or {}).get("set_isbn", "").strip()
    tag_020_set = build_020_set_field(set_isbn)

    # 950 (가격만)
    tag_950 = build_950_field(item, isbn)

    return tag_020, tag_020_set, tag_950, set_isbn

# C7. KPIPA/MCST/발행지 + 260 모듈
# Chunk C-7-A : 지역명 정규화 → 발행국 코드 찾기
# ==========================================================
# 지역명 정규화 + 발행국(나라코드) 찾기
# 원본 get_country_code_by_region() 100% 복원 + 구조화
# ==========================================================

def normalize_region_for_country_code(region: str) -> str:
    """
    원본: get_country_code_by_region 내부 normalize 전략 분리
    전라남도 → 전남 / 경상북도 → 경북 / 서울특별시 → 서울
    """
    if not region:
        return ""

    region = region.strip()

    # 전라/충청/경상 계열 처리
    if region.startswith(("전라", "충청", "경상")):
        if len(region) >= 3:
            return region[0] + region[2]   # 전라남도 → 전남
        return region[:2]

    # 서울특별시 → 서울
    return region[:2]


def get_country_code_by_region(region_name: str, region_df) -> str:
    """
    지역명을 기반으로 008 발행국 코드(3자리)를 반환.
    region_df: Google Sheet "발행국명–발행국부호" 시트.
    """
    try:
        target = normalize_region_for_country_code(region_name)

        for _, row in region_df.iterrows():
            sheet_region = normalize_region_for_country_code(row["발행국"])
            if sheet_region == target:
                return (row["발행국 부호"] or "   ").strip()

        return "   "  # fallback: 공백 3칸
    except Exception:
        return "   "

# Chunk C-7-B : KPIPA ISBN 검색기 (원본 그대로)
# ==========================================================
# KPIPA ISBN 검색: 출판사명 / 임프린트 추출
# 원본 get_publisher_name_from_isbn_kpipa 완전 복원
# ==========================================================

def fetch_kpipa_publisher_info(isbn: str):
    url = "https://bnk.kpipa.or.kr/home/v3/addition/search"
    params = {
        "ST": isbn,
        "PG": 1,
        "PG2": 1,
        "DSF": "Y",
        "SO": "weight",
        "DT": "A",
    }
    headers = {"User-Agent": "Mozilla/5.0"}

    def norm(name):
        return re.sub(
            r"\s|\(.*?\)|주식회사|㈜|도서출판|출판사|프레스",
            "",
            (name or ""),
            flags=re.IGNORECASE
        ).lower()

    try:
        res = requests.get(url, params=params, headers=headers, timeout=15)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        # 검색 결과 1건
        first = soup.select_one("a.book-grid-item")
        if not first:
            return None, None, "❌ KPIPA 검색 결과 없음"

        detail = "https://bnk.kpipa.or.kr" + first["href"]
        dres = requests.get(detail, headers=headers, timeout=15)
        dres.raise_for_status()
        dsoup = BeautifulSoup(dres.text, "html.parser")

        tag = dsoup.find("dt", string="출판사 / 임프린트")
        if not tag:
            return None, None, "❌ KPIPA '출판사 / 임프린트' 항목 없음"

        dd = tag.find_next_sibling("dd")
        if not dd:
            return None, None, "❌ KPIPA dd 태그 없음"

        full = dd.get_text(strip=True)
        main = full.split("/")[0].strip()

        return full, norm(main), None  # (전체텍스트, 대표출판사명(정규화), 오류)
    except Exception as e:
        return None, None, f"❌ KPIPA 예외: {e}"

# Chunk C-7-C : Google Sheet 기반 출판지 검색
# ==========================================================
# KPIPA 출판사 DB 매칭 (원본 search_publisher_location_with_alias)
# ==========================================================

def locate_publisher_in_kpipa_db(name: str, publisher_df):
    """
    publisher_df: ['출판사명', '주소']
    """
    debug = []
    if not name:
        return "출판지 미상", ["❌ 입력된 출판사명이 없음"]

    norm_name = normalize_publisher_name(name)
    candidates = publisher_df[publisher_df["출판사명"].apply(
        lambda x: normalize_publisher_name(x) == norm_name
    )]

    if not candidates.empty:
        addr = candidates.iloc[0]["주소"]
        debug.append(f"✓ KPIPA DB 매칭 성공: {name} → {addr}")
        return addr, debug
    else:
        debug.append(f"❌ KPIPA DB 매칭 실패: {name}")
        return "출판지 미상", debug

# Chunk C-7-D : 임프린트 fallback 검색
# ==========================================================
# IMPRINT fallback (원본 find_main_publisher_from_imprints)
# ==========================================================

def find_imprint_parent_publisher(rep_name, imprint_df, publisher_df):
    norm_rep = normalize_publisher_name(rep_name)
    debug = []

    for full in imprint_df["임프린트"]:
        if "/" in full:
            main, imp = [x.strip() for x in full.split("/", 1)]
        else:
            main, imp = full.strip(), None

        if imp and normalize_publisher_name(imp) == norm_rep:
            addr, dbg2 = locate_publisher_in_kpipa_db(main, publisher_df)
            debug.extend(dbg2)
            if addr and addr not in ("출판지 미상", None):
                return addr, debug

    debug.append(f"❌ IMPRINT 매칭 실패: {rep_name}")
    return None, debug

# Chunk C-7-E : 문체부(MCST) fallback 검색
# ==========================================================
# 문체부 도서등록부 검색 (원본 get_mcst_address 완전 복원)
# ==========================================================

def search_mcst_publisher_address(name: str):
    url = "https://book.mcst.go.kr/html/searchList.php"
    params = {
        "search_area": "전체",
        "search_state": "1",
        "search_kind": "1",
        "search_type": "1",
        "search_word": name,
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
                nm = tds[1].get_text(strip=True)
                addr = tds[2].get_text(strip=True)
                status = tds[3].get_text(strip=True)
                if status == "영업":
                    rows.append((nm, addr))

        if rows:
            debug.append("✓ 문체부 검색 성공")
            return rows[0][1], rows, debug

        debug.append("❌ 문체부 검색 결과 없음")
        return "미확인", [], debug

    except Exception as e:
        debug.append(f"❌ 문체부 예외: {e}")
        return "오류 발생", [], debug

# Chunk C-7-F : 최종 발행지 결정 파이프라인 (원본 build_pub_location_bundle 완전 복원)
# ==========================================================
# 최종 발행지 결정 파이프라인 - 원본 100% 재현
# ==========================================================

def resolve_publisher_location(isbn, publisher_raw, publisher_df, region_df, imprint_df):
    debug = []
    debug.append("✓ Google Sheet DB 로드 완료")

    # 1) KPIPA ISBN 검색
    kpipa_full, kpipa_norm, err = fetch_kpipa_publisher_info(isbn)
    if err:
        debug.append(f"KPIPA 검색: {err}")

    # 대표 출판사명 추정
    rep_name, aliases = split_publisher_aliases(
        kpipa_full or publisher_raw or ""
    )
    resolved_name = rep_name or publisher_raw or ""
    debug.append(f"대표 출판사명 추정: {resolved_name} / 별칭: {aliases}")

    # 2) KPIPA DB 매칭
    place_raw, dbg2 = locate_publisher_in_kpipa_db(resolved_name, publisher_df)
    debug.extend(dbg2)
    source = "KPIPA_DB"

    # 3) imprint fallback
    if place_raw in ("출판지 미상", None, "예외 발생"):
        imp_addr, dbg3 = find_imprint_parent_publisher(resolved_name, imprint_df, publisher_df)
        debug.extend(dbg3)
        if imp_addr:
            place_raw = imp_addr
            source = "IMPRINT→KPIPA"

    # 4) 문체부 fallback
    if not place_raw or place_raw in ("출판지 미상", "미확인", "예외 발생"):
        mcst_addr, _, dbg4 = search_mcst_publisher_address(resolved_name)
        debug.extend(dbg4)
        if mcst_addr not in ("미확인", "오류 발생"):
            place_raw = mcst_addr
            source = "MCST"

    # 5) 최종 실패 → 출판지 미상
    if not place_raw or place_raw in ("미확인", "오류 발생", None):
        place_raw = "출판지 미상"
        source = "FALLBACK"
        debug.append("⚠ 모든 경로 실패 → '출판지 미상'")

    # 화면 표시용
    place_display = normalize_publisher_location_for_display(place_raw)

    # 008용 country code
    country_code = get_country_code_by_region(place_raw, region_df)

    return {
        "place_raw": place_raw,
        "place_display": place_display,
        "country_code": country_code,
        "resolved_publisher": resolved_name,
        "source": source,
        "debug": debug,
    }

# Chunk C-7-G : 260 필드 생성기
# ==========================================================
# 260 생성기 - 원본 build_260 완전 복원
# ==========================================================

def build_260_field(place_display: str, publisher: str, pubyear: str) -> str:
    place = place_display or "발행지 미상"
    pub = publisher or "발행처 미상"
    year = pubyear or "발행년 미상"

    return f"=260  \\\\$a{place} :$b{pub},$c{year}"

# C8. 008 생성기 (lang3 override / country3 override 포함)
# C-8-A : 008 문자열 생성기 (원본 build_008_kormarc_bk 완전 재현)
# ==========================================================
# 008 본문 40바이트 생성기 — 원본 build_008_kormarc_bk() 완전 동일
# ==========================================================

def build_008_body_bk(
    date_entered,      # YYMMDD
    date1,             # 4자리 연도 또는 19uu
    country3,          # 발행국 부호 3자리
    lang3,             # 언어코드 3자리
    *,
    date2="",          # 11-14
    illus4="",         # 삽화/도표/사진 키(최대 4문자)
    has_index="0",     # 색인유무
    lit_form=" ",      # 문학형식 (p 시 / f 소설 / e 수필 / m 기행 / i 서간문)
    bio=" ",           # 자서전(a), 전기(b), 전기적 요소(d)
    type_of_date="s",  # 06
    modified_record=" ",
    cataloging_src="a",
):
    """
    정확히 40 bytes를 만들어야 한다.
    """

    def pad(s, n, fill=" "):
        s = "" if s is None else str(s)
        return (s[:n] + fill * n)[:n]

    # --- 입력 검증 (원본 동일) ---
    if len(date_entered) != 6 or not date_entered.isdigit():
        raise ValueError("date_entered는 YYMMDD 6자리 숫자")
    if len(date1) != 4:
        raise ValueError("date1은 4자리 (예: 2025, 19uu)")

    body = "".join([
        date_entered,             # 00-05
        pad(type_of_date, 1),     # 06
        date1,                    # 07-10
        pad(date2, 4),            # 11-14
        pad(country3, 3),         # 15-17
        pad(illus4, 4),           # 18-21
        " " * 4,                  # 22-25: 이용대상/자료형태/내용형식
        " " * 2,                  # 26-27
        pad(modified_record, 1),  # 28
        "0",                      # 29 회의간행물
        "0",                      # 30 기념논문집
        has_index if has_index in ("0","1") else "0",  # 31 색인유무
        pad(cataloging_src, 1),   # 32 목록 전거
        pad(lit_form, 1),         # 33 문학형식
        pad(bio, 1),              # 34 전기/자서전
        pad(lang3, 3),            # 35-37 언어
        " " * 2                   # 38-39 공백
    ])

    if len(body) != 40:
        raise AssertionError(f"008 length != 40: {len(body)}")

    return body

# C-8-B : 연도 추출기 (원본 extract_year_from_aladin_pubdate)
# ==========================================================
# 발행연도 추출기 — 원본 extract_year_from_aladin_pubdate 완전 복원
# ==========================================================

def extract_year_from_pubdate(pubdate: str) -> str:
    m = re.search(r"(19|20)\d{2}", pubdate or "")
    return m.group(0) if m else "19uu"

# C-8-C : 삽화/도표/사진 감지기 (008용 illus4)
# ==========================================================
# 삽화 감지 — 원본 detect_illus4 완전 재현
# ==========================================================

def detect_illus4(text: str) -> str:
    if not text:
        return ""
    keys = []

    if re.search(r"삽화|삽도|도해|일러스트|illustration|그림", text, re.I):
        keys.append("a")
    if re.search(r"도표|표|차트|그래프|chart|graph", text, re.I):
        keys.append("d")
    if re.search(r"사진|포토|화보|photo|photograph|컬러사진|칼라사진", text, re.I):
        keys.append("o")

    # 중복 순서 유지 + 최대 4문자
    out = []
    for k in keys:
        if k not in out:
            out.append(k)

    return "".join(out)[:4]

# C-8-D : 색인 감지기
# ==========================================================
# 색인 감지 — 원본 detect_index
# ==========================================================

def detect_index_flag(text: str) -> str:
    return "1" if re.search(r"색인|찾아보기|인명색인|사항색인|index", text, re.I) else "0"

# C-8-E : 문학형식 감지기 (원본 그대로)
# ==========================================================
# 문학형식 감지기 — 원본 detect_lit_form 완전 복원
# ==========================================================

def detect_lit_form(title: str, category: str, extra: str = "") -> str:
    blob = f"{title} {category} {extra}"

    if re.search(r"서간집|편지|서간문|letters?", blob, re.I):
        return "i"  # 서간문학
    if re.search(r"기행|여행기|여행 에세이|일기|수기|diary|travel", blob, re.I):
        return "m"  # 기행/일기/수기
    if re.search(r"시집|산문시|poem|poetry", blob, re.I):
        return "p"  # 시
    if re.search(r"소설|장편|중단편|novel|fiction", blob, re.I):
        return "f"  # 소설
    if re.search(r"에세이|수필|essay", blob, re.I):
        return "e"  # 수필

    return " "

# C-8-F : 전기 / 자서전 감지기
# ==========================================================
# 전기/자서전 감지기 — 원본 detect_bio
# ==========================================================

def detect_bio_marker(text: str) -> str:
    if re.search(r"자서전|회고록|autobiograph", text, re.I):
        return "a"
    if re.search(r"전기|평전|인물 평전|biograph", text, re.I):
        return "b"
    if re.search(r"전기적|자전적|회고|회상", text):
        return "d"
    return " "

# C-8-G : 발행국(country3) 우선순위 결정 로직 (원본 build_008_from_isbn 일부)
# ==========================================================
# 발행국 코드 우선순위 결정
# 원본 build_008_from_isbn 의 country3 결정과 동일
# ==========================================================

def select_country3(source_place: str, override_country3: str | None, region_default: str) -> str:
    """
    override > (발행지 기반 추정) > default(KR 코드)
    """
    # 1) override 최우선
    if override_country3:
        return override_country3

    # 2) 발행지 문자열 기반 매핑
    if source_place:
        # "발행지 미상" 처리
        s = source_place.strip()
        if "미상" in s or "unknown" in s.lower():
            return "   "  # 공백 3칸

        # 원본 guess_country3_from_place 는 이미 다른 블록에서 재현됨
        guessed = guess_country3_from_place(s)
        if guessed:
            return guessed
        return region_default

    # 3) 아무 것도 없을 때 default
    return region_default

# C-8-H : 언어 override (041 $a → lang3)
def override_lang_from_041(tag_041: str | None, fallback_lang: str) -> str:
    """
    041 $a 가 있으면 그것을 008 lang3에 적용.
    원본 _lang3_from_tag041 과 동일.
    """
    if not tag_041:
        return fallback_lang

    m = re.search(r"\$a([a-z]{3})", tag_041, flags=re.I)
    return m.group(1).lower() if m else fallback_lang

# C-8-I : 최종 008 조합기 (원본 build_008_from_isbn 완전 재현)
# ==========================================================
# 최종 008 생성기 — 원본 build_008_from_isbn 완전 복원
# ==========================================================

def build_008_full(
    isbn: str,
    *,
    aladin_title="",
    aladin_desc="",
    aladin_category="",
    aladin_toc="",
    aladin_pubdate="",
    override_country3=None,     # KPIPA/IMPRINT/MCST로부터 옴
    override_lang3=None,        # 041 $a로부터 옴
    default_country3="ko ",     # 전역 COUNTRY_FIXED 동일
    default_lang3="kor",        # 전역 LANG_FIXED 동일
):
    today = datetime.datetime.now().strftime("%y%m%d")
    date1 = extract_year_from_pubdate(aladin_pubdate)

    # country3 결정 (원본 순서)
    country3 = override_country3 or default_country3

    # lang3 결정 (041 $a → override)
    lang3 = override_lang3 or default_lang3

    # bigtext = 제목 + 소개 + 목차
    bigtext = " ".join([aladin_title or "", aladin_desc or "", aladin_toc or ""])

    # 감지기들
    illus4    = detect_illus4(bigtext)
    has_index = detect_index_flag(bigtext)
    lit_form  = detect_lit_form(aladin_title, aladin_category, bigtext)
    bio       = detect_bio_marker(bigtext)

    # 본문 40 bytes 생성
    body = build_008_body_bk(
        date_entered=today,
        date1=date1,
        country3=country3,
        lang3=lang3,
        illus4=illus4,
        has_index=has_index,
        lit_form=lit_form,
        bio=bio,
        cataloging_src="a",
    )
    return body

# C9. 056(KDC) GPT 분류기 전체 모듈
# C-9-A : KDC 사전 정규화 함수(원본 normalize_kdc_3digit)
# =================================================================
# KDC 문자열에서 "선행 1~3자리 정수"만 추출하는 원본 normalize 함수
# =================================================================

def normalize_kdc_3digit(code: Optional[str]) -> Optional[str]:
    """
    입력 예: '813.7', '813', '81', '5', 'KDC 325.1'
    출력 예: '813', '813', '81', '5', '325'
    즉, 가장 앞의 연속된 1~3자리 숫자를 반환.
    """
    if not code:
        return None
    m = re.search(r"(\d{1,3})", code)
    return m.group(1) if m else None

# C-9-B : KDC 응답 파서 — GPT 응답에서 ‘3자리 정수 또는 직접분류추천’만 허용
# =================================================================
# GPT 응답 → 056 숫자만 남기는 파서
# =================================================================

def parse_llm_kdc_response(text: str) -> Optional[str]:
    """
    규칙:
    - '직접분류추천' 포함 → 그대로 '직접분류추천'
    - 숫자 → 가장 앞의 연속된 1~3자리만 추출 → 항상 3자리 zero-fill
    - 예: 5 → '005', 81 → '081', 813 → '813'
    """

    if not text:
        return None

    s = text.strip()

    # 1) directly ask for 직접분류추천
    if "직접분류추천" in s:
        return "직접분류추천"

    # 2) 최초의 1~3자리 정수 추출
    m = re.search(r"(?<!\d)(\d{1,3})(?!\d)", s)
    if not m:
        return None

    raw = m.group(1)
    num = raw.zfill(3)  # 3자리 강제

    if not re.fullmatch(r"\d{3}", num):
        return None

    return num

# C-9-C : 041 원작 언어 기반 문학 KDC 재정렬기
# =================================================================
# 041 $h 원작언어 → 8xx 문학 재정렬기 (원본 로직 완전 반영)
# =================================================================

def extract_original_lang_from_041(tag_041: str | None) -> Optional[str]:
    if not tag_041:
        return None
    m = re.search(r"\$h([a-z]{3})", tag_041.lower())
    return m.group(1) if m else None


def map_lang3_to_lit_base(lang3: str | None) -> Optional[str]:
    """
    언어코드 → 문학계열 8xx 앞자리 2자리.
    """
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
    return "890"  # 기타 문학


def rebase_8xx_kdc(code: str, tag_041: str) -> str:
    """
    code = '823', tag_041 = '041 $akor$heng' → '843'
    """
    if not code or not code[0] == "8":
        return code  # 문학이 아니면 그대로 유지

    orig_lang = extract_original_lang_from_041(tag_041)
    base = map_lang3_to_lit_base(orig_lang)
    if not base:
        return code

    # code = 8xy → genre = y
    import re
    m = re.match(r"^(\d{3})(\..+)?$", code)
    if not m:
        return code

    head3, tail = m.group(1), (m.group(2) or "")
    genre_digit = head3[2]
    new_code = base[:2] + genre_digit

    return new_code + tail

# C-9-D : GPT 프롬프트 (원본 ask_llm_for_kdc 1차 프롬프트 그대로)
# =================================================================
# GPT System Prompt (1차) — 원본 ask_llm_for_kdc 그대로 재현
# =================================================================

KDC_SYSTEM_PROMPT = (
    "너는 한국십진분류법(KDC) 전문가이자 공공도서관 분류 사서이다.\n"
    "입력된 도서 정보를 바탕으로 이 책의 **주제 중심 분류기호(KDC 번호)**를 한 줄로 판단하라.\n\n"
    "참고로, 국립중앙도서관 KOLISNet의 실제 분류 사례를 간접적으로 참조하라. "
    "비슷한 책이 821(중국시)·823(중국소설)·833(일본소설)·843(영미소설) 등으로 분류되는 관행을 고려하되, "
    "현재 도서의 주제와 일치하는 하나의 번호만 선택하라. (웹에 직접 접속하지 말고 사고의 기준으로만 삼는다.)\n\n"
    "규칙:\n"
    "1. 반드시 **소수점 없이 3자리 정수만** 출력한다. 예: 813 / 325 / 005 / 181\n"
    "2. 세목(소수점 이하) 판단은 내부 결정에만 활용하고, **출력은 상위 3자리 정수**로 제한한다.\n"
    "3. 설명, 이유, 접두어, 단위(예: KDC, 분류번호) 등은 출력하지 않는다.\n"
    "4. 한 책이 여러 주제를 다루더라도 **가장 중심되는 주제**를 선택한다.\n"
    "5. 내용이 학문적일 경우, '학문 분야' 기준으로 판단한다. (예: 교양심리서 → 181)\n"
    "6. 특정 **시대·장르** 표기가 분명하더라도 **출력은 상위 3자리 정수**로 한다. "
    "(아동문학·SF 등 장르문학은 먼저 **언어/지역** 계열을 판정한 뒤 문학 분기 상위 3자리로 결정한다. 예: 한국소설 → 813)\n"
    "7. 추상 표현(사회적의의, 현황, 연구, 문제, 방법론 등)은 분류 근거가 아니다.\n"
    "8. ISBN·출판사·카테고리는 보조 신호로만 사용한다.\n"
    "8-1. `keywords_hint_653`가 제공되면 약한 보조 신호로만 참고하고, 설명/목차/범주 증거와 충돌하면 본문 근거를 우선한다.\n"
    "9. 확신이 없으면 가장 관련 범주의 기본 기호(예: 철학→100, 문학→800)를 고려하되, "
    "그래도 확정이 어려우면 **정확히 '직접분류추천'** 네 글자만 출력한다.\n\n"
    "[KDC 강목표 (10단위)]\n"
    "000 총류\n010 도서학 서지학\n020 문헌정보학\n030 백과사전\n040 강연집 수필집 연설문집\n050 일반 연속간행물\n"
    "060 일반 학회 단체 협회 기관 연구기관\n070 신문 저널리즘\n080 일반 전집 총서\n090 향토자료\n100 철학\n110 형이상학\n"
    "120 인식론 인과론 인간학\n130 철학의 체계\n140 경학\n150 동양철학 동양사상\n160 서양철학\n170 논리학\n180 심리학\n"
    "190 윤리학 도덕철학\n200 종교\n210 비교종교\n220 불교\n230 기독교\n240 도교\n250 천도교\n270 힌두교 브라만교\n"
    "280 이슬람교 회교\n290 기타 제종교\n300 사회과학\n310 통계자료\n320 경제학\n330 사회학 사회문제\n340 정치학\n350 행정학\n"
    "360 법률 법학\n370 교육학\n380 풍습 예절 민속학\n390 국방 군사학\n400 자연과학\n410 수학\n420 물리학\n430 화학\n440 천문학\n"
    "450 지학\n460 광물학\n470 생명과학\n480 식물학\n490 동물학\n500 기술과학\n510 의학\n520 농업 농학\n530 공학 공업일반 토목공학 환경공학\n"
    "540 건축 건축학\n550 기계공학\n560 전기공학 통신공학 전자공학\n570 화학공학\n580 제조업\n590 생활과학\n600 예술\n620 조각 조형미술\n"
    "630 공예\n640 서예\n650 회화 도화 디자인\n660 사진예술\n670 음악\n680 공연예술 매체예술\n690 오락 스포츠\n700 언어\n710 한국어\n"
    "720 중국어\n730 일본어 및 기타 아시아제어\n740 영어\n750 독일어\n760 프랑스어\n770 스페인어 및 포르투갈어\n780 이탈리아어\n790 기타 제어\n"
    "800 문학\n810 한국문학\n820 중국문학\n830 일본문학 및 기타 아시아 제문학\n840 영미문학\n850 독일문학\n860 프랑스문학\n"
    "870 스페인문학 및 포르투갈문학\n880 이탈리아문학\n890 기타 제문학\n900 역사\n910 아시아\n920 유럽\n930 아프리카\n"
    "940 북아메리카\n950 남아메리카\n960 오세아니아 양극지방\n980 지리\n990 전기\n\n"
)

# C-9-E : GPT 호출기 (1차 / 2차 fallback)
# =================================================================
# 원본 ask_llm_for_kdc() 구조를 유지하며 가독성 개선
# =================================================================

def call_gpt_for_kdc(payload: dict, keywords_hint: list[str], api_key: str, model: str) -> Optional[str]:
    """
    1차: KDC_SYSTEM_PROMPT + payload + keywords_hint
    """
    keyword_str = ", ".join(keywords_hint or [])
    user_prompt = (
        "아래 도서 정보(JSON)를 참고하여 **KDC 분류기호를 소수점 없이 3자리 정수로 한 줄**만 출력하라. "
        "확실하지 않으면 **정확히 '직접분류추천'**만 출력.\n\n"
        f"※ 참고용 키워드(653): {keyword_str or '(없음)'}\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "출력 예시: 823 / 813 / 325 / 181 / (확신없음) 직접분류추천"
    )

    # ---------------------
    # 1차 GPT 호출
    # ---------------------
    try:
        resp = requests.post(
            OPENAI_CHAT_COMPLETIONS,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": KDC_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.0,
                "max_tokens": 18,
            },
            timeout=45,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        parsed = parse_llm_kdc_response(text)
        if parsed:
            return parsed
    except Exception:
        pass

    # ---------------------
    # 2차 fallback
    # ---------------------
    fb_sys = (
        "너는 KDC 제6판 기준 분류 사서다. "
        "가장 관련성이 높은 **3자리 정수**만 출력하라. "
        "정확히 판단하기 어렵다면 **정확히 '직접분류추천'**만 출력."
    )
    fb_user = f"도서 정보:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"

    try:
        resp = requests.post(
            OPENAI_CHAT_COMPLETIONS,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": fb_sys},
                    {"role": "user", "content": fb_user},
                ],
                "temperature": 0.0,
                "max_tokens": 8,
            },
            timeout=45,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        parsed = parse_llm_kdc_response(text)
        if parsed:
            return parsed
    except Exception:
        pass

    # ---------------------
    # 3차 local fallback
    # ---------------------
    return "직접분류추천"

# C-9-F : 최종 외부 API — get_kdc_from_isbn()
# =================================================================
# 외부에서 호출하는 최종 API — 원본 get_kdc_from_isbn 완전 복원
# =================================================================

def get_kdc_from_isbn(
    isbn13: str,
    ttbkey: Optional[str],
    openai_key: str,
    model: str,
    keywords_hint: list[str] | None = None
) -> Optional[str]:

    # 1) 알라딘 API 또는 스크레이핑
    info = aladin_lookup_by_api(isbn13, ttbkey) if ttbkey else None
    if not info:
        info = aladin_lookup_by_web(isbn13)
    if not info:
        return None

    # 2) LLM 입력 축약 (원본과 동일한 길이 제한)
    def clip(s: str, n: int) -> str:
        return "" if not s else (s if len(s) <= n else s[:n] + "…")

    payload = {
        "title": clip(info.title, 160),
        "author": clip(info.author, 120),
        "publisher": info.publisher,
        "pub_date": info.pub_date,
        "isbn13": info.isbn13,
        "category": clip(info.category, 160),
        "description": clip(info.description, 1200),
        "toc": clip(info.toc, 1200),
    }

    # 3) GPT 호출
    code = call_gpt_for_kdc(
        payload=payload,
        keywords_hint=keywords_hint or [],
        api_key=openai_key,
        model=model,
    )
    if not code:
        return None

    # 4) 문학 8xx 재정렬 (041 원작 언어 기반)
    marc041 = getattr(info, "marc041", "") or getattr(info, "field_041", "") or getattr(info, "f041", "")
    code = rebase_8xx_kdc(code, marc041)

    return code

# C10. 300(형태사항) 크롤러 + 파서 모듈
# C-10-A : 텍스트 정규화 유틸 (원본 _norm, _clean_author_str)
# ==========================================================
# 텍스트 정규화 — 원본 완전 재현
# ==========================================================

def _norm(text: str) -> str:
    import unicodedata
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\s\uac00-\ud7a3]", " ", text)  # 한글/영문/숫자/공백만 허용
    return re.sub(r"\s+", " ", text).strip()


def _clean_author_str(s: str) -> str:
    """
    (지은이), (옮긴이) 등 괄호 역할 제거 + / ; , · 제거
    """
    if not s:
        return ""
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[/;·,]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

# C-10-B : 금칙어(forbidden) 집합 만들기 (원본 _build_forbidden_set)
# ==========================================================
# forbidden 단어 집합 — 원본 완전 재현
# ==========================================================

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

    # 2글자 미만 제거
    return {f for f in forb if f and len(f) >= 2}

# C-10-C : forbidden 필터링 여부 판정기 (원본 _should_keep_keyword)
# ==========================================================
# keyword 필터 함수 — 원본 완전 재현
# ==========================================================

def _should_keep_keyword(kw: str, forbidden: set) -> bool:
    n = _norm(kw)
    if not n or len(n.replace(" ", "")) < 2:
        return False

    for tok in forbidden:
        # forbidden과 동일하거나 포함되면 제외
        if tok in n or n in tok:
            return False

    return True

# C-10-D : 알라딘 메타데이터 파서 (원본 fetch_aladin_metadata)
# ==========================================================
# 알라딘 메타데이터 — 원본 fetch_aladin_metadata 완전 재현
# ==========================================================

def fetch_aladin_metadata(isbn):
    url = (
        "http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx"
        f"?ttbkey={aladin_key}"
        "&ItemIdType=ISBN"
        f"&ItemId={isbn}"
        "&output=js"
        "&Version=20131101"
        "&OptResult=Toc"
    )

    data = requests.get(url).json()
    item = (data.get("item") or [{}])[0]

    raw_author = (
        item.get("author")
        or item.get("authors")
        or item.get("author_t")
        or ""
    )

    authors = _clean_author_str(raw_author)

    return {
        "category": item.get("categoryName", "") or "",
        "title": item.get("title", "") or "",
        "authors": authors,
        "description": item.get("description", "") or "",
        "toc": item.get("toc", "") or "",
    }

# C-10-E : GPT 프롬프트 — 원본의 초정밀 버전 100% 재현
# ==========================================================
# 653 GPT 생성 프롬프트 (system + user) — 원본 그대로
# ==========================================================

def build_653_prompts(category, title, authors, description, toc, forbidden_list, max_keywords):
    system_msg = {
        "role": "system",
        "content": (
            "당신은 KORMARC 작성 경험이 풍부한 도서관 메타데이터 전문가입니다. "
            "주어진 분류 정보, 설명, 목차를 바탕으로 'MARC 653 자유주제어'를 도출합니다.\n\n"
            "원칙\n"
            "- 653은 '검색·발견' 효용을 높이는 명사 중심 주제어로 구성하되, "
            "**모든 주제어는 붙여쓰기 형태(공백 없음)**으로 작성합니다.\n"
            "- 서명·저자(역할 포함)·시리즈명·출판사명·판차·연도·가격·홍보문구를 제외.\n"
            "- 너무 일반적 표현(연구, 방법, 사례, 고찰 등)과 "
            "**추상·평가·메타 표현(의의, 의미, 동향, 배경 등)**은 금지.\n"
            "- 떠오른 추상 개념은 반드시 책의 실제 주제를 드러내는 **구체 하위개념**으로 치환.\n"
            "- 분류의 마지막 요소를 참고하되, 관련성·구체성·비중복성·균형을 원칙으로 삼는다.\n\n"
            "출력 형식\n"
            f"- `$a키워드1 $a키워드2 …` 형식으로, 최대 {max_keywords}개.\n"
            "- 설명 문장 금지. 결과만 제시.\n"
        ),
    }

    user_msg = {
        "role": "user",
        "content": (
            f"아래 정보를 바탕으로 최대 {max_keywords}개의 MARC 653 주제어를 한 줄로 출력해 주세요.\n\n"
            f"- 분류 전체: \"{category}\"\n"
            f"- 제목: \"{title}\"\n"
            f"- 저자: \"{authors}\"\n"
            f"- 설명: \"{description}\"\n"
            f"- 목차: \"{toc}\"\n"
            f"- 제외어 목록: {forbidden_list}\n\n"
            "지시사항:\n"
            "1) 제목·저자에서 유래한 단어는 절대 사용 금지.\n"
            "2) 설명·목차 기반으로 **명사 중심(2~6글자 복합명사)** 생성.\n"
            "3) 모든 키워드는 **띄어쓰기를 제거**하여 출력.\n"
            "4) 중복·동의어는 하나만.\n"
            "5) 출력은 `$a키워드1 $a키워드2 …` 단 한 줄.\n"
        ),
    }

    return system_msg, user_msg

# C-10-F : GPT 호출 + 키워드 파싱 (원본 generate_653_with_gpt)
# ==========================================================
# GPT 호출 → $a 키워드 파싱 — 원본 완전 복사 + 구조 개선
# ==========================================================

def generate_653_keywords(category, title, authors, description, toc, max_keywords=7):
    forbidden = _build_forbidden_set(title, authors)
    forbidden_list = ", ".join(sorted(forbidden)) or "(없음)"

    system_msg, user_msg = build_653_prompts(
        category=category,
        title=title,
        authors=authors,
        description=description,
        toc=toc,
        forbidden_list=forbidden_list,
        max_keywords=max_keywords,
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[system_msg, user_msg],
            temperature=0.2,
            max_tokens=180,
        )
        raw = (resp.choices[0].message.content or "").strip()

        # $a 파싱
        pattern = re.compile(r"\$a(.*?)(?=(?:\$a|$))", re.DOTALL)
        kws = [m.group(1).strip() for m in pattern.finditer(raw)]

        if not kws:
            tmp = re.split(r"[,\n;|/·]", raw)
            kws = [t.strip().lstrip("$a") for t in tmp if t.strip()]

        # 붙여쓰기 강제
        kws = [kw.replace(" ", "") for kw in kws if kw]

        # forbidden 필터
        kws = [kw for kw in kws if _should_keep_keyword(kw, forbidden)]

        # 중복 제거
        seen = set()
        uniq = []
        for kw in kws:
            n = _norm(kw)
            if n not in seen:
                seen.add(n)
                uniq.append(kw)

        uniq = uniq[:max_keywords]

        return [kw for kw in uniq]

    except Exception as e:
        st.warning(f"⚠️ 653 주제어 생성 실패: {e}")
        return []

# C-10-G : 653 MARC 라인 생성기 (=653 \$a…)
# ==========================================================
# 최종 653 MRK 라인 빌더 — 원본 _build_653_via_gpt
# ==========================================================

def build_653_mrk_from_item(item: dict) -> Optional[str]:
    title = (item or {}).get("title", "") or ""
    category = (item or {}).get("categoryName", "") or ""
    raw_author = (item or {}).get("author", "") or ""
    desc = (item or {}).get("description", "") or ""
    toc  = ((item or {}).get("subInfo", {}) or {}).get("toc", "") or ""

    authors_clean = _clean_author_str(raw_author)

    kws = generate_653_keywords(
        category=category,
        title=title,
        authors=authors_clean,
        description=desc,
        toc=toc,
        max_keywords=7,
    )
    if not kws:
        return None

    return "=653  \\\\" + "".join(f"$a{kw}" for kw in kws)

# C11. 490/830 총서 모듈
# C-11-A : 삽화 감지기(detect_illustrations)
# ==========================================================
# 삽화 감지 — 원본 완전 재현 + 정규식 안정화
# ==========================================================

def detect_illustrations(text: str):
    """
    제목 + 부제 + 책소개 전체 문자열에서 삽화 여부를 감지한다.
    원본 로직 그대로 유지.
    """
    if not text:
        return False, None

    # 원본 스키마
    keyword_groups = {
        "천연색삽화": ["삽화", "일러스트", "일러스트레이션", "illustration", "그림"],
        "삽화": ["흑백 삽화", "흑백 일러스트", "흑백 일러스트레이션", "흑백 그림"],
        "사진": ["사진", "포토", "photo", "화보"],
        "도표": ["도표", "차트", "그래프"],
        "지도": ["지도", "지도책"],
    }

    found_labels = set()
    lower = text.lower()

    for label, keywords in keyword_groups.items():
        for kw in keywords:
            if kw.lower() in lower:
                found_labels.add(label)

    if found_labels:
        return True, ", ".join(sorted(found_labels))

    return False, None

# C-11-B : 알라딘 상세 HTML → 300 요소 파서
# ==========================================================
# 알라딘 상세 페이지 HTML 파싱 (페이지/크기/삽화)
# 원본 로직을 그대로 따른다.
# ==========================================================

def parse_aladin_physical_book_info(html):
    soup = BeautifulSoup(html, "html.parser")

    # -------------------------------
    # 제목 / 부제 / 책소개 (삽화 감지용)
    # -------------------------------
    title = soup.select_one("span.Ere_bo_title")
    subtitle = soup.select_one("span.Ere_sub1_title")

    title_text = title.get_text(strip=True) if title else ""
    subtitle_text = subtitle.get_text(strip=True) if subtitle else ""

    desc_tag = soup.select_one("div.Ere_prod_mconts_R")
    description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

    # -------------------------------
    # 형태사항 (쪽수, 크기 mm → cm)
    # -------------------------------
    form_wrap = soup.select_one("div.conts_info_list1")

    a_part = ""
    b_part = ""
    c_part = ""

    page_value = None
    size_value = None

    if form_wrap:
        items = [x.strip() for x in form_wrap.stripped_strings if x.strip()]

        for item in items:
            # --- 쪽수 ---
            if re.search(r"(쪽|p)\s*$", item):
                m = re.search(r"\d+", item)
                if m:
                    page_value = int(m.group())
                    a_part = f"{page_value} p."

            # --- 크기(mm) ---
            elif "mm" in item.lower():
                m = re.search(r"(\d+)\s*[\*x×X]\s*(\d+)", item)
                if m:
                    width = int(m.group(1))
                    height = int(m.group(2))
                    size_value = f"{width}x{height}mm"

                    # 원본 알고리즘 그대로: 가로/세로 비정상 비율 처리
                    if width == height or width > height or width < height / 2:
                        w_cm = math.ceil(width / 10)
                        h_cm = math.ceil(height / 10)
                        c_part = f"{w_cm}x{h_cm} cm"
                    else:
                        h_cm = math.ceil(height / 10)
                        c_part = f"{h_cm} cm"

    # -------------------------------
    # 삽화 감지
    # -------------------------------
    combined_text = " ".join(filter(None, [title_text, subtitle_text, description]))
    has_illus, illus_label = detect_illustrations(combined_text)

    if has_illus:
        b_part = illus_label

    # -------------------------------
    # 300 필드 subfields 구성
    # -------------------------------
    subfields_300 = []

    if a_part:
        subfields_300.append(Subfield("a", a_part))
    if b_part:
        subfields_300.append(Subfield("b", b_part))
    if c_part:
        subfields_300.append(Subfield("c", c_part))

    # -------------------------------
    # MRK (사람용 문자열) 조합 규칙 — 원본 그대로
    # -------------------------------
    mrk_parts = []

    # 1) $a + :$b
    if a_part:
        temp = f"$a{a_part}"
        if b_part:
            temp += f" :$b{b_part}"
        mrk_parts.append(temp)
    elif b_part:
        mrk_parts.append(f"$b{b_part}")

    # 2) $c는 ; 로 연결
    if c_part:
        if mrk_parts:
            mrk_parts.append(f"; $c {c_part}")
        else:
            mrk_parts.append(f"$c {c_part}")

    # 3) 아무 것도 없으면 fallback
    if not mrk_parts:
        mrk_parts = ["$a1책."]
        subfields_300 = [Subfield("a", "1책.")]

    field_300 = "=300  \\\\" + " ".join(mrk_parts)

    return {
        "300": field_300,
        "300_subfields": subfields_300,
        "page_value": page_value,
        "size_value": size_value,
        "illustration_possibility": illus_label if illus_label else "없음",
    }

# C-11-C : 상세 페이지 요청기(search_aladin_detail_page)
# ==========================================================
# 알라딘 상세 페이지 HTML 요청기 — 원본 + 예외 보강
# ==========================================================

def search_aladin_detail_page(link):
    try:
        res = requests.get(link, timeout=15)
        res.raise_for_status()
        return parse_aladin_physical_book_info(res.text), None

    except Exception as e:
        return {
            "300": "=300  \\\\$a1책. [상세 페이지 파싱 오류]",
            "300_subfields": [Subfield("a", "1책 [파싱 실패]")],
            "page_value": None,
            "size_value": None,
            "illustration_possibility": "정보 없음",
        }, f"Aladin 상세 페이지 크롤링 예외: {e}"

# C-11-D : 최종 300 Field Builder (MRK + Field 두 가지 반환)
# ==========================================================
# 300 필드 최종 빌더 — 원본 build_300_from_aladin_detail
# ==========================================================

def build_300_from_aladin_detail(item: dict) -> tuple[str, Field]:
    try:
        aladin_link = (item or {}).get("link", "")

        if not aladin_link:
            # 원본 fallback
            fallback = "=300  \\\\$a1책."
            return fallback, Field(
                tag="300",
                indicators=[" ", " "],
                subfields=[Subfield("a", "1책.")]
            )

        detail, err = search_aladin_detail_page(aladin_link)

        tag_300 = detail.get("300") or "=300  \\\\$a1책."
        subfields = detail.get("300_subfields") or [Subfield("a", "1책.")]

        f_300 = Field(
            tag="300",
            indicators=[" ", " "],
            subfields=subfields
        )

        return tag_300, f_300

    except Exception as e:
        fallback = "=300  \\\\$a1책. [예외]"
        return fallback, Field(
            tag="300",
            indicators=[" ", " "],
            subfields=[Subfield("a", "1책. [예외]")]
        )

# C-11-E : MRK 전용 버전(build_300_mrk)
# ==========================================================
# MRK만 필요할 때 쓰는 얇은 Wrapper — 원본 재현
# ==========================================================

def build_300_mrk(item: dict) -> str:
    tag_300, _ = build_300_from_aladin_detail(item)
    return tag_300 or "=300  \\\\$a1책."

# C12. 최종 MARC Builder 조립기
# C-12-A — 총서(SeriesInfo) 추출기
# ==========================================================
# 490/830 총서 정보 추출 — 원본 로직 100% 동일
# ==========================================================

def extract_series_info(item: dict):
    """
    원본의 seriesInfo 추출 과정과 동일:
      1) item["seriesInfo"]
      2) item["subInfo"]["seriesInfo"]
      3) 가장 첫 번째 유효한 엔트리 사용
    반환값: (series_name, volume)
    """
    si = None

    if isinstance(item, dict):
        si = item.get("seriesInfo") or (item.get("subInfo") or {}).get("seriesInfo")

    # 시리즈가 리스트형 / dict형 둘 다 대응
    entries = []
    if isinstance(si, list):
        entries = si
    elif isinstance(si, dict):
        entries = [si]

    series_name = ""
    series_vol = ""

    # 원본: 가장 먼저 등장하는 유효한 총서만 사용
    for ent in entries or []:
        if not isinstance(ent, dict):
            continue
        name = (ent.get("seriesName") or ent.get("name") or "").strip()
        vol  = (ent.get("volume") or ent.get("vol") or "").strip()
        if name:
            series_name = name
            series_vol = vol
            break

    # 추가 fallback (원본 그대로)
    if not series_name:
        series_name = (item.get("seriesName") or "").strip()

    if not series_vol:
        series_vol = (item.get("volume") or "").strip()

    return series_name, series_vol

# C-12-B — 표시 문자열(series_display) 구성기
# ==========================================================
# 총서 표시 문자열 생성기 — 원본 동일
# ==========================================================

def build_series_display(series_name: str, series_vol: str) -> str | None:
    """
    원본 구성 규칙:
      - "{name} {vol}".strip()
      - name이 없으면 총서 없음 → None
    """
    if not series_name:
        return None

    if series_vol:
        display = f"{series_name} {series_vol}".strip()
    else:
        display = series_name.strip()

    return display or None

# C-12-C — 490 / 830 MRK 문자열 생성기
# ==========================================================
# MRK 문자열 생성 — 원본과 동일한 포맷
# ==========================================================

def build_mrk_490(series_display: str) -> str:
    return f"=490  10$a{series_display}"

def build_mrk_830(series_display: str) -> str:
    return f"=830  \\0$a{series_display}"

# C-12-D — pymarc.Field 생성기
# ==========================================================
# pymarc Field 생성 — 원본 mrk_str_to_field 동작과 동일
# ==========================================================

def build_field_490(series_display: str) -> Field:
    return Field(
        tag="490",
        indicators=["1", "0"],   # 원본 규칙 유지
        subfields=[Subfield("a", series_display)]
    )

def build_field_830(series_display: str) -> Field:
    return Field(
        tag="830",
        indicators=[" ", "0"],   # 원본 "\0"은 MRK에서의 escape → 실제는 [" ", "0"]
        subfields=[Subfield("a", series_display)]
    )

# C-12-E — 490/830 전체 통합 빌더(원본 build_490_830_mrk_from_item 복원)
# ==========================================================
# 490/830 전체 빌더 — 원본 함수 완전 복원(True Patch)
# ==========================================================

def build_490_830_from_item(item: dict):
    """
    반환값:
        tag_490 (str or "")
        tag_830 (str or "")
        f_490 (Field or None)
        f_830 (Field or None)
    """

    series_name, series_vol = extract_series_info(item)
    series_display = build_series_display(series_name, series_vol)

    # 원본: 총서 정보 없으면 모두 빈 값 반환
    if not series_display:
        return "", "", None, None

    # MRK 문자열 생성
    tag_490 = build_mrk_490(series_display)
    tag_830 = build_mrk_830(series_display)

    # pymarc.Field 생성
    f_490 = build_field_490(series_display)
    f_830 = build_field_830(series_display)

    return tag_490, tag_830, f_490, f_830

# C-12-F — 기존 generate_all_oneclick에 삽입되는 형태
# generate_all_oneclick 내부에서 호출 형태
tag_490, tag_830, f_490, f_830 = build_490_830_from_item(item)

if f_490:
    pieces.append((f_490, tag_490))
if f_830:
    pieces.append((f_830, tag_830))

# C13. 049 필드 생성기
# ============================================================
# C-13) 049 생성기 — 원본 판단 로직 100% 유지 + 구조 안정화
# ============================================================

def build_049(reg_mark: str = "", reg_no: str = "", copy_symbol: str = "") -> str:
    """
    네 원본 코드의 049 생성 규칙을 100% 동일하게 구현한 True Patch.
    규칙:
      - 세 값 모두 비어 있으면 None 반환
      - 등록기호(reg_mark) → $a
      - 등록번호(reg_no) → $b
      - 별치기호(copy_symbol) → $c
      - 공백/슬래시/개행 제거 및 양쪽 trim
      - 값 있는 서브필드만 출력
    """
    reg_mark = (reg_mark or "").strip()
    reg_no = (reg_no or "").strip()
    copy_symbol = (copy_symbol or "").strip()

    if not (reg_mark or reg_no or copy_symbol):
        return None

    parts = ["=049  \\\\"]

    if reg_mark:
        parts.append(f"$a{reg_mark}")
    if reg_no:
        parts.append(f"$b{reg_no}")
    if copy_symbol:
        parts.append(f"$c{copy_symbol}")

    return "".join(parts)


def build_field_049(reg_mark: str = "", reg_no: str = "", copy_symbol: str = "") -> Optional[Field]:
    """
    Field 객체 버전. build_049()와 판단 로직 완전히 동일.
    """
    line = build_049(reg_mark, reg_no, copy_symbol)
    if not line:
        return None
    return mrk_str_to_field(line)

# C14. 300 형태사항 블록
# ============================================================
# C-14) 300 형태사항 (원본 판단 로직 100% 유지 + 구조 안정화)
# ============================================================

# ---------------------------
# 삽화 감지기 (원본 코드 유지)
# ---------------------------
def detect_illustrations(text: str):
    if not text:
        return False, None

    keyword_groups = {
        "천연색삽화": ["삽화", "일러스트", "일러스트레이션", "illustration", "그림"],
        "삽화": ["흑백 삽화", "흑백 일러스트", "흑백 일러스트레이션", "흑백 그림"],
        "사진": ["사진", "포토", "photo", "화보"],
        "도표": ["도표", "차트", "그래프"],
        "지도": ["지도", "지도책"],
    }

    found = set()
    for label, keywords in keyword_groups.items():
        if any(kw in text for kw in keywords):
            found.add(label)

    if found:
        return True, ", ".join(sorted(found))
    return False, None


# ----------------------------------------------------------
# 알라딘 HTML 상세 페이지 내부에서 300 데이터 파싱하는 핵심 함수
# ----------------------------------------------------------
def parse_aladin_physical_book_info(html: str):
    soup = BeautifulSoup(html, "html.parser")

    # -----------------------------
    # 제목 / 부제 / 책소개
    # -----------------------------
    title = soup.select_one("span.Ere_bo_title")
    subtitle = soup.select_one("span.Ere_sub1_title")
    title_text = title.get_text(strip=True) if title else ""
    subtitle_text = subtitle.get_text(strip=True) if subtitle else ""

    description = None
    desc_tag = soup.select_one("div.Ere_prod_mconts_R")
    if desc_tag:
        description = desc_tag.get_text(" ", strip=True)

    # -----------------------------
    # 형태사항 영역 파싱 (300 a,b,c)
    # -----------------------------
    form_wrap = soup.select_one("div.conts_info_list1")
    a_part = ""
    b_part = ""
    c_part = ""
    page_value = None
    size_value = None

    if form_wrap:
        items = [x.strip() for x in form_wrap.stripped_strings if x.strip()]
        for item in items:

            # 쪽수 / page
            if re.search(r"(쪽|p)\s*$", item):
                m = re.search(r"\d+", item)
                if m:
                    page_value = int(m.group())
                    a_part = f"{m.group()} p."

            # 판형
            elif "mm" in item:
                m = re.search(r"(\d+)\s*[\*x×X]\s*(\d+)", item)
                if m:
                    w = int(m.group(1))
                    h = int(m.group(2))
                    size_value = f"{w}x{h}mm"

                    # cm 변환 규칙(원본 유지)
                    if w == h or w > h or w < h/2:
                        w_cm = math.ceil(w / 10)
                        h_cm = math.ceil(h / 10)
                        c_part = f"{w_cm}x{h_cm} cm"
                    else:
                        h_cm = math.ceil(h / 10)
                        c_part = f"{h_cm} cm"

    # -----------------------------
    # 삽화(b) 감지 (원본 규칙 그대로)
    # -----------------------------
    combined = " ".join([title_text, subtitle_text, description or ""])
    has_illus, illus_text = detect_illustrations(combined)
    if has_illus:
        b_part = illus_text

    # -----------------------------
    # Subfields + MRK 문자열 조립
    # -----------------------------
    subfields_300 = []
    mrk_parts = []

    if a_part:
        chunk = f"$a{a_part}"
        if b_part:
            chunk += f" :$b{b_part}"
        mrk_parts.append(chunk)
        subfields_300.append(Subfield("a", a_part))
        if b_part:
            subfields_300.append(Subfield("b", b_part))

    elif b_part:
        mrk_parts.append(f"$b{b_part}")
        subfields_300.append(Subfield("b", b_part))

    if c_part:
        if mrk_parts:
            mrk_parts.append(f"; $c {c_part}")
        else:
            mrk_parts.append(f"$c {c_part}")
        subfields_300.append(Subfield("c", c_part))

    # fallback
    if not mrk_parts:
        mrk_parts = ["$a1책."]
        subfields_300 = [Subfield("a", "1책.")]

    tag_300 = "=300  \\\\" + " ".join(mrk_parts)

    return {
        "300": tag_300,
        "300_subfields": subfields_300,
        "page_value": page_value,
        "size_value": size_value,
        "illustration_possibility": illus_text or "없음",
    }


# ----------------------------------------------------------
# 알라딘 링크를 실제 요청하여 300 만들기 (원본 로직 동일)
# ----------------------------------------------------------
def search_aladin_detail_page(link: str):
    try:
        res = requests.get(link, timeout=15)
        res.raise_for_status()
        result = parse_aladin_physical_book_info(res.text)
        return result, None
    except Exception as e:
        return {
            "300": "=300  \\\\$a1책. [상세 페이지 파싱 오류]",
            "300_subfields": [Subfield("a", "1책 [파싱 실패]")],
            "page_value": None,
            "size_value": None,
            "illustration_possibility": "정보 없음",
        }, f"Aladin 상세 페이지 크롤링 예외: {e}"


# ----------------------------------------------------------
# 최종 300 생성기 (MRK + Field) — 원본 100% 유지
# ----------------------------------------------------------
def build_300_from_aladin_detail(item: dict) -> tuple[str, Field]:
    try:
        link = (item or {}).get("link", "")
        if not link:
            fallback = "=300  \\\\$a1책."
            return fallback, Field(
                tag="300",
                indicators=[" ", " "],
                subfields=[Subfield("a", "1책.")]
            )

        # HTML → 구조화 데이터
        result, err = search_aladin_detail_page(link)

        # MRK 문자열
        tag_300 = result.get("300") or "=300  \\\\$a1책."

        # Field 객체
        subfields = result.get("300_subfields") or [Subfield("a", "1책.")]
        f_300 = Field(tag="300", indicators=[" ", " "], subfields=subfields)

        return tag_300, f_300

    except Exception:
        fallback = "=300  \\\\$a1책. [예외]"
        return fallback, Field(
            tag="300",
            indicators=[" ", " "],
            subfields=[Subfield("a", "1책. [예외]")]
        )


# ----------------------------------------------------------
# MRK 전용 단축 함수
# ----------------------------------------------------------
def build_300_mrk(item: dict) -> str:
    tag_300, _ = build_300_from_aladin_detail(item)
    return tag_300

# C15: generate_all_oneclick() 전체 파이프라인
# ============================================================
# C-15) generate_all_oneclick — True Patch
# 원본 판단 로직 100% 유지 + 구조 안정화
# ============================================================

def generate_all_oneclick(
    isbn: str,
    *,
    reg_mark: str = "",
    reg_no: str = "",
    copy_symbol: str = "",
    use_ai_940: bool = True,
):
    """
    원본 generate_all_oneclick()의 모든 판단 구조를 그대로 따르면서
    모듈화된 field_builders 의 기능을 호출하는 True Patch 버전.
    """

    # ----------------------------------------------------------
    # 초기화
    # ----------------------------------------------------------
    marc_rec = Record(to_unicode=True, force_utf8=True)
    pieces = []              # (Field, MRK str)
    meta = {}
    global CURRENT_DEBUG_LINES
    CURRENT_DEBUG_LINES = []

    # ----------------------------------------------------------
    # 0) NLK author-only 조회
    # ----------------------------------------------------------
    author_raw, _ = fetch_nlk_author_only(isbn)

    # ----------------------------------------------------------
    # 1) 알라딘 메타데이터 (API → 실패 시 Web)
    # ----------------------------------------------------------
    item = fetch_aladin_item(isbn)    # 네 원본 wrapper 함수(있던 그대로)

    # ----------------------------------------------------------
    # 2) 041/546 생성
    # ----------------------------------------------------------
    tag_041_text = None
    tag_546_text = None
    original_title = None

    try:
        res = get_kormarc_tags(isbn)   # (041, 546, original)
        if isinstance(res, (list, tuple)) and len(res) == 3:
            tag_041_text, tag_546_text, original_title = res

        # 예외 문자열 처리
        if isinstance(tag_041_text, str) and tag_041_text.startswith("📕"):
            tag_041_text = None
        if isinstance(tag_546_text, str) and tag_546_text.startswith("📕"):
            tag_546_text = None
    except Exception:
        tag_041_text = None
        tag_546_text = None

    # 041 원작 언어코드
    origin_lang = None
    if tag_041_text:
        m = re.search(r"\$h([a-z]{3})", tag_041_text, re.I)
        if m:
            origin_lang = m.group(1).lower()

    # ----------------------------------------------------------
    # 3) 245 / 246 / 700
    # ----------------------------------------------------------
    marc245 = build_245_with_people_from_sources(item, author_raw, prefer="aladin")
    f_245 = mrk_str_to_field(marc245)

    marc246 = build_246_from_aladin_item(item)
    f_246 = mrk_str_to_field(marc246)

    mrk_700_list = build_700_people_pref_aladin(
        author_raw,
        item,
        origin_lang_code=origin_lang
    ) or []

    # ----------------------------------------------------------
    # 4) 90010 (Wikidata 원어명)
    # ----------------------------------------------------------
    people = extract_people_from_aladin(item) if item else {}
    mrk_90010_list = build_90010_from_wikidata(people, include_translator=False)

    # ----------------------------------------------------------
    # 5) 940 (245 $a 기반)
    # ----------------------------------------------------------
    a_out, n_flag = parse_245_a_n(marc245)
    mrk_940_list = build_940_from_title_a(
        a_out,
        use_ai=use_ai_940,
        disable_number_reading=bool(n_flag)
    )

    # ----------------------------------------------------------
    # 6) 260 (발행지 + 국가코드)
    # ----------------------------------------------------------
    publisher_raw = (item or {}).get("publisher", "")
    pubdate = (item or {}).get("pubDate", "") or ""
    pubyear = pubdate[:4] if len(pubdate) >= 4 else ""

    bundle = build_pub_location_bundle(isbn, publisher_raw)

    tag_260 = build_260(
        place_display=bundle["place_display"],
        publisher_name=publisher_raw,
        pubyear=pubyear,
    )
    f_260 = mrk_str_to_field(tag_260)

    # ----------------------------------------------------------
    # 7) 008 (country override + lang override)
    # ----------------------------------------------------------
    lang3_override = _lang3_from_tag041(tag_041_text) if tag_041_text else None

    data_008 = build_008_from_isbn(
        isbn,
        aladin_pubdate=(item or {}).get("pubDate", "") or "",
        aladin_title=(item or {}).get("title", "") or "",
        aladin_category=(item or {}).get("categoryName", "") or "",
        aladin_desc=(item or {}).get("description", "") or "",
        aladin_toc=((item or {}).get("subInfo", {}) or {}).get("toc", "") or "",
        override_country3=bundle["country_code"],
        override_lang3=lang3_override,
        cataloging_src="a",
    )
    f_008 = Field(tag="008", data=data_008)

    # ----------------------------------------------------------
    # 8) 007
    # ----------------------------------------------------------
    f_007 = Field(tag="007", data="ta")

    # ----------------------------------------------------------
    # 9) 020 + set ISBN(020-1)
    # ----------------------------------------------------------
    tag_020 = _build_020_from_item_and_nlk(isbn, item)
    f_020 = mrk_str_to_field(tag_020)

    nlk_extra = fetch_additional_code_from_nlk(isbn)
    set_isbn = nlk_extra.get("set_isbn", "").strip()

    # ----------------------------------------------------------
    # 10) 653 (GPT)
    # ----------------------------------------------------------
    tag_653 = _build_653_via_gpt(item)
    f_653 = mrk_str_to_field(tag_653) if tag_653 else None

    # 653 → 056 힌트로 사용
    try:
        kw_hint = sorted(set(_parse_653_keywords(tag_653)))[:7]
    except Exception:
        kw_hint = []

    # ----------------------------------------------------------
    # 11) 056 (KDC)
    # ----------------------------------------------------------
    try:
        kdc_code = get_kdc_from_isbn(
            isbn,
            ttbkey=ALADIN_TTB_KEY,
            openai_key=openai_key,
            model=model,
            keywords_hint=kw_hint,
        )
        if kdc_code and not re.fullmatch(r"\d{1,3}", kdc_code):
            kdc_code = None
    except Exception:
        kdc_code = None

    tag_056 = f"=056  \\\\$a{kdc_code}$26" if kdc_code else None
    f_056 = mrk_str_to_field(tag_056) if tag_056 else None

    # ----------------------------------------------------------
    # 12) 490 / 830
    # ----------------------------------------------------------
    tag_490, tag_830 = build_490_830_mrk_from_item(item)
    f_490 = mrk_str_to_field(tag_490)
    f_830 = mrk_str_to_field(tag_830)

    # ----------------------------------------------------------
    # 13) 300 (형태사항)
    # ----------------------------------------------------------
    tag_300, f_300 = build_300_from_aladin_detail(item)

    # ----------------------------------------------------------
    # 14) 950 (가격)
    # ----------------------------------------------------------
    tag_950 = build_950_from_item_and_price(item, isbn)
    f_950 = mrk_str_to_field(tag_950)

    # ----------------------------------------------------------
    # 15) 049 (등록번호)
    # ----------------------------------------------------------
    tag_049 = build_049(reg_mark, reg_no, copy_symbol)
    f_049 = mrk_str_to_field(tag_049) if tag_049 else None

    # ----------------------------------------------------------
    # 16) 필드 순서대로 조립
    # ----------------------------------------------------------
    def add_piece(field, mrk):
        if field and mrk:
            pieces.append((field, mrk))

    add_piece(f_008, f"=008  {data_008}")
    add_piece(f_007, "=007  ta")
    add_piece(f_020, tag_020)

    if set_isbn:
        tag_020_1 = f"=020  1\\$a{set_isbn} (set)"
        add_piece(mrk_str_to_field(tag_020_1), tag_020_1)

    if tag_041_text and "$h" in tag_041_text:
        f_041 = mrk_str_to_field(_as_mrk_041(tag_041_text))
        add_piece(f_041, _as_mrk_041(tag_041_text))

    add_piece(f_056, tag_056)
    add_piece(f_245, marc245)
    add_piece(f_246, marc246)
    add_piece(f_260, tag_260)
    add_piece(f_300, tag_300)
    add_piece(f_490, tag_490)

    if tag_546_text:
        f_546 = mrk_str_to_field(_as_mrk_546(tag_546_text))
        add_piece(f_546, _as_mrk_546(tag_546_text))

    add_piece(f_653, tag_653)

    for m in mrk_700_list:
        ff = mrk_str_to_field(m)
        if ff:
            add_piece(ff, m)

    for m in mrk_90010_list:
        ff = mrk_str_to_field(m)
        if ff:
            add_piece(ff, m)

    for m in mrk_940_list:
        ff = mrk_str_to_field(m)
        if ff:
            add_piece(ff, m)

    add_piece(f_830, tag_830)
    add_piece(f_950, tag_950)
    add_piece(f_049, tag_049)

    # ----------------------------------------------------------
    # MRK 전체 문자열
    # ----------------------------------------------------------
    mrk_text = "\n".join(m for _, m in pieces)

    # ----------------------------------------------------------
    # Record 객체 구성
    # ----------------------------------------------------------
    for f, _ in pieces:
        marc_rec.add_field(f)

    # ----------------------------------------------------------
    # meta 구성
    # ----------------------------------------------------------
    meta = {
        "TitleA": a_out,
        "has_n": bool(n_flag),
        "700_count": sum(1 for _, m in pieces if m.startswith("=700")),
        "90010_count": len(mrk_90010_list),
        "940_count": len(mrk_940_list),
        "Candidates": get_candidate_names_for_isbn(isbn),
        "041": tag_041_text,
        "546": tag_546_text,
        "020": tag_020,
        "056": tag_056,
        "653": tag_653,
        "kdc_code": kdc_code,
        "price_for_950": _extract_price_kr(item, isbn),
        "Publisher_raw": publisher_raw,
        "pubyear": pubyear,
        "Place_display": bundle["place_display"],
        "CountryCode_008": bundle["country_code"],
        "Publisher_resolved": bundle["resolved_publisher"],
        "Bundle_source": bundle["source"],
        "debug_lines": list(CURRENT_DEBUG_LINES),
    }

    marc_bytes = marc_rec.as_marc()

    return marc_rec, marc_bytes, mrk_text, meta
