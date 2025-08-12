import re
import os
import streamlit as st
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI

# ===== 환경변수 로드 =====
load_dotenv()
ALADIN_KEY = os.getenv("ALADIN_TTB_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_KEY)

# ===== ISDS 언어코드 매핑 =====
ISDS_LANGUAGE_CODES = {
    'kor': '한국어', 'eng': '영어', 'jpn': '일본어', 'chi': '중국어',
    'rus': '러시아어', 'ara': '아랍어', 'fre': '프랑스어', 'ger': '독일어',
    'ita': '이탈리아어', 'spa': '스페인어', 'por': '포르투갈어', 'tur': '터키어',
    'und': '알 수 없음'
}

# ===== GPT 판단 함수 =====
def gpt_guess_original_lang(title, category, publisher, author="", original_title=""):
    prompt = f"""
    다음 도서의 정보를 바탕으로 원서의 언어(041 $h)를 ISDS 코드(kor, eng, jpn, chi, rus, fre, ger, ita, spa, por, tur) 중 하나로 결정해줘.
    - 제목: {title}
    - 원제: {original_title}
    - 분류(카테고리 경로/텍스트): {category}
    - 출판사: {publisher}
    - 저자: {author}

    카테고리에 국가/지역 단서가 있는 경우 그 언어를 우선 고려하고, 원제 문자열이 해당 언어 문자인지 간단히 교차 확인한 다음 결정해.
    응답은 반드시 아래 형식으로만:
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

def gpt_guess_main_lang(title, category, publisher, author=""):
    prompt = f"""
    다음 도서의 정보를 바탕으로 본문 언어(041 $a)를 ISDS 코드(kor, eng, jpn, chi, rus, fre, ger, ita, spa, por, tur) 중 하나로 결정해줘.
    - 제목: {title}
    - 분류(카테고리 경로/텍스트): {category}
    - 출판사: {publisher}
    - 저자: {author}
    응답은 반드시 아래 형식으로만:
    $a=[ISDS 코드]
    """
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "도서 정보를 바탕으로 본문 언어를 판단하는 사서 AI입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        content = resp.choices[0].message.content.strip()
        return content.replace("$a=", "").strip() if content.startswith("$a=") else "und"
    except Exception as e:
        st.error(f"GPT 오류: {e}")
        return "und"

# ===== 유니코드/키워드 기반 감지 =====
def detect_language_by_unicode(text):
    text = re.sub(r'[\s\W_]+', '', text)
    if not text:
        return 'und'
    first_char = text[0]
    if '\uac00' <= first_char <= '\ud7a3': return 'kor'
    elif '\u3040' <= first_char <= '\u30ff': return 'jpn'
    elif '\u4e00' <= first_char <= '\u9fff': return 'chi'
    elif '\u0600' <= first_char <= '\u06FF': return 'ara'
    elif '\u0e00' <= first_char <= '\u0e7f': return 'tha'
    return 'und'

def override_language_by_keywords(text, initial_lang):
    text = text.lower()
    if initial_lang == 'chi' and re.search(r'[\u3040-\u30ff]', text): return 'jpn'
    if initial_lang in ['und', 'eng']:
        if "spanish" in text or "español" in text: return "spa"
        if "italian" in text or "italiano" in text: return "ita"
        if "french" in text or "français" in text: return "fre"
        if "portuguese" in text or "português" in text: return "por"
        if "german" in text or "deutsch" in text: return "ger"
        if any(ch in text for ch in ['é','è','ê','à','ç','ù','ô','â','î','û']): return "fre"
        if any(ch in text for ch in ['ñ','á','í','ó','ú']): return "spa"
        if any(ch in text for ch in ['ã','õ']): return "por"
    return initial_lang

def detect_language(text):
    lang = detect_language_by_unicode(text)
    return override_language_by_keywords(text, lang)

# ===== 카테고리(국가/지역) 기반 언어 매핑 =====
def detect_language_from_category(cat_text):
    # 자주 보이는 국가/지역 키워드 확장
    mapping = [
        ("일본", "jpn"),
        ("중국", "chi"), ("대만", "chi"), ("홍콩", "chi"),
        ("영미", "eng"), ("영어", "eng"), ("영국", "eng"), ("미국", "eng"),
        ("캐나다", "eng"), ("호주", "eng"), ("아일랜드", "eng"), ("뉴질랜드", "eng"),
        ("프랑스", "fre"),
        ("독일", "ger"), ("오스트리아", "ger"),
        ("러시아", "rus"),
        ("이탈리아", "ita"),
        ("스페인", "spa"),
        ("포르투갈", "por"), ("브라질", "por"),
        ("튀르키예", "tur"), ("터키", "tur"),
        ("아랍", "ara"), ("중동", "ara")  # 필요시 확장
    ]
    if not cat_text:
        return None
    for key, code in mapping:
        if key in cat_text:
            return code
    return None

# ===== 546 생성 =====
def generate_546_from_041_kormarc(marc_041):
    a_codes, h_code = [], None
    for part in marc_041.split():
        if part.startswith("$a"): a_codes.append(part[2:])
        elif part.startswith("$h"): h_code = part[2:]
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
    return "언어 정보 없음"

# ===== 네임스페이스 제거 =====
def strip_ns(tag): return tag.split('}')[-1] if '}' in tag else tag

# ===== 알라딘 상세 페이지에서 보조 정보 크롤링 =====
def crawl_aladin_fallback(isbn13):
    url = f"https://www.aladin.co.kr/shop/wproduct.aspx?ISBN={isbn13}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        original = soup.select_one("div.info_original")
        lang_info = soup.select_one("div.conts_info_list1")
        category_text = ""
        categories = soup.select("div.conts_info_list2 li")
        for cat in categories:
            category_text += cat.get_text(separator=" ", strip=True) + " "
        detected_lang = ""
        if lang_info and "언어" in lang_info.text:
            if "Japanese" in lang_info.text: detected_lang = "jpn"
            elif "Chinese" in lang_info.text: detected_lang = "chi"
            elif "English" in lang_info.text: detected_lang = "eng"
        return {
            "original_title": original.text.strip() if original else "",
            "subject_lang": detect_language_from_category(category_text) or detected_lang,
            "category_text": category_text
        }
    except Exception as e:
        st.error(f"❌ 크롤링 중 오류 발생: {e}")
        return {}

# ===== KORMARC 태그 생성 =====
def get_kormarc_tags(isbn):
    isbn = isbn.strip().replace("-", "")
    url = "http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx"
    params = {
        "ttbkey": ALADIN_KEY,
        "itemIdType": "ISBN13",
        "ItemId": isbn,
        "output": "xml",
        "Version": "20131101"
    }
    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code != 200:
            raise ValueError("API 호출 실패")
        root = ET.fromstring(response.content)
        for elem in root.iter():
            elem.tag = strip_ns(elem.tag)
        item = root.find("item")
        if item is None:
            raise ValueError("<item> 태그 없음")

        title = item.findtext("title", default="")
        publisher = item.findtext("publisher", default="")
        author = item.findtext("author", default="")
        subinfo = item.find("subInfo")
        original_title = subinfo.findtext("originalTitle") if subinfo is not None else ""

        crawl = crawl_aladin_fallback(isbn)
        if not original_title:
            original_title = crawl.get("original_title", "")
        subject_lang_from_cat = crawl.get("subject_lang")  # 이미 detect_language_from_category 적용됨
        category_text = crawl.get("category_text", "")

        # ===== $a 판단 (본문 언어) =====
        lang_a = detect_language(title)
        st.write("📘 [DEBUG][$a] 제목 기반 초깃값 =", lang_a)
        if lang_a in ['und', 'eng']:  # 영문 제목인데 실제 본문이 한국어일 수 있어 GPT 보완
            st.write("📘 [DEBUG][$a] GPT 요청 (title/category/publisher/author) →", title, category_text, publisher, author)
            gpt_a = gpt_guess_main_lang(title, category_text, publisher, author)
            st.write("📘 [DEBUG][$a] GPT 판단 =", gpt_a)
            if gpt_a != 'und':
                lang_a = gpt_a

        # ===== $h 판단 (원서 언어) =====
        # 1) 원제 문자열 기반
        lang_h_first = detect_language(original_title) if original_title else "und"
        if original_title:
            st.write("📘 [DEBUG][$h] 원제 감지됨:", original_title)
            st.write("📘 [DEBUG][$h] 원제 기반 1차 =", lang_h_first)
        else:
            st.write("📘 [DEBUG][$h] 원제 없음")

        # 2) 카테고리(국가/지역) 기반 → GPT보다 우선
        lang_h_cat = subject_lang_from_cat or detect_language_from_category(category_text)
        st.write("📘 [DEBUG][$h] 카테고리 기반 후보 =", lang_h_cat)

        # 결정 로직: 원제 언어 or 카테고리 언어 중 신뢰되는 것을 먼저 사용
        lang_h = "und"
        decision = ""

        if lang_h_first != "und":
            lang_h = lang_h_first
            decision = "원제(문자군)로 확정"
        elif lang_h_cat:
            lang_h = lang_h_cat
            decision = "카테고리(국가/지역)로 확정"
        else:
            decision = "보완 필요 → GPT로 판단"

        # 3) 여전히 und면 GPT 보완
        if lang_h == "und":
            st.write("📘 [DEBUG][$h] GPT 보완 요청 (title/category/publisher/author/original) →",
                     title, category_text, publisher, author, original_title)
            lang_h = gpt_guess_original_lang(title, category_text, publisher, author, original_title)
            st.write("📘 [DEBUG][$h] GPT 판단 =", lang_h)
            if lang_h != "und":
                decision = "GPT로 확정"

        st.write(f"📘 [DEBUG][$h] 최종 = {lang_h}  (결정 근거: {decision})")

        # ===== 태그 생성 =====
        if lang_h and lang_h != lang_a and lang_h != "und":
            tag_041 = f"041 $a{lang_a} $h{lang_h}"
        else:
            tag_041 = f"041 $a{lang_a}"
        tag_546 = generate_546_from_041_kormarc(tag_041)

        return tag_041, tag_546, original_title
    except Exception as e:
        return f"📕 예외 발생: {e}", "", ""

# ===== Streamlit UI =====
st.title("📘 KORMARC 041/546 태그 생성기 (카테고리 우선 → GPT 보완)")

isbn_input = st.text_input("ISBN을 입력하세요 (13자리):")
if st.button("태그 생성"):
    if isbn_input:
        try:
            tag_041, tag_546, original = get_kormarc_tags(isbn_input)
            st.text(f"📄 041 태그: {tag_041}")
            if tag_546:
                st.text(f"📄 546 태그: {tag_546}")
            if original:
                st.text(f"📕 원제: {original}")
        except Exception as e:
            st.error(f"⚠️ 오류 발생: {e}")
    else:
        st.warning("ISBN을 입력해주세요.")
