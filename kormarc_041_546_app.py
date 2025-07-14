"""
KORMARC 041 · 546 태그 자동 생성기
 └ fastText + pycld3 + 유니코드 휴리스틱 3단계 언어 감지
"""
from __future__ import annotations
import os, re, unicodedata, urllib.request, xml.etree.ElementTree as ET

import streamlit as st
import requests
import fasttext

# pycld3는 경량, 설치 실패해도 동작하도록
try:
    import pycld3
    HAVE_CLD3 = True
except ModuleNotFoundError:
    HAVE_CLD3 = False


##############################################################################
# 1) fastText 모델 로드 (캐싱) ----------------------------------------------
##############################################################################
MODEL_PATH = "lid.176.ftz"
MODEL_URL  = "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz"

@st.cache_resource(hash_funcs={fasttext.FastText: id})
def load_ft_model():
    if not os.path.exists(MODEL_PATH):
        with st.spinner("fastText 언어 모델(약 120 MB) 다운로드 중…"):
            urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    return fasttext.load_model(MODEL_PATH)

ft_model = load_ft_model()

##############################################################################
# 2) 코드 매핑 / 설명 --------------------------------------------------------
##############################################################################
ISO2_TO_MARC = {
    'ko':'kor','en':'eng','ja':'jpn','zh':'chi','fr':'fre','de':'ger','it':'ita',
    'es':'spa','pt':'por','ru':'rus','ar':'ara','nl':'dut','sv':'swe','fi':'fin',
}
MARC_TO_KO = {
    'kor':'한국어','eng':'영어','jpn':'일본어','chi':'중국어','fre':'프랑스어',
    'ger':'독일어','ita':'이탈리아어','spa':'스페인어','por':'포르투갈어',
    'rus':'러시아어','ara':'아랍어','dut':'네덜란드어','swe':'스웨덴어',
    'fin':'핀란드어','und':'알 수 없음'
}

##############################################################################
# 3) 언어 감지 --------------------------------------------------------------
##############################################################################
SCRIPT_TABLE = [
    (re.compile(r'[\u3040-\u30ff]'), ['ja']),              # 가나
    (re.compile(r'[\uac00-\ud7a3]'), ['ko']),              # 한글
    (re.compile(r'[\u4e00-\u9fff]'), ['zh','ja']),         # 한자
    (re.compile(r'[\u0600-\u06ff]'), ['ar','fa','ur']),    # Arabic
]

def script_hint(text:str) -> list[str] | None:
    for pattern, langs in SCRIPT_TABLE:
        if pattern.search(text):
            return langs
    return None

def detect_language(text:str) -> str:
    """ISO-639-2(3자리 MARC) 코드 반환. 실패 시 'und'."""
    # 0) 전처리
    text = re.sub(r'\s+', ' ', text.strip())
    if len(text.encode('utf-8')) < 20:
        return 'und'

    # 1) 스크립트 휴리스틱
    hints = script_hint(text)

    # 2) fastText 1~2위 예측
    labels, probs = ft_model.predict(text.lower(), k=2)
    iso1_ft, conf_ft = labels[0].replace('__label__',''), probs[0]

    # 3) 필요하면 2순위로 교체 (스크립트 불일치 + 2위가 일치)
    if hints and iso1_ft not in hints and probs[1] > 0.15 and labels[1].replace('__label__','') in hints:
        iso1_ft, conf_ft = labels[1].replace('__label__',''), probs[1]

    # 4) pycld3 교차검증 (선택)
    if HAVE_CLD3:
        cld = pycld3.get_language(text)
        if cld.is_reliable and cld.language in ISO2_TO_MARC:
            if cld.probability > 0.7 and cld.language != iso1_ft:
                iso1_ft = cld.language
                conf_ft = cld.probability

    # 5) 신뢰도 임계
    if conf_ft < 0.50:
        return 'und'

    iso1 = iso1_ft.split('-')[0]      # zh-tw → zh
    return ISO2_TO_MARC.get(iso1, 'und')

##############################################################################
# 4) 041→546 변환 -----------------------------------------------------------
##############################################################################
def make_546(marc_041:str) -> str:
    subs = marc_041.split('$')[1:]       # ['ajpn','hfre']
    langs_a = [s[1:] for s in subs if s.startswith('a')]
    lang_h  = next((s[1:] for s in subs if s.startswith('h')), None)

    if len(langs_a)==1:
        main = MARC_TO_KO.get(langs_a[0],'알 수 없음')
        if lang_h and lang_h != langs_a[0]:
            orig = MARC_TO_KO.get(lang_h,'알 수 없음')
            return f"{main}로 씀, 원저는 {orig}임"
        return f"{main}로 씀"

    return "、".join(MARC_TO_KO.get(l,'알 수 없음') for l in langs_a) + " 병기"

def build_041(text_lang:str, orig_lang:str|None) -> str:
    ind1 = '1' if orig_lang and orig_lang!=text_lang else '0'
    sub  = f"$a{text_lang}" + (f"$h{orig_lang}" if orig_lang and orig_lang!=text_lang else "")
    return f"041 {ind1}#{sub}"

##############################################################################
# 5) 알라딘 API -------------------------------------------------------------
##############################################################################
def fetch_aladin(isbn13:str) -> tuple[str,str]:
    url = "http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx"
    params = {"ttbkey":"ttbmary38642333002","itemIdType":"ISBN13","ItemId":isbn13,
              "output":"xml","Version":"20131101"}
    r = requests.get(url, params=params, timeout=8)
    if r.status_code!=200:
        return "❌ API 호출 실패",""

    root = ET.fromstring(r.content)
    ns   = {"ns":"http://www.aladin.co.kr/ttb/apiguide.aspx"}
    item = root.find("ns:item", ns)
    if item is None:
        return "📕 item 태그 없음",""

    title   = item.findtext("ns:title", default="", namespaces=ns)
    orig    = item.findtext("ns:subInfo/ns:originalTitle", default="", namespaces=ns)

    lang_a  = detect_language(title)
    lang_h  = detect_language(orig) if orig else None

    tag041  = build_041(lang_a, lang_h)
    tag546  = f"546 ##$a{make_546(tag041)}"
    return tag041, tag546

##############################################################################
# 6) Streamlit UI -----------------------------------------------------------
##############################################################################
st.title("📘 KORMARC 041·546 자동 생성기")

isbn = st.text_input("ISBN-13 입력:")
if st.button("생성"):
    if not isbn.strip():
        st.warning("ISBN을 입력하세요.")
    else:
        t041, t546 = fetch_aladin(isbn.strip().replace('-',''))
        st.code(t041, language="text")
        if t546:
            st.code(t546, language="text")