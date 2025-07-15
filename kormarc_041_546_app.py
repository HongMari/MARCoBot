import re
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
        crawl_result = crawl_aladin_details(isbn)
        if crawl_result:
            if not original_title and crawl_result.get("original_title"):
                original_title = crawl_result["original_title"]
            price = crawl_result.get("price", "")
        else:
            price = ""

        lang_a = detect_language(title)
        lang_h = detect_language(original_title)

        marc_041 = f"041 $a{lang_a}" + (f" $h{lang_h}" if original_title else "")
        marc_546 = generate_546_from_041_kormarc(marc_041)
        marc_020 = f"020 :$c{price}" if price else ""

        return marc_041, marc_546, marc_020, original_title

    except Exception as e:
        return f"📕 예외 발생: {str(e)}", "", "", ""

# 실행용
if __name__ == "__main__":
    isbn_input = input("ISBN13을 입력하세요: ").strip()
    tag_041, tag_546, tag_020, original_title = get_kormarc_tags(isbn_input)

    print("\n📄 생성된 MARC 태그")
    print("041:", tag_041)
    print("546:", tag_546)
    if tag_020:
        print("020:", tag_020)
    if original_title:
        print("원제:", original_title)
