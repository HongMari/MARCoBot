"""
fastText + pycld3 + 스크립트 휴리스틱 + ISBN 그룹(0/1/2/3/4/5/7) 보정
⇒ KORMARC 041 · 546 태그 자동 생성
"""
from __future__ import annotations
import os, re, unicodedata, urllib.request, xml.etree.ElementTree as ET
import streamlit as st, requests, fasttext

try:
    import pycld3
    HAVE_CLD3=True
except ModuleNotFoundError:
    HAVE_CLD3=False

# -------------------------------------------------------------------------
MODEL_PATH="lid.176.ftz"
MODEL_URL ="https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz"

@st.cache_resource(hash_funcs={fasttext.FastText:id})
def ft():
    if not os.path.exists(MODEL_PATH):
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    return fasttext.load_model(MODEL_PATH)
ft_model=ft()
# -------------------------------------------------------------------------
ISO2_TO_MARC={'ko':'kor','en':'eng','ja':'jpn','zh':'chi','fr':'fre','de':'ger',
              'it':'ita','es':'spa','pt':'por','ru':'rus','ar':'ara','nl':'dut'}
MARC_TO_KO={'kor':'한국어','eng':'영어','jpn':'일본어','chi':'중국어','fre':'프랑스어',
            'ger':'독일어','ita':'이탈리아어','spa':'스페인어','por':'포르투갈어',
            'rus':'러시아어','ara':'아랍어','dut':'네덜란드어','und':'알 수 없음'}
SCRIPT_TABLE=[
    (re.compile(r'[\u3040-\u30ff]'),['ja']),           # 가나
    (re.compile(r'[\uac00-\ud7a3]'),['ko']),           # 한글
    (re.compile(r'[\u4e00-\u9fff]'),['zh','ja']),      # 한자
    (re.compile(r'[\u0600-\u06ff]'),['ar','fa','ur'])  # 아랍
]

def isbn_hint(isbn:str) -> str|None:
    """ISBN-13 → iso-639-1 힌트(ja/zh/en/fr/…)"""
    m=re.match(r'97[89](\d)', isbn)
    if not m: return None
    g=m.group(1)
    return {'0':'en','1':'en','2':'fr','3':'de','4':'ja','5':'ru','7':'zh'}.get(g)

def script_hint(txt:str)->list[str]|None:
    for pat,l in SCRIPT_TABLE:
        if pat.search(txt):
            return l
    return None

def detect_lang(text:str, isbn:str|None=None)->str:
    t=re.sub(r'\s+','',text)[:500]
    if len(t.encode())<20: return 'und'
    hints=script_hint(t)
    lbls,prbs=ft_model.predict(t.lower(),k=2)
    lang=lbls[0].replace('__label__',''); conf=prbs[0]

    # 스크립트 불일치 → 2순위 후보 채택
    if hints and lang not in hints and prbs[1]>0.15 and \
       lbls[1].replace('__label__','') in hints:
        lang=lbls[1].replace('__label__',''); conf=prbs[1]

    # CLD3 교차검증
    if HAVE_CLD3:
        c=pycld3.get_language(text)
        if c.is_reliable and c.probability>0.7 and c.language in ISO2_TO_MARC and \
           c.language!=lang:
            lang=c.language; conf=c.probability

    # ISBN 그룹 보정 (zh/ja/en/fr/de 등 주요 언어)
    hint=isbn_hint(isbn) if isbn else None
    if hint and conf<0.80 and lang in ('zh','ja','en','fr','de','ru') and lang!=hint:
        lang=hint

    if conf<0.45: lang='und'
    return ISO2_TO_MARC.get(lang.split('-')[0],'und')
# -------------------------------------------------------------------------
def build_041(text,orig):
    ind='1' if orig and orig!=text else '0'
    sub=f"$a{text}"+(f"$h{orig}" if orig and orig!=text else "")
    return f"041 {ind}#{sub}"

def make_546(tag041):
    subs=tag041.split('$')[1:]
    a=[s[1:] for s in subs if s.startswith('a')]
    h=next((s[1:] for s in subs if s.startswith('h')),None)
    if len(a)==1:
        main=MARC_TO_KO.get(a[0],'알 수 없음')
        if h and h!=a[0]:
            return f"{main}로 씀, 원저는 {MARC_TO_KO.get(h,'알 수 없음')}임"
        return f"{main}로 씀"
    return "、".join(MARC_TO_KO.get(x,'알 수 없음') for x in a)+" 병기"
# -------------------------------------------------------------------------
def fetch_tags(isbn):
    url="http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx"
    p={"ttbkey":"ttbmary38642333002","itemIdType":"ISBN13","ItemId":isbn,
       "output":"xml","Version":"20131101"}
    r=requests.get(url,params=p,timeout=6); r.raise_for_status()
    ns={"ns":"http://www.aladin.co.kr/ttb/apiguide.aspx"}
    item=ET.fromstring(r.content).find("ns:item",ns)
    if item is None: return "📕 item 없음",""
    title=item.findtext("ns:title","",ns)
    orig =item.findtext("ns:subInfo/ns:originalTitle","",ns)

    a=detect_lang(title,isbn)
    h=detect_lang(orig,isbn) if orig else None
    tag041=build_041(a,h)
    tag546=f"546 ##$a{make_546(tag041)}"
    return tag041,tag546
# -------------------------------------------------------------------------
st.title("📘 KORMARC 041·546 자동 생성기 (ISBN 보정판)")
isbn=st.text_input("ISBN-13 입력:")
if st.button("생성"):
    if not isbn.strip():
        st.warning("ISBN을 입력하세요.")
    else:
        t041,t546=fetch_tags(isbn.strip().replace('-',''))
        st.code(t041); st.code(t546)