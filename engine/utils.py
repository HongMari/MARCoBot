# ===========================================
# utils.py  (True Patch)
# 원본 코드 로직 100% 그대로 유지
# ===========================================

import re
import html
import math
from dataclasses import dataclass
from typing import Optional, Dict, Any

# -------------------------
# 공통 텍스트 정리 유틸
# -------------------------
def clean_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def strip_tags(html_text: str) -> str:
    return re.sub(r"<[^>]+>", " ", html_text)

# -------------------------
# KDC 숫자 파싱 유틸
# -------------------------
def first_match_number(text: str) -> Optional[str]:
    """KDC 숫자만 추출: 0~999 또는 소수점 포함(예: 813.7)"""
    if not text:
        return None
    m = re.search(r"\b([0-9]{1,3}(?:\.[0-9]+)?)\b", text)
    return m.group(1) if m else None

def normalize_kdc_3digit(code: Optional[str]) -> Optional[str]:
    """
    입력 예: '813.7', '813', '81', '5', 'KDC 325.1'
    출력 예: '813', '813', '81', '5', '325'  (선행 1~3자리 정수부만)
    """
    if not code:
        return None
    m = re.search(r"(\d{1,3})", code)
    return m.group(1) if m else None

def first_or_empty(lst):
    return lst[0] if lst else ""

# -------------------------
# 300 형태사항에서 사용되는 mm → cm 계산 유틸
# -------------------------
def convert_mm_to_cm(width: int, height: int) -> str:
    """
    원본 코드에서 사용되는 방식 그대로:
    - 정사각형 or 비정상 비율: w_cm x h_cm cm
    - 일반적인 세로형: h_cm cm
    """
    if width == height or width > height or width < height / 2:
        w_cm = math.ceil(width / 10)
        h_cm = math.ceil(height / 10)
        return f"{w_cm}x{h_cm} cm"
    else:
        h_cm = math.ceil(height / 10)
        return f"{h_cm} cm"

# -------------------------
# BookInfo dataclass
# (원본 구조 그대로 유지)
# -------------------------
@dataclass
class BookInfo:
    title: str = ""
    author: str = ""
    pub_date: str = ""
    publisher: str = ""
    isbn13: str = ""
    category: str = ""
    description: str = ""
    toc: str = ""
    extra: Optional[Dict[str, Any]] = None
