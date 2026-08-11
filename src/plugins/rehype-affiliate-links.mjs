// アフィリエイトリンクに rel="sponsored noopener" と target="_blank" を自動付与する。
// 目的:
//   1. Googleのリンクスパム対策ガイドライン（有料・アフィリエイトリンクは rel="sponsored"）への準拠
//   2. 別タブで開くことで、商品ページを見た読者が記事に戻れる（比較検討中の離脱防止）
// 可搬性規約（CLAUDE.md 9-2）を守るため、Markdown本文はURL直書きのまま一切変更しない。
// 外部依存を増やさないよう、unist-util-visit は使わず自前で走査する。

const AFFILIATE_HOSTS = [
  'af.moshimo.com',
  'afr.moshimo.com',
  'hb.afl.rakuten.co.jp',
  'item.rakuten.co.jp',
];

function hostOf(href) {
  try {
    return new URL(href).hostname.toLowerCase();
  } catch {
    return null;
  }
}

function walk(node, fn) {
  fn(node);
  if (Array.isArray(node.children)) {
    for (const child of node.children) walk(child, fn);
  }
}

export default function rehypeAffiliateLinks() {
  return (tree) => {
    walk(tree, (node) => {
      if (node.type !== 'element' || node.tagName !== 'a') return;
      const href = node.properties?.href;
      if (typeof href !== 'string') return;

      const host = hostOf(href);
      if (!host) return; // 内部リンク（/posts/... 等）は対象外

      const isAffiliate = AFFILIATE_HOSTS.some(
        (h) => host === h || host.endsWith('.' + h)
      );

      node.properties.rel = isAffiliate
        ? ['sponsored', 'noopener']
        : ['noopener'];
      if (isAffiliate) node.properties.target = '_blank';
    });
  };
}
