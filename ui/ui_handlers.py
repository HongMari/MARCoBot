# C16. run_and_export() + Streamlit UI 분리
# C-16-2 : ui_handlers.py (Streamlit UI 전용 True Patch)
# ============================================================
# ui_handlers.py — True Patch
# Streamlit 전용 UI Layer (엔진과 완전 분리)
# ============================================================

import streamlit as st
import pandas as pd

from engine.core_exporter import run_and_export


# ------------------------------------------------------------
# CSV 업로드 파서 (원본 기능 100% 유지)
# ------------------------------------------------------------
def load_uploaded_csv(uploaded_file):
    try:
        df = pd.read_csv(uploaded_file, dtype=str)
        df = df.fillna("")
        return df
    except Exception as e:
        st.error(f"❌ CSV 파일 읽기 실패: {e}")
        return None


# ------------------------------------------------------------
# 결과 UI 출력 (한 ISBN 단위)
# ------------------------------------------------------------
def render_result_block(isbn: str, result: dict, idx: int, total: int):
    """
    Streamlit에 변환 결과 표시.
    원본 UI의 동작을 유지하되, 엔진 로직은 절대 포함하지 않음.
    """

    st.markdown(f"### 📘 결과 {idx}/{total} — ISBN: `{isbn}`")

    meta = result.get("meta", {})
    mrk_text = result.get("mrk_text", "")

    # 간단한 메타 요약
    with st.expander("📊 Meta 정보", expanded=False):
        safe_meta = {k: v for k, v in meta.items() if k != "debug_lines"}
        st.json(safe_meta)

        debug_lines = meta.get("debug_lines") or []
        if debug_lines:
            st.markdown("#### 🔍 Debug Lines")
            st.text("\n".join(str(x) for x in debug_lines))

    # MRK 미리보기
    with st.expander("📄 MRK 출력 미리보기", expanded=True):
        st.code(mrk_text or "(생성 실패)", language="text")

    # 다운로드 버튼
    st.download_button(
        label="📥 MRC 다운로드",
        data=open(result["mrc_path"], "rb").read(),
        file_name=f"{isbn}.mrc",
        mime="application/marc"
    )

    st.download_button(
        label="📥 MRK 다운로드",
        data=mrk_text,
        file_name=f"{isbn}.mrk",
        mime="text/plain"
    )


# ------------------------------------------------------------
# 메인 UI 처리 함수
# ------------------------------------------------------------
def handle_ui():
    """
    UI 전체 실행을 담당.
    Streamlit 앱(app.py)에서 이 함수를 호출한다.
    """

    st.header("📚 ISBN → MARC 자동 생성기 (True Patch)")
    st.caption("엔진 로직 완전 분리 버전")

    st.checkbox("🧠 940 생성에 OpenAI 활용", value=True, key="use_ai_940")

    # -------------------------------
    # Form 입력 영역
    # -------------------------------
    with st.form(key="isbn_form", clear_on_submit=False):
        st.text_input("🔹 단일 ISBN 입력", key="single_isbn")
        st.file_uploader(
            "📁 CSV 업로드 (열: ISBN, 등록기호, 등록번호, 별치기호)",
            type=["csv"],
            key="csv_input"
        )
        submitted = st.form_submit_button("🚀 변환 실행")

    # -------------------------------
    # 제출 처리
    # -------------------------------
    if not submitted:
        return

    single_isbn = (st.session_state.get("single_isbn") or "").strip()
    uploaded = st.session_state.get("csv_input")

    jobs = []
    if single_isbn:
        jobs.append([single_isbn, "", "", ""])

    if uploaded:
        df = load_uploaded_csv(uploaded)
        if df is None:
            return

        need_cols = {"ISBN", "등록기호", "등록번호", "별치기호"}
        if not need_cols.issubset(df.columns):
            st.error("❌ CSV에 필요한 열이 없습니다: ISBN, 등록기호, 등록번호, 별치기호")
            return

        rows = df[list(need_cols)].values.tolist()
        jobs.extend(rows)

    if not jobs:
        st.warning("변환할 항목이 없습니다.")
        return

    # -------------------------------
    # 변환 실행
    # -------------------------------
    st.write(f"총 {len(jobs)}건 처리 중…")
    prog = st.progress(0)
    results = []

    for idx, (isbn, reg_mark, reg_no, copy_symbol) in enumerate(jobs, start=1):

        result = run_and_export(
            isbn,
            reg_mark=reg_mark,
            reg_no=reg_no,
            copy_symbol=copy_symbol,
            use_ai_940=st.session_state.get("use_ai_940", True),
            save_dir="./output"
        )

        results.append((isbn, result))
        prog.progress(idx / len(jobs))

        render_result_block(isbn, result, idx, len(jobs))

    st.success("🎉 모든 변환이 완료되었습니다!")

    # 전체 MRK 묶음 다운로드
    all_mrk = "\n\n".join([res["mrk_text"] for _, res in results]).encode("utf-8-sig")
    st.download_button(
        label="📦 전체 MRK 묶음 다운로드",
        data=all_mrk,
        file_name="marc_all.txt",
        mime="text/plain"
    )

    st.info("⚙️ 엔진과 UI가 완전히 분리된 구조입니다.")
