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
//   spokes:    ハブ記事のあとに並べる主要5本（categories.ts の hub を指定したカテゴリで使う。ちょうど5本）
//   beginners: 「最初は、この3本から」（hub を指定していないカテゴリで使う。ちょうど3本）
// hub を指定したカテゴリはハブブロックが「最初の入口」を兼ねるため、beginners は出さない。
export const CATEGORY_EDITORIAL = {
  'tea-leaves': {
    spokes: ['seiron-koucha-santi-kubun', 'assam-tea-nyumon', 'chaba-grade-op-bop-ctc-yomikata', 'wakoucha-nyumon', 'darjeeling-autumnal-second-flush-hikaku'],
    beginners: ['sekai-sandai-koucha-towa', 'seiron-koucha-santi-kubun', 'assam-tea-nyumon'],
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
    spokes: ['keirounohi-koucha-gift', 'kisei-temiyage-koucha-gift', 'pair-cup-saucer-kekkonjoshii-tanjoubi-hikaku', 'twg-tea-gift-koucha-erabikata', 'zansho-mimai-koucha-gift'],
    beginners: ['keirounohi-koucha-gift', 'kisei-temiyage-koucha-gift', 'pair-cup-saucer-kekkonjoshii-tanjoubi-hikaku'],
    featured: 'twg-tea-gift-koucha-erabikata',
  },
  seasons: {
    spokes: ['bousai-koucha-teabag-erabikata', 'otsukimi-wakoucha-tsukimi-dango', 'koucha-no-hi-yurai', 'halloween-ouchi-ochakai-noncaffeine', 'natsumatsuri-hanabi-suitou-icetea'],
  },
} as const;
