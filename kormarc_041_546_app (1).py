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
    words = re.split(r'[>/>\s]+', text or "")
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

# ===== 문학/비문학 판정 (보강) =====
def is_literature_category(category_text: str) -> bool:
    """
    알라딘 카테고리 문자열에서 문학/소설/시/희곡 계열이면 True.
    ※ '에세이'는 문학 판정에서 제외(논픽션 성격이 강함).
    """
    ct = (category_text or "").lower()
    # 한국어 키워드 (에세이 제외)
    ko_hits = ["문학", "소설/시/희곡", "소설", "시", "희곡"]
    # 영문 키워드
    en_hits = ["literature", "fiction", "novel", "poetry", "poem", "drama", "play"]
    return any(k in (category_text or "") for k in ko_hits) or any(k in ct for k in en_hits)

def is_nonfiction_override(category_text: str) -> bool:
    """
    문학처럼 보여도 '역사/지역/전기/사회과학/에세이' 등 비문학 지표가 있으면 비문학으로 강제.
    """
    ct = (category_text or "").lower()
    ko_nf = [
        "역사", "사 ", "근현대사", "서양사", "유럽사", "독일/오스트리아사",
        "전기", "평전", "사회", "정치", "철학", "경제", "경영", "과학", "기술",
        "인문", "에세이", "수필"
    ]
    en_nf = [
        "history", "biography", "memoir", "politics", "philosophy", "economics",
        "science", "technology", "nonfiction", "essay", "essays"
    ]
    return any(k in (category_text or "") for k in ko_nf) or any(k in ct for k in en_nf)

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

# ===== $h 우선순위 결정 (문학/비문학 판정만 보강) =====
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
    ※ 문학/비문학 판정만 보강, 나머지 흐름은 기존과 동일.
    """
    lit_raw = is_literature_category(category_text, user_extra=user_lit_keywords)
    nf_override = is_nonfiction_override(category_text, user_extra=user_nonlit_keywords)
    is_lit_final = lit_raw and not nf_override
    
    # 사람이 읽기 쉽게 설명
    if lit_raw and not nf_override:
    st.write("📘 [판정] 이 책은 문학(소설/시/희곡 등)으로 분류됩니다.")
    elif lit_raw and nf_override:
    st.write("📘 [판정] 겉보기에는 문학이지만, '역사·에세이·사회과학' 등 비문학 요소가 섞여 최종적으로는 비문학으로 분류될 수 있습니다.")
    elif not lit_raw and nf_override:
    st.write("📘 [판정] 문학적 특징은 없고, 비문학(역사·사회·철학 등)으로 분류됩니다.")
    else:
    st.write("📘 [판정] 문학/비문학 단서가 뚜렷하지 않아 추가 판단이 필요합니다.")

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
            st.write("📘 [DEBUG] GPT 요청: 본문 언어 판단 정보 =", title, category_text, publisher, author)
            gpt_a = gpt_guess_main_lang(title, category_text, publisher, author)
            st.write("📘 [DEBUG] GPT 판단 lang_a =", gpt_a)
            if gpt_a != 'und':
                lang_a = gpt_a

        # ---- $h: 원저 언어 (문학/비문학 판정만 보강) ----
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
        st.write("📘 [DEBUG] 최종 lang_h =", lang_h)

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
st.title("📘 KORMARC 041/546 태그 생성기 (문학/비문학 판정 보강)")

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


