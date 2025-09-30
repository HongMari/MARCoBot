import re
import os
import streamlit as st
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI

# ===== 환경변수 로드 =====
load_dotenv()
ALADIN_KEY = os.getenv("ALADIN_TTB_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_KEY)

# ===== ISDS 언어코드 매핑 =====
ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어',
    'rus': '러시아어', 'ara': '아랍어', 'fre': '프랑스어', 'ger': '독일어',
    'ita': '이탈리아어', 'spa': '스페인어', 'por': '포르투갈어', 'tur': '터키어',
    'und': '알 수 없음'
}
ALLOWED_CODES = set(ISDS_LANGUAGE_CODES.keys()) - {"und"}

# ===== 공통 유틸: GPT 응답 파싱(코드 + 이유) =====
def _extract_code_and_reason(content, code_key="$h"):
    code, reason, signals = "und", "", ""
    lines = [l.strip() for l in (content or "").splitlines() if l.strip()]
    for ln in lines:
        if ln.startswith(f"{code_key}="):
            code = ln.split("=", 1)[1].strip()
        elif ln.lower().startswith("#reason="):
            reason = ln.split("=", 1)[1].strip()
        elif ln.lower().startswith("#signals="):
            signals = ln.split("=", 1)[1].strip()
    return code, reason, signals

# ===== GPT 판단 함수 (원서; 일반) =====
def gpt_guess_original_lang(title, category, publisher, author="", original_title=""):
    prompt = f"""
    아래 도서의 원서 언어(041 $h)를 ISDS 코드로 추정해줘.
    가능한 코드: kor, eng, jpn, chi, rus, fre, ger, ita, spa, por, tur

    도서정보:
    - 제목: {title}
    - 원제: {original_title or "(없음)"}
    - 분류: {category}
    - 출판사: {publisher}
    - 저자: {author}

    지침:
    - 국가/지역을 언어로 곧바로 치환하지 말 것.
    - 저자 국적·주 집필 언어·최초 출간 언어를 우선 고려.
    - 불확실하면 임의 추정 대신 'und' 사용.

    출력형식(정확히 이 2~3줄):
    $h=[ISDS 코드]
    #reason=[짧게 근거 요약]
    #signals=[잡은 단서들, 콤마로](선택)
    """.strip()
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system","content":"사서용 언어 추정기"},
                      {"role":"user","content":prompt}],
            temperature=0
        )
        content = (resp.choices[0].message.content or "").strip()
        code, reason, signals = _extract_code_and_reason(content, "$h")
        if code not in ALLOWED_CODES:
            code = "und"
        st.write(f"🧭 [GPT 근거] $h={code}")
        if reason: st.write(f"🧭 [이유] {reason}")
        if signals: st.write(f"🧭 [단서] {signals}")
        return code
    except Exception as e:
        st.error(f"GPT 오류: {e}")
        return "und"

# ===== GPT 판단 함수 (본문) =====
def gpt_guess_main_lang(title, category, publisher):
    prompt = f"""
    아래 도서의 본문 언어(041 $a)를 ISDS 코드로 추정.
    가능한 코드: kor, eng, jpn, chi, rus, fre, ger, ita, spa, por, tur

    입력:
    - 제목: {title}
    - 분류: {category}
    - 출판사: {publisher}

    지침:
    - '본문 언어'는 이 자료의 **현시본(Manifestation)** 언어다.
    - 저자 국적, 원작 언어, 시리즈 원산지 등 **원작 관련 단서 사용 금지**.
    - 카테고리에 '국내도서'가 있거나, 제목에 **한글이 1자라도** 포함되면 반드시 kor.
    - 허용 코드 밖이거나 불확실하면 'und'.

    출력형식:
    $a=[ISDS 코드]
    #reason=[짧게 근거 요약]
    #signals=[잡은 단서들, 콤마로](선택)
    """.strip()
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system","content":"사서용 본문 언어 추정기"},
                      {"role":"user","content":prompt}],
            temperature=0
        )
        content = (resp.choices[0].message.content or "").strip()
        code, reason, signals = _extract_code_and_reason(content, "$a")
        if code not in ALLOWED_CODES:
            code = "und"
        st.write(f"🧭 [GPT 근거] $a={code}")
        if reason: st.write(f"🧭 [이유] {reason}")
        if signals: st.write(f"🧭 [단서] {signals}")
        return code
    except Exception as e:
        st.error(f"GPT 오류: {e}")
        return "und"

# ===== GPT 판단 함수 (신규) — 저자 기반 원서 언어 추정 =====
def gpt_guess_original_lang_by_author(author, title="", category="", publisher=""):
    prompt = f"""
    저자 정보를 중심으로 원서 언어(041 $h)를 ISDS 코드로 추정.
    가능한 코드: kor, eng, jpn, chi, rus, fre, ger, ita, spa, por, tur

    입력:
    - 저자: {author}
    - (참고) 제목: {title}
    - (참고) 분류: {category}
    - (참고) 출판사: {publisher}

    지침:
    - 저자 국적·주 집필 언어·대표 작품 원어를 우선.
    - 국가=언어 단순 치환 금지.
    - 불확실하면 'und'.

    출력형식:
    $h=[ISDS 코드]
    #reason=[짧게 근거 요약]
    #signals=[잡은 단서들, 콤마로](선택)
    """.strip()
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role":"system","content":"저자 기반 원서 언어 추정기"},
                      {"role":"user","content":prompt}],
            temperature=0
        )
        content = (resp.choices[0].message.content or "").strip()
        code, reason, signals = _extract_code_and_reason(content, "$h")
        if code not in ALLOWED_CODES:
            code = "und"
        st.write(f"🧭 [저자기반 근거] $h={code}")
        if reason: st.write(f"🧭 [이유] {reason}")
        if signals: st.write(f"🧭 [단서] {signals}")
        return code
    except Exception as e:
        st.error(f"GPT(저자기반) 오류: {e}")
        return "und"

# ===== 언어 감지 함수들 =====
def detect_language_by_unicode(text):
    text = re.sub(r'[\s\W_]+', '', text or "")
    if not text:
        return 'und'
    c = text[0]
    if '\uac00' <= c <= '\ud7a3': return 'kor'
    if '\u3040' <= c <= '\u30ff': return 'jpn'
    if '\u4e00' <= c <= '\u9fff': return 'chi'
    if '\u0600' <= c <= '\u06FF': return 'ara'
    if '\u0e00' <= c <= '\u0e7f': return 'tha'
    return 'und'

def override_language_by_keywords(text, initial_lang):
    text = (text or "").lower()
    if initial_lang == 'chi' and re.search(r'[\u3040-\u30ff]', text): return 'jpn'
    if initial_lang in ['und', 'eng']:
        if "spanish" in text or "español" in text: return "spa"
        if "italian" in text or "italiano" in text: return "ita"
        if "french" in text or "français" in text: return "fre"
        if "portuguese" in text or "português" in text: return "por"
        if "german" in text or "deutsch" in text: return "ger"
        if any(ch in text for ch in ['é','è','ê','à','ç','ù','ô','â','î','û']): return "fre"
        if any(ch in text for ch in ['ñ','á','í','ó','ú']): return "spa"
        if any(ch in text for ch in ['ã','õ']): return "por"
    return initial_lang

def detect_language(text):
    lang = detect_language_by_unicode(text)
    return override_language_by_keywords(text, lang)

def detect_language_from_category(text):
    words = re.split(r'[>/\s]+', text or "")
    for w in words:
        if "일본" in w: return "jpn"
        if "중국" in w: return "chi"
        if "영미" in w or "영어" in w or "아일랜드" in w: return "eng"
        if "프랑스" in w: return "fre"
        if "독일" in w or "오스트리아" in w: return "ger"
        if "러시아" in w: return "rus"
        if "이탈리아" in w: return "ita"
        if "스페인" in w: return "spa"
        if "포르투갈" in w: return "por"
        if "튀르키예" in w or "터키" in w: return "tur"
    return None

# ===== 카테고리 토크나이즈 & 판정 유틸 =====
def tokenize_category(text: str):
    if not text:
        return []
    t = re.sub(r'[()]+', ' ', text)
    raw = re.split(r'[>/\s]+', t)
    tokens = []
    for w in raw:
        w = w.strip()
        if not w:
            continue
        if '/' in w and w.count('/') <= 3 and len(w) <= 20:
            tokens.extend([p for p in w.split('/') if p])
        else:
            tokens.append(w)
    lower_tokens = tokens + [w.lower() for w in tokens if any('A'<=ch<='Z' or 'a'<=ch<='z' for ch in w)]
    return lower_tokens

def has_kw_token(tokens, kws):
    s = set(tokens)
    return any(k in s for k in kws)

def trigger_kw_token(tokens, kws):
    s = set(tokens)
    for k in kws:
        if k in s:
            return k
    return None

def is_literature_top(category_text: str) -> bool:
    return "소설/시/희곡" in (category_text or "")

def is_literature_category(category_text: str) -> bool:
    tokens = tokenize_category(category_text or "")
    ko_hits = ["문학", "소설", "시", "희곡"]
    en_hits = ["literature", "fiction", "novel", "poetry", "poem", "drama", "play"]
    return has_kw_token(tokens, ko_hits) or has_kw_token(tokens, en_hits)

def is_nonfiction_override(category_text: str) -> bool:
    """
    문학처럼 보여도 '역사/지역/전기/사회과학/에세이' 등 비문학 지표가 있으면 비문학으로 강제.
    단, 문학 최상위(소설/시/희곡)면 '과학/기술'은 제외(SF 보호).
    """
    tokens = tokenize_category(category_text or "")
    lit_top = is_literature_top(category_text or "")

    ko_nf_strict = ["역사","근현대사","서양사","유럽사","전기","평전",
                    "사회","정치","철학","경제","경영","인문","에세이","수필"]
    en_nf_strict = ["history","biography","memoir","politics","philosophy",
                    "economics","science","technology","nonfiction","essay","essays"]

    sci_keys = ["과학","기술"]; sci_keys_en = ["science","technology"]

    k = trigger_kw_token(tokens, ko_nf_strict) or trigger_kw_token(tokens, en_nf_strict)
    if k:
        st.write(f"🔎 [판정근거] 비문학 키워드 발견: '{k}'")
        return True

    if not lit_top:
        k2 = trigger_kw_token(tokens, sci_keys) or trigger_kw_token(tokens, sci_keys_en)
        if k2:
            st.write(f"🔎 [판정근거] 비문학 최상위 추정 & '{k2}' 발견 → 비문학 오버라이드")
            return True

    if lit_top:
        st.write("🔎 [판정근거] 문학 최상위 감지: '과학/기술'은 오버라이드에서 제외(SF 보호).")
    return False

# ===== 기타 유틸 =====
def strip_ns(tag): return tag.split('}')[-1] if '}' in tag else tag

def generate_546_from_041_kormarc(marc_041):
    a_codes, h_code = [], None
    for part in marc_041.split():
        if part.startswith("$a"): a_codes.append(part[2:])
        elif part.startswith("$h"): h_code = part[2:]
    if len(a_codes) == 1:
        a_lang = ISDS_LANGUAGE_CODES.get(a_codes[0], "알 수 없음")
        if h_code:
            h_lang = ISDS_LANGUAGE_CODES.get(h_code, "알 수 없음")
            return f"{h_lang}원작을 {a_lang}로 번역"
        else:
            return f"{a_lang}로 씀"
    elif len(a_codes) > 1:
        langs = [ISDS_LANGUAGE_CODES.get(code, "알 수 없음") for code in a_codes]
        return f"{'、'.join(langs)} 병기"
    return "언어 정보 없음"

# ===== 웹 크롤링 =====
def crawl_aladin_fallback(isbn13):
    url = f"https://www.aladin.co.kr/shop/wproduct.aspx?ISBN={isbn13}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        original = soup.select_one("div.info_original")
        lang_info = soup.select_one("div.conts_info_list1")
        category_text = ""
        categories = soup.select("div.conts_info_list2 li")
        for cat in categories:
            category_text += cat.get_text(separator=" ", strip=True) + " "
        detected_lang = ""
        if lang_info and "언어" in lang_info.text:
            if "Japanese" in lang_info.text: detected_lang = "jpn"
            elif "Chinese" in lang_info.text: detected_lang = "chi"
            elif "English" in lang_info.text: detected_lang = "eng"
        return {
            "original_title": original.text.strip() if original else "",
            "subject_lang": detect_language_from_category(category_text) or detected_lang,
            "category_text": category_text
        }
    except Exception as e:
        st.error(f"❌ 크롤링 중 오류 발생: {e}")
        return {}

# ===== 결과 조정(충돌 해소) =====
def reconcile_language(candidate, fallback_hint=None, author_hint=None):
    """
    candidate: 1차 GPT 결과
    fallback_hint: 카테고리/원제 규칙에서 얻은 힌트(예: 'ger')
    author_hint: 저자 기반 GPT 결과
    """
    if author_hint and author_hint != "und" and author_hint != candidate:
        st.write(f"🔁 [조정] 저자기반({author_hint}) ≠ 1차({candidate}) → 저자기반 우선")
        return author_hint
    if fallback_hint and fallback_hint != "und" and fallback_hint != candidate:
        if candidate in {"ita","fre","spa","por"}:
            st.write(f"🔁 [조정] 규칙힌트({fallback_hint}) vs 1차({candidate}) → 규칙힌트 우선")
            return fallback_hint
    return candidate

# ===== $h 우선순위 결정 (저자 기반 보정 + 근거 로깅 포함) =====
def determine_h_language(
    title: str,
    original_title: str,
    category_text: str,
    publisher: str,
    author: str,
    subject_lang: str
) -> str:
    """
    문학: 카테고리/웹 → (부족시) GPT → (여전히 불확실) 저자 기반 보정
    비문학: GPT → (부족시) 카테고리/웹 → (여전히 불확실) 저자 기반 보정
    """
    lit_raw = is_literature_category(category_text)
    nf_override = is_nonfiction_override(category_text)
    is_lit_final = lit_raw and not nf_override

    # 사람이 읽기 쉬운 설명
    if lit_raw and not nf_override:
        st.write("📘 [판정] 이 자료는 문학(소설/시/희곡 등) 성격이 뚜렷합니다.")
    elif lit_raw and nf_override:
        st.write("📘 [판정] 겉보기에는 문학이지만, '역사·에세이·사회과학' 등 비문학 요소가 함께 보여 최종적으로는 비문학으로 처리될 수 있습니다.")
    elif not lit_raw and nf_override:
        st.write("📘 [판정] 문학적 단서는 없고, 비문학(역사·사회·철학 등) 성격이 강합니다.")
    else:
        st.write("📘 [판정] 문학/비문학 판단 단서가 약해 추가 판단이 필요합니다.")

    rule_from_original = detect_language(original_title) if original_title else "und"
    lang_h = None
    author_hint = None

    if is_lit_final:
        # 문학: 1) 카테고리/웹 → 2) 원제 유니코드 → 3) GPT → 4) 저자 기반
        lang_h = subject_lang or rule_from_original
        st.write(f"📘 [설명] (문학 흐름) 1차 후보: {lang_h or 'und'}")
        if not lang_h or lang_h == "und":
            st.write("📘 [설명] (문학 흐름) GPT 보완 시도…")
            lang_h = gpt_guess_original_lang(title, category_text, publisher, author, original_title)
            st.write(f"📘 [설명] (문학 흐름) GPT 결과: {lang_h}")
        if (not lang_h or lang_h == "und") and author:
            st.write("📘 [설명] (문학 흐름) 원제 없음/애매 → 저자 기반 보정 시도…")
            author_hint = gpt_guess_original_lang_by_author(author, title, category_text, publisher)
            st.write(f"📘 [설명] (문학 흐름) 저자 기반 결과: {author_hint}")
    else:
        # 비문학: 1) GPT → 2) 카테고리/웹 → 3) 원제 유니코드 → 4) 저자 기반
        st.write("📘 [설명] (비문학 흐름) GPT 선행 판단…")
        lang_h = gpt_guess_original_lang(title, category_text, publisher, author, original_title)
        st.write(f"📘 [설명] (비문학 흐름) GPT 결과: {lang_h or 'und'}")
        if not lang_h or lang_h == "und":
            lang_h = subject_lang or rule_from_original
            st.write(f"📘 [설명] (비문학 흐름) 보조 규칙 적용 → 후보: {lang_h or 'und'}")
        if author and (not lang_h or lang_h == "und"):
            st.write("📘 [설명] (비문학 흐름) 원제 없음/애매 → 저자 기반 보정 시도…")
            author_hint = gpt_guess_original_lang_by_author(author, title, category_text, publisher)
            st.write(f"📘 [설명] (비문학 흐름) 저자 기반 결과: {author_hint}")

    # 충돌 조정
    fallback_hint = subject_lang or rule_from_original
    lang_h = reconcile_language(candidate=lang_h, fallback_hint=fallback_hint, author_hint=author_hint)
    st.write("📘 [결과] 조정 후 원서 언어(h) =", lang_h)

    return (lang_h if lang_h in ALLOWED_CODES else "und") or "und"

# ===== 국내도서 여부 가드 =====
def is_domestic_category(category_text: str) -> bool:
    return "국내도서" in (category_text or "")

# ===== KORMARC 태그 생성기 =====
def get_kormarc_tags(isbn):
    isbn = isbn.strip().replace("-", "")
    url = "http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx"
    params = {
        "ttbkey": ALADIN_KEY,
        "itemIdType": "ISBN13",
        "ItemId": isbn,
        "output": "xml",
        "Version": "20131101"
    }
    try:
        response = requests.get(url, params=params)
        if response.status_code != 200:
            raise ValueError("API 호출 실패")
        root = ET.fromstring(response.content)
        for elem in root.iter():
            elem.tag = strip_ns(elem.tag)
        item = root.find("item")
        if item is None:
            raise ValueError("<item> 태그 없음")

        title = item.findtext("title", default="")
        publisher = item.findtext("publisher", default="")
        author = item.findtext("author", default="")
        subinfo = item.find("subInfo")
        original_title = subinfo.findtext("originalTitle") if subinfo is not None else ""

        crawl = crawl_aladin_fallback(isbn)
        if not original_title:
            original_title = crawl.get("original_title", "")
        subject_lang = crawl.get("subject_lang")
        category_text = crawl.get("category_text", "")

        # ---- $a: 본문 언어 (요청한 순서로 재정렬) ----
        # 1) 규칙 기반 1차 감지
        lang_a = detect_language(title)
        st.write("📘 [DEBUG] 규칙 기반 1차 lang_a =", lang_a)

        # 2) 강한 가드: '국내도서'면 kor로 고정
        if is_domestic_category(category_text):
            st.write("📘 [판정] 카테고리에 '국내도서' 감지 → $a=kor(강한 가드)")
            lang_a = "kor"

        # 3) GPT 보조: und/eng일 때만 호출
        if lang_a in ('und', 'eng'):
            st.write("📘 [설명] und/eng → GPT 보조로 본문 언어 재판정…")
            gpt_a = gpt_guess_main_lang(title, category_text, publisher)
            st.write(f"📘 [설명] GPT 판단 lang_a = {gpt_a}")
            if gpt_a in ALLOWED_CODES:
                lang_a = gpt_a
            else:
                lang_a = "und"

        # ---- $h: 원저 언어 (저자 기반 보정 & 근거 로깅 포함) ----
        st.write("📘 [DEBUG] 원제 감지됨:", bool(original_title), "| 원제:", original_title or "(없음)")
        st.write("📘 [DEBUG] 카테고리 기반 lang_h 후보 =", subject_lang or "(없음)")
        lang_h = determine_h_language(
            title=title,
            original_title=original_title,
            category_text=category_text,
            publisher=publisher,
            author=author,
            subject_lang=subject_lang
        )
        st.write("📘 [결과] 최종 원서 언어(h) =", lang_h)

        # ---- 태그 조합 ----
        if lang_h and lang_h != lang_a and lang_h != "und":
            tag_041 = f"041 $a{lang_a} $h{lang_h}"
        else:
            tag_041 = f"041 $a{lang_a}"
        tag_546 = generate_546_from_041_kormarc(tag_041)

        return tag_041, tag_546, original_title
    except Exception as e:
        return f"📕 예외 발생: {e}", "", ""

# ===== Streamlit UI =====
st.title("📘 KORMARC 041/546 태그 생성기 (저자 보정 + 근거 로깅 통합본)")

isbn_input = st.text_input("ISBN을 입력하세요 (13자리):")
if st.button("태그 생성"):
    if isbn_input:
        try:
            tag_041, tag_546, original = get_kormarc_tags(isbn_input)
            st.text(f"📄 041 태그: {tag_041}")
            if tag_546:
                st.text(f"📄 546 태그: {tag_546}")
            if original:
                st.text(f"📕 원제: {original}")
        except Exception as e:
            st.error(f"⚠️ 오류 발생: {e}")
    else:
        st.warning("ISBN을 입력해주세요.")
