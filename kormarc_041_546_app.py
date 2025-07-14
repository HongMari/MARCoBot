"""
KORMARC 041·546 태그 자동 생성기
 └ fastText + pycld3 + 스크립트 휴리스틱 + ISBN 그룹 보정
     ▸ 가나(ひらがな/カタカナ)가 한 글자라도 있으면 일본어 확정!
"""
from __future__ import annotations
import os, re, urllib.request, xml.etree.ElementTree as ET
import streamlit as st, requests, fasttext

# ────────────────────────────────────────────────────────────────
# 0. (선택) CLD3 ― 설치 실패해도 동작
try:
    import pycld3
    HAVE_CLD3 = True
except ModuleNotFoundError:
    HAVE_CLD3 = False
# ────────────────────────────────────────────────────────────────
# 1. fastText 모델 로드 (lid.176.ftz 없으면 자동 다운로드)
MODEL_PATH = "lid.176.ftz"
MODEL_URL  = "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz"

@st.cache_resource(hash_funcs={fasttext.FastText: id})
def load_model():
    if not os.path.exists(MODEL_PATH):
        with st.spinner("fastText 언어 모델(120 MB) 다운로드 중…"):
            urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    return fasttext.load_model(MODEL_PATH)

ft_model = load_model()
# ────────────────────────────────────────────────────────────────
# 2. 코드 매핑
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
SCRIPT_TABLE = [
    (re.compile(r'[\u3040-\u30ff]'), ['ja']),           # 가나
    (re.compile(r'[\uac00-\ud7a3]'), ['ko']),           # 한글
    (re.compile(r'[\u4e00-\u9fff]'), ['zh', 'ja']),     # 한자
    (re.compile(r'[\u0600-\u06ff]'), ['ar', 'fa', 'ur'])# 아랍계
]
# ────────────────────────────────────────────────────────────────
# 3. 언어 감지 함수
def isbn_hint(isbn: str) -> str | None:
    m = re.match(r'97[89](\d)', isbn)
    if not m:
        return None
    return {
        '0':'en','1':'en','2':'fr','3':'de','4':'ja','5':'ru','7':'zh'
    }.get(m.group(1))

def script_hint(txt: str) -> list[str] | None:
    for pat, langs in SCRIPT_TABLE:
        if pat.search(txt):
            return langs
    return None

def detect_lang(text: str, isbn: str | None = None) -> str:
    txt = re.sub(r'\s+', '', text)[:500]
    if len(txt.encode()) < 20:
        return 'und'

    # 0) **가나가 있으면 일본어 확정**
    if re.search(r'[\u3040-\u30ff]', txt):
        return 'jpn'

    hints = script_hint(txt)

    # 1) fastText top-k
    labels, probs = ft_model.predict(txt.lower(), k=2)
    lang = labels[0].replace('__label__', '')
    conf = probs[0]

    # 2) 스크립트와 불일치할 때 2순위 교체
    if hints and lang not in hints and probs[1] > .15 and \
       labels[1].replace('__label__', '') in hints:
        lang = labels[1].replace('__label__', '')
        conf = probs[1]

    # 3) CLD3 교차검증
    if HAVE_CLD3:
        c = pycld3.get_language(text)
        if c.is_reliable and c.probability > .7 and c.language in ISO2_TO_MARC \
           and c.language != lang:
            lang = c.language
            conf = c.probability

    # 4) ISBN 그룹 보정 (ja / zh / en / fr / de / ru)
    hint = isbn_hint(isbn) if isbn else None
    if hint and lang != hint:
        lang = hint            # 그룹 식별자가 우선

    if conf < .45:
        lang = 'und'

    return ISO2_TO_MARC.get(lang.split('-')[0], 'und')
# ────────────────────────────────────────────────────────────────
# 4. 041·546 생성
def build_041(a: str, h: str | None) -> str:
    ind1 = '1' if h and h != a else '0'
    subf = f"$a{a}" + (f"$h{h}" if h and h != a else "")
    return f"041 {ind1}#{subf}"

def make_546(tag041: str) -> str:
    subs = tag041.split('$')[1:]
    langs_a = [s[1:] for s in subs if s.startswith('a')]
    lang_h  = next((s[1:] for s in subs if s.startswith('h')), None)
    if len(langs_a) == 1:
        main = MARC_TO_KO.get(langs_a[0], '알 수 없음')
        if lang_h and lang_h != langs_a[0]:
            orig = MARC_TO_KO.get(lang_h, '알 수 없음')
            return f"{main}로 씀, 원저는 {orig}임"
        return f"{main}로 씀"
    return "、".join(MARC_TO_KO.get(l, '알 수 없음') for l in langs_a) + " 병기"
# ────────────────────────────────────────────────────────────────
# 5. 알라딘 API → 041/546
def fetch_tags(isbn13: str) -> tuple[str, str]:
    url = "http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx"
    params = {
        "ttbkey": "ttbmary38642333002",
        "itemIdType": "ISBN13",
        "ItemId": isbn13,
        "output": "xml",
        "Version": "20131101"
    }
    r = requests.get(url, params=params, timeout=6)
    r.raise_for_status()

    ns   = {"ns": "http://www.aladin.co.kr/ttb/apiguide.aspx"}
    item = ET.fromstring(r.content).find("ns:item", ns)
    if item is None:
        return "📕 item 태그 없음", ""

    title = item.findtext("ns:title", "", ns)
    orig  = item.findtext("ns:subInfo/ns:originalTitle", "", ns)

    lang_a = detect_lang(title, isbn13)
    lang_h = detect_lang(orig, isbn13) if orig else None

    tag041 = build_041(lang_a, lang_h)
    tag546 = f"546 ##$a{make_546(tag041)}"
    return tag041, tag546
# ────────────────────────────────────────────────────────────────
# 6. Streamlit UI
st.title("📘 KORMARC 041·546 자동 생성기 (완성판)")

isbn = st.text_input("ISBN-13 입력:")
if st.button("태그 생성"):
    if not isbn.strip():
        st.warning("ISBN을 입력하세요.")
    else:
        t041, t546 = fetch_tags(isbn.strip().replace('-', ''))
        st.code(t041, language="text")
        st.code(t546, language="text")