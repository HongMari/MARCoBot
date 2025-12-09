import json

from original_app import generate_all_oneclick as gen_orig
from truepatch_app import generate_all_oneclick as gen_new


TEST_ISBNS = [
    "9788937462849",
    "9788965746980",
    "9788954671492",
    "9791190090011",
]


def norm(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def compare(isbn, orig, new):
    rec_o, mrc_o, mrk_o, meta_o = orig
    rec_n, mrc_n, mrk_n, meta_n = new

    if mrc_o != mrc_n:
        print(f"❌ MRC DIFF: {isbn}")
        return False

    if norm(mrk_o) != norm(mrk_n):
        print(f"❌ MRK DIFF: {isbn}")
        print("=== ORIGINAL ===")
        print(mrk_o)
        print("=== NEW ===")
        print(mrk_n)
        return False

    def clean_meta(x):
        drop = {"debug", "debug_lines", "Provenance"}
        return {k: v for k, v in x.items() if k not in drop}

    if clean_meta(meta_o) != clean_meta(meta_n):
        print(f"❌ META DIFF: {isbn}")
        return False

    print(f"✔ SAME: {isbn}")
    return True


def run():
    ok_all = True
    for isbn in TEST_ISBNS:
        print(f"\n▶ TEST {isbn}")
        o = gen_orig(isbn, use_ai_940=False)
        n = gen_new(isbn, use_ai_940=False)
        if not compare(isbn, o, n):
            ok_all = False

    print("\n🎉 ALL PASS" if ok_all else "\n⚠ SOME FAILED")


if __name__ == "__main__":
    run()
