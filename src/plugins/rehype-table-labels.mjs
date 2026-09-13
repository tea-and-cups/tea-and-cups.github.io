// Adds accessible table semantics and a local scroll region without touching Markdown.
function textOf(node) {
  if (node.type === 'text') return node.value;
  return Array.isArray(node.children) ? node.children.map(textOf).join('') : '';
}
const childrenOf = (node, tag) => (node.children ?? []).filter((c) => c.type === 'element' && c.tagName === tag);

function prepare(table, index) {
  const thead = childrenOf(table, 'thead')[0];
  const headerRow = thead && childrenOf(thead, 'tr')[0];
  if (!headerRow) return;
  const headers = childrenOf(headerRow, 'th');
  const labels = headers.map(textOf);
  headers.forEach((cell) => { cell.properties = { ...(cell.properties ?? {}), scope: 'col' }; });
  if (!childrenOf(table, 'caption').length) {
    table.children.unshift({ type: 'element', tagName: 'caption', properties: {}, children: [{ type: 'text', value: `記事内の比較表 ${index + 1}` }] });
  }
  const tbody = childrenOf(table, 'tbody')[0];
  for (const row of tbody ? childrenOf(tbody, 'tr') : []) {
    const cells = childrenOf(row, 'td');
    cells.forEach((cell, i) => { cell.properties = { ...(cell.properties ?? {}), dataLabel: labels[i] ?? '' }; });
    if (cells[0]) { cells[0].tagName = 'th'; cells[0].properties.scope = 'row'; }
  }
}

export default function rehypeTableLabels() {
  return (tree) => {
    let tableIndex = 0;
    const visit = (node) => {
      if (!Array.isArray(node.children)) return;
      const out = [];
      for (const child of node.children) {
        if (child.type === 'element' && child.tagName === 'table') {
          prepare(child, tableIndex);
          out.push({ type: 'element', tagName: 'div', properties: { className: ['table-scroll'], tabindex: 0, role: 'region', ariaLabel: `比較表 ${tableIndex + 1}。横にスクロールできます` }, children: [
            { type: 'element', tagName: 'p', properties: { className: ['table-hint'] }, children: [{ type: 'text', value: '表は横にスクロールできます' }] },
            child,
          ] });
          tableIndex += 1;
        } else { visit(child); out.push(child); }
      }
      node.children = out;
    };
    visit(tree);
  };
}
