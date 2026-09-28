"""Bounded subprocess entry point for PDF text extraction (no network)."""
import json
import sys

from .importers import MAX_UPLOAD, extract_pdf


def main():
    try:
        data = sys.stdin.buffer.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise ValueError("PDF เกินขนาดที่กำหนด")
        result = extract_pdf(data, research="--research" in sys.argv)
        sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
    except Exception:
        sys.stdout.buffer.write(json.dumps({"error": "อ่าน PDF ไม่สำเร็จ; ต้องไม่เข้ารหัส ไม่เกิน 200 หน้า/1 ล้านตัวอักษร และเป็นไฟล์ที่อ่านได้"}, ensure_ascii=False).encode("utf-8"))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
