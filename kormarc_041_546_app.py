import re
import streamlit as st
import requests
import xml.etree.ElementTree as ET

# ISDS 코드 → 한국어 표현
ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어', 'rus': '러시아어',
    'fre': '프랑스어', 'ger': '독일어', 'ita': '이탈리아어', 'spa': '스페인어',
    'ara': '아랍어', 'per': '페르시아어', 'urd': '우르두어',
    'tha': '태국어', 'mya': '미얀마어', 'khm': '크메르어', 'lao': '라오어',
    'vie': '베트남어', 'ind': '인도네시아어', 'msa': '말레이어',
    'und': '알 수 없음'
}

# ✅ 외부 언어 감지 API 사용 (LibreTranslate)
def detect_language_external(text: str) -> str:
    try:
        url = "https://libretranslate.de/detect"
        response = requests.post(url, json={"q": text}, timeout=5)
        response.raise_for_status()
        result = response.json()
        if not result:
            return 'und'

        lang_code = result[0]['language']
        return {
            'ko': 'kor', 'en': 'eng', 'ja': 'jpn', 'zh': 'chi',
            'fr': 'fre', 'de': 'ger', 'it': 'ita', 'es': 'spa',
            'ar': 'ara', 'fa': 'per', 'ur': 'urd', 'vi': 'vie',
            'th': 'tha', 'id': 'ind', 'ms': 'msa', 'my': 'mya',
            'km': 'khm', 'lo': 'lao', 'ru': 'rus'
        }.get(lang_code, 'und')
    except Exception as e:
        print(f"🌐 언어 감지 API 오류: {e}")
        return 'und'

# ✅ 제목 / 원제 기반으로 $a / $h 언어코드 추출
def infer_languages(title: str, original_title: str) -> tuple:
    lang_a = detect_language_external(title)
    lang_h = detect_language_external(original_title) if original_title else ''
    return lang_a, lang_h

# ✅ 041 → 546 주기 생성
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

# ✅ 알라딘 API 호출 및 041/546 생성
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

        lang_a, lang_h = infer_languages(title, original_title)

        marc_a = f"$a{lang_a}" if lang_a else ""
        marc_h = f"$h{lang_h}" if lang_h else ""

        marc_041 = f"041 {marc_a} {marc_h}".strip()
        marc_546 = generate_546_from_041_kormarc(marc_041)

        return marc_041, marc_546

    except ET.ParseError as e:
        return f"📕 XML 파싱 오류: {str(e)}", ""
    except Exception as e:
        return f"📕 예외 발생: {str(e)}", ""

# ✅ Streamlit 앱 UI
st.title("📘 KORMARC 041 & 546 태그 생성기 (외부 언어 감지 API 연동)")

isbn_input = st.text_input("ISBN을 입력하세요 (13자리):")
if st.button("태그 생성"):
    if isbn_input:
        tag_041, tag_546 = get_kormarc_041_tag(isbn_input)
        st.text(f"📄 생성된 041 태그: {tag_041}")
        if tag_546:
            st.text(f"📄 생성된 546 태그: {tag_546}")
    else:
        st.warning("ISBN을 입력해주세요.")