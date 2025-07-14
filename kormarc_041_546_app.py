"""
KORMARC 041·546 태그 자동 생성기
  • 가나가 있으면 jpn
  • fastText + (선택)CLD3
  • ISBN 그룹(4→ja, 7→zh …) 무조건 최종 오버라이드
"""
from __future__ import annotations
import os, re, urllib.request, xml.etree.ElementTree as ET, hashlib
import streamlit as st, requests, fasttext

# ── fastText 모델 ────────────────────────────────────────────────
MODEL_PATH = "lid.176.ftz"
MODEL_URL  = "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz"

def _load_ft():
    if not os.path.exists(MODEL_PATH):
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    return fasttext.load_model(MODEL_PATH)

# 코드 해시를 캐시 키에 포함 → 파일 바뀌면 자동으로 새로 로드
_code_hash = hashlib.sha1(open(__file__, 'rb').read()).hexdigest()
ft_model = st.cache_resource(hash_funcs={fasttext.FastText: id},
                             ttl=None, show_spinner=False)(_load_ft)()

# ── 매핑 ─────────────────────────────────────────────────────────
ISO2_TO_MARC = {'ko':'kor','en':'eng','ja':'jpn','zh':'chi','fr':'fre',
                'de':'ger','it':'ita','es':'spa','pt':'por','ru':'rus','ar':'ara'}
MARC2KO = {'kor':'한국어','eng':'영어','jpn':'일본어','chi':'중국어',
           'fre':'프랑스어','ger':'독일어','ita':'이탈리아어','spa':'스페인어',
           'por':'포르투갈어','rus':'러시아어','ara':'아랍어','und':'알 수 없음'}

def isbn_hint(isbn:str)->str|None:
    m=re.match(r'97[89](\d)', isbn)
    return {'0':'en','1':'en','2':'fr','3':'de','4':'ja','5':'ru','7':'zh'}.get(m.group(1)) if m else None

def detect_lang(txt:str,isbn:str|None=None)->str:
    txt=re.sub(r'\s+','',txt)[:500]
    if len(txt.encode())<20: return 'und'
    if re.search(r'[\u3040-\u30ff]',txt): return 'jpn'       # 가나 → jpn
    lbl,_=ft_model.predict(txt.lower(),k=1)
    lang=lbl[0].replace('__label__','')
    hint=isbn_hint(isbn) if isbn else None
    if hint: lang=hint                                       # ISBN 최우선
    return ISO2_TO_MARC.get(lang,'und')

def build_041(a,h):
    ind='1' if h and h!=a else '0'
    return f"041 {ind}#$a{a}"+(f"$h{h}" if h and h!=a else "")

def build_546(tag041):
    a=[s[2:] for s in tag041.split('$') if s.startswith('a')]
    h=next((s[2:] for s in tag041.split('$') if s.startswith('h')),None)
    if len(a)==1:
        main=MARC2KO.get(a[0],'알 수 없음')
        if h and h!=a[0]:
            return f"{main}로 씀, 원저는 {MARC2KO.get(h,'알 수 없음')}임"
        return f"{main}로 씀"
    return "、".join(MARC2KO.get(x,'알 수 없음') for x in a)+" 병기"

def fetch_tags(isbn):
    url="http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx"
    p={"ttbkey":"ttbmary38642333002","itemIdType":"ISBN13","ItemId":isbn,
       "output":"xml","Version":"20131101"}
    ns={"ns":"http://www.aladin.co.kr/ttb/apiguide.aspx"}
    r=requests.get(url,params=p,timeout=7); r.raise_for_status()
    item=ET.fromstring(r.content).find("ns:item",ns)
    if item is None: return "item 없음",""
    title=item.findtext("ns:title","",ns)
    orig =item.findtext("ns:subInfo/ns:originalTitle","",ns)
    a=detect_lang(title,isbn)
    h=detect_lang(orig,isbn) if orig else None
    t041=build_041(a,h)
    t546="546 ##$a"+build_546(t041)
    return t041, t546

# ── Streamlit UI ────────────────────────────────────────────────
st.title("📘 KORMARC 041·546 태그 생성기 (ISBN 보정 · 캐시무효)")

isbn=st.text_input("ISBN-13 입력:")
if st.button("생성"):
    if not isbn.strip():
        st.warning("ISBN을 입력하세요.")
    else:
        tag041,tag546=fetch_tags(isbn.strip().replace('-',''))
        st.code(tag041); st.code(tag546)