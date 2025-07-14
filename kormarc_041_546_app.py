import re
import streamlit as st
import requests
import xml.etree.ElementTree as ET
from langdetect import detect

# ISO 639-1 → ISDS 코드
ISO_TO_ISDS = {
    'ko': 'kor', 'en': 'eng', 'ja': 'jpn', 'zh-cn': 'chi', 'zh-tw': 'chi',
    'fr': 'fre', 'de': 'ger', 'ru': 'rus', 'ar': 'ara', 'it': 'ita', 'es': 'spa'
}

# ISDS 코드 → 한국어
ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어',
    'rus': '러시아어', 'ara': '아랍어', 'fre': '프랑스어', 'ger': '독일어',
    'ita': '이탈리아어', 'spa': '스페인어', 'und': '알 수 없음'
}

# 언어 감지 및 매핑
def detect_language(text):
    try:
        lang_code = detect(text)
        return ISO_TO_ISDS.get(lang_code.lower(), 'und')
    except:
        return 'und'

# 041 → 546 변환
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

# 알라딘 API 호출
def get_kormarc_041_tag(isbn):
    isbn = isbn.strip().replace("-", "")
    url = "http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx"
    params = {
        "ttbkey": "ttbmary38642333002",  # 사용자 알라딘 API 키
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
        item = root.find(".//item")
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
        lang_h = detect_language(original_title) if original_title else None

        marc_a = f"$a{lang_a}"
        marc_h = f"$h{lang_h}" if lang_h else ""

        # KORMARC 필드 양식 적용
        marc_041_field = f"041 0#{marc_a}{marc_h}"
        marc_546_text = generate_546_from_041_kormarc(f"{marc_a} {marc_h}".strip())
        marc_546_field = f"546 ##$a{marc_546_text}"

        return marc_041_field, marc_546_field

    except ET.ParseError as e:
        return f"📕 XML 파싱 오류: {str(e)}", ""
    except Exception as e:
        return f"📕 예외 발생: {str(e)}", ""

# Streamlit UI
st.title("📘 KORMARC 041 & 546 태그 생성기")

isbn_input = st.text_input("ISBN을 입력하세요 (13자리):")
if st.button("태그 생성"):
    if isbn_input:
        tag_041, tag_546 = get_kormarc_041_tag(isbn_input)
        st.code(tag_041, language="text")
        if tag_546:
            st.code(tag_546, language="text")
    else:
        st.warning("ISBN을 입력해주세요.")