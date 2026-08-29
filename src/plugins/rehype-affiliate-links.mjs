// アフィリエイトリンクに rel="sponsored noopener" と target="_blank" を自動付与し、
// 続けて商品ブロック（画像段落＋★段落、または★段落単独）を <div class="product-card"> で包む。
// 目的:
//   1. Googleのリンクスパム対策ガイドライン（有料・アフィリエイトリンクは rel="sponsored"）への準拠
//   2. 別タブで開くことで、商品ページを見た読者が記事に戻れる（比較検討中の離脱防止）
//   3. 画像の有無に関わらず商品ブロックをカード化する（CSSの :has() 依存をやめる）
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

// ---- ここから商品ブロックのカード化 ----------------------------------------

function isWhitespace(node) {
  return (
    node &&
    (node.type === 'text' || node.type === 'raw') &&
    typeof node.value === 'string' &&
    node.value.trim() === ''
  );
}

// 空白テキストノードを除いた子（コメントも落とす）
function contentChildren(node) {
  if (!node || !Array.isArray(node.children)) return [];
  return node.children.filter((c) => !isWhitespace(c) && c.type !== 'comment');
}

function isSponsoredAnchor(node) {
  if (!node || node.type !== 'element' || node.tagName !== 'a') return false;
  const rel = node.properties?.rel;
  const list = Array.isArray(rel)
    ? rel
    : typeof rel === 'string'
      ? rel.split(/\s+/)
      : [];
  return list.includes('sponsored');
}

function hasSponsoredAnchor(node) {
  let found = false;
  walk(node, (n) => {
    if (isSponsoredAnchor(n)) found = true;
  });
  return found;
}

// 段落内のテキストを連結する。<img> の alt は属性でありテキストノードではないため、
// 画像リンクを含む段落でも alt の文言は混ざらない。
function textContentOf(node) {
  let text = '';
  walk(node, (n) => {
    if (n.type === 'text' && typeof n.value === 'string') text += n.value;
  });
  return text;
}

// 「★で始まる段落」= 段落のテキスト全体の先頭（前後の空白を除く）が★。
// 画像リンクと★行が空行なしで1段落にまとまっている記事（記事側の書き方のばらつき）も
// この判定なら拾える。地の文の中にリンクがあるだけの段落は★で始まらないので対象外。
function isStarParagraph(node) {
  if (!node || node.type !== 'element' || node.tagName !== 'p') return false;
  return textContentOf(node).trim().startsWith('★');
}

// 「画像だけの商品段落」= sponsoredなaを1つだけ持ち、そのaの中身が<img>だけ。
function isProductImageParagraph(node) {
  if (!node || node.type !== 'element' || node.tagName !== 'p') return false;
  const kids = contentChildren(node);
  if (kids.length !== 1) return false;
  const a = kids[0];
  if (!isSponsoredAnchor(a)) return false;
  const inner = contentChildren(a);
  return inner.length === 1 && inner[0].type === 'element' && inner[0].tagName === 'img';
}

function addClass(node, name) {
  const cur = node.properties?.className;
  const list = Array.isArray(cur)
    ? cur
    : typeof cur === 'string'
      ? cur.split(/\s+/)
      : [];
  node.properties = node.properties ?? {};
  node.properties.className = [...list.filter(Boolean), name];
}

// 記事本文直下（rootの子）の段落だけを見る。<li> や <blockquote> の中には降りない。
function wrapProductCards(tree) {
  if (!Array.isArray(tree.children)) return;
  const out = [];
  for (const node of tree.children) {
    if (!isStarParagraph(node) || !hasSponsoredAnchor(node)) {
      out.push(node);
      continue;
    }
    addClass(node, 'product-card__meta');

    // 直前の兄弟（段落間の改行テキストは読み飛ばす）が画像段落なら、同じカードに含める
    const spacer = [];
    while (out.length && isWhitespace(out[out.length - 1])) spacer.unshift(out.pop());
    const prev = out[out.length - 1];
    let cardChildren;
    if (isProductImageParagraph(prev)) {
      out.pop();
      addClass(prev, 'product-card__image');
      cardChildren = [prev, ...spacer, node];
    } else {
      out.push(...spacer);
      cardChildren = [node];
    }

    out.push({
      type: 'element',
      tagName: 'div',
      properties: { className: ['product-card'] },
      children: cardChildren,
    });
  }
  tree.children = out;
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

    // rel付与の後段で実行する（sponsoredの有無でカード対象を判定するため）
    wrapProductCards(tree);
  };
}
