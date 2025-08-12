import re
import os
import streamlit as st
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI

# 환경변수 로드
load_dotenv()
ALADIN_KEY = os.getenv("ALADIN_TTB_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_KEY)

# 언어코드 매핑
ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어',
    'rus': '러시아어', 'ara': '아랍어', 'fre': '프랑스어', 'ger': '독일어',
    'ita': '이탈리아어', 'spa': '스페인어', 'por': '포르투갈어', 'tur': '터키어',
    'und': '알 수 없음'
}

# GPT 원서 언어 감지
def gpt_guess_original_lang(title, category, publisher, author="", original_title=""):
    prompt = f"""
    다음 도서의 정보를 바탕으로 원서의 언어(041 $h)를 ISDS 코드(kor, eng, jpn, chi, rus, fre, ger, ita, spa, por, tur) 중 하나로 결정해줘.
    - 제목: {title}
    - 원제: {original_title}
    - 분류: {category}
    - 출판사: {publisher}
    - 저자: {author}
    응답은 반드시 아래 형식으로:
    $h=[ISDS 코드]
    """
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "도서 정보를 바탕으로 원서 언어를 판단하는 사서 AI입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        content = resp.choices[0].message.content.strip()
        return content.replace("$h=", "").strip() if content.startswith("$h=") else "und"
    except Exception as e:
        st.error(f"GPT 오류: {e}")
        return "und"

# 언어 감지 함수들
def detect_language_by_unicode(text):
    text = re.sub(r'[\s\W_]+', '', text)
    if not text: return 'und'
    first = text[0]
    if '\uac00' <= first <= '\ud7a3': return 'kor'
    elif '\u3040' <= first <= '\u30ff': return 'jpn'
    elif '\u4e00' <= first <= '\u9fff': return 'chi'
    elif '\u0600' <= first <= '\u06FF': return 'ara'
    elif '\u0e00' <= first <= '\u0e7f': return 'tha'
    return 'und'

def override_language_by_keywords(text, initial):
    text = text.lower()
    if initial == 'chi' and re.search(r'[\u3040-\u30ff]', text): return 'jpn'
    if initial in ['und', 'eng']:
        if "french" in text or "français" in text or any(c in text for c in "éèêçàùôâîû"): return 'fre'
        if "spanish" in text or "español" in text or any(c in text for c in "ñáíóú"): return 'spa'
        if "german" in text or "deutsch" in text: return 'ger'
        if "portuguese" in text or "português" in text or any(c in text for c in "ãõ"): return 'por'
        if "italian" in text or "italiano" in text: return 'ita'
    return initial

def detect_language(text):
    return override_language_by_keywords(text, detect_language_by_unicode(text))

# 카테고리 기반 언어 추정
def detect_language_from_category(text):
    mapping = [
        ("일본", "jpn"), ("중국", "chi"), ("대만", "chi"), ("홍콩", "chi"),
        ("영미", "eng"), ("영어", "eng"), ("영국", "eng"), ("미국", "eng"),
        ("프랑스", "fre"), ("독일", "ger"), ("오스트리아", "ger"), ("러시아", "rus"),
        ("이탈리아", "ita"), ("스페인", "spa"), ("포르투갈", "por"),
        ("터키", "tur"), ("튀르키예", "tur")
    ]
    for keyword, code in mapping:
        if keyword in text: return code
    return None

# 546 태그 생성
def generate_546_from_041_kormarc(marc_041):
    a_codes, h_code = [], None
    for part in marc_041.split():
        if part.startswith("$a"): a_codes.append(part[2:])
        elif part.startswith("$h"): h_code = part[2:]
    if len(a_codes) == 1:
        a = ISDS_LANGUAGE_CODES.get(a_codes[0], "알 수 없음")
        h = ISDS_LANGUAGE_CODES.get(h_code, "알 수 없음") if h_code else None
        return f"{a}로 씀" if not h else f"{a}로 씀, 원저는 {h}임"
    elif len(a_codes) > 1:
        langs = [ISDS_LANGUAGE_CODES.get(code, "알 수 없음") for code in a_codes]
        return f"{'、'.join(langs)} 병기"
    return "언어 정보 없음"

# 크롤링 (원제/카테고리)
def crawl_aladin_fallback(isbn13):
    url = f"https://www.aladin.co.kr/shop/wproduct.aspx?ISBN={isbn13}"
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        original = soup.select_one("div.info_original")
        categories = soup.select("div.conts_info_list2 li")
        cat_text = " ".join([cat.get_text(separator=" ", strip=True) for cat in categories])
        return {
            "original_title": original.text.strip() if original else "",
            "category_text": cat_text
        }
    except Exception as e:
        st.error(f"크롤링 실패: {e}")
        return {"original_title": "", "category_text": ""}

# 네임스페이스 제거
def strip_ns(tag): return tag.split("}")[-1] if "}" in tag else tag

# 최종 태그 생성
def get_kormarc_tags(isbn):
    isbn = isbn.strip().replace("-", "")
    url = "http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx"
    params = {"ttbkey": ALADIN_KEY, "itemIdType": "ISBN13", "ItemId": isbn, "output": "xml", "Version": "20131101"}
    try:
        r = requests.get(url, params=params)
        root = ET.fromstring(r.content)
        for el in root.iter(): el.tag = strip_ns(el.tag)
        item = root.find("item")
        title = item.findtext("title", "")
        publisher = item.findtext("publisher", "")
        author = item.findtext("author", "")
        subinfo = item.find("subInfo")
        original_title = subinfo.findtext("originalTitle", "") if subinfo is not None else ""

        crawl = crawl_aladin_fallback(isbn)
        if not original_title:
            original_title = crawl.get("original_title", "")
        category_text = crawl.get("category_text", "")

        # 본문 언어 ($a)
        lang_a = detect_language(title)
        st.write("📘 [DEBUG][$a] 제목 기반 초깃값 =", lang_a)
        if lang_a in ['und', 'eng']:
            st.write("📘 [DEBUG][$a] GPT 요청 →", title, category_text, publisher, author)
            gpt_a = gpt_guess_original_lang(title, category_text, publisher, author)
            st.write("📘 [DEBUG][$a] GPT 판단 =", gpt_a)
            if gpt_a != "und":
                lang_a = gpt_a

        # 원서 언어 ($h)
        lang_h = "und"
        decision = ""
        lang_h_cat = detect_language_from_category(category_text)
        st.write("📘 [DEBUG][$h] 카테고리 기반 후보 =", lang_h_cat)
        if lang_h_cat:
            lang_h = lang_h_cat
            decision = "카테고리 기반으로 확정"
        elif original_title:
            lang_h = detect_language(original_title)
            decision = "원제 문자열로 감지"
        if lang_h == "und":
            st.write("📘 [DEBUG][$h] GPT 판단 요청 중...")
            lang_h = gpt_guess_original_lang(title, category_text, publisher, author, original_title)
            decision = "GPT 보완 판단"

        st.write(f"📘 [DEBUG][$h] 최종 = {lang_h} (결정 근거: {decision})")

        tag_041 = f"041 $a{lang_a}" if lang_h == "und" or lang_h == lang_a else f"041 $a{lang_a} $h{lang_h}"
        tag_546 = generate_546_from_041_kormarc(tag_041)
        return tag_041, tag_546, original_title
    except Exception as e:
        return f"📕 예외 발생: {e}", "", ""

# Streamlit 앱 UI
st.title("📘 KORMARC 041/546 태그 생성기 (카테고리 우선)")

isbn_input = st.text_input("ISBN을 입력하세요 (13자리):")
if st.button("태그 생성"):
    if isbn_input:
        tag_041, tag_546, original = get_kormarc_tags(isbn_input)
        st.text(f"📄 041 태그: {tag_041}")
        if tag_546: st.text(f"📄 546 태그: {tag_546}")
        if original: st.text(f"📕 원제: {original}")
    else:
        st.warning("ISBN을 입력해주세요.")
