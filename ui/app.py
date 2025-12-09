# ============================================================
# app.py — True Patch
# Streamlit 앱 진입점(Launcher)
# ============================================================

import streamlit as st
from ui.ui_handlers import handle_ui


def main():
    """
    Streamlit 전용 앱 엔트리.
    UI → 엔진 호출 흐름만 남기고,
    엔진 내부의 판단 로직/메타데이터 파이프라인은 절대 변경하지 않음.
    """
    st.set_page_config(
        page_title="MARCoBot — ISBN → MARC 자동 변환",
        layout="wide",
        page_icon="📚"
    )

    handle_ui()


if __name__ == "__main__":
    main()
