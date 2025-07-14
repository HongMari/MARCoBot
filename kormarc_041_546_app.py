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
    # Step 1: 알라딘 API 호출
    api_url = (
        f"http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx?"
        f"ttbkey={ttbkey}&itemIdType=ISBN13&ItemId={isbn13}"
        f"&output=xml&Version=20131101&OptResult=ebookList,reviewList"
    )
    response = requests.get(api_url)
    root = ET.fromstring(response.text)

    item = root.find("item")
    if item is None:
        raise ValueError("알라딘 API에서 item을 찾을 수 없습니다")

    # API에서 원제와 상품명 추출
    title = item.findtext("title", "")
    original_title = item.findtext("subInfo/originalTitle", "")

    def lang_detect(name, fallback_text):
        lang = detect_language_from_text(name)
        if not lang:
            # 웹 크롤링 보완
            try:
                html = requests.get(f"https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={item.findtext('itemId')}").text
                soup = BeautifulSoup(html, "html.parser")
                detail = soup.select_one("#Ere_prod_mconts_box").text
                lang = detect_language_from_text(detail)
            except Exception:
                lang = None
        return lang or fallback_text

    # 언어 감지 수행
    lang_a = lang_detect(title, "und")
    lang_h = lang_detect(original_title, "und") if original_title else None

    # 041 태그 구성
    field_041 = f"041 0#$a{lang_a}" + (f"$h{lang_h}" if lang_h else "")

    # 546 태그 구성
    desc = f"본문 언어는 {lang_a}"
    if lang_h:
        desc += f", 원작은 {lang_h}"
    desc += "."

    field_546 = f"546 ##$a{desc}"

    return field_041, field_546