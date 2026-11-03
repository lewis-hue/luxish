import { type FeedFit } from '@/api/queries/discover-feed';
import { intoColumns } from '@/features/feed/columns';

/** Only the shape matters here, so the rest is filled in once. */
function fit(id: string, coverRatio: number | null): FeedFit {
  return { id, coverRatio } as unknown as FeedFit;
}

/** How tall a lane stands, per unit of column width. */
function tall(lane: FeedFit[]): number {
  return lane.reduce((at, one) => at + 1 / (one.coverRatio ?? 3 / 4), 0);
}

describe('intoColumns', () => {
  it('keeps every fit, exactly once', () => {
    const fits = Array.from({ length: 9 }, (_, at) =>
      fit(`f${at}`, at % 2 === 0 ? 0.75 : 1.2),
    );
    const ids = intoColumns(fits)
      .flat()
      .map((one) => one.id)
      .sort();
    expect(ids).toEqual(fits.map((one) => one.id).sort());
  });

  it('puts the next fit in whichever column is shortest', () => {
    // A tall one first: it must not be followed down the same column.
    const fits = [fit('tall', 0.5), fit('wide', 1.4), fit('next', 0.75)];
    const [left, right] = intoColumns(fits);
    expect(left.map((one) => one.id)).toEqual(['tall']);
    expect(right.map((one) => one.id)).toEqual(['wide', 'next']);
  });

  it('ends with columns of about the same height', () => {
    // The whole point: a column that runs long is the band of white
    // the wrapped-row layout used to leave.
    const fits = Array.from({ length: 20 }, (_, at) =>
      fit(`f${at}`, [0.5, 0.75, 1.4, 0.6, 1.0][at % 5]),
    );
    const lanes = intoColumns(fits);
    const [left, right] = lanes.map(tall);
    // Within one short tile of each other.
    expect(Math.abs(left - right)).toBeLessThan(1 / 1.4);
  });

  it('treats an unmeasured cover as a portrait rather than skipping it', () => {
    const lanes = intoColumns([fit('a', null), fit('b', null)]);
    expect(lanes.map((lane) => lane.length)).toEqual([1, 1]);
  });

  it('clamps a freakish ratio, the same as the tile does', () => {
    // A panorama would otherwise count as almost no height at all and
    // the column would be handed every remaining fit.
    const lanes = intoColumns([fit('panorama', 8), fit('b', 0.75)]);
    expect(lanes[0].map((one) => one.id)).toEqual(['panorama']);
    expect(lanes[1].map((one) => one.id)).toEqual(['b']);
  });

  it('can deal into three columns on a wide screen', () => {
    const fits = Array.from({ length: 6 }, (_, at) => fit(`f${at}`, 0.75));
    expect(intoColumns(fits, 3).map((lane) => lane.length)).toEqual([2, 2, 2]);
  });
});
