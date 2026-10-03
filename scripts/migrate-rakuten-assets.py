"""既存記事の商品リンク・商品画像を楽天アフィリエイトへ一括移行するための準備と確認（第2段・D-0261）。

公開済み記事の本文の書き換え・画像の差し替え・commit・push は
publish-article.py --migrate-rakuten が行う。このスクリプトはその前後の作業だけを受け持つ。

作業用の置き場: output/product-images/_migration/（在庫表・Chromeに渡す商品URLの束・
Chromeの戻り値・比較結果・差し替え候補の画像・移行計画）

使い方（上から順に実行する）:
  python site/scripts/migrate-rakuten-assets.py inventory
      公開済み記事（site/src/content/posts/）の もしもアフィリエイトのリンク（af.moshimo.com）から
      楽天の商品URL（url=）を取り出し、記事×商品の在庫表（inventory.tsv）と、Chromeに渡す
      商品URLの束（batch-NN.json・40件ずつ・クエリを外したURL）を作る。

  python site/scripts/migrate-rakuten-assets.py move-old [--dry-run]
      output/product-images/ にある旧原本（APIから取った画像 <slug>-<連番>.<拡張子>）と
      テスト用の zz-rakuten-test-* を output/product-images/_delete-me/ へ移す（削除はしない。
      *-rakuten-links.tsv はテスト用以外は移さない）。新しい原本と同じ名前のため、
      prepare より前に実行する。

  （Chrome）batch-NN.json の配列で rakuten-freelink-extract.js を実行し、戻り値を
      短い形（read_compact の説明を参照）で _migration/freelink-NN.tsv に書き写す。

  python site/scripts/migrate-rakuten-assets.py verify-freelink
      書き写した freelink-NN.tsv を check 列で照合する（写し間違いの検出）。

  python site/scripts/migrate-rakuten-assets.py prepare [--text-only <file>]
      freelink-NN.tsv を読み（check 列で写し間違いを照合）、画像のある記事×商品ごとに
      リンク作成ページの画像を 400x400 で取得して、差し替え候補（_migration/candidates/<slug>/<連番>.webp）
      と原本（output/product-images/<slug>-<連番>.<拡張子>）を作る。今の画像との見た目の差を
      差分ハッシュ（dHash・64ビット）で比べ、compare.tsv に書く。
      移行計画（plan.tsv）と、記事ごとの取得記録（output/product-images/<slug>-rakuten-links.tsv）も書く。
      --text-only は「slug<TAB>連番<TAB>理由」の表で、目視の結果、文字リンクにする商品を指定する。

  python site/scripts/migrate-rakuten-assets.py contact-sheet [--all] [--extra <slug:連番,...>]
      目視が要る画像を、今の画像（左）と差し替え候補（右）を並べた一覧画像にする（_migration/sheets/）。

  （ここで publish-article.py --migrate-rakuten <plan.tsv> を実行する）

  python site/scripts/migrate-rakuten-assets.py link-health [--write]
      data/link-health.md の画像列を、移行後の本文の画像の有無と照合する（--write で書き換え）。
      台帳の行数と記事の商品数が違う記事も表示する。

  python site/scripts/migrate-rakuten-assets.py check-records
      公開済み記事が参照する /images/<slug>/products/N.webp のすべてに、
      <slug>-rakuten-links.tsv の行（seq=N・image_url あり）があるかを確かめる。

  python site/scripts/migrate-rakuten-assets.py verify-live
      本番（https://kohaku-jikan.com）の全記事を取得し、商品カード・「リンク先：楽天市場」・
      クレジットの数、もしものリンクの有無、商品画像URLが200で手元のファイルと同じ中身か、を確かめる。

終了コード: 0=問題なし / 1=問題あり（内容を表示）
"""

import csv
import glob
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS_DIR = os.path.join(ROOT, "site", "scripts")
POSTS_DIR = os.path.join(ROOT, "site", "src", "content", "posts")
PUBLIC_IMAGES = os.path.join(ROOT, "site", "public", "images")
PRODUCT_IMAGES = os.path.join(ROOT, "output", "product-images")
MIG_DIR = os.path.join(PRODUCT_IMAGES, "_migration")
DELETE_ME = os.path.join(PRODUCT_IMAGES, "_delete-me")
CANDIDATES = os.path.join(MIG_DIR, "candidates")
RAW_CACHE = os.path.join(MIG_DIR, "raw")

BATCH_SIZE = 40
# 見た目の差の閾値（dHash 64ビット中の異なるビット数）。これ以下は「同じ画像」とみなして目視しない。
DHASH_THRESHOLD = 10
# 細かい差の閾値（余白を除いた64×64グレースケールの明るさの差の平均・0〜255）。
# 全243件の分布（2026-10-03・中央0.8・90%点11.8）で、10を超えると値がまばらになるため10とした。
MAD_THRESHOLD = 10.0
LIVE_BASE = "https://kohaku-jikan.com"
LIVE_WAIT = 0.3
CREDIT_TEXT = "Supported by Rakuten Developers"
SHOP_LABEL = "リンク先：楽天市場"

RE_MOSHIMO = re.compile(r"https?://[^\s\)\"'\]<>]*af\.moshimo\.com[^\s\)\"'\]<>]*")
RE_IMAGE_LINE = re.compile(r"\[!\[[^\]]*\]\(/images/([a-z0-9-]+)/products/(\d+)\.webp\)\]\(([^)]+)\)")
RE_IMAGE_REF = re.compile(r"/images/([a-z0-9-]+)/products/(\d+)\.webp")
RE_OLD_ORIGINAL = re.compile(r"^[a-z0-9-]+-\d+\.(?:jpe?g|png|gif|webp)$", re.IGNORECASE)


def load_build():
    path = os.path.join(SCRIPTS_DIR, "build-rakuten-affiliate-products.py")
    spec = importlib.util.spec_from_file_location("build_rakuten", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_text(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def moshimo_item(url):
    """もしものURLの url= にある楽天の商品URLを返す（無ければ None）。"""
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    values = qs.get("url")
    return values[0] if values else None


def strip_query(url):
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def post_slugs():
    return sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(POSTS_DIR, "*.md")))


def write_tsv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\t".join(header) + "\n")
        for row in rows:
            f.write("\t".join(str(c) for c in row) + "\n")


def read_tsv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


# --- inventory ---------------------------------------------------------------


RE_TEXT_LINK = re.compile(r"(?<!!)\[([^\[\]]+)\]\((https?://[^\s)]*af\.moshimo\.com[^\s)]*)\)")


def scan_posts():
    """記事×商品の一覧を返す: [(slug, item_url_raw, [連番...], 本文での商品名)]（記事内の出現順）。"""
    pairs = []
    for slug in post_slugs():
        text = read_text(os.path.join(POSTS_DIR, slug + ".md"))
        order = []
        seqs = {}
        names = {}
        for url in RE_MOSHIMO.findall(text):
            item = moshimo_item(url)
            if item is None:
                raise SystemExit("url= が無いもしものリンクがあります: %s %s" % (slug, url))
            if item not in seqs:
                order.append(item)
                seqs[item] = []
        for m in RE_TEXT_LINK.finditer(text):
            item = moshimo_item(m.group(2))
            name = re.sub(r"はこちら（楽天市場）$", "", m.group(1).strip())
            names.setdefault(item, name.replace("\t", " "))
        for line in text.splitlines():
            m = RE_IMAGE_LINE.fullmatch(line.strip())
            if m and "af.moshimo.com" in m.group(3):
                seqs[moshimo_item(m.group(3))].append(m.group(2))
        for item in order:
            pairs.append((slug, item, seqs[item], names.get(item, "")))
    return pairs


def cmd_inventory():
    pairs = scan_posts()
    os.makedirs(MIG_DIR, exist_ok=True)
    write_tsv(os.path.join(MIG_DIR, "inventory.tsv"), ["slug", "item_url_raw", "item_url", "image_seqs", "name"],
              [(s, raw, strip_query(raw), ",".join(seqs), name) for s, raw, seqs, name in pairs])
    items = []
    for _s, raw, _seqs, _n in pairs:
        u = strip_query(raw)
        if u not in items:
            items.append(u)
    batches = [items[i:i + BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)]
    for no, batch in enumerate(batches, start=1):
        path = os.path.join(MIG_DIR, "batch-%02d.json" % no)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                if json.load(f) != batch:
                    # Chromeの戻り値（freelink-NN.tsv）は束の並びに対応するため、取得後に束を変えない
                    raise SystemExit("既存の %s と内容が違います。取得をやり直す場合は束を移してから実行してください" % rel(path))
            continue
        with open(path, "w", encoding="utf-8") as f:
            json.dump(batch, f, ensure_ascii=False)
    articles = {p[0] for p in pairs}
    images = sum(len(p[2]) for p in pairs)
    queried = [(p[0], p[1]) for p in pairs if p[1] != strip_query(p[1])]
    print("記事 %d本 / 記事×商品 %d組 / 商品 %d件 / 画像の行 %d件（画像のある記事×商品 %d組）" % (
        len(articles), len(pairs), len(items), images, sum(1 for p in pairs if p[2])))
    print("クエリ付きの商品URL: %d組" % len(queried))
    for s, raw in queried:
        print("  %s  %s" % (s, raw))
    print("Chromeに渡す束: %d個（batch-01.json〜batch-%02d.json）" % (len(batches), len(batches)))
    print("在庫表: %s" % rel(os.path.join(MIG_DIR, "inventory.tsv")))
    return 0


# --- move-old ----------------------------------------------------------------


def cmd_move_old(args):
    dry_run = "--dry-run" in args
    targets = []
    for name in sorted(os.listdir(PRODUCT_IMAGES)):
        path = os.path.join(PRODUCT_IMAGES, name)
        if not os.path.isfile(path):
            continue
        if name.startswith("zz-rakuten-test-") or RE_OLD_ORIGINAL.match(name):
            targets.append(name)
    print("移す対象: %d件（旧原本 %d件・テスト用 %d件）" % (
        len(targets), sum(1 for n in targets if not n.startswith("zz-")), sum(1 for n in targets if n.startswith("zz-"))))
    if dry_run:
        for n in targets[:10]:
            print("  " + n)
        print("[dry-run] 移していません")
        return 0
    os.makedirs(DELETE_ME, exist_ok=True)
    for name in targets:
        dst = os.path.join(DELETE_ME, name)
        if os.path.exists(dst):
            print("NG  移し先に同名のファイルがあります: %s" % rel(dst))
            return 1
        shutil.move(os.path.join(PRODUCT_IMAGES, name), dst)
    print("移しました: %s（削除はオーナーが手で行う）" % rel(DELETE_ME))
    return 0


# --- prepare -----------------------------------------------------------------


def dhash(path):
    """白い余白を除いた中身の差分ハッシュ（dHash・64ビット）。

    旧画像（APIの画像を600×600へ拡大縮小して余白を付けたもの）と新画像（400×400の中央へ
    原寸で置いたもの）は余白の幅と縮尺が違うため、余白（明るさ245以上）を切り落としてから比べる。
    中身をグレースケールにして9×8へ縮め、横に隣り合う画素の明暗の大小で64ビットを作る。
    """
    gray = Image.open(path).convert("L")
    bbox = gray.point(lambda v: 255 if v < 245 else 0).getbbox()
    if bbox:
        gray = gray.crop(bbox)
    im = gray.resize((9, 8), Image.LANCZOS)
    px = list(im.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (1 if px[row * 9 + col] > px[row * 9 + col + 1] else 0)
    return bits


def read_compact(build, path):
    """Chromeの戻り値（短い形）を読み、rakuten-freelink-extract.js と同じ列の行に戻す。

    Chrome拡張は1回の出力が約1,000字で切れるため、取得結果（window上に保持）を短い形にして
    分けて読み出し、Writeツールで書き写す。短い形は1行「seq 商品パス リンクID 画像 経過秒 check」
    （空白区切り）で、1行目は「start=<最初の行の取得時刻>」。商品パスは https://item.rakuten.co.jp/ を、
    画像の「~」は /@0_mall/<店舗>/cabinet/ を省いたもの。ERROR行は「seq ERROR 理由」。
    元に戻した値で check 列を照合し、1行でも合わなければ止める（写し間違いの検出）。
    """
    from datetime import datetime, timedelta

    lines = [l for l in read_text(path).splitlines() if l.strip()]
    if not lines or not lines[0].startswith("start="):
        raise SystemExit("%s の1行目が start=... ではありません" % rel(path))
    start = datetime.strptime(lines[0][6:].strip(), "%Y-%m-%dT%H:%M:%S.%fZ")
    rows = []
    for raw in lines[1:]:
        cols = raw.split(" ")
        if len(cols) >= 2 and cols[1] == "ERROR":
            rows.append({"seq": cols[0], "item_url": "ERROR", "link_id": " ".join(cols[2:])})
            continue
        if len(cols) != 6:
            raise SystemExit("%s の行の形が違います: %s" % (rel(path), raw))
        seq, item, link_id, img, dt, check = cols
        shop = item.split("/")[0]
        image_path = "/@0_mall/%s/cabinet/%s" % (shop, img[1:]) if img.startswith("~") else img
        row = {
            "seq": seq,
            "item_url": "https://item.rakuten.co.jp/" + item,
            "link_id": link_id,
            "image_path": image_path,
            "created_at": (start + timedelta(seconds=int(dt))).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "item_name": "",
        }
        if build.row_check(row) != check:
            raise SystemExit("%s seq=%s の check 列が一致しません（写し間違いの可能性）" % (rel(path), seq))
        rows.append(row)
    return rows


def content_gray(path, size):
    gray = Image.open(path).convert("L")
    bbox = gray.point(lambda v: 255 if v < 245 else 0).getbbox()
    if bbox:
        gray = gray.crop(bbox)
    return list(gray.resize((size, size), Image.LANCZOS).getdata())


def mean_abs_diff(path_a, path_b):
    """白い余白を除いた中身を64×64のグレースケールにして、画素ごとの明るさの差の平均（0〜255）。

    dHash（9×8）は粗く、隅に小さな販促表示やクーポンの帯が足された程度では差が出ないことがあるため、
    細かい差を見る2つ目の指標として併用する。
    """
    a = content_gray(path_a, 64)
    b = content_gray(path_b, 64)
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def load_freelink(build):
    """{クエリなしの商品URL: 行(dict)} と、取得できなかった商品 {URL: 理由} を返す。"""
    found = {}
    failed = {}
    for batch_path in sorted(glob.glob(os.path.join(MIG_DIR, "batch-*.json"))):
        no = os.path.basename(batch_path)[6:8]
        with open(batch_path, encoding="utf-8") as f:
            batch = json.load(f)
        tsv_path = os.path.join(MIG_DIR, "freelink-%s.tsv" % no)
        if not os.path.isfile(tsv_path):
            raise SystemExit("Chromeの戻り値がありません: %s" % rel(tsv_path))
        rows = read_compact(build, tsv_path)  # check 列の照合もここで行う
        if len(rows) != len(batch):
            raise SystemExit("%s の行数（%d）が束の件数（%d）と違います" % (rel(tsv_path), len(rows), len(batch)))
        for row in rows:
            seq = int(row["seq"])
            url = batch[seq - 1]
            item_url = (row.get("item_url") or "").strip()
            if item_url == "ERROR":
                failed[url] = (row.get("link_id") or "").strip()
                continue
            if item_url != url:
                raise SystemExit("%s seq=%d の商品URLが束と違います: %s / %s" % (rel(tsv_path), seq, item_url, url))
            found[url] = row
    return found, failed


def read_text_only(path):
    result = {}
    if not path:
        return result
    for no, raw in enumerate(read_text(path).splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            raise SystemExit("--text-only の %d行目が「slug<TAB>連番<TAB>理由」の形ではありません" % no)
        result[(parts[0], parts[1])] = parts[2]
    return result


def cmd_prepare(args):
    text_only_path = None
    if args[:1] == ["--text-only"] and len(args) == 2:
        text_only_path = args[1]
    elif args:
        print(__doc__)
        return 1
    build = load_build()
    text_only = read_text_only(text_only_path)
    inventory = read_tsv(os.path.join(MIG_DIR, "inventory.tsv"))
    found, failed = load_freelink(build)
    os.makedirs(CANDIDATES, exist_ok=True)
    os.makedirs(RAW_CACHE, exist_ok=True)

    plan = []      # slug, item_url_raw, affiliate_url, mode, image_seqs, reason
    compare = []   # slug, seq, item_url, dhash_distance, query, needs_visual
    records = {}   # slug -> rows
    first = True
    image_errors = 0
    for row in inventory:
        slug, raw, url = row["slug"], row["item_url_raw"], row["item_url"]
        seqs = [s for s in row["image_seqs"].split(",") if s]
        if url in failed:
            # リンクも画像も取れない商品は、もしものリンクを残し、APIから取った画像だけを外して
            # 文字リンクにする（keep-text）。画像の無い商品はそのまま（keep）。
            plan.append((slug, raw, "", "keep-text" if seqs else "keep", ",".join(seqs),
                         "リンク作成ページで取得できない（%s）" % failed[url]))
            continue
        fr = found[url]
        link = build.build_link(fr["link_id"].strip(), url)
        image_path = fr["image_path"].strip()
        mode = "image" if seqs else "text"
        reason = ""
        if seqs and not build.RE_IMAGE_PATH.fullmatch(image_path):
            mode, reason = "text", "リンク作成ページに画像が無い（%s）" % image_path
        for seq in seqs:
            if (slug, seq) in text_only:
                mode, reason = "text", text_only[(slug, seq)]
        image_url = ""
        if mode == "image" or (seqs and (slug, seqs[0]) in text_only):
            # 文字リンクにする商品も、目視の記録として候補画像は作っておく（本文には使わない）
            ext = os.path.splitext(image_path)[1].lower() or ".jpg"
            cache = os.path.join(RAW_CACHE, hashlib.sha256(image_path.encode("utf-8")).hexdigest()[:16] + ext)
            if not os.path.isfile(cache):
                if not first:
                    time.sleep(build.WAIT_SECONDS)
                first = False
                err = build.download(build.image_url(image_path), cache)
                if err:
                    if os.path.exists(cache):
                        os.remove(cache)
                    mode, reason = "text", "画像を取得できない（%s）" % err
                    image_errors += 1
            if os.path.isfile(cache):
                for seq in seqs:
                    shutil.copyfile(cache, os.path.join(PRODUCT_IMAGES, "%s-%s%s" % (slug, seq, ext)))
                    os.makedirs(os.path.join(CANDIDATES, slug), exist_ok=True)
                    cand = os.path.join(CANDIDATES, slug, "%s.webp" % seq)
                    _size, err = build.to_webp(cache, cand)
                    if err:
                        mode, reason = "text", "画像を変換できない（%s）" % err
                        image_errors += 1
                        continue
                    current = os.path.join(PUBLIC_IMAGES, slug, "products", "%s.webp" % seq)
                    dist = bin(dhash(cand) ^ dhash(current)).count("1")
                    mad = mean_abs_diff(cand, current)
                    queried = raw != url
                    compare.append((slug, seq, url, dist, "%.1f" % mad, "query" if queried else "",
                                    "yes" if (dist > DHASH_THRESHOLD or mad > MAD_THRESHOLD or queried) else ""))
                if mode == "image":
                    image_url = build.image_url(image_path)
        plan.append((slug, raw, link, mode, ",".join(seqs), reason))
        record_seqs = seqs if mode == "image" else ["-"]
        for seq in record_seqs:
            records.setdefault(slug, []).append(
                (seq, url, link, image_url if mode == "image" else "", fr["created_at"].strip(),
                 fr["item_name"].strip() or row.get("name", "")))

    write_tsv(os.path.join(MIG_DIR, "plan.tsv"),
              ["slug", "item_url_raw", "affiliate_url", "mode", "image_seqs", "reason"], plan)
    write_tsv(os.path.join(MIG_DIR, "compare.tsv"),
              ["slug", "seq", "item_url", "dhash_distance", "mad", "query", "needs_visual"], compare)
    for slug, rows in records.items():
        write_tsv(os.path.join(PRODUCT_IMAGES, "%s-rakuten-links.tsv" % slug),
                  ["seq", "item_url", "affiliate_url", "image_url", "created_at", "item_name"], rows)

    dists = sorted(c[3] for c in compare)
    modes = {}
    for p in plan:
        modes[p[3]] = modes.get(p[3], 0) + 1
    print("移行計画: %s" % rel(os.path.join(MIG_DIR, "plan.tsv")))
    print("  記事×商品 %d組（画像あり image %d / 文字リンク text %d / 取得できず keep %d・keep-text %d）" % (
        len(plan), modes.get("image", 0), modes.get("text", 0), modes.get("keep", 0), modes.get("keep-text", 0)))
    print("  取得できなかった商品: %d件" % len(failed))
    for url, why in failed.items():
        print("    %s（%s）" % (url, why))
    print("比較: %s（%d件・dHash閾値 %d・平均差の閾値 %.1f）" % (
        rel(os.path.join(MIG_DIR, "compare.tsv")), len(compare), DHASH_THRESHOLD, MAD_THRESHOLD))
    if dists:
        print("  dHashの分布: 最小 %d / 中央 %d / 最大 %d / 閾値以下 %d件 / 閾値超 %d件" % (
            dists[0], dists[len(dists) // 2], dists[-1],
            sum(1 for d in dists if d <= DHASH_THRESHOLD), sum(1 for d in dists if d > DHASH_THRESHOLD)))
        mads = sorted(float(c[4]) for c in compare)
        print("  平均差の分布: 最小 %.1f / 中央 %.1f / 90%%点 %.1f / 最大 %.1f / 閾値超 %d件" % (
            mads[0], mads[len(mads) // 2], mads[int(len(mads) * 0.9)], mads[-1], sum(1 for m in mads if m > MAD_THRESHOLD)))
    print("  目視が要る画像（どちらかの閾値超、またはクエリ付き）: %d件" % sum(1 for c in compare if c[6]))
    text_rows = [p for p in plan if p[3] in ("text", "keep-text") and p[4]]
    print("  画像の行を消して文字リンクにする記事×商品: %d組" % len(text_rows))
    for p in text_rows:
        print("    %s 連番%s: %s" % (p[0], p[4], p[5]))
    print("取得記録: output/product-images/<slug>-rakuten-links.tsv（%d記事）" % len(records))
    return 1 if image_errors else 0


# --- contact-sheet -----------------------------------------------------------


def cmd_contact_sheet(args):
    """目視が要る画像（compare.tsv の needs_visual=yes、または --all で全件）を、
    今の画像（左）とリンク作成ページの画像（右）を並べた一覧画像にする（_migration/sheets/）。
    --extra <slug:連番,...> で目視対象を足せる（クエリ付き商品・過去に販促の指摘があった商品など）。
    """
    from PIL import ImageDraw

    show_all = "--all" in args
    extra = set()
    if "--extra" in args:
        i = args.index("--extra")
        for token in args[i + 1].split(","):
            slug, seq = token.split(":")
            extra.add((slug, seq))
    rows = read_tsv(os.path.join(MIG_DIR, "compare.tsv"))
    if "--grid" in args:
        # 閾値以内（目視の対象外）の残りを、差し替え候補の画像だけ4×4で並べる。
        # 粗いハッシュでは隅の小さな販促表示・クーポンの日付の変化を見落とすことがあるため（2026-10-03実測）
        rest = [r for r in rows if not r["needs_visual"] and (r["slug"], r["seq"]) not in extra]
        out_dir = os.path.join(MIG_DIR, "grids")
        os.makedirs(out_dir, exist_ok=True)
        for old in glob.glob(os.path.join(out_dir, "*.png")):
            os.remove(old)
        cell, cols, per = 250, 4, 16
        for n in range(0, len(rest), per):
            chunk = rest[n:n + per]
            sheet = Image.new("RGB", (cols * (cell + 10), ((len(chunk) + cols - 1) // cols) * (cell + 24)), (230, 230, 230))
            draw = ImageDraw.Draw(sheet)
            for k, r in enumerate(chunk):
                x, y = (k % cols) * (cell + 10), (k // cols) * (cell + 24)
                img = Image.open(os.path.join(CANDIDATES, r["slug"], r["seq"] + ".webp")).convert("RGB")
                sheet.paste(img.resize((cell, cell)), (x, y + 22))
                draw.text((x + 2, y + 6), "%d) %s/%s" % (n + k + 1, r["slug"][:36], r["seq"]), fill=(0, 0, 0))
            sheet.save(os.path.join(out_dir, "grid-%02d.png" % (n // per + 1)))
        print("閾値以内の残り %d件 → %s（差し替え候補の画像のみ）" % (len(rest), rel(out_dir)))
        for i, r in enumerate(rest, start=1):
            print("  %d) %s 連番%s %s" % (i, r["slug"], r["seq"], r["item_url"]))
        return 0
    targets = [r for r in rows if show_all or r["needs_visual"] or (r["slug"], r["seq"]) in extra]
    out_dir = os.path.join(MIG_DIR, "sheets")
    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, "*.png")):
        os.remove(old)
    cell, per_sheet, cols = 260, 6, 2
    for n in range(0, len(targets), per_sheet):
        chunk = targets[n:n + per_sheet]
        rows_n = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * (cell * 2 + 30), rows_n * (cell + 40)), (230, 230, 230))
        draw = ImageDraw.Draw(sheet)
        for k, r in enumerate(chunk):
            x = (k % cols) * (cell * 2 + 30)
            y = (k // cols) * (cell + 40)
            old_img = Image.open(os.path.join(PUBLIC_IMAGES, r["slug"], "products", r["seq"] + ".webp")).convert("RGB")
            new_img = Image.open(os.path.join(CANDIDATES, r["slug"], r["seq"] + ".webp")).convert("RGB")
            sheet.paste(old_img.resize((cell, cell)), (x, y + 30))
            sheet.paste(new_img.resize((cell, cell)), (x + cell + 10, y + 30))
            label = "%d) %s/%s d=%s m=%s %s" % (n + k + 1, r["slug"][:34], r["seq"], r["dhash_distance"], r["mad"], r["query"])
            draw.text((x + 4, y + 8), label, fill=(0, 0, 0))
        path = os.path.join(out_dir, "sheet-%02d.png" % (n // per_sheet + 1))
        sheet.save(path)
    print("目視対象 %d件 → %s（左=今の画像・右=リンク作成ページの画像）" % (len(targets), rel(out_dir)))
    for i, r in enumerate(targets, start=1):
        print("  %d) %s 連番%s d=%s m=%s %s %s" % (i, r["slug"], r["seq"], r["dhash_distance"], r["mad"], r["query"], r["item_url"]))
    return 0


# --- link-health -------------------------------------------------------------

LINK_HEALTH = os.path.join(ROOT, "data", "link-health.md")
RE_LH_CODE = re.compile(r"／([A-Za-z0-9_.-]+)・([^）]+)）\s*$")


def cmd_link_health(args):
    """data/link-health.md の画像列を、移行後の実際の画像の有無に合わせる（列の形式・行数は変えない）。

    台帳の行と記事×商品の対応は、商品名列の末尾「（販売店名／店舗コード・商品コード）」と商品URLの
    店舗コード・商品コードの一致で取る。取れない行は、同じ記事の「リンク箇所」の番号（N.）と
    記事内の商品の出現順で取る。画像の有無は公開済み記事の本文の画像の行（/images/<slug>/products/N.webp）
    で判定する。--write を付けたときだけ画像列を書き換える。
    """
    write = args == ["--write"]
    if args and not write:
        print(__doc__)
        return 1
    # 移行後の本文から、記事ごとの商品の並び（商品URL・画像の有無）を取る
    rakuten_item = re.compile(r"https://hb\.afl\.rakuten\.co\.jp/ichiba/[^/]+/\?pc=([^&\s)]+)")
    articles = {}
    for slug in post_slugs():
        text = read_text(os.path.join(POSTS_DIR, slug + ".md"))
        order = []
        with_image = set()
        for line in text.splitlines():
            urls = [urllib.parse.unquote(m.group(1)) for m in rakuten_item.finditer(line)]
            urls += [strip_query(moshimo_item(u) or "") for u in RE_MOSHIMO.findall(line)]
            for u in urls:
                if u and u not in order:
                    order.append(u)
            m = RE_IMAGE_LINE.fullmatch(line.strip())
            if m and urls:
                with_image.add(urls[0])
        articles[slug] = (order, with_image)

    lines = read_text(LINK_HEALTH).split("\n")
    header = None
    ledger = {}  # slug -> [(行番号, 商品名, リンク箇所, 画像)]
    for i, line in enumerate(lines):
        if line.startswith("## "):
            if header is not None:
                break
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            if "画像" in cells and "記事slug" in cells:
                header = cells
            continue
        if set("".join(cells)) <= set("-"):
            continue
        ledger.setdefault(cells[header.index("記事slug")], []).append(
            (i, cells[header.index("商品名")], cells[header.index("リンク箇所")], cells[header.index("画像")]))

    rows = sum(len(v) for v in ledger.values())
    fixes = []
    count_diff = []    # (slug, 台帳の行数, 記事の商品数)
    unmatched = []     # 対応が取れない台帳の行
    sequential = 0
    for slug in sorted(set(ledger) | set(articles)):
        order, with_image = articles.get(slug, ([], set()))
        entries = ledger.get(slug, [])
        if len(entries) != len(order):
            count_diff.append((slug, len(entries), len(order)))
        assigned = {}
        # 1) 商品名列の店舗コード・商品コード 2) リンク箇所の番号 で対応を取る
        for entry in entries:
            i, name, place, _image = entry
            m = RE_LH_CODE.search(name)
            if m:
                shop, code = m.group(1).lower(), m.group(2).strip().lower()
                for u in order:
                    parts = urllib.parse.urlsplit(u).path.strip("/").split("/")
                    if len(parts) >= 2 and parts[0].lower() == shop and parts[1].lower() == code and u not in assigned.values():
                        assigned[i] = u
                        break
            if i not in assigned:
                n = re.match(r"(\d+)\.", place)
                if n and 1 <= int(n.group(1)) <= len(order) and order[int(n.group(1)) - 1] not in assigned.values():
                    assigned[i] = order[int(n.group(1)) - 1]
        # 3) 残りは、台帳の並びと記事内の出現順で対応させる（件数が一致する記事だけ）
        rest_entries = [e for e in entries if e[0] not in assigned]
        rest_items = [u for u in order if u not in assigned.values()]
        if rest_entries and len(rest_entries) == len(rest_items):
            for e, u in zip(rest_entries, rest_items):
                assigned[e[0]] = u
                sequential += 1
        for i, name, place, image in entries:
            if i not in assigned:
                unmatched.append("%d行目 %s ｜%s ｜画像 %s" % (i + 1, slug, place, image))
                continue
            want = "済" if assigned[i] in with_image else "-"
            if image != want:
                fixes.append((i, slug, place, image, want))
    print("台帳 %d行 / 記事×商品 %d組（うち並び順で対応させた行 %d）" % (
        rows, sum(len(o) for o, _w in articles.values()), sequential))
    print("台帳の行数と記事の商品数が違う記事: %d本" % len(count_diff))
    for slug, a, b in count_diff:
        print("  %s  台帳 %d行 / 記事 %d組" % (slug, a, b))
    print("対応が取れない台帳の行: %d行" % len(unmatched))
    for r in unmatched:
        print("  " + r)
    print("画像列の食い違い: %d行" % len(fixes))
    for i, slug, place, old, new in fixes:
        print("  %d行目 %s ｜%s ｜%s → %s" % (i + 1, slug, place, old, new))
    if write and fixes:
        idx = header.index("画像")
        for i, *_rest, new in fixes:
            cells = lines[i].strip().strip("|").split("|")
            cells[idx] = " %s " % new
            lines[i] = "|" + "|".join(cells) + "|"
        with open(LINK_HEALTH, "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(lines))
        print("画像列を %d行 書き換えました" % len(fixes))
    return 0


# --- check-records -----------------------------------------------------------


def cmd_check_records():
    missing = []
    total = 0
    for slug in post_slugs():
        refs = sorted(set(m.group(2) for m in RE_IMAGE_REF.finditer(read_text(os.path.join(POSTS_DIR, slug + ".md")))
                          if m.group(1) == slug), key=int)
        if not refs:
            continue
        path = os.path.join(PRODUCT_IMAGES, "%s-rakuten-links.tsv" % slug)
        have = set()
        if os.path.isfile(path):
            have = {r["seq"] for r in read_tsv(path) if (r.get("image_url") or "").strip()}
        for seq in refs:
            total += 1
            if seq not in have:
                missing.append("%s/products/%s.webp" % (slug, seq))
    print("記事が参照する商品画像 %d件 / 取得記録の無い画像 %d件" % (total, len(missing)))
    for m in missing:
        print("  " + m)
    return 1 if missing else 0


# --- verify-live -------------------------------------------------------------


def fetch(url):
    req = urllib.request.Request(url + ("&" if "?" in url else "?") + "t=%d" % time.time(),
                                 headers={"User-Agent": "Mozilla/5.0 (compatible; kohaku-jikan-verify/1.0)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        return str(e), b""


def expected_cards(text):
    """本文の「★で始まり商品リンクを含む行」の数（rehype が作るカードの数）。"""
    return sum(1 for line in text.splitlines()
               if line.startswith("★") and ("hb.afl.rakuten.co.jp" in line or "af.moshimo.com" in line))


def cmd_verify_live():
    problems = []
    totals = {"articles": 0, "cards": 0, "labels": 0, "credits": 0, "images": 0}
    for slug in post_slugs():
        text = read_text(os.path.join(POSTS_DIR, slug + ".md"))
        status, body = fetch("%s/posts/%s/" % (LIVE_BASE, slug))
        time.sleep(LIVE_WAIT)
        if status != 200:
            problems.append("%s: 記事ページが %s" % (slug, status))
            continue
        html = body.decode("utf-8", errors="replace")
        cards = len(re.findall(r'class="product-card"', html))
        labels = html.count(SHOP_LABEL)
        credits = html.count(CREDIT_TEXT)
        moshimo = html.count("af.moshimo.com")
        want = expected_cards(text)
        totals["articles"] += 1
        totals["cards"] += cards
        totals["labels"] += labels
        totals["credits"] += credits
        if cards != want or labels != cards or credits != 1:
            problems.append("%s: カード %d（本文の★行 %d）・表記 %d・クレジット %d" % (slug, cards, want, labels, credits))
        if moshimo and "af.moshimo.com" not in text:
            problems.append("%s: 本文に無いもしものリンクが本番に %d件" % (slug, moshimo))
        for seq in sorted(set(m.group(2) for m in RE_IMAGE_REF.finditer(text) if m.group(1) == slug), key=int):
            path = "/images/%s/products/%s.webp" % (slug, seq)
            st, data = fetch(LIVE_BASE + path)
            time.sleep(LIVE_WAIT)
            totals["images"] += 1
            local = os.path.join(PUBLIC_IMAGES, slug, "products", "%s.webp" % seq)
            if st != 200:
                problems.append("%s: %s" % (path, st))
            elif hashlib.sha256(data).hexdigest() != hashlib.sha256(open(local, "rb").read()).hexdigest():
                problems.append("%s: 本番の中身が手元のファイルと違う（未デプロイ）" % path)
    print("本番の記事 %d本 / 商品カード %d / 「%s」%d / クレジット %d / 商品画像 %d件" % (
        totals["articles"], totals["cards"], SHOP_LABEL, totals["labels"], totals["credits"], totals["images"]))
    print("問題: %d件" % len(problems))
    for p in problems:
        print("  " + p)
    return 1 if problems else 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cmd, rest = args[0], args[1:]
    if cmd == "inventory" and not rest:
        return cmd_inventory()
    if cmd == "move-old":
        return cmd_move_old(rest)
    if cmd == "prepare":
        return cmd_prepare(rest)
    if cmd == "contact-sheet":
        return cmd_contact_sheet(rest)
    if cmd == "link-health":
        return cmd_link_health(rest)
    if cmd == "verify-freelink" and not rest:
        # 書き写したChromeの戻り値（freelink-NN.tsv）だけを先に照合する（prepare の前の確認用）
        build = load_build()
        for path in sorted(glob.glob(os.path.join(MIG_DIR, "freelink-*.tsv"))):
            rows = read_compact(build, path)
            print("OK  %s（%d行・ERROR %d行）" % (rel(path), len(rows), sum(1 for r in rows if r["item_url"] == "ERROR")))
        return 0
    if cmd == "check-records" and not rest:
        return cmd_check_records()
    if cmd == "verify-live" and not rest:
        return cmd_verify_live()
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
