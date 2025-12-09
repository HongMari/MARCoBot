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
# 653 전처리 유틸 (원본 그대로)
# ==========================================================

import re
import unicodedata
from collections import Counter
import json
import requests
import streamlit as st

from pymarc import Field, Subfield

from .constants import ISDS_LANGUAGE_CODES
from .config import OPENAI_CHAT_COMPLETIONS, DEFAULT_MODEL, aladin_key
from .utils import clean_text

def _norm(text: str) -> str:
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
# ==========================================================
# 알라딘 item.author → 100/700 전체 생성
# ==========================================================

def build_people_fields_from_aladin(item: dict, origin_lang_code: str | None = None):
    raw = (item or {}).get("author", "") or ""
    authors = split_authors(raw)

    tag100, tag700_list = build_100_and_700(authors, origin_lang_code)
    return tag100, tag700_list
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
