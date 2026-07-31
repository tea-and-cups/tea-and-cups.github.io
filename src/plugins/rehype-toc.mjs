// 記事本文のH2から目次（<details>）を自動生成し、本文の先頭に差し込む。
// 記事Markdown側には一切書き込まない（CLAUDE.md 9-2規約4「純Markdownのみ」を守るため）。
//
// 前提: astro.config.mjs で rehypeHeadingIds をこのプラグインより前に置くこと。
//   見出しIDの生成規則はAstro標準（github-slugger）のままで、既存アンカーは変わらない。
//   rehypeHeadingIds は id が既にある見出しには触らないため、Astro内部での再実行と二重にならない。
//
// 差し込み位置: アフィリエイト表記の段落の直後（表記が無い記事では本文の先頭）。

const MIN_HEADINGS = 3; // 見出し2つ以下の記事では目次を出さない
const NOTICE_PREFIX = '※当サイトはアフィリエイト';

function textOf(node) {
  if (node.type === 'text') return node.value;
  if (!Array.isArray(node.children)) return '';
  return node.children.map(textOf).join('');
}

const el = (tagName, properties, children) => ({
  type: 'element',
  tagName,
  properties,
  children,
});

export default function rehypeToc() {
  return (tree) => {
    const body = tree.children;
    const headings = body.filter(
      (n) =>
        n.type === 'element' &&
        n.tagName === 'h2' &&
        typeof n.properties?.id === 'string'
    );
    if (headings.length < MIN_HEADINGS) return;

    const toc = el('details', { className: ['toc'] }, [
      el('summary', {}, [{ type: 'text', value: '目次' }]),
      el(
        'ul',
        {},
        headings.map((h) =>
          el('li', {}, [
            el('a', { href: `#${h.properties.id}` }, [
              { type: 'text', value: textOf(h) },
            ]),
          ])
        )
      ),
    ]);

    const noticeIndex = body.findIndex(
      (n) =>
        n.type === 'element' &&
        n.tagName === 'p' &&
        textOf(n).trimStart().startsWith(NOTICE_PREFIX)
    );
    body.splice(noticeIndex >= 0 ? noticeIndex + 1 : 0, 0, toc);
  };
}
