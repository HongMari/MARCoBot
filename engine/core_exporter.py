# C15: generate_all_oneclick() 전체 파이프라인
# ============================================================
# C-15) generate_all_oneclick — True Patch
# 원본 판단 로직 100% 유지 + 구조 안정화
# ============================================================

def generate_all_oneclick(
    isbn: str,
    *,
    reg_mark: str = "",
    reg_no: str = "",
    copy_symbol: str = "",
    use_ai_940: bool = True,
):
    """
    원본 generate_all_oneclick()의 모든 판단 구조를 그대로 따르면서
    모듈화된 field_builders 의 기능을 호출하는 True Patch 버전.
    """

    # ----------------------------------------------------------
    # 초기화
    # ----------------------------------------------------------
    marc_rec = Record(to_unicode=True, force_utf8=True)
    pieces = []              # (Field, MRK str)
    meta = {}
    global CURRENT_DEBUG_LINES
    CURRENT_DEBUG_LINES = []

    # ----------------------------------------------------------
    # 0) NLK author-only 조회
    # ----------------------------------------------------------
    author_raw, _ = fetch_nlk_author_only(isbn)

    # ----------------------------------------------------------
    # 1) 알라딘 메타데이터 (API → 실패 시 Web)
    # ----------------------------------------------------------
    item = fetch_aladin_item(isbn)    # 네 원본 wrapper 함수(있던 그대로)

    # ----------------------------------------------------------
    # 2) 041/546 생성
    # ----------------------------------------------------------
    tag_041_text = None
    tag_546_text = None
    original_title = None

    try:
        res = get_kormarc_tags(isbn)   # (041, 546, original)
        if isinstance(res, (list, tuple)) and len(res) == 3:
            tag_041_text, tag_546_text, original_title = res

        # 예외 문자열 처리
        if isinstance(tag_041_text, str) and tag_041_text.startswith("📕"):
            tag_041_text = None
        if isinstance(tag_546_text, str) and tag_546_text.startswith("📕"):
            tag_546_text = None
    except Exception:
        tag_041_text = None
        tag_546_text = None

    # 041 원작 언어코드
    origin_lang = None
    if tag_041_text:
        m = re.search(r"\$h([a-z]{3})", tag_041_text, re.I)
        if m:
            origin_lang = m.group(1).lower()

    # ----------------------------------------------------------
    # 3) 245 / 246 / 700
    # ----------------------------------------------------------
    marc245 = build_245_with_people_from_sources(item, author_raw, prefer="aladin")
    f_245 = mrk_str_to_field(marc245)

    marc246 = build_246_from_aladin_item(item)
    f_246 = mrk_str_to_field(marc246)

    mrk_700_list = build_700_people_pref_aladin(
        author_raw,
        item,
        origin_lang_code=origin_lang
    ) or []

    # ----------------------------------------------------------
    # 4) 90010 (Wikidata 원어명)
    # ----------------------------------------------------------
    people = extract_people_from_aladin(item) if item else {}
    mrk_90010_list = build_90010_from_wikidata(people, include_translator=False)

    # ----------------------------------------------------------
    # 5) 940 (245 $a 기반)
    # ----------------------------------------------------------
    a_out, n_flag = parse_245_a_n(marc245)
    mrk_940_list = build_940_from_title_a(
        a_out,
        use_ai=use_ai_940,
        disable_number_reading=bool(n_flag)
    )

    # ----------------------------------------------------------
    # 6) 260 (발행지 + 국가코드)
    # ----------------------------------------------------------
    publisher_raw = (item or {}).get("publisher", "")
    pubdate = (item or {}).get("pubDate", "") or ""
    pubyear = pubdate[:4] if len(pubdate) >= 4 else ""

    bundle = build_pub_location_bundle(isbn, publisher_raw)

    tag_260 = build_260(
        place_display=bundle["place_display"],
        publisher_name=publisher_raw,
        pubyear=pubyear,
    )
    f_260 = mrk_str_to_field(tag_260)

    # ----------------------------------------------------------
    # 7) 008 (country override + lang override)
    # ----------------------------------------------------------
    lang3_override = _lang3_from_tag041(tag_041_text) if tag_041_text else None

    data_008 = build_008_from_isbn(
        isbn,
        aladin_pubdate=(item or {}).get("pubDate", "") or "",
        aladin_title=(item or {}).get("title", "") or "",
        aladin_category=(item or {}).get("categoryName", "") or "",
        aladin_desc=(item or {}).get("description", "") or "",
        aladin_toc=((item or {}).get("subInfo", {}) or {}).get("toc", "") or "",
        override_country3=bundle["country_code"],
        override_lang3=lang3_override,
        cataloging_src="a",
    )
    f_008 = Field(tag="008", data=data_008)

    # ----------------------------------------------------------
    # 8) 007
    # ----------------------------------------------------------
    f_007 = Field(tag="007", data="ta")

    # ----------------------------------------------------------
    # 9) 020 + set ISBN(020-1)
    # ----------------------------------------------------------
    tag_020 = _build_020_from_item_and_nlk(isbn, item)
    f_020 = mrk_str_to_field(tag_020)

    nlk_extra = fetch_additional_code_from_nlk(isbn)
    set_isbn = nlk_extra.get("set_isbn", "").strip()

    # ----------------------------------------------------------
    # 10) 653 (GPT)
    # ----------------------------------------------------------
    tag_653 = _build_653_via_gpt(item)
    f_653 = mrk_str_to_field(tag_653) if tag_653 else None

    # 653 → 056 힌트로 사용
    try:
        kw_hint = sorted(set(_parse_653_keywords(tag_653)))[:7]
    except Exception:
        kw_hint = []

    # ----------------------------------------------------------
    # 11) 056 (KDC)
    # ----------------------------------------------------------
    try:
        kdc_code = get_kdc_from_isbn(
            isbn,
            ttbkey=ALADIN_TTB_KEY,
            openai_key=openai_key,
            model=model,
            keywords_hint=kw_hint,
        )
        if kdc_code and not re.fullmatch(r"\d{1,3}", kdc_code):
            kdc_code = None
    except Exception:
        kdc_code = None

    tag_056 = f"=056  \\\\$a{kdc_code}$26" if kdc_code else None
    f_056 = mrk_str_to_field(tag_056) if tag_056 else None

    # ----------------------------------------------------------
    # 12) 490 / 830
    # ----------------------------------------------------------
    tag_490, tag_830 = build_490_830_mrk_from_item(item)
    f_490 = mrk_str_to_field(tag_490)
    f_830 = mrk_str_to_field(tag_830)

    # ----------------------------------------------------------
    # 13) 300 (형태사항)
    # ----------------------------------------------------------
    tag_300, f_300 = build_300_from_aladin_detail(item)

    # ----------------------------------------------------------
    # 14) 950 (가격)
    # ----------------------------------------------------------
    tag_950 = build_950_from_item_and_price(item, isbn)
    f_950 = mrk_str_to_field(tag_950)

    # ----------------------------------------------------------
    # 15) 049 (등록번호)
    # ----------------------------------------------------------
    tag_049 = build_049(reg_mark, reg_no, copy_symbol)
    f_049 = mrk_str_to_field(tag_049) if tag_049 else None

    # ----------------------------------------------------------
    # 16) 필드 순서대로 조립
    # ----------------------------------------------------------
    def add_piece(field, mrk):
        if field and mrk:
            pieces.append((field, mrk))

    add_piece(f_008, f"=008  {data_008}")
    add_piece(f_007, "=007  ta")
    add_piece(f_020, tag_020)

    if set_isbn:
        tag_020_1 = f"=020  1\\$a{set_isbn} (set)"
        add_piece(mrk_str_to_field(tag_020_1), tag_020_1)

    if tag_041_text and "$h" in tag_041_text:
        f_041 = mrk_str_to_field(_as_mrk_041(tag_041_text))
        add_piece(f_041, _as_mrk_041(tag_041_text))

    add_piece(f_056, tag_056)
    add_piece(f_245, marc245)
    add_piece(f_246, marc246)
    add_piece(f_260, tag_260)
    add_piece(f_300, tag_300)
    add_piece(f_490, tag_490)

    if tag_546_text:
        f_546 = mrk_str_to_field(_as_mrk_546(tag_546_text))
        add_piece(f_546, _as_mrk_546(tag_546_text))

    add_piece(f_653, tag_653)

    for m in mrk_700_list:
        ff = mrk_str_to_field(m)
        if ff:
            add_piece(ff, m)

    for m in mrk_90010_list:
        ff = mrk_str_to_field(m)
        if ff:
            add_piece(ff, m)

    for m in mrk_940_list:
        ff = mrk_str_to_field(m)
        if ff:
            add_piece(ff, m)

    add_piece(f_830, tag_830)
    add_piece(f_950, tag_950)
    add_piece(f_049, tag_049)

    # ----------------------------------------------------------
    # MRK 전체 문자열
    # ----------------------------------------------------------
    mrk_text = "\n".join(m for _, m in pieces)

    # ----------------------------------------------------------
    # Record 객체 구성
    # ----------------------------------------------------------
    for f, _ in pieces:
        marc_rec.add_field(f)

    # ----------------------------------------------------------
    # meta 구성
    # ----------------------------------------------------------
    meta = {
        "TitleA": a_out,
        "has_n": bool(n_flag),
        "700_count": sum(1 for _, m in pieces if m.startswith("=700")),
        "90010_count": len(mrk_90010_list),
        "940_count": len(mrk_940_list),
        "Candidates": get_candidate_names_for_isbn(isbn),
        "041": tag_041_text,
        "546": tag_546_text,
        "020": tag_020,
        "056": tag_056,
        "653": tag_653,
        "kdc_code": kdc_code,
        "price_for_950": _extract_price_kr(item, isbn),
        "Publisher_raw": publisher_raw,
        "pubyear": pubyear,
        "Place_display": bundle["place_display"],
        "CountryCode_008": bundle["country_code"],
        "Publisher_resolved": bundle["resolved_publisher"],
        "Bundle_source": bundle["source"],
        "debug_lines": list(CURRENT_DEBUG_LINES),
    }

    marc_bytes = marc_rec.as_marc()

    return marc_rec, marc_bytes, mrk_text, meta

# C16. run_and_export() + Streamlit UI 분리
# C-16-1 : core_exporter.py (True Patch)
# ============================================================
# core_exporter.py — True Patch
# 엔진 전용: UI(Streamlit) 100% 분리
# ============================================================

import os
from pymarc import MARCWriter
from .field_builders import generate_all_oneclick, record_to_mrk_from_record


def save_mrc_mrk(record, isbn: str, save_dir: str):
    """
    엔진 전용 MRC/MRK 저장 함수
    """
    os.makedirs(save_dir, exist_ok=True)

    # -------------------------
    # Save MRC
    # -------------------------
    mrc_path = os.path.join(save_dir, f"{isbn}.mrc")
    with open(mrc_path, "wb") as f:
        f.write(record.as_marc())

    # -------------------------
    # Save MRK
    # -------------------------
    mrk_path = os.path.join(save_dir, f"{isbn}.mrk")
    mrk_text = record_to_mrk_from_record(record)

    with open(mrk_path, "w", encoding="utf-8") as f:
        f.write(mrk_text)

    return mrc_path, mrk_path, mrk_text


def run_and_export(
    isbn: str,
    *,
    reg_mark: str = "",
    reg_no: str = "",
    copy_symbol: str = "",
    use_ai_940: bool = True,
    save_dir: str = "./output",
):
    """
    원본 run_and_export()의 기능 중
    - Streamlit 요소 제거
    - 순수 엔진으로 사용 가능한 버전
    - generate_all_oneclick() 출력값 그대로 유지
    """

    # -------------------------
    # generate_all_oneclick 호출
    # -------------------------
    record, marc_bytes, mrk_text, meta = generate_all_oneclick(
        isbn,
        reg_mark=reg_mark,
        reg_no=reg_no,
        copy_symbol=copy_symbol,
        use_ai_940=use_ai_940,
    )

    # -------------------------
    # 파일 저장
    # -------------------------
    mrc_path, mrk_path, mrk_text_from_file = save_mrc_mrk(record, isbn, save_dir)

    # -------------------------
    # 반환 값은 원본 구조를 유지
    # -------------------------
    return {
        "record": record,
        "marc_bytes": marc_bytes,
        "mrk_text": mrk_text_from_file,
        "meta": meta,
        "mrc_path": mrc_path,
        "mrk_path": mrk_path,
    }
