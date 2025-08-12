import re
import os
import openai
import streamlit as st
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()
ALADIN_KEY = os.getenv("ALADIN_TTB_KEY", "ttbdawn63091003001")
openai.api_key = os.getenv("OPENAI_API_KEY")

ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어',
    'rus': '러시아어', 'ara': '아랍어', 'fre': '프랑스어', 'ger': '독일어',
    'ita': '이탈리아어', 'spa': '스페인어', 'por': '포르투갈어', 'tur': '터키어',
    'und': '알 수 없음'
}

def gpt_guess_original_lang(title: str, category: str, publisher: str, author: str = "") -> str:
    prompt = f"""
    다음 도서의 정보를 기반으로 원서의 언어(041 $h)를 ISDS 코드 기준으로 유추해줘.
    - 제목: {title}
    - 분류: {category}
    - 출판사: {publisher}
    - 저자: {author}
    가능한 ISDS 언어코드: kor, eng, jpn, chi, rus, fre, ger, ita, spa, por, tur
    응답은 반드시 아래 형식으로 줄 것:
    $h=[ISDS 코드]
    """
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "도서 정보를 바탕으로 원서 언어를 판단하는 사서 AI입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0
        )
        result = response['choices'][0]['message']['content'].strip()
        if result.startswith("$h="):
            return result.replace("$h=", "").strip()
        return "und"
    except Exception as e:
        st.error(f"GPT 오류: {e}")
        return "und"

def gpt_guess_main_lang(title: str, category: str, publisher: str, author: str = "") -> str:
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
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "도서 정보를 바탕으로 본문 언어를 판단하는 사서 AI입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0
        )
        result = response['choices'][0]['message']['content'].strip()
        if result.startswith("$a="):
            return result.replace("$a=", "").strip()
        return "und"
    except Exception as e:
        st.error(f"GPT 오류: {e}")
        return "und"

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
    words = re.split(r'[>/>\s]+', text)
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

def strip_ns(tag): return tag.split('}')[-1] if '}' in tag else tag

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
        subinfo = item.find("subInfo")
        original_title = subinfo.findtext("originalTitle") if subinfo is not None else ""
        crawl = crawl_aladin_fallback(isbn)
        if not original_title:
            original_title = crawl.get("original_title", "")
        subject_lang = crawl.get("subject_lang")
        category_text = crawl.get("category_text", "")
        lang_a = detect_language(title)
        if lang_a in ['und', 'eng']:
            gpt_a = gpt_guess_main_lang(title, category_text, publisher)
            if gpt_a != 'und':
                lang_a = gpt_a
        if original_title:
            lang_h = subject_lang or detect_language(original_title)
        else:
            lang_h = gpt_guess_original_lang(title, category_text, publisher)
        if lang_h and lang_h != lang_a and lang_h != "und":
            tag_041 = f"041 $a{lang_a} $h{lang_h}"
        else:
            tag_041 = f"041 $a{lang_a}"
        tag_546 = generate_546_from_041_kormarc(tag_041)
        return tag_041, tag_546, original_title
    except Exception as e:
        return f"📕 예외 발생: {e}", "", ""

st.title("📘 KORMARC 041/546 태그 생성기 (GPT 보완 언어 감지 버전)")

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
