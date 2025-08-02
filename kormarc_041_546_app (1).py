import re
import os
import streamlit as st
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# 환경변수에서 API 키 로드
load_dotenv()
ALADIN_KEY = os.getenv("ALADIN_TTB_KEY", "ttbdawn63091003001")

# ISDS 언어코드 매핑
ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어',
    'rus': '러시아어', 'ara': '아랍어', 'fre': '프랑스어', 'ger': '독일어',
    'ita': '이탈리아어', 'spa': '스페인어', 'por': '포르투갈어', 'tur': '터키어',
    'und': '알 수 없음'
}

# 유니코드 범위 기반 언어 감지
def detect_language_by_unicode(text):
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
    elif '\u0600' <= first_char <= '\u06FF':
        return 'ara'
    elif '\u0e00' <= first_char <= '\u0e7f':
        return 'tha'
    elif 'a' <= first_char.lower() <= 'z':
        return 'eng'
    return 'und'

# 언어 키워드 및 특수문자 기반 오버라이드
def override_language_by_keywords(text, initial_lang):
    text = text.lower()

    if initial_lang == 'chi' and re.search(r'[\u3040-\u30ff]', text):
        return 'jpn'

    if initial_lang == 'eng':
        if "spanish" in text or "español" in text:
            return "spa"
        if "italian" in text or "italiano" in text:
            return "ita"
        if "french" in text or "français" in text:
            return "fre"
        if "portuguese" in text or "português" in text:
            return "por"
        if "german" in text or "deutsch" in text:
            return "ger"
        if any(ch in text for ch in ['é', 'è', 'ê', 'à', 'ç', 'ù', 'ô', 'â', 'î', 'û']):
            return "fre"
        if any(ch in text for ch in ['ñ', 'á', 'í', 'ó', 'ú']):
            return "spa"
        if any(ch in text for ch in ['ã', 'õ']):
            return "por"

    return initial_lang

# 종합 언어 감지
def detect_language(text):
    lang = detect_language_by_unicode(text)
    return override_language_by_keywords(text, lang)

# 카테고리에서 언어 추정
def detect_language_from_category(text):
    words = re.split(r'[>/>\s]+', text)
    for word in words:
        if "일본" in word:
            return "jpn"
        elif "중국" in word:
            return "chi"
        elif "영미" in word or "영어" in word or "아일랜드" in word:
            return "eng"
        elif "프랑스" in word:
            return "fre"
        elif "독일" in word or "오스트리아" in word:
            return "ger"
        elif "러시아" in word:
            return "rus"
        elif "이탈리아" in word:
            return "ita"
        elif "스페인" in word:
            return "spa"
        elif "포르투갈" in word:
            return "por"
        elif "튀르키예" in word or "터키" in word:
            return "tur"
    return None

# 546 태그 생성
def generate_546_from_041_kormarc(marc_041: str) -> str:
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
            return f"{a_lang}로 씀, 원저는 {h_lang}임"
        else:
            return f"{a_lang}로 씀"
    elif len(a_codes) > 1:
        langs = [ISDS_LANGUAGE_CODES.get(code, "알 수 없음") for code in a_codes]
        return f"{'、'.join(langs)} 병기"
    return "언어 정보 없음"

# 네임스페이스 제거
def strip_ns(tag):
    return tag.split('}')[-1] if '}' in tag else tag

# 알라딘 웹페이지 크롤링
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

        st.write("📘 [DEBUG] category_text =", category_text)
        category_lang = detect_language_from_category(category_text)
        st.write("📘 [DEBUG] category_lang =", category_lang)

        detected_lang = ""
        if lang_info and "언어" in lang_info.text:
            if "Japanese" in lang_info.text:
                detected_lang = "jpn"
            elif "Chinese" in lang_info.text:
                detected_lang = "chi"
            elif "English" in lang_info.text:
                detected_lang = "eng"

        return {
            "original_title": original.text.strip() if original else "",
            "subject_lang": category_lang or detected_lang
        }
    except Exception as e:
        st.error(f"❌ 크롤링 중 오류 발생: {e}")
        return {}

# KORMARC 태그 생성
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
        subinfo = item.find("subInfo")
        original_title = subinfo.findtext("originalTitle") if subinfo is not None else ""

        crawl = crawl_aladin_fallback(isbn)
        if not original_title:
            original_title = crawl.get("original_title", "")
        subject_lang = crawl.get("subject_lang")

        lang_a = detect_language(title)
        lang_h = subject_lang or detect_language(original_title)

        tag_041 = f"041 $a{lang_a}" + (
            f" $h{lang_h}" if lang_h and lang_h != lang_a and lang_h != "und" else ""
        )
        tag_546 = generate_546_from_041_kormarc(tag_041)

        return tag_041, tag_546, original_title

    except Exception as e:
        return f"📕 예외 발생: {e}", "", ""

# ✅ Streamlit UI 시작
st.title("📘 KORMARC 041/546 태그 생성기 (카테고리 기반 언어 감지 포함)")

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
