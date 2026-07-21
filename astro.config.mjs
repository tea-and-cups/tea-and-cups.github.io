import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// 将来カスタムドメイン導入時はここを変えるだけ（記事側のURL・画像パスは変更不要）。
export default defineConfig({
  site: 'https://tea-and-cups.github.io',
  trailingSlash: 'always',
  integrations: [sitemap()],
});
