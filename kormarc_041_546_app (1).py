
import re
import os
import openai
import streamlit as st
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
ALADIN_KEY = os.getenv("ALADIN_TTB_KEY")
openai.api_key = os.getenv("OPENAI_API_KEY")

ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어',
    'rus': '러시아어', 'ara': '아랍어', 'fre': '프랑스어', 'ger': '독일어',
    'ita': '이탈리아어', 'spa': '스페인어', 'por': '포르투갈어', 'tur': '터키어',
    'und': '알 수 없음'
}

def gpt_guess_lang(title, category, publisher, author=""):
    roman_hint = "이 도서의 제목은 로마자 표기로 되어 있지만 반드시 영어(eng)라는 보장은 없습니다.\n" if re.match(r'^[A-Za-z0-9\s\W]+$', title) else ""
    prompt = f"""
    {roman_hint}
    다음 도서 정보를 바탕으로 원서의 언어(041 $h)를 ISDS 코드로 정확히 추정해줘.
    - 제목: {title}
    - 분류: {category}
    - 출판사: {publisher}
    - 저자: {author}

    가능한 ISDS 언어코드: kor, eng, jpn, chi, rus, fre, ger, ita, spa, por, tur
    응답 형식: $h=[ISDS 코드]
    """
    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "도서 정보를 바탕으로 언어를 감별하는 사서 AI입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        result = response.choices[0].message.content.strip()
        if result.startswith("$h="):
            return result[3:].strip()
    except Exception as e:
        st.error(f"GPT 오류: {e}")
    return "und"

def detect_language_by_unicode(text):
    text = re.sub(r'[\s\W_]+', '', text)
    if not text: return 'und'
    ch = text[0]
    if '\uac00' <= ch <= '\ud7a3': return 'kor'
    elif '\u3040' <= ch <= '\u30ff': return 'jpn'
    elif '\u4e00' <= ch <= '\u9fff': return 'chi'
    elif '\u0600' <= ch <= '\u06FF': return 'ara'
    elif '\u0e00' <= ch <= '\u0e7f': return 'tha'
    return 'und'

def override_by_keywords(text, lang):
    text = text.lower()
    if lang == 'chi' and re.search(r'[\u3040-\u30ff]', text): return 'jpn'
    if lang in ['und', 'eng']:
        if "french" in text or "français" in text or any(ch in text for ch in ['é', 'è']): return "fre"
        if "spanish" in text or "español" in text or 'ñ' in text: return "spa"
        if "german" in text or "deutsch" in text: return "ger"
        if "italian" in text or "italiano" in text: return "ita"
        if "portuguese" in text or "português" in text: return "por"
    return lang

def detect_language(text):
    return override_by_keywords(text, detect_language_by_unicode(text))

def detect_from_category(text):
    if any(w in text for w in ["일본"]): return "jpn"
    if any(w in text for w in ["중국"]): return "chi"
    if any(w in text for w in ["영미", "영어", "아일랜드"]): return "eng"
    if "프랑스" in text: return "fre"
    if any(w in text for w in ["독일", "오스트리아"]): return "ger"
    if "러시아" in text: return "rus"
    if "이탈리아" in text: return "ita"
    if "스페인" in text: return "spa"
    if "포르투갈" in text: return "por"
    if any(w in text for w in ["튀르키예", "터키"]): return "tur"
    return None

def generate_546(marc_041):
    a_codes, h_code = [], None
    for part in marc_041.split():
        if part.startswith("$a"): a_codes.append(part[2:])
        elif part.startswith("$h"): h_code = part[2:]
    if len(a_codes) == 1:
        a = ISDS_LANGUAGE_CODES.get(a_codes[0], "알 수 없음")
        h = ISDS_LANGUAGE_CODES.get(h_code, "알 수 없음") if h_code else None
        return f"{a}로 씀, 원저는 {h}임" if h else f"{a}로 씀"
    elif len(a_codes) > 1:
        langs = [ISDS_LANGUAGE_CODES.get(code, "알 수 없음") for code in a_codes]
        return f"{'、'.join(langs)} 병기"
    return "언어 정보 없음"

def strip_ns(tag): return tag.split('}')[-1] if '}' in tag else tag

def crawl_aladin(isbn):
    url = f"https://www.aladin.co.kr/shop/wproduct.aspx?ISBN={isbn}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        original = soup.select_one("div.info_original")
        categories = soup.select("div.conts_info_list2 li")
        category_text = " ".join([c.get_text(" ", strip=True) for c in categories])
        return {
            "original_title": original.text.strip() if original else "",
            "category_text": category_text
        }
    except Exception as e:
        st.error(f"크롤링 오류: {e}")
        return {"original_title": "", "category_text": ""}

# $h 원서 언어 판단
def guess_lang_h(original_title, category, publisher, author):
    if original_title:
        return detect_language(original_title)
    if re.search(r'[가-힣]', author):
        st.write("📘 [DEBUG][$h] 저자명 한글 → 한국어")
        return "kor"
    if re.search(r'[一-龥]', author): return "chi"
    if re.search(r'[ぁ-んァ-ン]', author): return "jpn"
    cat_lang = detect_from_category(category)
    if cat_lang:
        st.write("📘 [DEBUG][$h] 카테고리 기반 판단 =", cat_lang)
        return cat_lang
    st.write("📘 [DEBUG][$h] GPT 요청 →", original_title, category, publisher, author)
    return gpt_guess_lang(original_title or "없음", category, publisher, author)

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
        r = requests.get(url, params=params)
        if r.status_code != 200: raise Exception("API 오류")
        root = ET.fromstring(r.content)
        for e in root.iter(): e.tag = strip_ns(e.tag)

        item = root.find("item")
        if item is None: raise Exception("item 태그 없음")

        title = item.findtext("title", default="")
        publisher = item.findtext("publisher", default="")
        author = item.findtext("author", default="")
        subinfo = item.find("subInfo")
        original_title = subinfo.findtext("originalTitle") if subinfo is not None else ""

        crawl = crawl_aladin(isbn)
        if not original_title:
            original_title = crawl["original_title"]
        category_text = crawl["category_text"]

        lang_a = detect_language(title)
        if lang_a == "und":
            lang_a = detect_from_category(category_text) or gpt_guess_lang(title, category_text, publisher, author)
        st.write("📘 [DEBUG][$a] 최종 판단 =", lang_a)

        lang_h = guess_lang_h(original_title, category_text, publisher, author)
        st.write("📘 [DEBUG][$h] 최종 판단 =", lang_h)

        if lang_h and lang_h != lang_a and lang_h != "und":
            tag_041 = f"041 $a{lang_a} $h{lang_h}"
        else:
            tag_041 = f"041 $a{lang_a}"
        tag_546 = generate_546(tag_041)
        return tag_041, tag_546, original_title

    except Exception as e:
        return f"📕 오류: {e}", "", ""

# UI
st.title("📘 KORMARC 041/546 태그 생성기")

isbn_input = st.text_input("ISBN을 입력하세요 (13자리):")
if st.button("태그 생성"):
    if isbn_input:
        tag_041, tag_546, original = get_kormarc_tags(isbn_input)
        st.text(f"📄 041 태그: {tag_041}")
        if tag_546: st.text(f"📄 546 태그: {tag_546}")
        if original: st.text(f"📕 원제: {original}")
    else:
        st.warning("ISBN을 입력해주세요.")
