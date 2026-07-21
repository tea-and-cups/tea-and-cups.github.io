# 紅茶とティーカップのメディア（サイトリポジトリ）

Astro製の静的サイト。main へ push すると GitHub Actions が自動でビルド・公開する。

## 公開の手順（オーナーのみが行う）
1. `src/content/posts/` の記事の frontmatter `status: draft` を `published` に変える（＝公開承認の記録）
2. `date` / `updated` を公開日に合わせる
3. commit して main へ push → 数分で公開される

## 記事の規約（可搬性のため厳守）
- frontmatter は8項目のみ: `title / slug / date / updated / description / tags / hero / status`
- URL は `/posts/{slug}/`。**slug は公開後変更禁止**
- 画像は `public/images/{slug}/` に置き、本文から `/images/{slug}/ファイル名` で参照
- 本文は純Markdownのみ（MDX・コンポーネント・HTML禁止）。アフィリエイトリンクはURL直書き

この規約は、将来ほかのCMS（WordPress等）へ移行してもそのまま持ち出せるようにするためのもの。
記事の下書き・運営文書は別管理（このリポジトリには承認済み記事のみ置く）。
