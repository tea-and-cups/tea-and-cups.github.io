// 楽天アフィリエイトの「リンク作成ページ」（/freelink?u=<商品URL>）から、
// 商品リンクの組み立てに要る値と画像のパスを取り出す（D-0260）。
//
// 使い方（Claude in Chrome・楽天アフィリエイトにログインしたタブで実行する）:
//   1. Chromeのタブで https://affiliate.rakuten.co.jp/ を開く（ログイン済みであること）
//   2. このファイルの中身をそのまま javascript_tool に渡し、末尾の1行
//        await kohakuFreelink([...商品URL...])
//      の配列だけを、今回の商品URL（item.rakuten.co.jp の商品ページURL）に差し替えて実行する
//   3. 戻り値のTSV（1行目は見出し）を、output/product-images/<slug>-freelink.tsv に
//      Writeツールでそのまま保存する
//   4. python site/scripts/build-rakuten-affiliate-products.py <slug> output/product-images/<slug>-freelink.tsv
//
// 出力にクエリ文字列（?・&・=を含むURL）を入れない。Chrome拡張はクエリ文字列を含む出力を
// 伏せるため、リンクは「リンクID（パスの一部）」、画像は「パス」だけを返し、
// クエリ（pc・link_type・ut、画像の _ex）は Python 側で組み立てる。
// 連続取得は1件ごとに1.2秒の間隔を空ける（1秒以上・D-0260）。
//
// check 列は「seq・item_url・link_id・image_path をタブでつないだ文字列」のSHA-256先頭12桁。
// 戻り値をWriteツールで書き写す際の写し間違いを、Python側（build-rakuten-affiliate-products.py）が
// 同じ計算で照合して検出する（D-0261）。

async function kohakuFreelink(urls) {
  const WAIT_MS = 1200;
  const rows = [['seq', 'item_url', 'link_id', 'image_path', 'created_at', 'item_name', 'check'].join('\t')];
  const clean = (s) => String(s ?? '').replace(/[\t\r\n]+/g, ' ').trim();
  const check = async (fields) => {
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(fields.join('\t')));
    return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, 12);
  };
  for (let i = 0; i < urls.length; i++) {
    if (i > 0) await new Promise((r) => setTimeout(r, WAIT_MS));
    const seq = i + 1;
    let res;
    try {
      res = await fetch('/freelink?u=' + encodeURIComponent(urls[i]), { credentials: 'include' });
    } catch (e) {
      rows.push([seq, 'ERROR', 'fetch_failed', '', '', ''].join('\t'));
      continue;
    }
    if (/\/error\/item_down/.test(res.url)) {
      // 「こちらの商品は削除されたか、ページが移動された可能性があります」のエラーページ（2026-10-03実測）
      rows.push([seq, 'ERROR', 'item_down(商品が削除・移動された)', '', '', ''].join('\t'));
      continue;
    }
    const html = await res.text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const view = doc.querySelector('item-view');
    if (!view) {
      rows.push([seq, 'ERROR', 'no_item_view(未ログインか商品URLが不正)', '', '', ''].join('\t'));
      continue;
    }
    let data;
    try {
      data = JSON.parse(view.getAttribute(':data'));
    } catch (e) {
      rows.push([seq, 'ERROR', 'json_parse_failed', '', '', ''].join('\t'));
      continue;
    }
    const item = data.item_data || {};
    const info = item.link_info || {};
    const link = String(item.hybrid_link || '');
    const id = (link.match(/^https:\/\/hb\.afl\.rakuten\.co\.jp\/ichiba\/([0-9a-f]{8}(?:\.[0-9a-f]{8}){3})\//) || [])[1];
    const pc = (link.match(/[?&]pc=([^&]+)/) || [])[1];
    const img = String(info.image_url || '');
    const imgPath = img.startsWith('https://thumbnail.image.rakuten.co.jp/') ? img.slice('https://thumbnail.image.rakuten.co.jp'.length).split('?')[0] : '';
    if (item.status !== 'success' || !id || !pc) {
      rows.push([seq, 'ERROR', 'link_not_found(status=' + clean(item.status) + ')', '', '', ''].join('\t'));
      continue;
    }
    const itemUrl = decodeURIComponent(pc);
    if (/[?#]/.test(itemUrl)) {
      // クエリ付きの商品URLは出力が伏せられるうえ、Python側で元の形に戻せないため扱わない
      rows.push([seq, 'ERROR', 'item_url_has_query(クエリなしの商品URLで作り直す)', '', '', ''].join('\t'));
      continue;
    }
    const fields = [String(seq), clean(itemUrl), id, imgPath || 'NO_IMAGE'];
    rows.push([
      ...fields,
      new Date().toISOString(),
      clean(info.item_name),
      await check(fields),
    ].join('\t'));
  }
  return rows.join('\n');
}

await kohakuFreelink(['https://item.rakuten.co.jp/SHOP/ITEM/']);
