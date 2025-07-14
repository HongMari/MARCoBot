import re
import streamlit as st
import requests
import xml.etree.ElementTree as ET

# 언어코드 → 한국어 표현
ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어', 'rus': '러시아어',
    'fre': '프랑스어', 'ger': '독일어', 'ita': '이탈리아어', 'spa': '스페인어',
    'ara': '아랍어', 'per': '페르시아어', 'urd': '우르두어',
    'tha': '태국어', 'mya': '미얀마어', 'khm': '크메르어', 'lao': '라오어',
    'vie': '베트남어', 'ind': '인도네시아어', 'msa': '말레이어',
    'und': '알 수 없음'
}

# 유니코드 기반 기본 언어 감지
def detect_language_unicode(text: str) -> str:
    text = re.sub(r'[\s\W_]+', '', text)
    if not text:
        return 'und'
    first = text[0]
    if '\u0E00' <= first <= '\u0E7F':
        return 'tha'  # 태국어
    elif '\u1000' <= first <= '\u109F':
        return 'mya'  # 미얀마어
    elif '\u1780' <= first <= '\u17FF':
        return 'khm'  # 크메르어
    elif '\u0E80' <= first <= '\u0EFF':
        return 'lao'  # 라오어
    elif '\u3040' <= first <= '\u30FF':
        return 'jpn'  # 일본어
    elif '\u4E00' <= first <= '\u9FFF':
        return 'han'  # 한자권
    elif '\uAC00' <= first <= '\uD7A3':
        return 'kor'
    elif '\u0600' <= first <= '\u06FF':
        return 'ara'
    elif '\u0400' <= first <= '\u04FF':
        return 'rus'
    elif 'a' <= first.lower() <= 'z':
        return 'latn'
    else:
        return 'und'

# 라틴 문자의 경우 언어 보정
def refine_latin_language(text: str) -> str:
    if any(x in text for x in ['đ', 'ă', 'ơ', 'ư', 'â', 'ê', 'ấ', 'ộ', 'ồ']):
        return 'vie'
    elif any(x in text.lower() for x in ['yang', 'tidak', 'dengan']):
        return 'ind'
    elif any(x in text.lower() for x in ['saya', 'akan', 'ialah']):
        return 'msa'
    else:
        return 'eng'

# 두 텍스트 기반으로 본문언어/원어 추론
def infer_languages(title: str, original_title: str) -> tuple:
    lang_title = detect_language_unicode(title)
    lang_orig = detect_language_unicode(original_title)

    if lang_title == 'latn':
        lang_title = refine_latin_language(title)
    if lang_orig == 'latn':
        lang_orig = refine_latin_language(original_title)

    if lang_title == 'han':
        if lang_orig in ['fre', 'eng', 'ger', 'ita', 'spa']:
            lang_title = 'jpn'
        else:
            lang_title = 'chi'

    if lang_orig == 'han':
        if lang_title == 'jpn':
            lang_orig = 'chi'
        else:
            lang_orig = ''

    return lang_title, lang_orig

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

# 알라딘 API 조회 및 태그 생성
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

# Streamlit UI
st.title("📘 KORMARC 041 & 546 태그 생성기 (다국어 지원)")

isbn_input = st.text_input("ISBN을 입력하세요 (13자리):")
if st.button("태그 생성"):
    if isbn_input:
        tag_041, tag_546 = get_kormarc_041_tag(isbn_input)
        st.text(f"📄 생성된 041 태그: {tag_041}")
        if tag_546:
            st.text(f"📄 생성된 546 태그: {tag_546}")
    else:
        st.warning("ISBN을 입력해주세요.")