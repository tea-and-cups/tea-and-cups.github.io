import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import rehypeAffiliateLinks from './src/plugins/rehype-affiliate-links.mjs';

// 将来カスタムドメイン導入時はここを変えるだけ（記事側のURL・画像パスは変更不要）。
export default defineConfig({
  site: 'https://tea-and-cups.github.io',
  trailingSlash: 'always',
  integrations: [sitemap()],
  markdown: {
    // アフィリエイトリンクへの rel/target 付与（Markdown本文は純Markdownのまま）
    rehypePlugins: [rehypeAffiliateLinks],
  },
});
