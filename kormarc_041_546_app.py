import re
import streamlit as st
import requests
import xml.etree.ElementTree as ET
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# ISDS 언어코드 → 한국어 표현
ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어', 'rus': '러시아어',
    'ara': '아랍어', 'fre': '프랑스어', 'ger': '독일어', 'ita': '이탈리아어', 'spa': '스페인어',
    'und': '알 수 없음'
}

# 언어 감지 함수
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

# 041 → 546 주기 생성
def generate_546_from_041_kormarc(marc_041: str) -> str:
    a_codes = []
    h_code = None
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
    else:
        return "언어 정보 없음"

# Playwright로 알라딘 상품 상세 크롤링
def crawl_aladin_details(itemid_or_isbn13):
    url = f"https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={itemid_or_isbn13}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=10000)
            content = page.content()
            browser.close()
        soup = BeautifulSoup(content, 'html.parser')
        original_tag = soup.select_one("div.info_original")
        original_title = original_tag.text.strip() if original_tag else None
        price_tag = soup.select_one("span.price2")
        price_text = price_tag.text.strip() if price_tag else ""
        price_text = price_text.replace("정가 : ", "").replace("원", "").replace(",", "").strip()
        return {
            "original_title": original_title,
            "price": price_text
        }
    except Exception as e:
        print("크롤링 실패:", e)
        return None

# API 호출 및 MARC 필드 생성
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

    response = requests.get(url, params=params)
    if response.status_code != 200:
        return "❌ API 호출 실패", "", "", ""

    try:
        root = ET.fromstring(response.content)
        item = root.find(".//item")
        if item is None:
            raise ValueError("📕 <item> 태그 없음")

        title = item.findtext("title", default="")
        subinfo = item.find("subInfo")
        original_title = ""
        if subinfo is not None:
            ot = subinfo.find("originalTitle")
            if ot is not None and ot.text:
                original_title = ot.text.strip()

        # 크롤링으로 보완
        if not original_title:
            crawl_result = crawl_aladin_details(isbn)
            if crawl_result and crawl_result["original_title"]:
                original_title = crawl_result["original_title"]
            if crawl_result and crawl_result["price"]:
                price = f":$c{crawl_result['price']}"
            else:
                price = ""
        else:
            price = ""

        lang_a = detect_language(title)
        lang_h = detect_language(original_title)
        marc_a = f"$a{lang_a}"
        marc_h = f"$h{lang_h}" if original_title else ""

        tag_041 = f"041 {marc_a} {marc_h}".strip()
        tag_546 = generate_546_from_041_kormarc(tag_041)
        tag_020 = f"020 {price}" if price else ""

        return tag_041, tag_546, tag_020, original_title

    except Exception as e:
        return f"📕 예외 발생: {str(e)}", "", "", ""

# Streamlit 앱 UI
st.title("📘 KORMARC 041 & 546 + 020 태그 생성기 (API + 크롤링)")

isbn_input = st.text_input("ISBN을 입력하세요 (13자리):")
if st.button("태그 생성"):
    if isbn_input:
        tag_041, tag_546, tag_020, ot = get_kormarc_tags(isbn_input)
        st.text(f"📄 생성된 041 태그: {tag_041}")
        if tag_546:
            st.text(f"📄 생성된 546 태그: {tag_546}")
        if tag_020:
            st.text(f"📄 생성된 020 태그: {tag_020}")
        if ot:
            st.text(f"📕 원제: {ot}")
    else:
        st.warning("ISBN을 입력해주세요.")
