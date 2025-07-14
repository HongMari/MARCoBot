import re
import streamlit as st
import requests
import xml.etree.ElementTree as ET

ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어', 'rus': '러시아어',
    'ara': '아랍어', 'per': '페르시아어', 'urd': '우르두어',
    'fre': '프랑스어', 'ger': '독일어', 'ita': '이탈리아어', 'spa': '스페인어',
    'und': '알 수 없음'
}

# 언어 판별: 특수문자/공백 제거 후 첫 글자 기준
def detect_language(text: str) -> str:
    text = re.sub(r'[\s\W_]+', '', text)
    if not text:
        return 'und'

    # 유니코드 범위 기반 언어 감지
    has_hiragana = any('\u3040' <= c <= '\u309F' for c in text)
    has_katakana = any('\u30A0' <= c <= '\u30FF' for c in text)
    has_han = any('\u4E00' <= c <= '\u9FFF' for c in text)
    has_arabic = any('\u0600' <= c <= '\u06FF' for c in text)

    if has_hiragana or has_katakana:
        return 'jpn'
    elif has_han:
        return 'chi'
    elif has_arabic:
        # 아랍어 단어 패턴으로 간이 구분
        if any(word in text for word in ['الله', 'محمد', 'السلام']):
            return 'ara'
        elif any(word in text for word in ['فارسی', 'کتاب', 'دانشگاه']):
            return 'per'  # 페르시아어
        elif any(word in text for word in ['اردو', 'کتابیں', 'خبریں']):
            return 'urd'  # 우르두어
        else:
            return 'ara'
    elif '\u0400' <= text[0] <= '\u04FF':
        return 'rus'
    elif 'a' <= text[0].lower() <= 'z':
        return 'eng'
    elif '\uAC00' <= text[0] <= '\uD7A3':
        return 'kor'
    else:
        return 'und'

# 041 태그 → 546 주기 생성
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

# API 호출 및 041 + 546 생성
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

        lang_a = detect_language(title)
        lang_h = detect_language(original_title)

        marc_a = f"$a{lang_a}"
        marc_h = f"$h{lang_h}" if original_title else ""

        marc_041 = f"041 {marc_a} {marc_h}".strip()
        marc_546 = generate_546_from_041_kormarc(marc_041)

        return marc_041, marc_546

    except ET.ParseError as e:
        return f"📕 XML 파싱 오류: {str(e)}", ""
    except Exception as e:
        return f"📕 예외 발생: {str(e)}", ""

# Streamlit 앱 인터페이스
st.title("📘 KORMARC 041 & 546 태그 생성기")

isbn_input = st.text_input("ISBN을 입력하세요 (13자리):")
if st.button("태그 생성"):
    if isbn_input:
        tag_041, tag_546 = get_kormarc_041_tag(isbn_input)
        st.text(f"📄 생성된 041 태그: {tag_041}")
        if tag_546:
            st.text(f"📄 생성된 546 태그: {tag_546}")
    else:
        st.warning("ISBN을 입력해주세요.")