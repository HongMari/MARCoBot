# tests/test_diff.py
import json
from original.marcobot_original import generate_all_oneclick as gen_orig
from truepatch.marcobot_truepatch import generate_all_oneclick as gen_new

# 비교 대상 ISBN
TEST_ISBNS = [
    "9788937462849",
    "9788965746980",
    "9788954671492",
    "9791190090011",
]

def normalize_mrk(text: str) -> str:
    """줄바꿈, 공백 차이로 diff가 흔들리지 않도록 정규화."""
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()

def normalize_meta(meta: dict) -> dict:
    """디버그 라인처럼 매번 달라지는 필드는 제외."""
    drop_keys = {"debug", "debug_lines", "Provenance"}
    return {k: v for k, v in meta.items() if k not in drop_keys}

def compare_records(isbn, result_orig, result_new):
    rec_o, mrc_o, mrk_o, meta_o = result_orig
    rec_n, mrc_n, mrk_n, meta_n = result_new

    # 1) MRC 바이너리 비교
    if mrc_o != mrc_n:
        print(f"❌ MRC 다름: {isbn}")
        return False

    # 2) MRK 문자열 비교
    if normalize_mrk(mrk_o) != normalize_mrk(mrk_n):
        print(f"❌ MRK 다름: {isbn}")
        print("=== ORIGINAL MRK ===")
        print(mrk_o)
        print("=== NEW MRK ===")
        print(mrk_n)
        return False

    # 3) META 비교
    if normalize_meta(meta_o) != normalize_meta(meta_n):
        print(f"❌ META 다름: {isbn}")
        print("=== ORIGINAL META ===")
        print(json.dumps(normalize_meta(meta_o), ensure_ascii=False, indent=2))
        print("=== NEW META ===")
        print(json.dumps(normalize_meta(meta_n), ensure_ascii=False, indent=2))
        return False

    print(f"✔ SAME: {isbn}")
    return True


def run_tests():
    print("=== RUNNING MARCOBOT TRUE PATCH DIFF TEST ===")

    all_passed = True
    for isbn in TEST_ISBNS:
        result_orig = gen_orig(isbn, use_ai_940=False)
        result_new  = gen_new(isbn, use_ai_940=False)

        ok = compare_records(isbn, result_orig, result_new)
        if not ok:
            all_passed = False

    if all_passed:
        print("\n🎉 SUCCESS: 원본과 True Patch 출력이 모두 동일함!\n")
    else:
        print("\n⚠ SOME TESTS FAILED: 위 출력 참고\n")


if __name__ == "__main__":
    run_tests()
