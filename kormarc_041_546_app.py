import streamlit as st
import requests
import re
import xml.etree.ElementTree as ET
import fasttext
import fasttext.util
import os

# 1) 모델 다운로드 (최초 1회 실행)
MODEL_PATH = "lid.176.ftz"
if not os.path.exists(MODEL_PATH):
    with st.spinner("🔽 fastText 언어 모델 다운로드 중..."):
        fasttext.util.download_model('lid.176', if_exists='ignore')

# 2) 모델 로딩 (캐싱으로 재사용)
@st.cache_resource
def load_fasttext_model():
    return fasttext.load_model(MODEL_PATH)

model = load_fasttext_model()

# 3) fastText 기반 언어 감지
def detect_language_fasttext(text: str) -> str:
    if not text.strip():
        return 'und'
    prediction = model.predict(text.strip().replace("\n", " "))[0][0]
    lang_code = prediction.replace('__label__', '')
    return {
        'ko': 'kor', 'en': 'eng', 'ja': 'jpn', 'zh': 'chi',
        'fr': 'fre', 'de': 'ger', 'it': 'ita', 'es': 'spa',
        'ar': 'ara', 'fa': 'per', 'ur': 'urd', 'vi': 'vie',
        'th': 'tha', 'id': 'ind', 'ms': 'msa', 'my': 'mya',
        'km': 'khm', 'lo': 'lao', 'ru': 'rus'
    }.get(lang_code, 'und')

# 4) 041 → 546 주기
ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어', 'rus': '러시아어',
    'fre': '프랑스어', 'ger': '독일어', 'ita': '이탈리아어', 'spa': '스페인어',
    'ara': '아랍어', 'per': '페르시아어', 'urd': '우르두어',
    'tha': '태국어', 'mya': '미얀마어', 'khm': '크메르어', 'lao': '라오어',
    'vie': '베트남어', 'ind': '인도네시아어', 'msa': '말레이어',
    'und': '알 수 없음'
}

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

# 5) 알라딘 API 호출 및 태그 생성
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

        lang_a = detect_language_fasttext(title)
        lang_h = detect_language_fasttext(original_title) if original_title else ""

        marc_a = f"$a{lang_a}" if lang_a else ""
        marc_h = f"$h{lang_h}" if lang_h else ""

        marc_041 = f"041 {marc_a} {marc_h}".strip()
        marc_546 = generate_546_from_041_kormarc(marc_041)

        return marc_041, marc_546

    except ET.ParseError as e:
        return f"📕 XML 파싱 오류: {str(e)}", ""
    except Exception as e:
        return f"📕 예외 발생: {str(e)}", ""

# 6) Streamlit UI
st.title("📘 KORMARC 041 & 546 태그 생성기 (fastText 기반 정확한 언어 감지)")

isbn_input = st.text_input("ISBN을 입력하세요 (13자리):")
if st.button("태그 생성"):
    if isbn_input:
        tag_041, tag_546 = get_kormarc_041_tag(isbn_input)
        st.text(f"📄 생성된 041 태그: {tag_041}")
        if tag_546:
            st.text(f"📄 생성된 546 태그: {tag_546}")
    else:
        st.warning("ISBN을 입력해주세요.")