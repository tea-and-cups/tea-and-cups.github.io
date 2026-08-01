// スマホ幅で表を「1行=1カード」に組み替えるためのラベルを各セルに付与する。
// CSS(::before{content:attr(data-label)})でPC/スマホの表示切替を行うための下ごしらえで、
// 実際の見た目の切り替えはBaseLayout.astroのメディアクエリ（CSSのみ）が行う。
// 記事Markdown側には一切書き込まない（CLAUDE.md 9-2規約4「純Markdownのみ」を守るため）。

function textOf(node) {
  if (node.type === 'text') return node.value;
  if (!Array.isArray(node.children)) return '';
  return node.children.map(textOf).join('');
}

function walk(node, fn) {
  fn(node);
  if (Array.isArray(node.children)) {
    for (const child of node.children) walk(child, fn);
  }
}

function childrenOfTag(node, tagName) {
  return (node.children ?? []).filter((c) => c.type === 'element' && c.tagName === tagName);
}

export default function rehypeTableLabels() {
  return (tree) => {
    walk(tree, (node) => {
      if (node.type !== 'element' || node.tagName !== 'table') return;

      const thead = childrenOfTag(node, 'thead')[0];
      const headerRow = thead ? childrenOfTag(thead, 'tr')[0] : null;
      if (!headerRow) return;
      const labels = childrenOfTag(headerRow, 'th').map(textOf);
      if (labels.length === 0) return;

      const tbody = childrenOfTag(node, 'tbody')[0];
      for (const row of tbody ? childrenOfTag(tbody, 'tr') : []) {
        const cells = childrenOfTag(row, 'td');
        cells.forEach((cell, i) => {
          if (i >= labels.length) return;
          cell.properties = cell.properties || {};
          cell.properties.dataLabel = labels[i];
        });
      }
    });
  };
}
