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

export const CATEGORY_EDITORIAL = {
  'tea-leaves': {
    beginners: ['sekai-sandai-koucha-towa', 'seiron-koucha-santi-kubun', 'assam-tea-nyumon'],
    featured: 'seiron-koucha-santi-kubun',
  },
  'how-to': {
    beginners: ['koucha-kihon-no-irekata', 'koucha-mizu-nansui-kousui', 'chaba-hokan-natsu'],
    featured: 'koucha-kihon-no-irekata',
  },
  teaware: {
    beginners: ['teacup-coffee-cup-chigai', 'bone-china-jiki-touki-chigai', 'tea-strainer-chakoshi-erabikata'],
    featured: 'bone-china-jiki-touki-chigai',
  },
  gift: {
    beginners: ['keirounohi-koucha-gift', 'kisei-temiyage-koucha-gift', 'pair-cup-saucer-kekkonjoshii-tanjoubi-hikaku'],
    featured: 'twg-tea-gift-koucha-erabikata',
  },
} as const;
