// カテゴリ定義（D-0020 / UI/UX改善 Phase2 / D-0246で6カテゴリへ再編）。
// frontmatterの category はここに定義した slug のみを許可する（content.config.ts で検証）。
// カテゴリの追加・改名は「扱うジャンルの追加」に当たるためオーナー承認＋decisions.md記録が必要。
// URLは /category/{slug}/ 。公開後の slug 変更は禁止（記事slugと同じ扱い）。表示名（name）だけは変えてよい。

export const CATEGORY_SLUGS = ['tea-leaves', 'how-to', 'teaware', 'care', 'gift', 'seasons'] as const;

// テーマ一覧のカードに「（◯記事）」を出すかどうか。
// 記事数が少ないうちは見え方が寂しいため false。将来 true に戻せば復活する。
export const SHOW_CATEGORY_COUNT = false;

// 並び順がそのままヘッダー・フッター・テーマ一覧・記事一覧の絞り込みの表示順になる。
// hub: そのカテゴリのハブ記事のslug（省略可）。指定すると次の3か所に効く（D-0246）。
//   - カテゴリページの冒頭に「ハブ記事＋主要5本」のブロックを出す（主要5本は editorial.ts の spokes）
//   - 記事末の「次に読む」がカテゴリ一覧ではなくハブ記事へ向く
//   - ハブ記事のページに、同じカテゴリの全記事の一覧が自動で出る
// 新しいハブ記事を公開したら、そのカテゴリに hub を足す（未指定のカテゴリは従来どおりカテゴリ一覧へ向く）。
export const CATEGORIES = [
  {
    slug: 'tea-leaves',
    name: '茶葉と産地',
    en: 'Tea Leaves',
    description:
      '産地・等級・フレーバーごとの特徴をふまえて、目的や気分に合う茶葉の選び方をご紹介します。',
    hub: 'sekai-sandai-koucha-towa',
  },
  {
    slug: 'how-to',
    name: '淹れ方・楽しみ方',
    en: 'Brewing',
    description:
      '紅茶をおいしく淹れるコツと、アイスティーやアレンジ、お菓子との組み合わせなど、日々のティータイムの楽しみ方をまとめました。',
    hub: 'koucha-kihon-no-irekata',
  },
  {
    slug: 'teaware',
    name: '器とブランド',
    en: 'Teaware',
    description:
      'ティーカップ・グラス・ポットなど、紅茶の時間を支える器と道具の選び方、ブランドごとの違いをまとめました。',
  },
  {
    slug: 'care',
    name: 'お手入れ',
    en: 'Care',
    description:
      'ティーカップの汚れ落としや扱い方、食器棚の整理、開封後の茶葉の保存など、器と茶葉を長く楽しむためのお手入れをまとめました。',
    hub: 'teacup-shokusenki-denshirenji-otenire-qa',
  },
  {
    slug: 'gift',
    name: 'ギフト',
    en: 'Gift',
    description:
      '贈る相手やシーンに合わせて選ぶ、紅茶のギフト・手土産の選び方をご紹介します。',
    hub: 'koucha-gift-erabikata-aite-bamen-yosan',
  },
  {
    slug: 'seasons',
    name: '行事・季節',
    en: 'Seasons',
    description:
      'お月見・ハロウィン・夏祭りなど、行事や季節に合わせて楽しむ紅茶の過ごし方をまとめました。',
    hub: 'koucha-nenkan-calendar-gyoji-kisetsu',
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

// 記事末の「次に読む」の行き先。ハブ記事を指定したカテゴリはハブ記事、未指定はカテゴリ一覧。
// ハブ記事そのもののページでは自分自身へ送らないよう、カテゴリ一覧を返す（呼び出し側で判定する）。
export function categoryHubPath(slug) {
  const hub = getCategory(slug)?.hub;
  return hub ? `/posts/${hub}/` : categoryPath(slug);
}

// テーマ一覧のカード画像。パスはslugから導出する（対応表は持たない）。
// 生成は python site/scripts/hero-to-webp.py --category <入力画像> <slug>（1200x675・16:9）。
// 画像が未配置でもカード側でフォールバックするため、カテゴリ追加時は画像を置くだけでよい。
export function categoryImagePath(slug) {
  return `/images/categories/${slug}.webp`;
}
