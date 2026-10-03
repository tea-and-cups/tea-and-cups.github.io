"""【廃止（D-0260）】商品画像URL（楽天商品検索APIのmediumImageUrls）をWebPに変換する旧経路。

楽天ウェブサービス規約 第10条(9)により、APIから取った画像は保存できない。
新規記事の商品画像は、楽天アフィリエイトのリンク作成ページの画像（400x400）を使う。

代わりの手順（rules/product-linking.md 2節・3節）:
  1. Claude in Chrome で site/scripts/rakuten-freelink-extract.js を実行し、TSVを保存する
  2. python site/scripts/build-rakuten-affiliate-products.py <slug> <freelink.tsv>

このスクリプトは実行しても何もせず、終了コード1で終わる。
"""

import sys


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("product-image-to-webp.py は廃止しました（D-0260）。APIの画像URLを保存する使い方はできません。")
    print("代わりに rakuten-freelink-extract.js（Chrome）→ "
          "python site/scripts/build-rakuten-affiliate-products.py <slug> <freelink.tsv> を使ってください"
          "（rules/product-linking.md 2節・3節）。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
