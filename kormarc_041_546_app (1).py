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

# ===== GPT 판단 함수 (원서) =====
def gpt_guess_original_lang(title, category, publisher, author="", original_title=""):
    prompt = f"""
    다음 도서의 정보를 기반으로 원서의 언어(041 $h)를 ISDS 코드 기준으로 유추해줘.
    - 제목: {title}
    - 원제: {original_title}
    - 분류: {category}
    - 출판사: {publisher}
    - 저자: {author}
    가능한 ISDS 언어코드: kor, eng, jpn, chi, rus, fre, ger, ita, spa, por, tur
    응답은 반드시 아래 형식으로 줄 것:
    $h=[ISDS 코드]
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "도서 정보를 바탕으로 원서 언어를 판단하는 사서 AI입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        content = response.choices[0].message.content.strip()
        return content.replace("$h=", "").strip() if content.startswith("$h=") else "und"
    except Exception as e:
        st.error(f"GPT 오류: {e}")
        return "und"

# ===== GPT 판단 함수 (본문) =====
def gpt_guess_main_lang(title, category, publisher, author=""):
    prompt = f"""
    다음 도서의 정보를 기반으로 본문의 언어(041 $a)를 ISDS 코드 기준으로 유추해줘.
    - 제목: {title}
    - 분류: {category}
    - 출판사: {publisher}
    - 저자: {author}
    가능한 ISDS 언어코드: kor, eng, jpn, chi, rus, fre, ger, ita, spa, por, tur
    응답은 반드시 아래 형식으로 줄 것:
    $a=[ISDS 코드]
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "도서 정보를 바탕으로 본문 언어를 판단하는 사서 AI입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        content = response.choices[0].message.content.strip()
        return content.replace("$a=", "").strip() if content.startswith("$a=") else "und"
    except Exception as e:
        st.error(f"GPT 오류: {e}")
        return "und"

# ===== 언어 감지 함수들 =====
def detect_language_by_unicode(text):
    text = re.sub(r'[\s\W_]+', '', text)
    if not text:
        return 'und'
    first_char = text[0]
    if '\uac00' <= first_char <= '\ud7a3': return 'kor'
    elif '\u3040' <= first_char <= '\u30ff': return 'jpn'
    elif '\u4e00' <= first_char <= '\u9fff': return 'chi'
    elif '\u0600' <= first_char <= '\u06FF': return 'ara'
    elif '\u0e00' <= first_char <= '\u0e7f': return 'tha'
    return 'und'

def override_language_by_keywords(text, initial_lang):
    text = text.lower()
    if initial_lang == 'chi' and re.search(r'[\u3040-\u30ff]', text): return 'jpn'
    if initial_lang in ['und', 'eng']:
        if "spanish" in text or "español" in text: return "spa"
        if "italian" in text or "italiano" in text: return "ita"
        if "french" in text or "français" in text: return "fre"
        if "portuguese" in text or "português" in text: return "por"
        if "german" in text or "deutsch" in text: return "ger"
        if any(ch in text for ch in ['é', 'è', 'ê', 'à', 'ç', 'ù', 'ô', 'â', 'î', 'û']): return "fre"
        if any(ch in text for ch in ['ñ', 'á', 'í', 'ó', 'ú']): return "spa"
        if any(ch in text for ch in ['ã', 'õ']): return "por"
    return initial_lang

def detect_language(text):
    lang = detect_language_by_unicode(text)
    return override_language_by_keywords(text, lang)

def detect_language_from_category(text):
    words = re.split(r'[>/\s]+', text or "")
    for word in words:
        if "일본" in word: return "jpn"
        elif "중국" in word: return "chi"
        elif "영미" in word or "영어" in word or "아일랜드" in word: return "eng"
        elif "프랑스" in word: return "fre"
        elif "독일" in word or "오스트리아" in word: return "ger"
        elif "러시아" in word: return "rus"
        elif "이탈리아" in word: return "ita"
        elif "스페인" in word: return "spa"
        elif "포르투갈" in word: return "por"
        elif "튀르키예" in word or "터키" in word: return "tur"
    return None

# ===== 카테고리 토크나이저/키워드 유틸 =====
def tokenize_category(text: str):
    """
    카테고리 문자열을 단어 토큰 리스트로 변환.
    '국내도서 > 소설/시/희곡 > 과학소설(SF)' -> ['국내도서','소설','시','희곡','과학소설','sf']
    """
    if not text:
        return []
    # 구분자: > / 공백, 괄호 제거
    t = re.sub(r'[()]+', ' ', text)
    raw = re.split(r'[>/\s]+', t)
    tokens = []
    for w in raw:
        w = w.strip()
        if not w:
            continue
        # '소설/시/희곡' 같은 묶음을 다시 분해
        if '/' in w and w.count('/') <= 3 and len(w) <= 20:
            parts = [p for p in w.split('/') if p]
            tokens.extend(parts)
        else:
            tokens.append(w)
    # 소문자 버전도 추가(영문 대응)
    lower_tokens = tokens + [w.lower() for w in tokens if any('A' <= ch <= 'Z' or 'a' <= ch <= 'z' for ch in w)]
    return lower_tokens

def has_kw_token(tokens, kws):
    """토큰 리스트에서 '정확히 같은' 키워드가 있는지 검사(부분 일치 배제)."""
    s = set(tokens)
    for k in kws:
        if k in s:
            return True
    return False

def trigger_kw_token(tokens, kws):
    """매칭된 키워드를 하나 돌려줌(디버그용)."""
    s = set(tokens)
    for k in kws:
        if k in s:
            return k
    return None

# ===== 문학/비문학 판정 (보강) =====
def is_literature_top(category_text: str) -> bool:
    """최상위/상위에 문학 장르가 있는지 간단 확인."""
    return "소설/시/희곡" in (category_text or "")

def is_literature_category(category_text: str) -> bool:
    """
    문학(소설/시/희곡) 관련 키워드가 있으면 True.
    ※ '에세이'는 문학 판정에서 제외(논픽션 성격이 강함).
    """
    tokens = tokenize_category(category_text or "")
    ko_hits = ["문학", "소설", "시", "희곡"]
    en_hits = ["literature", "fiction", "novel", "poetry", "poem", "drama", "play"]
    return has_kw_token(tokens, ko_hits) or has_kw_token(tokens, en_hits)

def is_nonfiction_override(category_text: str) -> bool:
    """
    문학처럼 보여도 '역사/지역/전기/사회과학/에세이' 등 비문학 지표가 있으면 비문학으로 강제.
    단, 문학 최상위(소설/시/희곡)가 있으면 '과학/기술'은 오버라이드에서 제외하여
    '과학소설(SF)' 같은 정상적인 문학 장르가 비문학으로 뒤집히지 않게 함.
    """
    tokens = tokenize_category(category_text or "")
    lit_top = is_literature_top(category_text or "")

    # 엄격 비문학 키워드(항상 오버라이드)
    ko_nf_strict = ["역사", "근현대사", "서양사", "유럽사", "전기", "평전",
                    "사회", "정치", "철학", "경제", "경영", "인문", "에세이", "수필"]
    en_nf_strict = ["history", "biography", "memoir", "politics", "philosophy",
                    "economics", "science", "technology", "nonfiction", "essay", "essays"]

    # '과학','기술'은 문학 최상위일 경우 제외(=SF 보호)
    sci_keys = ["과학", "기술"]
    sci_keys_en = ["science", "technology"]

    # 먼저 엄격 비문학 키워드로 체크
    k = trigger_kw_token(tokens, ko_nf_strict) or trigger_kw_token(tokens, en_nf_strict)
    if k:
        st.write(f"🔎 [판정근거] 비문학 키워드 발견: '{k}'")
        return True

    # 문학 최상위가 아니면 과학/기술도 비문학 신호로 허용
    if not lit_top:
        k2 = trigger_kw_token(tokens, sci_keys) or trigger_kw_token(tokens, sci_keys_en)
        if k2:
            st.write(f"🔎 [판정근거] 비문학 최상위 추정 & '{k2}' 발견 → 비문학 오버라이드")
            return True

    # 문학 최상위(+SF) 보호: 과학/기술로는 뒤집지 않음
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
            return f"{a_lang}로 씀, 원저는 {h_lang}임"
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

# ===== $h 우선순위 결정 (설명 메시지 포함) =====
def determine_h_language(
    title: str,
    original_title: str,
    category_text: str,
    publisher: str,
    author: str,
    subject_lang: str
) -> str:
    """
    문학 작품이면: 카테고리/웹 기반 → (부족 시) GPT
    문학 외 자료면: GPT → (부족 시) 카테고리/웹 기반
    (과학소설(SF) 오판 방지: 문학 최상위 시 '과학/기술'로는 비문학 오버라이드 금지)
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

    if is_lit_final:
        # 1순위: 카테고리/웹 기반(크롤링 subject_lang) → 2순위: 원제 유니코드 → 3순위: GPT
        lang_h = subject_lang or rule_from_original
        st.write(f"📘 [설명] (문학 흐름) 카테고리/웹 정보로 우선 판단 → 현재 후보: {lang_h or 'und'}")
        if not lang_h or lang_h == "und":
            st.write("📘 [설명] (문학 흐름) 보완을 위해 GPT에 원서 언어 질의…")
            lang_h = gpt_guess_original_lang(title, category_text, publisher, author, original_title)
            st.write(f"📘 [설명] (문학 흐름) GPT 판단 결과: {lang_h}")
    else:
        # 비문학: 1순위: GPT → 2순위: 카테고리/웹 기반 → 3순위: 원제 유니코드
        st.write("📘 [설명] (비문학 흐름) 우선 GPT로 원서 언어를 판단합니다…")
        lang_h = gpt_guess_original_lang(title, category_text, publisher, author, original_title)
        st.write(f"📘 [설명] (비문학 흐름) GPT 판단 결과: {lang_h or 'und'}")
        if not lang_h or lang_h == "und":
            lang_h = subject_lang or rule_from_original
            st.write(f"📘 [설명] (비문학 흐름) 보조 정보로 카테고리/웹/원제 규칙 적용 → 후보: {lang_h or 'und'}")

    return lang_h or "und"

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

        # ---- $a: 본문 언어 ----
        lang_a = detect_language(title)
        st.write("📘 [DEBUG] 제목 기반 초깃값 lang_a =", lang_a)
        if lang_a in ['und', 'eng']:
            st.write("📘 [설명] 제목만으로 판단이 애매하여 GPT에 본문 언어를 질의합니다…")
            gpt_a = gpt_guess_main_lang(title, category_text, publisher, author)
            st.write(f"📘 [설명] GPT 판단 lang_a = {gpt_a}")
            if gpt_a != 'und':
                lang_a = gpt_a

        # ---- $h: 원저 언어 (문학/비문학 판정 보강 + 설명 메시지) ----
        st.write("📘 [DEBUG] 원제 감지됨:", bool(original_title), "| 원제:", original_title or "(없음)")
        st.write("📘 [DEBUG] 카테고리 기반 lang_h 후보 =", subject_lang)
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
st.title("📘 KORMARC 041/546 태그 생성기 (문학/SF 오판 방지 개선판)")

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
