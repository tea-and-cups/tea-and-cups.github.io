import io
import os
import sys

FILES = [
    "5000en-ika-brand-teacup-hikaku.md",
    "atsui-hi-suibunhokyu-koucha.md",
    "bousai-koucha-teabag-erabikata.md",
    "chaba-hokan-natsu.md",
    "creamdown-boushi.md",
    "glass-cup-hikaku.md",
    "hokuou-teacup-arabia-iittala-hikaku.md",
    "honey-koucha-erabikata.md",
    "ice-royal-milktea.md",
    "kisei-temiyage-koucha-gift.md",
    "koucha-caffeine-ryou-qa.md",
    "koucha-teapot-erabikata-hikaku.md",
    "mariage-freres-marco-polo.md",
    "mizudashi-pitcher-hikaku.md",
    "mizudashi-tea-leaves.md",
    "natsu-fruit-flavor-tea-hikaku.md",
    "noritake-narumi-okuratouen-cup-saucer-hikaku.md",
    "ouchi-afternoon-tea-hajimekata.md",
    "outdoor-camp-mizudashi-koucha.md",
    "pair-cup-saucer-kekkonjoshii-tanjoubi-hikaku.md",
    "raikyaku-motenashi-icetea.md",
    "suzushige-natsu-table-coordinate.md",
    "teacup-coffee-cup-chigai.md",
    "tokekunikui-kori-icetea.md",
    "wakoucha-nyumon.md",
    "wedgwood-teacup-erabikata-hikaku.md",
    "zansho-mimai-koucha-gift.md",
]

OLD = "※当サイトはアフィリエイト広告（もしもアフィリエイト経由の楽天市場、Amazonアソシエイト・プログラムを利用した商品リンク）を利用しています。Amazonのアソシエイトとして、当サイトは適格販売により収入を得ています。"
NEW = "※当サイトはアフィリエイト広告（もしもアフィリエイト経由の楽天市場）を利用しています。"

BASE = os.path.join(os.path.dirname(__file__), "..", "src", "content", "posts")

ok_count = 0
missing = []

for f in FILES:
    path = os.path.join(BASE, f)
    with io.open(path, encoding="utf-8") as fh:
        content = fh.read()
    if OLD not in content:
        missing.append(f)
        continue
    content = content.replace(OLD, NEW, 1)
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    ok_count += 1
    print("OK:", f)

print("---")
print("replaced:", ok_count, "/", len(FILES))
if missing:
    print("MISSING:", missing)
    sys.exit(1)
