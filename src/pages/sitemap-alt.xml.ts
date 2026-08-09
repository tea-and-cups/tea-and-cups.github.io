import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';

// GSCが sitemap-index.xml の取得失敗をキャッシュしている可能性を検証するための予備サイトマップ（D-XXXX）。
// 既存の @astrojs/sitemap 出力（sitemap-index.xml等）には一切触れず、
// 同じ記事コンテンツコレクションから全記事URLを動的に生成する別URL。
// 記事の追加・削除は自動反映される（手動でのURL列挙はしない）。
export const GET: APIRoute = async ({ site }) => {
  const posts = await getCollection('posts', (p) => p.data.status === 'published');

  const siteUrl = site ?? new URL('https://tea-and-cups.github.io');
  const urls = posts.map((post) => {
    const loc = new URL(`/posts/${post.data.slug}/`, siteUrl).toString();
    const lastmod = new Date(post.data.updated).toISOString();
    return `  <url>\n    <loc>${loc}</loc>\n    <lastmod>${lastmod}</lastmod>\n  </url>`;
  });

  const body = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls.join('\n')}\n</urlset>\n`;

  return new Response(body, {
    status: 200,
    headers: {
      'Content-Type': 'application/xml; charset=utf-8',
    },
  });
};
