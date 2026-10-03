"""楽天アフィリエイトのリンク作成ページから取った値で、商品リンクと商品画像を用意する（D-0260）。

背景:
  新規記事の商品リンクは、楽天アフィリエイトの「リンク作成ページ」（/freelink?u=<商品URL>）が
  出すリンク（hb.afl.rakuten.co.jp/ichiba/<リンクID>/?pc=..&link_type=picttext&ut=..）を使い、
  商品画像は同じページの画像（thumbnail.image.rakuten.co.jp・?_ex=400x400 が最大）を使う。
  楽天ウェブサービス規約 第10条(9)によりAPIから取った画像は保存できないため、
  旧経路（product-image-to-webp.py に API の画像URLを渡す使い方）は廃止した。

  リンク作成ページはログインが要るため、値の取り出しは Claude in Chrome で
  site/scripts/rakuten-freelink-extract.js を実行して行う。Chrome拡張はクエリ文字列を
  含む出力を伏せるため、JS側はリンクID（パスの一部）と画像のパスだけを返し、
  クエリ（pc・link_type・ut、画像の _ex）はこのスクリプトが組み立てる。

使い方:
  python site/scripts/build-rakuten-affiliate-products.py <slug> <freelink.tsv>
      freelink.tsv は rakuten-freelink-extract.js の戻り値をそのまま保存したもの
      （見出し行: seq item_url link_id image_path created_at item_name）。
      行ごとに次を行う（画像のダウンロードは1件ごとに1秒以上の間隔を空ける）。
        1. リンク（picttext・400x400）を組み立てる
        2. 画像を ?_ex=400x400 でダウンロードし、原本を output/product-images/ に残す
        3. 400x400 の白い正方形に、拡大縮小せずに中央へ置いて WebP にする
           （site/public/images/<slug>/products/<seq>.webp）。
           楽天ガイドラインで、リンク作成ページの画像は「サイズ変更・周辺部分への加工」は可、
           「画像の上への文字入れ・一部の切り取り」は不可。ここでは余白の追加だけを行う。
        4. 本文に貼るMarkdown（画像リンク・テキストリンク）を表示する
      結果は output/product-images/<slug>-rakuten-links.tsv にも書き出す
      （リンクを作った日時＝created_at を含む）。

  python site/scripts/build-rakuten-affiliate-products.py --self-test
      リンクの組み立てが、リンク作成ページが出すリンクと同じになるかを確認する
      （2026-10-03 に実測したリンクのSHA-256先頭16桁と照合する）。

失敗時の挙動:
  画像だけ失敗した行は、画像をスキップしてテキストリンクのMarkdownだけを出す（終了コード1）。
  本文はスコアバッジ付きのテキストリンクのみ（画像なし）で続行してよい。
  リンクを組み立てられない行（ERROR行・リンクIDの形が違う等）があれば終了コード1。

終了コード: 全行のリンクと画像がそろえば0、1行でも欠ければ1
"""

import base64
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image, UnidentifiedImageError

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT, "output", "product-images")
OUT_DIR = os.path.join(ROOT, "site", "public", "images")

LINK_BASE = "https://hb.afl.rakuten.co.jp/ichiba/%s/"
IMAGE_HOST = "https://thumbnail.image.rakuten.co.jp"
IMAGE_SIZE = 400  # リンク作成ページで選べる最大の画像サイズ（?_ex=400x400）。拡大しない
QUALITY = 85
PAD_COLOR = (255, 255, 255)
WAIT_SECONDS = 1.2  # 連続取得の間隔（1秒以上・D-0260）
USER_AGENT = "Mozilla/5.0 (compatible; kohaku-jikan-product-image-fetch/2.0)"

RE_LINK_ID = re.compile(r"[0-9a-f]{8}(?:\.[0-9a-f]{8}){3}")
RE_ITEM_URL = re.compile(r"https://item\.rakuten\.co\.jp/[^\s?#]+")
# 店舗の画像はR-Cabinet（/@0_mall/）と、店舗独自の置き場（/@0_gold/）の2種類がある（2026-10-03実測）
RE_IMAGE_PATH = re.compile(r"/@0_(?:mall|gold)/[^\s?#]+\.(?:jpe?g|png|gif|webp)", re.IGNORECASE)

# リンク作成ページの表示設定（ut）。2026-10-03 にリンク作成ページで「画像あり（picttext）・400」を
# 選んだときの値を復元したもの。商品によらず同じ値になる。
UT_SETTINGS = {
    "page": "item",
    "type": "picttext",
    "size": "%dx%d" % (IMAGE_SIZE, IMAGE_SIZE),
    "nam": 1,
    "namp": "right",
    "com": 1,
    "comp": "down",
    "price": 1,
    "bor": 1,
    "col": 1,
    "bbtn": 1,
    "prod": 0,
    "amp": False,
}

# --self-test 用: 2026-10-03 にリンク作成ページが出したリンク（eins-shop/10003731・400x400）の
# SHA-256 先頭16桁。リンクID自体はこのファイルに書かず、照合用のハッシュだけを置く。
SELF_TEST_ITEM = "https://item.rakuten.co.jp/eins-shop/10003731/"
SELF_TEST_SHA16 = "8cade6bc422e3ee0"

SKIP_HINT = "この商品の画像はスキップし、本文はテキストリンクのみ（画像なし）で続行してください（D-0260）。"


def js_encode(value):
    """JavaScript の encodeURIComponent と同じ規則でエンコードする。"""
    return urllib.parse.quote(value, safe="-_.!~*'()")


def ut_value():
    raw = json.dumps(UT_SETTINGS, separators=(",", ":"), ensure_ascii=False)
    return js_encode(base64.b64encode(raw.encode("utf-8")).decode("ascii"))


def build_link(link_id, item_url):
    return "%s?pc=%s&link_type=picttext&ut=%s" % (LINK_BASE % link_id, js_encode(item_url), ut_value())


def image_url(image_path):
    return "%s%s?_ex=%dx%d" % (IMAGE_HOST, image_path, IMAGE_SIZE, IMAGE_SIZE)


def read_rows(tsv_path):
    with open(tsv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        need = {"seq", "item_url", "link_id", "image_path", "created_at", "item_name"}
        if not reader.fieldnames or not need.issubset(set(reader.fieldnames)):
            sys.exit("TSVの見出し行が違います（必要: %s）: %s" % (" ".join(sorted(need)), tsv_path))
        return [row for row in reader if any((v or "").strip() for v in row.values())]


def download(url, dst_path):
    """成功なら None、失敗なら理由の文字列を返す。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as res, open(dst_path, "wb") as f:
            f.write(res.read())
    except urllib.error.HTTPError as e:
        return "HTTPエラー %d" % e.code
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        return "通信エラー: %s" % e
    return None


def to_webp(src_path, dst_path):
    """拡大縮小せずに 400x400 の白い正方形の中央へ置いて保存する。(元の寸法, エラー) を返す。"""
    try:
        im = Image.open(src_path).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        return None, "画像として読めません（%s）" % e
    w, h = im.size
    if w > IMAGE_SIZE or h > IMAGE_SIZE:
        return (w, h), "画像が %dx%d を超えています（%dx%d）。縮小はしない決まりのため扱いません" % (
            IMAGE_SIZE, IMAGE_SIZE, w, h)
    canvas = Image.new("RGB", (IMAGE_SIZE, IMAGE_SIZE), PAD_COLOR)
    canvas.paste(im, ((IMAGE_SIZE - w) // 2, (IMAGE_SIZE - h) // 2))
    canvas.save(dst_path, "WEBP", quality=QUALITY, method=6)
    return (w, h), None


def self_test():
    # リンクIDはファイルに置かないため、リンク作成ページから取り直した TSV を引数で受け取って照合する。
    args = sys.argv[2:]
    if len(args) != 1:
        print("usage: python site/scripts/build-rakuten-affiliate-products.py --self-test <freelink.tsv>")
        print("  TSVの中に %s の行が必要です" % SELF_TEST_ITEM)
        return 1
    for row in read_rows(args[0]):
        if row["item_url"] == SELF_TEST_ITEM:
            link = build_link(row["link_id"], row["item_url"])
            got = hashlib.sha256(link.encode("utf-8")).hexdigest()[:16]
            ok = got == SELF_TEST_SHA16
            print("SELF_TEST_%s（組み立てたリンクのSHA-256先頭16桁 %s / 実測 %s）" % ("OK" if ok else "NG", got, SELF_TEST_SHA16))
            return 0 if ok else 1
    print("SELF_TEST_NG（TSVに %s の行がありません）" % SELF_TEST_ITEM)
    return 1


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if sys.argv[1:2] == ["--self-test"]:
        return self_test()

    args = sys.argv[1:]
    if len(args) != 2:
        print(__doc__)
        return 1
    slug, tsv_path = args
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        print("slugは英小文字・数字・ハイフンのみ: %s" % slug)
        return 1
    if not os.path.isfile(tsv_path):
        print("TSVが見つかりません: %s" % tsv_path)
        return 1

    rows = read_rows(tsv_path)
    if not rows:
        print("TSVに商品の行がありません: %s" % tsv_path)
        return 1

    os.makedirs(SRC_DIR, exist_ok=True)
    dst_dir = os.path.join(OUT_DIR, slug, "products")
    os.makedirs(dst_dir, exist_ok=True)

    records = []
    snippets = []
    ng = 0
    first_download = True
    for row in rows:
        seq = (row.get("seq") or "").strip()
        item_url = (row.get("item_url") or "").strip()
        link_id = (row.get("link_id") or "").strip()
        image_path = (row.get("image_path") or "").strip()
        name = (row.get("item_name") or "").strip()
        created_at = (row.get("created_at") or "").strip()

        if not re.fullmatch(r"[0-9]+", seq):
            print("NG  seq=%r: 連番が数字ではありません" % seq)
            ng += 1
            continue
        if item_url == "ERROR" or not RE_LINK_ID.fullmatch(link_id) or not RE_ITEM_URL.fullmatch(item_url):
            print("NG  %s: リンクを組み立てられません（item_url=%s / link_id=%s）" % (
                seq, item_url, "形式OK" if RE_LINK_ID.fullmatch(link_id) else link_id))
            ng += 1
            continue

        link = build_link(link_id, item_url)
        image_ok = False
        image_note = ""
        if RE_IMAGE_PATH.fullmatch(image_path):
            if not first_download:
                time.sleep(WAIT_SECONDS)
            first_download = False
            ext = os.path.splitext(image_path)[1].lower() or ".jpg"
            src_path = os.path.join(SRC_DIR, "%s-%s%s" % (slug, seq, ext))
            dst_path = os.path.join(dst_dir, "%s.webp" % seq)
            err = download(image_url(image_path), src_path)
            if err is None:
                size, err = to_webp(src_path, dst_path)
                if err is None:
                    image_ok = True
                    image_note = "%dx%d -> %dx%d %.1fKB" % (
                        size[0], size[1], IMAGE_SIZE, IMAGE_SIZE, os.path.getsize(dst_path) / 1024)
                else:
                    os.remove(src_path)
            if err is not None:
                image_note = err
        else:
            image_note = "画像のパスがありません（%s）" % (image_path or "空欄")

        if not image_ok:
            ng += 1
        print("%s  %s: %s ｜画像: %s" % ("OK" if image_ok else "NG", seq, name or item_url, image_note))
        if not image_ok:
            print("    " + SKIP_HINT)

        alt = name or "商品画像"
        lines = []
        if image_ok:
            lines.append("[![%s](/images/%s/products/%s.webp)](%s)" % (alt, slug, seq, link))
            lines.append("")
        lines.append("★R（v件） [%sはこちら（楽天市場）](%s)" % (name or "商品", link))
        snippets.append((seq, lines))
        records.append([seq, item_url, link, image_url(image_path) if image_ok else "", created_at, name])

    record_path = os.path.join(SRC_DIR, "%s-rakuten-links.tsv" % slug)
    with open(record_path, "w", encoding="utf-8", newline="") as f:
        f.write("seq\titem_url\taffiliate_url\timage_url\tcreated_at\titem_name\n")
        for rec in records:
            f.write("\t".join(rec) + "\n")

    print("")
    print("--- 本文に貼るMarkdown（★R（v件）は score-product.py の表示用の値に置き換える） ---")
    for seq, lines in snippets:
        print("# 商品%s" % seq)
        for line in lines:
            print(line)
        print("")
    print("記録: %s" % os.path.relpath(record_path, ROOT).replace("\\", "/"))
    print("総合: %s（%d行中 %d行に欠けあり）" % ("OK" if ng == 0 else "NG", len(rows), ng))
    return 0 if ng == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
