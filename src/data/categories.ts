// カテゴリ定義（D-0020 / UI/UX改善 Phase2）。
// frontmatterの category はここに定義した slug のみを許可する（content.config.ts で検証）。
// カテゴリの追加・改名は「扱うジャンルの追加」に当たるためオーナー承認＋decisions.md記録が必要。
// URLは /category/{slug}/ 。公開後の slug 変更は禁止（記事slugと同じ扱い）。

export const CATEGORY_SLUGS = ['how-to', 'tea-leaves', 'teaware', 'gift'] as const;

// テーマ一覧のカードに「（◯記事）」を出すかどうか。
// 記事数が少ないうちは見え方が寂しいため false。将来 true に戻せば復活する。
export const SHOW_CATEGORY_COUNT = false;

export const CATEGORIES = [
  {
    slug: 'how-to',
    name: '淹れ方・楽しみ方',
    description:
      '紅茶をおいしくいれるコツと、茶葉の扱い方や保存など、日々のティータイムを整える基本をまとめました。',
  },
  {
    slug: 'tea-leaves',
    name: '茶葉を選ぶ',
    description:
      '産地やフレーバーごとの特徴をふまえて、目的や気分に合う茶葉の選び方をご紹介します。',
  },
  {
    slug: 'teaware',
    name: '茶器・道具',
    description:
      'ティーカップ・グラス・ポットなど、紅茶の時間を支える器と道具の選び方をまとめました。',
  },
  {
    slug: 'gift',
    name: 'ギフト・手土産',
    description:
      '贈る相手やシーンに合わせて選ぶ、紅茶のギフト・手土産の選び方をご紹介します。',
  },
];

export function getCategory(slug) {
  return CATEGORIES.find((c) => c.slug === slug);
}

export function categoryName(slug) {
  return getCategory(slug)?.name ?? slug;
}

export function categoryPath(slug) {
  return `/category/${slug}/`;
}

// テーマ一覧のカード画像。パスはslugから導出する（対応表は持たない）。
// 生成は python site/scripts/hero-to-webp.py --category <入力画像> <slug>（1200x675・16:9）。
// 画像が未配置でもカード側でフォールバックするため、カテゴリ追加時は画像を置くだけでよい。
export function categoryImagePath(slug) {
  return `/images/categories/${slug}.webp`;
}
