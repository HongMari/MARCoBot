import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

def detect_language_from_text(text):
    text = text.lower()
    if any(word in text for word in ["english", "영어"]):
        return "eng"
    elif any(word in text for word in ["korean", "한국어", "한글"]):
        return "kor"
    elif any(word in text for word in ["japanese", "일본어"]):
        return "jpn"
    elif any(word in text for word in ["chinese", "중국어"]):
        return "chi"
    elif any(word in text for word in ["french", "프랑스어"]):
        return "fre"
    elif any(word in text for word in ["german", "독일어"]):
        return "ger"
    else:
        return None

def get_041_546_by_aladin_api_and_crawl(isbn13: str, ttbkey: str):
    api_url = (
        f"http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx?"
        f"ttbkey={ttbkey}&itemIdType=ISBN13&ItemId={isbn13}"
        f"&output=xml&Version=20131101&OptResult=ebookList,reviewList"
    )
    response = requests.get(api_url)
    root = ET.fromstring(response.text)

    item = root.find("item")
    if item is None:
        raise ValueError("알라딘 API에서 item을 찾을 수 없습니다.\n응답내용:\n" + response.text)

    title = item.findtext("title", "")
    sub_info = item.find("subInfo")
    original_title = sub_info.findtext("originalTitle", "") if sub_info is not None else ""

    def lang_detect(text_source, fallback_lang):
        lang = detect_language_from_text(text_source)
        if lang:
            return lang

        # 웹 크롤링 보완
        try:
            item_id = item.findtext("itemId")
            if not item_id:
                return fallback_lang
            html = requests.get(f"https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={item_id}").text
            soup = BeautifulSoup(html, "html.parser")
            detail_elem = soup.select_one("#Ere_prod_mconts_box")
            if detail_elem:
                detail = detail_elem.get_text()
                lang = detect_language_from_text(detail)
        except Exception:
            lang = None
        return lang or fallback_lang

    lang_a = lang_detect(title, "und")
    lang_h = lang_detect(original_title, "und") if original_title else None

    # 041 MARC 필드
    field_041 = f"041 0#$a{lang_a}" + (f"$h{lang_h}" if lang_h else "")

    # 546 MARC 필드
    desc = f"본문 언어는 {lang_a}"
    if lang_h:
        desc += f", 원작은 {lang_h}"
    desc += "."
    field_546 = f"546 ##$a{desc}"

    return field_041, field_546