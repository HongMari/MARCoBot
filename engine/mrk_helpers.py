# =====================================================
# mrk_helpers.py  (True Patch)
# 원본 코드에서 MRK/MARC 관련 함수만 그대로 분리
# =====================================================

import re
from pymarc import Field, Subfield, Record, MARCWriter

# -----------------------------------------------------
# 원본 mrk_str_to_field (로직 그대로)
# -----------------------------------------------------
def mrk_str_to_field(line):
    # 0) None/빈 값
    if line is None:
        return None

    # 1) 이미 Field 유사 객체면 그대로 반환 (덕타이핑)
    try:
        if getattr(line, "tag", None) is not None and (hasattr(line, "data") or hasattr(line, "subfields")):
            return line
    except Exception:
        pass

    # 2) 문자열 확보
    if not isinstance(line, str):
        try:
            line = str(line)
        except Exception:
            return None
    
    s = line.strip()
    if not s.startswith("=") or len(s) < 8:
        return None

    # 3) 태그/인디케이터/본문 분해
    m = re.match(r"^=(\d{3})\s{2}(.)(.)(.*)$", s)
    if m:
        tag, ind1_raw, ind2_raw, tail = m.groups()
    else:
        # 컨트롤필드 (=008  <data>)
        m_ctl = re.match(r"^=(\d{3})\s\s(.*)$", s)
        if not m_ctl:
            return None
        tag, data = m_ctl.group(1), m_ctl.group(2).strip()
        if tag.isdigit() and int(tag) < 10:
            return Field(tag=tag, data=data) if data else None
        return None

    # 4) 컨트롤필드
    if tag.isdigit() and int(tag) < 10:
        data = (ind1_raw + ind2_raw + tail).strip()
        return Field(tag=tag, data=data) if data else None

    # 5) 데이터필드: 인디케이터 역슬래시(\) → 공백
    ind1 = " " if ind1_raw == "\\" else ind1_raw
    ind2 = " " if ind2_raw == "\\" else ind2_raw

    subs_part = tail or ""
    if "$" not in subs_part:
        return None  # 서브필드 없으면 의미 없음

    # 6) 서브필드 파싱
    subfields = []
    i, L = 0, len(subs_part)
    while i < L:
        if subs_part[i] != "$":
            i += 1
            continue
        if i + 1 >= L:
            break
        code = subs_part[i + 1]
        j = i + 2
        while j < L and subs_part[j] != "$":
            j += 1
        value = subs_part[i + 2:j].strip()
        if code and value:
            subfields.append(Subfield(code, value))
        i = j

    if not subfields:
        return None

    return Field(tag=tag, indicators=[ind1, ind2], subfields=subfields)


# -----------------------------------------------------
# 원본 record_to_mrk_from_record (로직 그대로)
# -----------------------------------------------------
def record_to_mrk_from_record(rec: Record) -> str:
    lines = []
    # LDR
    leader = rec.leader.decode("utf-8") if isinstance(rec.leader, (bytes, bytearray)) else str(rec.leader)
    lines.append("=LDR  " + leader)

    for f in rec.get_fields():
        tag = f.tag

        # 컨트롤필드
        if tag.isdigit() and int(tag) < 10:
            lines.append(f"={tag}  " + (f.data or ""))
            continue

        # 데이터필드
        ind1 = (f.indicators[0] if getattr(f, "indicators", None) else " ") or " "
        ind2 = (f.indicators[1] if getattr(f, "indicators", None) else " ") or " "

        # 공백 → '\' 표시
        ind1_disp = "\\" if ind1 == " " else ind1
        ind2_disp = "\\" if ind2 == " " else ind2

        parts = ""
        subs = getattr(f, "subfields", None)

        # Subfield 객체 리스트
        if isinstance(subs, list) and subs and isinstance(subs[0], Subfield):
            for s in subs:
                parts += f"${s.code}{s.value}"

        # 구형 리스트 [code, value, ...]
        elif isinstance(subs, list):
            it = iter(subs)
            for code, val in zip(it, it):
                parts += f"${code}{val}"

        else:
            try:
                for s in f:
                    parts += f"${s.code}{s.value}"
            except Exception:
                pass

        lines.append(f"={tag}  {ind1_disp}{ind2_disp}{parts}")

    return "\n".join(lines)


# -----------------------------------------------------
# 원본 save_marc_files (로직 그대로)
# -----------------------------------------------------
def save_marc_files(record: Record, save_dir: str, base_filename: str):
    """
    .mrc(바이너리)와 .mrk(텍스트) 저장
    """
    import os
    os.makedirs(save_dir, exist_ok=True)

    # MRC 저장
    mrc_path = os.path.join(save_dir, f"{base_filename}.mrc")
    with open(mrc_path, "wb") as f:
        f.write(record.as_marc())

    # MRK 저장
    mrk_path = os.path.join(save_dir, f"{base_filename}.mrk")
    try:
        mrk_text = record_to_mrk_from_record(record)
    except Exception:
        mrk_text = record_to_mrk_from_record(record)

    with open(mrk_path, "w", encoding="utf-8") as f:
        f.write(mrk_text)

    return mrc_path, mrk_path
