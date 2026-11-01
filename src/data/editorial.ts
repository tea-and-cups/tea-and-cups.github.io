// Local staging design candidates. Keep editorial choices in one place so templates
// remain data-driven and production can approve or replace individual selections.
export const HOME_FIRST_STEPS = [
  { slug: 'koucha-kihon-no-irekata', verb: '淹れる' },
  { slug: 'sekai-sandai-koucha-towa', verb: '知る' },
  { slug: 'bone-china-jiki-touki-chigai', verb: '選ぶ' },
] as const;

export const HOME_DOORS = [
  { category: 'tea-leaves', mark: '葉', note: '産地と等級で、味はここまで変わる。', featured: 'chaba-grade-op-bop-ctc-yomikata' },
  { category: 'how-to', mark: '淹', note: '同じ茶葉でも、淹れ方で別の一杯に。', featured: 'koucha-mizu-nansui-kousui' },
  { category: 'teaware', mark: '器', note: '器が変わると、紅茶の時間が変わる。', featured: 'teacup-coffee-cup-chigai' },
] as const;

// カテゴリページの冒頭の編集枠（D-0246）。すべて任意で、無いカテゴリは該当ブロックを出さない。
//   spokes:    ハブ記事のあとに並べる主要記事（categories.ts の hub を指定したカテゴリで使う。seasonal が無ければちょうど5本。時期を問わない記事だけにする）
//   seasonal:  時期のある記事（slug・from・to。形は MM-DD。from が to より後なら年をまたぐ）。並べ方は selectCategoryEntry
//   beginners: 「最初は、この3本から」（hub を指定していないカテゴリで使う。ちょうど3本）
// hub を指定したカテゴリはハブブロックが「最初の入口」を兼ねるため、beginners は出さない。
export const CATEGORY_EDITORIAL = {
  'tea-leaves': {
    spokes: ['sekai-sandai-koucha-towa', 'seiron-koucha-santi-kubun', 'assam-tea-nyumon', 'wakoucha-nyumon', 'darjeeling-autumnal-second-flush-hikaku'],
    featured: 'seiron-koucha-santi-kubun',
  },
  'how-to': {
    spokes: ['koucha-mizu-nansui-kousui', 'mizudashi-koucha-chaba-erabikata', 'royal-milk-tea-to-no-chigai', 'hot-brew-mizudashi-icetea-hikaku', 'koucha-nisenme-degarashi-tanoshimikata'],
    beginners: ['koucha-kihon-no-irekata', 'koucha-mizu-nansui-kousui', 'hot-brew-mizudashi-icetea-hikaku'],
    featured: 'koucha-kihon-no-irekata',
  },
  teaware: {
    spokes: ['teacup-coffee-cup-chigai', 'bone-china-jiki-touki-chigai', 'wedgwood-teacup-erabikata-hikaku', 'kaigai-brand-teacup-hikaku', '5000en-ika-brand-teacup-hikaku'],
    featured: 'bone-china-jiki-touki-chigai',
  },
  care: {
    spokes: ['chashibu-kibami-otoshikata', 'kinsai-teacup-atsukaikata', 'teacup-kyusu-shuunou-shokkidana-seiri', 'chakan-canister-erabikata', 'chaba-hokan-natsu'],
  },
  gift: {
    spokes: ['pair-cup-saucer-kekkonjoshii-tanjoubi-hikaku', 'twg-tea-gift-koucha-erabikata'],
    seasonal: [
      { slug: 'zansho-mimai-koucha-gift', from: '06-17', to: '08-01' },
      { slug: 'kisei-temiyage-koucha-gift', from: '06-29', to: '08-13' },
      { slug: 'keirounohi-koucha-gift', from: '08-01', to: '09-15' },
      { slug: 'shichigosan-uchiiwai-koucha-gift', from: '10-15', to: '11-30' },
      { slug: 'iifuufu-no-hi-pair-cup-erabikata', from: '10-25', to: '11-22' },
      { slug: 'kinrou-kansha-no-hi-koucha-petit-gift', from: '10-25', to: '11-23' },
      { slug: 'oseibo-koucha-gift-erabikata', from: '11-01', to: '12-20' },
      { slug: 'christmas-present-koucha-gift-aite-betsu', from: '11-15', to: '12-25' },
      { slug: 'onenga-koucha-gift-erabikata', from: '12-10', to: '01-15' },
    ],
    beginners: ['keirounohi-koucha-gift', 'kisei-temiyage-koucha-gift', 'pair-cup-saucer-kekkonjoshii-tanjoubi-hikaku'],
    featured: 'twg-tea-gift-koucha-erabikata',
  },
  seasons: {
    spokes: ['koucha-no-hi-yurai'],
    seasonal: [
      { slug: 'natsumatsuri-hanabi-suitou-icetea', from: '07-01', to: '08-31' },
      { slug: 'bousai-koucha-teabag-erabikata', from: '07-18', to: '09-01' },
      { slug: 'otsukimi-wakoucha-tsukimi-dango', from: '07-24', to: '09-07' },
      { slug: 'halloween-ouchi-ochakai-noncaffeine', from: '09-16', to: '10-31' },
      { slug: 'stollen-koucha-pairing', from: '10-15', to: '11-29' },
      { slug: 'koucha-advent-calendar-erabikata', from: '10-17', to: '12-01' },
      { slug: 'toji-yuzu-koucha-oyatsu', from: '11-06', to: '12-21' },
      { slug: 'christmas-cake-ni-au-koucha-erabikata', from: '11-10', to: '12-25' },
      { slug: 'nonaru-hotwine-fu-koucha', from: '11-10', to: '12-25' },
    ],
  },
} as const;

const ENTRY_SIZE = 5;
const isMonthDay = (value) => {
  const m = /^(\d{2})-(\d{2})$/.exec(value ?? '');
  if (!m) return false;
  const date = new Date(Date.UTC(2024, Number(m[1]) - 1, Number(m[2]))); // 閏年を基準にして 02-29 も通す
  return date.getUTCMonth() === Number(m[1]) - 1 && date.getUTCDate() === Number(m[2]);
};
const dayOfYear = (monthDay) => {
  const [month, day] = monthDay.split('-').map(Number);
  return Date.UTC(2024, month - 1, day) / 86400000;
};

// 入口の基準日（日本時間の MM-DD）。ビルドの日付で決まるため、切り替わるのは次の push のとき（schedule は入れていない）。
// CATEGORY_ENTRY_TODAY=YYYY-MM-DD は手元のビルドと検査で日付を固定するためのもの。GitHub Actions では無視する。
export function categoryEntryToday(now = new Date()) {
  const fixed = process.env.GITHUB_ACTIONS ? undefined : process.env.CATEGORY_ENTRY_TODAY;
  if (fixed) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(fixed) || !isMonthDay(fixed.slice(5))) throw new Error(`[category] CATEGORY_ENTRY_TODAY must be YYYY-MM-DD: ${fixed}`);
    return fixed.slice(5);
  }
  return new Date(now.getTime() + 9 * 3600000).toISOString().slice(5, 10);
}

// カテゴリページの入口の slug を選ぶ。today は MM-DD。次の順で5本を埋める。
//   (1) 期間中の seasonal（to が近い順）
//   (2) spokes
//   (3) まだ期間の来ていない seasonal（from が近い順。今年の期間が過ぎた記事は来年の分として後ろに回る）
export function selectCategoryEntry(editorial, today) {
  const until = (monthDay) => (dayOfYear(monthDay) - dayOfYear(today) + 366) % 366;
  const inPeriod = ({ from, to }) => (from <= to ? from <= today && today <= to : today >= from || today <= to);
  const seasonal = editorial.seasonal ?? [];
  const current = seasonal.filter(inPeriod).sort((a, b) => until(a.to) - until(b.to));
  const upcoming = seasonal.filter((s) => !inPeriod(s)).sort((a, b) => until(a.from) - until(b.from));
  return [...current.map((s) => s.slug), ...(editorial.spokes ?? []), ...upcoming.map((s) => s.slug)].slice(0, ENTRY_SIZE);
}

// 入口の設定の崩れを返す。今日の並びに出ない記事も見るので、崩れは日付によらずビルドで止まる。
// findPost は公開済みの記事だけを探す関数。
export function categoryEntryErrors(categorySlug, editorial, findPost) {
  const spokes = editorial.spokes ?? [];
  const seasonal = editorial.seasonal ?? [];
  const slugs = [...spokes, ...seasonal.map((s) => s.slug)];
  const errors = [];
  if (seasonal.length === 0 ? spokes.length !== ENTRY_SIZE : slugs.length < ENTRY_SIZE) errors.push(`entry count: ${slugs.length}`);
  if (new Set(slugs).size !== slugs.length) errors.push('duplicate slug');
  for (const slug of slugs) {
    const post = findPost(slug);
    if (!post) errors.push(`not published: ${slug}`);
    else if (post.data.category !== categorySlug) errors.push(`other category: ${slug}`);
  }
  for (const s of seasonal) {
    if (!isMonthDay(s.from) || !isMonthDay(s.to)) errors.push(`period must be MM-DD: ${s.slug} ${s.from}〜${s.to}`);
  }
  return errors;
}
