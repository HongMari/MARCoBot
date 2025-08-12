import re
import os
import streamlit as st
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import langid
from dotenv import load_dotenv

# 환경변수에서 알라딘 API 키 로드
load_dotenv()
ALADIN_KEY = os.getenv("ALADIN_TTB_KEY", "ttbdawn63091003001")

# 언어 코드 매핑표
ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어',
    'rus': '러시아어', 'ara': '아랍어', 'fre': '프랑스어', 'ger': '독일어',
    'ita': '이탈리아어', 'spa': '스페인어', 'por': '포르투갈어', 'tur': '터키어',
    'und': '알 수 없음'
}

# ISBN 그룹 코드에 따른 언어 추정
ISBN_GROUP_LANGUAGE_MAP = {
    '0': 'eng', '1': 'eng',
    '2': 'fre', '3': 'ger', '4': 'jpn', '5': 'rus', '7': 'chi',
    '80': 'ces', '84': 'spa', '85': 'por', '88': 'ita', '89': 'kor'
}

def detect_language_langid(text):
    if not text.strip():
        return 'und'
    code, prob = langid.classify(text)
    return code if prob > 0.85 else 'und'

def infer_language_by_isbn(isbn):
    for length in [2, 1]:
        prefix = isbn[3:3+length]
        if prefix in ISBN_GROUP_LANGUAGE_MAP:
            return ISBN_GROUP_LANGUAGE_MAP[prefix]
    return None

# 웹에서 원제 및 카테고리 언어 추정
def crawl_aladin_fallback(isbn13):
    url = f"https://www.aladin.co.kr/shop/wproduct.aspx?ISBN={isbn13}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        original = soup.select_one("div.info_original")
        return {
            "original_title": original.text.strip() if original else ""
        }
    except:
        return {}

def strip_ns(tag):
    return tag.split('}')[-1] if '}' in tag else tag

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

        # 크롤링 보완
        crawl = crawl_aladin_fallback(isbn)
        if not original_title:
            original_title = crawl.get("original_title", "")

        lang_a = detect_language_langid(title)
        lang_h = detect_language_langid(original_title) if original_title else None

        # ISBN 그룹 보정
        isbn_lang = infer_language_by_isbn(isbn)
        if lang_a == 'und' and isbn_lang:
            lang_a = isbn_lang

        if lang_h and lang_h != lang_a and lang_h != "und":
            tag_041 = f"041 $a{lang_a} $h{lang_h}"
        else:
            tag_041 = f"041 $a{lang_a}"

        tag_546 = generate_546_from_041_kormarc(tag_041)
        return tag_041, tag_546, original_title

    except Exception as e:
        return f"📕 예외 발생: {e}", "", ""

# Streamlit UI
st.title("📘 KORMARC 041/546 태그 생성기 (langid + ISBN 그룹 보정)")

isbn_input = st.text_input("ISBN을 입력하세요 (13자리):")
if st.button("태그 생성"):
    if isbn_input:
        tag_041, tag_546, original = get_kormarc_tags(isbn_input)
        st.text(f"📄 041 태그: {tag_041}")
        if tag_546:
            st.text(f"📄 546 태그: {tag_546}")
        if original:
            st.text(f"📕 원제: {original}")
    else:
        st.warning("ISBN을 입력해주세요.")
