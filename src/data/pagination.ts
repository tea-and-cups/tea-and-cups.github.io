// 一覧ページの1ページあたり件数（トップ・カテゴリ別一覧で共通）。
// 記事が増えても1ページの重さを一定に保つための定数上限。ここだけ変えれば両方に効く。
export const POSTS_PER_PAGE = 12;

// 記事一覧の並び順の共通比較関数（D-0170）。
// 「日付の新しい順 → slug の昇順」。
// 日付が同じ記事どうしの前後を決める条件が無いと、getCollection の返却順
// （ビルドごとに変わりうる）がその隙間を埋めてしまい、同じ入力から同じ dist が出ない。
// slug は公開後不変・全記事で一意なので、これで並びは完全に確定する。
type DateSlugSortable = { data: { date: Date; slug: string } };

export function compareByDateDescThenSlugAsc(
  a: DateSlugSortable,
  b: DateSlugSortable
): number {
  const byDate = b.data.date.valueOf() - a.data.date.valueOf();
  if (byDate !== 0) return byDate;
  // slug は ASCII の kebab-case のみ。ロケール非依存で確定させるため単純比較を使う。
  if (a.data.slug < b.data.slug) return -1;
  if (a.data.slug > b.data.slug) return 1;
  return 0;
}
