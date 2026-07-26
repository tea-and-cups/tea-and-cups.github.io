import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';
import { CATEGORY_SLUGS } from './data/categories';

// 可搬性規約: frontmatterは汎用9項目のみ（decisions.md D-0005 / D-0020でcategory追加）。
// Astro固有キーを増やさないこと。
const posts = defineCollection({
  loader: glob({ pattern: '**/[^_]*.md', base: './src/content/posts' }),
  schema: z.object({
    title: z.string(),
    slug: z.string().regex(/^[a-z0-9-]+$/, 'slugは英小文字・数字・ハイフンのみ'),
    date: z.coerce.date(),
    updated: z.coerce.date(),
    description: z.string().max(160),
    tags: z.array(z.string()),
    hero: z.string(),
    status: z.enum(['draft', 'published']),
    // 1記事1カテゴリ。値は src/data/categories.ts の定義に限る
    category: z.enum(CATEGORY_SLUGS),
  }),
});

export const collections = { posts };
