import re
import streamlit as st
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

# 언어 코드 → 한국어 표현
ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어', 'rus': '러시아어',
    'ara': '아랍어', 'fre': '프랑스어', 'ger': '독일어', 'ita': '이탈리아어', 'spa': '스페인어',
    'und': '알 수 없음'
}

def detect_language(text):
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

# 네임스페이스 제거 함수
def strip_ns(tag):
    return tag.split('}')[-1] if '}' in tag else tag

# 웹에서 원제와 가격 보완
def crawl_aladin_fallback(isbn13):
    url = f"https://www.aladin.co.kr/shop/wproduct.aspx?ISBN={isbn13}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        original = soup.select_one("div.info_original")
        price = soup.select_one("span.price2")
        return {
            "original_title": original.text.strip() if original else "",
            "price": price.text.strip().replace("정가 : ", "").replace("원", "").replace(",", "").strip() if price else ""
        }
    except:
        return {}

# 041/546/020 생성
def get_kormarc_tags(isbn):
    isbn = isbn.strip().replace("-", "")
    url = "http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx"
    params = {
        "ttbkey": "ttbmary38642333002",
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

        # 네임스페이스 제거: {http://...}item → item
        for elem in root.iter():
            elem.tag = strip_ns(elem.tag)

        item = root.find("item")
        if item is None:
            raise ValueError("<item> 태그 없음")

        title = item.findtext("title", default="")
        subinfo = item.find("subInfo")
        original_title = subinfo.findtext("originalTitle") if subinfo is not None else ""

        # 부족한 경우 웹 크롤링 보완
        crawl = crawl_aladin_fallback(isbn)
        if not original_title:
            original_title = crawl.get("original_title", "")
        price = crawl.get("price", "")

        lang_a = detect_language(title)
        lang_h = detect_language(original_title)
        tag_041 = f"041 $a{lang_a}" + (f" $h{lang_h}" if original_title else "")
        tag_546 = generate_546_from_041_kormarc(tag_041)
        tag_020 = f"020 :$c{price}" if price else ""

        return tag_041, tag_546, tag_020, original_title

    except Exception as e:
        return f"📕 예외 발생: {e}", "", "", ""

# Streamlit UI
st.title("📘 KORMARC 041 & 546 + 020 태그 생성기 (네임스페이스 대응 완전판)")

isbn_input = st.text_input("ISBN을 입력하세요 (13자리):")
if st.button("태그 생성"):
    if isbn_input:
        tag_041, tag_546, tag_020, original = get_kormarc_tags(isbn_input)
        st.text(f"📄 041 태그: {tag_041}")
        if tag_546:
            st.text(f"📄 546 태그: {tag_546}")
        if tag_020:
            st.text(f"📄 020 태그: {tag_020}")
        if original:
            st.text(f"📕 원제: {original}")
    else:
        st.warning("ISBN을 입력해주세요.")
