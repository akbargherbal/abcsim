#!/usr/bin/env python3
"""
find_abc_duplicates.py
يبحث عن ملفات ABC المتشابهة بنسبة >= العتبة (الافتراضي 95%).

الاستخدام (PowerShell):
    python find_abc_duplicates.py .
    python find_abc_duplicates.py . --threshold 90
    python find_abc_duplicates.py . --full        # مقارنة الملف كاملاً بما فيه العنوان

اختياري (أسرع بكثير):
    pip install rapidfuzz
"""
import argparse
import csv
import hashlib
import re
import sys
from itertools import combinations
from pathlib import Path

try:
    from rapidfuzz import fuzz

    def similarity(a: str, b: str, cutoff: float) -> float:
        return fuzz.ratio(a, b, score_cutoff=cutoff)  # 0..100

    ENGINE = "rapidfuzz"
except ImportError:
    from difflib import SequenceMatcher

    def similarity(a: str, b: str, cutoff: float) -> float:
        sm = SequenceMatcher(None, a, b, autojunk=False)
        c = cutoff / 100.0
        # حدود عليا سريعة لتفادي الحساب الكامل غير الضروري
        if sm.real_quick_ratio() < c or sm.quick_ratio() < c:
            return 0.0
        return sm.ratio() * 100

    ENGINE = "difflib"

# حقول الترويسة التي نتجاهلها عند المقارنة (رقم المقطوعة والعنوان)
SKIP_HEADERS = re.compile(r"^[XT]:", re.IGNORECASE)


def normalize(text: str, full: bool) -> str:
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("%"):
            continue
        if not full and SKIP_HEADERS.match(line):
            continue
        line = line.split("%", 1)[0]          # إزالة التعليقات الجانبية
        lines.append(re.sub(r"\s+", "", line))  # إزالة كل المسافات
    return "\n".join(lines)


class UnionFind:
    def __init__(self, items):
        self.parent = {i: i for i in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default=".")
    ap.add_argument("--threshold", type=float, default=95.0)
    ap.add_argument("--full", action="store_true", help="قارن الملف كاملاً (بما فيه X: و T:)")
    ap.add_argument("--out", default="duplicates_report.csv")
    args = ap.parse_args()

    folder = Path(args.folder)
    files = sorted(folder.glob("*.abc"))
    if not files:
        sys.exit(f"لا توجد ملفات .abc في: {folder.resolve()}")

    print(f"عدد الملفات: {len(files)} | المحرك: {ENGINE} | العتبة: {args.threshold}%")

    contents = {}
    for f in files:
        raw = f.read_text(encoding="utf-8", errors="replace")
        contents[f.name] = normalize(raw, args.full)

    # 1) التطابق التام (بعد التطبيع)
    by_hash = {}
    for name, txt in contents.items():
        by_hash.setdefault(hashlib.md5(txt.encode("utf-8")).hexdigest(), []).append(name)
    exact_groups = [g for g in by_hash.values() if len(g) > 1]

    # 2) التشابه التقريبي لكل زوج
    names = list(contents)
    pairs = []
    total = len(names) * (len(names) - 1) // 2
    for i, (a, b) in enumerate(combinations(names, 2), 1):
        ta, tb = contents[a], contents[b]
        longer, shorter = max(len(ta), len(tb)), min(len(ta), len(tb))
        # فرق الطول وحده يمنع الوصول للعتبة
        if longer == 0 or shorter / longer * 100 < args.threshold:
            continue
        score = similarity(ta, tb, args.threshold)
        if score >= args.threshold:
            pairs.append((a, b, round(score, 2)))
        if i % 20000 == 0:
            print(f"  ... {i}/{total}", end="\r")

    pairs.sort(key=lambda p: -p[2])

    # 3) تجميع الأزواج في مجموعات
    uf = UnionFind(names)
    for a, b, _ in pairs:
        uf.union(a, b)
    groups = {}
    for n in names:
        groups.setdefault(uf.find(n), []).append(n)
    groups = [sorted(g) for g in groups.values() if len(g) > 1]

    # النتائج
    print(f"\nملفات متطابقة تماماً: {len(exact_groups)} مجموعة")
    for g in exact_groups:
        print("  =", ", ".join(g))

    print(f"\nأزواج متشابهة >= {args.threshold}%: {len(pairs)}")
    for a, b, s in pairs[:50]:
        print(f"  {s:6.2f}%  {a}  <->  {b}")
    if len(pairs) > 50:
        print(f"  ... و{len(pairs) - 50} زوج آخر في ملف التقرير")

    print(f"\nمجموعات التكرار: {len(groups)}")
    for g in groups:
        print("  *", ", ".join(g))

    with open(args.out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["file_a", "file_b", "similarity_percent"])
        w.writerows(pairs)
    print(f"\nتم حفظ التقرير في: {Path(args.out).resolve()}")

    if groups:
        redundant = sum(len(g) - 1 for g in groups)
        print(f"عدد الملفات الزائدة التي يمكن حذفها (إبقاء واحد من كل مجموعة): {redundant}")


if __name__ == "__main__":
    main()
