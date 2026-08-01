import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import { rehypeHeadingIds } from '@astrojs/markdown-remark';
import rehypeAffiliateLinks from './src/plugins/rehype-affiliate-links.mjs';
import rehypeToc from './src/plugins/rehype-toc.mjs';
import rehypeTableLabels from './src/plugins/rehype-table-labels.mjs';

// 将来カスタムドメイン導入時はここを変えるだけ（記事側のURL・画像パスは変更不要）。
export default defineConfig({
  site: 'https://tea-and-cups.github.io',
  trailingSlash: 'always',
  integrations: [sitemap()],
  markdown: {
    // アフィリエイトリンクへの rel/target 付与・目次の自動生成・表のスマホ用ラベル付与
    // （Markdown本文は純Markdownのまま）。
    // rehypeHeadingIds を先頭に置くのは、目次が見出しIDを必要とするため（Astro標準の生成規則のまま）。
    rehypePlugins: [rehypeHeadingIds, rehypeAffiliateLinks, rehypeToc, rehypeTableLabels],
  },
});
