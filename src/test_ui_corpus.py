# -*- coding: utf-8 -*-
"""
UI 테스트 코퍼스(Data/08_ui_test_corpus_20260726) 기반 UI 파일 인테이크 검증.

목적:
  Codex가 제공한 권장 테스트 세트(recommended_test_set.csv)의 각 파일에 대해
  UI(src/ui/index.html)의 파일 형식 식별 로직과 동일한 분류를 적용하고,
  기대 결과(expected_result: positive/boundary/negative)와 대조한 보고서를 생성한다.

UI 인테이크 정책 (v0.2):
  - 이미지 확장자(png/jpg/jpeg/bmp/gif/webp/svg) → 미리보기 시도 (매직바이트 검증)
  - 알려진 CAD/BIM/시뮬레이션 형식 → "미지원 안내 후 복귀" (경고, UI 중단 없음)
  - 그 외 → "인식 불가 경고 후 복귀"

출력:
  results/ui_corpus_intake_report.json
  results/UI코퍼스_인테이크_보고.md (한국어 요약)

실행: python src/test_ui_corpus.py
"""
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(ROOT, "Data", "08_ui_test_corpus_20260726")
TEST_SET = os.path.join(CORPUS, "00_manifest", "recommended_test_set.csv")
OUT_JSON = os.path.join(ROOT, "results", "ui_corpus_intake_report.json")
OUT_MD = os.path.join(ROOT, "results", "UI코퍼스_인테이크_보고.md")

# UI와 동일한 분류 (index.html의 IMG_EXT / KNOWN_FMT / MAX_IMG_MB와 일치할 것)
IMG_EXT = {"png", "jpg", "jpeg", "bmp", "gif", "webp", "svg"}
MAX_IMG_MB = 20
KNOWN_FMT = {
    "ifc", "ifcxml", "ifczip", "bcfzip", "ids", "dxf", "dwg", "dgn", "stp",
    "step", "stl", "amf", "ply", "obj", "skp", "fds", "idf", "epjson", "xml",
    "gbxml", "ttl", "rdf", "pdf", "zip", "csv", "json", "txt", "md", "yaml",
    "yml", "tif", "tiff",
}

# 이미지 매직바이트 (UI의 브라우저 디코딩 검증을 근사)
MAGIC = {
    "png": b"\x89PNG",
    "jpg": b"\xff\xd8\xff",
    "jpeg": b"\xff\xd8\xff",
    "bmp": b"BM",
    "gif": b"GIF8",
    "webp": None,  # RIFF....WEBP — 별도 처리
}


def sniff_image(head):
    if head[:2] == b"\x89P":
        return "png"
    if head[:2] == b"\xff\xd8":
        return "jpg"
    if head[:2] == b"BM":
        return "bmp"
    if head[:3] == b"GIF":
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def classify(path, ext):
    """UI 인테이크 결과를 반환: (ui_outcome, detail)
    ui_outcome ∈ preview_ok | size_guard | image_decode_error | unsupported_notice
                 | unknown_warning | missing
    """
    if not os.path.isfile(path):
        return "missing", "파일 없음"
    if ext in ("tif", "tiff"):
        return "unsupported_notice", "TIFF — 브라우저 미리보기 미지원, 변환 안내"
    if ext == "" or ext == "[none]":
        try:
            head = open(path, "rb").read(16)
        except OSError as exc:
            return "unknown_warning", str(exc)
        if sniff_image(head):
            ext = sniff_image(head)  # 이미지로 계속 진행
        else:
            try:
                head.decode("utf-8")
                return "unsupported_notice", "확장자 없음·텍스트 추정 — 안내 후 복귀"
            except UnicodeDecodeError:
                return "unknown_warning", "확장자 없음·이진 파일 — 경고 후 복귀"
    if ext in IMG_EXT:
        if os.path.getsize(path) > MAX_IMG_MB * 1048576:
            return "size_guard", f"이미지 {MAX_IMG_MB}MB 초과 — 안전 경고 후 복귀"
        if ext == "svg":
            try:
                head = open(path, "rb").read(512)
                ok = b"<svg" in head or b"<?xml" in head
            except OSError as exc:
                return "image_decode_error", str(exc)
            return ("preview_ok", "SVG 텍스트 확인") if ok else ("image_decode_error", "SVG 서명 없음")
        try:
            head = open(path, "rb").read(16)
        except OSError as exc:
            return "image_decode_error", str(exc)
        if ext == "webp":
            ok = head[:4] == b"RIFF" and head[8:12] == b"WEBP"
        else:
            ok = head.startswith(MAGIC[ext])
        return ("preview_ok", "매직바이트 일치") if ok else ("image_decode_error", "매직바이트 불일치")
    if ext in KNOWN_FMT:
        return "unsupported_notice", "알려진 CAD/BIM/문서/텍스트 형식 — 안내 후 복귀"
    return "unknown_warning", "미인식 확장자 — 경고 후 복귀"


def verdict(ui_outcome, expected_result):
    """코퍼스 기대와 UI 정책의 정합성 판정.
    positive: 어떤 결과든 '중단 없는 처리'면 OK (이미지면 preview_ok 요구)
    boundary/negative: 안전한 경고/오류 표시 후 복귀가 기대 → unsupported/unknown/decode_error 모두 OK
    """
    if ui_outcome == "missing":
        return "FAIL"
    if expected_result == "positive":
        return "OK" if ui_outcome in ("preview_ok", "unsupported_notice") else "CHECK"
    return "OK" if ui_outcome != "preview_ok" else "CHECK"


def main():
    if not os.path.isfile(TEST_SET):
        sys.exit(f"권장 테스트 세트를 찾을 수 없음: {TEST_SET}")
    rows = []
    with open(TEST_SET, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rel = row["relative_path"]
            path = os.path.join(CORPUS, rel.replace("/", os.sep))
            ext = (row["extension"] or "").lstrip(".").lower()
            outcome, detail = classify(path, ext)
            rows.append({
                "profile_id": row["profile_id"],
                "extension": ext,
                "bytes": int(row["bytes"]),
                "expected_result": row["expected_result"],
                "ui_outcome": outcome,
                "verdict": verdict(outcome, row["expected_result"]),
                "detail": detail,
                "relative_path": rel,
            })

    total = len(rows)
    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump({"total": total, "verdict_counts": counts, "rows": rows},
                  fh, ensure_ascii=False, indent=2)

    bad = [r for r in rows if r["verdict"] != "OK"]
    by_outcome = {}
    for r in rows:
        by_outcome[r["ui_outcome"]] = by_outcome.get(r["ui_outcome"], 0) + 1
    lines = [
        "# UI 테스트 코퍼스 인테이크 검증 보고",
        "",
        f"- 테스트 세트: `{os.path.relpath(TEST_SET, ROOT)}` ({total}건)",
        f"- 판정: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
        f"- UI 인테이크 결과 분포: " + ", ".join(f"{k}={v}" for k, v in sorted(by_outcome.items())),
        "",
        "판정 기준: positive는 중단 없는 처리(이미지는 미리보기 성공), "
        "boundary/negative는 안전한 경고·오류 표시 후 복귀를 기대. "
        "CHECK = UI 정책과 코퍼스 기대가 어긋나 수동 확인 필요, FAIL = 파일 누락.",
        "",
    ]
    if bad:
        lines.append("## OK가 아닌 항목")
        lines.append("")
        lines.append("| profile_id | ext | expected | ui_outcome | verdict | detail |")
        lines.append("|---|---|---|---|---|---|")
        for r in bad:
            lines.append(f"| {r['profile_id']} | {r['extension']} | {r['expected_result']} "
                         f"| {r['ui_outcome']} | {r['verdict']} | {r['detail']} |")
    else:
        lines.append("모든 항목 OK.")
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"total={total} verdicts={counts}")
    print(f"보고서: {OUT_MD}")


if __name__ == "__main__":
    main()
