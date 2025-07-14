import re
import streamlit as st
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

# ISDS 언어코드 → 한국어 표현
ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어', 'rus': '러시아어',
    'ara': '아랍어', 'fre': '프랑스어', 'ger': '독일어', 'ita': '이탈리아어', 'spa': '스페인어',
    'und': '알 수 없음'
}

# 알라딘 주제분류 → 언어 코드 매핑
SUBJECT_TO_LANG = {
    "일본소설": "jpn", "일본문학": "jpn", "영미문학": "eng", "영국소설": "eng",
    "프랑스소설": "fre", "프랑스문학": "fre", "독일문학": "ger", "중국소설": "chi",
    "중국문학": "chi", "러시아문학": "rus", "한국소설": "kor", "한국문학": "kor"
}

# 크롤링으로 알라딘 주제 + 본문 언어 힌트 가져오기
def get_aladin_subject_and_language_hint(isbn13: str):
    url = f"https://www.aladin.co.kr/shop/wproduct.aspx?ISBN={isbn13}"
    headers = {"User-Agent": "Mozilla/5.0"}

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return "", ""

    soup = BeautifulSoup(response.text, "html.parser")

    # 주제분류
    subject = ""
    subject_tag = soup.select_one("#divCategory > ul > li")
    if subject_tag:
        subject = subject_tag.get_text(strip=True)

    # 본문 언어 힌트 (텍스트 탐색)
    text = soup.get_text()
    language_hint = ""
    if "일본어로 된 책" in text or "일본어 원서" in text:
        language_hint = "jpn"
    elif "영어 원서" in text or "영어로 쓰인 책" in text:
        language_hint = "eng"
    elif "프랑스어로" in text or "프랑스어 원서" in text:
        language_hint = "fre"
    elif "독일어로 된 책" in text:
        language_hint = "ger"
    elif "중국어" in text or "중국어로 된 책" in text:
        language_hint = "chi"

    return subject, language_hint

# 주제분류 → 언어코드 ($h)
def infer_h_from_subject(subject: str) -> str:
    for keyword, lang_code in SUBJECT_TO_LANG.items():
        if keyword in subject:
            return lang_code
    return ""

# fallback 언어 감지기 (유니코드 기반)
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

# 알라딘 API 호출 + 웹 크롤링으로 041/546 생성
def get_kormarc_041_tag(isbn):
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
        return "❌ API 호출 실패", ""

    try:
        root = ET.fromstring(response.content)
        item = root.find("item")
        if item is None:
            return "📕 <item> 태그를 찾을 수 없습니다.", ""

        title = item.findtext("title", default="")
        subinfo = item.find("subInfo")
        original_title = ""
        if subinfo is not None:
            ot = subinfo.find("originalTitle")
            if ot is not None and ot.text:
                original_title = ot.text

        # 크롤링으로 주제 + 언어 힌트 추출
        subject, page_lang_hint = get_aladin_subject_and_language_hint(isbn)

        lang_a = page_lang_hint or detect_language(title)
        lang_h = detect_language(original_title) if original_title else infer_h_from_subject(subject)

        marc_a = f"$a{lang_a}"
        marc_h = f"$h{lang_h}" if lang_h else ""

        marc_041 = f"041 {marc_a} {marc_h}".strip()
        marc_546 = generate_546_from_041_kormarc(marc_041)

        return marc_041, marc_546

    except ET.ParseError as e:
        return f"📕 XML 파싱 오류: {str(e)}", ""
    except Exception as e:
        return f"📕 예외 발생: {str(e)}", ""

# Streamlit 앱 인터페이스
st.title("📘 KORMARC 041 & 546 태그 생성기 (알라딘 웹페이지 기반)")

isbn_input = st.text_input("ISBN을 입력하세요 (13자리):")
if st.button("태그 생성"):
    if isbn_input:
        tag_041, tag_546 = get_kormarc_041_tag(isbn_input)
        st.text(f"📄 생성된 041 태그: {tag_041}")
        if tag_546:
            st.text(f"📄 생성된 546 태그: {tag_546}")
    else:
        st.warning("ISBN을 입력해주세요.")