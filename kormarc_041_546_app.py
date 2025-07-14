import re
import streamlit as st
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어', 'rus': '러시아어',
    'ara': '아랍어', 'fre': '프랑스어', 'ger': '독일어', 'ita': '이탈리아어', 'spa': '스페인어',
    'und': '알 수 없음'
}

SUBJECT_TO_LANG = {
    "일본": "jpn", "프랑스": "fre", "영미": "eng", "영국": "eng",
    "독일": "ger", "중국": "chi", "러시아": "rus", "한국": "kor"
}

def infer_h_from_subject(subject: str) -> str:
    for keyword, lang_code in SUBJECT_TO_LANG.items():
        if keyword in subject:
            return lang_code
    return ""

def detect_language(text):
    text = re.sub(r'[\s\W_]+', '', text)
    if not text:
        return 'und'
    first_char = text[0]
    if '\uac00' <= first_char <= '\ud7a3':
        return 'kor'
    elif '\u3040' <= first_char <= '\u30ff':
        return 'jpn'
    elif '\u4e00' <= first_char <= '\u9fff':
        return 'chi'
    elif '\u0400' <= first_char <= '\u04FF':
        return 'rus'
    elif 'a' <= first_char.lower() <= 'z':
        return 'eng'
    else:
        return 'und'

def get_aladin_subject_and_language_hint(isbn13: str):
    headers = {"User-Agent": "Mozilla/5.0"}

    search_url = f"https://www.aladin.co.kr/search/wsearchresult.aspx?SearchTarget=All&SearchWord={isbn13}"
    search_res = requests.get(search_url, headers=headers)
    if search_res.status_code != 200:
        return "", ""

    soup = BeautifulSoup(search_res.text, "html.parser")
    first_link = soup.select_one("div.ss_book_box a.bo3")
    if not first_link or not first_link["href"]:
        return "", ""

    detail_url = "https://www.aladin.co.kr" + first_link["href"]
    detail_res = requests.get(detail_url, headers=headers)
    if detail_res.status_code != 200:
        return "", ""

    soup = BeautifulSoup(detail_res.text, "html.parser")
    page_text = soup.get_text(separator=" ", strip=True)

    subject = ""
    cat = soup.select_one("#divCategory")
    if cat:
        subject = cat.get_text(" ", strip=True)

    language_hint = ""
    lang_patterns = {
        "언어 : Japanese": "jpn", "Language : Japanese": "jpn",
        "언어 : English": "eng", "Language : English": "eng",
        "언어 : French": "fre", "Language : French": "fre",
        "언어 : German": "ger", "Language : German": "ger",
        "언어 : Chinese": "chi", "Language : Chinese": "chi",
        "언어 : Korean": "kor", "Language : Korean": "kor",
    }
    for phrase, code in lang_patterns.items():
        if phrase in page_text:
            language_hint = code
            break

    return subject, language_hint

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

def get_kormarc_041_tag(isbn):
    isbn = isbn.strip().replace("-", "")
    title, original_title = "", ""
    lang_a, lang_h = "", ""

    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = "http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx"
        params = {
            "ttbkey": "ttbmary38642333002",
            "itemIdType": "ISBN13",
            "ItemId": isbn,
            "output": "xml",
            "Version": "20131101"
        }

        response = requests.get(url, params=params, headers=headers)
        root = ET.fromstring(response.content)
        item = root.find("item")

        if item is None:
            raise Exception("item 없음")

        title = item.findtext("title", default="")
        subinfo = item.find("subInfo")
        if subinfo is not None:
            original_title = subinfo.findtext("originalTitle", default="")

        lang_a = detect_language(title)
        lang_h = detect_language(original_title) if original_title else ""

    except Exception:
        subject, lang_hint = get_aladin_subject_and_language_hint(isbn)
        lang_a = lang_hint
        lang_h = infer_h_from_subject(subject)

    marc_a = f"$a{lang_a or 'und'}"
    marc_h = f"$h{lang_h}" if lang_h else ""
    marc_041 = f"041 {marc_a} {marc_h}".strip()
    marc_546 = generate_546_from_041_kormarc(marc_041)

    return marc_041, marc_546

# Streamlit UI
st.title("📘 KORMARC 041 & 546 태그 생성기 (namespace 제거)")

isbn_input = st.text_input("ISBN을 입력하세요 (13자리):")
if st.button("태그 생성"):
    if isbn_input:
        tag_041, tag_546 = get_kormarc_041_tag(isbn_input)
        st.text(f"📄 생성된 041 태그: {tag_041}")
        if tag_546:
            st.text(f"📄 생성된 546 태그: {tag_546}")
    else:
        st.warning("ISBN을 입력해주세요.")