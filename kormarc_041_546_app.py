import os
import urllib.request
import streamlit as st
import requests
import xml.etree.ElementTree as ET
import fasttext

########################################################################
# 1) fastText 모델 로드 (없으면 자동 다운로드) --------------------------
########################################################################
MODEL_PATH = "lid.176.ftz"
MODEL_URL  = "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz"

if not os.path.exists(MODEL_PATH):
    with st.spinner("fastText 언어 모델을 다운로드 하는 중입니다…(약 120 MB)"):
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)

model = fasttext.load_model(MODEL_PATH)

########################################################################
# 2) 언어 코드 매핑 ----------------------------------------------------
########################################################################
ISO_TO_ISDS = {
    'ko': 'kor', 'en': 'eng', 'ja': 'jpn',
    'zh': 'chi',           # fastText는 zh 로 반환
    'fr': 'fre', 'de': 'ger', 'ru': 'rus',
    'ar': 'ara', 'it': 'ita', 'es': 'spa'
}

ISDS_TO_KO = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어',
    'rus': '러시아어', 'ara': '아랍어', 'fre': '프랑스어', 'ger': '독일어',
    'ita': '이탈리아어', 'spa': '스페인어', 'und': '알 수 없음'
}

def detect_language(text: str) -> str:
    """fastText 로 언어 감지 → ISDS 코드(kor, eng…) 반환"""
    text = text.strip()
    if not text:
        return 'und'
    try:
        label, prob = model.predict(text, k=1)  # [('__label__ja',)]
        lang = label[0].replace('__label__', '')
        # zh-cn, zh-tw 처럼 지역표기가 붙으면 앞부분만
        lang = lang.split('-')[0]
        return ISO_TO_ISDS.get(lang, 'und')
    except Exception:
        return 'und'

########################################################################
# 3) 041 → 546 변환 ----------------------------------------------------
########################################################################
def make_546(marc_041: str) -> str:
    a_codes, h_code = [], None
    for part in marc_041.split():
        if part.startswith("$a"):
            a_codes.append(part[2:])
        elif part.startswith("$h"):
            h_code = part[2:]

    if len(a_codes) == 1:
        a_lang = ISDS_TO_KO.get(a_codes[0], "알 수 없음")
        if h_code:
            h_lang = ISDS_TO_KO.get(h_code, "알 수 없음")
            return f"{a_lang}로 씀, 원저는 {h_lang}임"
        return f"{a_lang}로 씀"
    elif len(a_codes) > 1:
        langs = [ISDS_TO_KO.get(c, "알 수 없음") for c in a_codes]
        return "、".join(langs) + " 병기"
    return "언어 정보 없음"

########################################################################
# 4) 알라딘 API 호출 → 041/546 생성 -----------------------------------
########################################################################
def build_tags(isbn13: str):
    isbn13 = isbn13.strip().replace("-", "")
    url = "http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx"
    params = {
        "ttbkey": "ttbmary38642333002",
        "itemIdType": "ISBN13",
        "ItemId": isbn13,
        "output": "xml",
        "Version": "20131101"
    }

    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        return "❌ API 호출 실패", ""

    try:
        root  = ET.fromstring(r.content)
        item  = root.find(".//item")
        if item is None:
            return "📕 <item> 태그를 찾을 수 없습니다.", ""

        title = item.findtext("title", default="")
        sub   = item.find("subInfo")
        orig  = sub.findtext("originalTitle") if sub is not None else ""

        a = detect_language(title)
        h = detect_language(orig) if orig else None

        marc_a = f"$a{a}"
        marc_h = f"$h{h}" if h else ""

        field_041 = f"041 0#{marc_a}{marc_h}"
        field_546 = f"546 ##$a{make_546(f'{marc_a} {marc_h}'.strip())}"
        return field_041, field_546

    except Exception as e:
        return f"📕 처리 오류: {e}", ""

########################################################################
# 5) Streamlit UI ------------------------------------------------------
########################################################################
st.title("📘 KORMARC 041 · 546 태그 자동 생성기 (fastText 버전)")

isbn = st.text_input("ISBN-13 입력(하이픈 가능):")
if st.button("생성"):
    if not isbn:
        st.warning("ISBN을 입력해주세요.")
    else:
        tag041, tag546 = build_tags(isbn)
        st.code(tag041, language="text")
        if tag546:
            st.code(tag546, language="text")