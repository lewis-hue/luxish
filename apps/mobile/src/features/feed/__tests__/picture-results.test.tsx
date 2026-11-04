/**
 * What the camera shows after the shutter.
 *
 * **It used to be an alert and a redirect.** A picture whose tags
 * matched something jumped straight to that tag's page, losing the
 * photograph and every other reading. A picture whose tags matched
 * nothing produced "Nothing to go on" and left the person exactly
 * where they started, having opened a camera, framed a shot and
 * waited nine seconds. Neither is an answer to "find me things like
 * this".
 *
 * The rule these pin is that the two bands are never merged. "The
 * nearest thing here" and "this is your picture" are different
 * claims, and running them together makes the app look wrong rather
 * than helpful.
 */
import { screen } from '@testing-library/react-native';

import type { FeedFit } from '@/api/queries/discover-feed';
import { PictureResults } from '@/features/feed/picture-results';
import { renderWithProviders } from '@/test-support/render';

function fit(id: string, caption: string): FeedFit {
  return {
    id,
    authorId: `a-${id}`,
    authorName: 'Rena',
    caption,
    captionIsDescribed: false,
    mediaAssetIds: [`m-${id}`],
    coverRatio: 0.75,
    tags: [],
    groups: [],
    reactions: 0,
    saves: 0,
    comments: 0,
    myReaction: null,
    savedByMe: false,
    publishedAt: null,
  };
}

const noop = () => {};

test('nothing to show says so, and says what to do', async () => {
  await renderWithProviders(
    <PictureResults
      result={{ outfit: 'a pair of white trainers', subject: 'footwear', close: [], loosely: [] }}
      onClose={noop}
    />,
  );

  expect(screen.getByText(/Nothing like it here yet/)).toBeTruthy();
  // An empty screen is an invitation to act, not a dead end.
  expect(screen.getByText(/Try a wider shot/)).toBeTruthy();
});

test('it says what it thought it saw', async () => {
  // So somebody can tell a wrong reading from a thin board, which
  // are two very different problems with the same symptom.
  await renderWithProviders(
    <PictureResults
      result={{
        outfit: 'a pair of white trainers',
        subject: 'footwear',
        close: [],
        loosely: [],
      }}
      onClose={noop}
    />,
  );

  expect(screen.getByText(/I saw: a pair of white trainers/)).toBeTruthy();
});

test('loose matches are labelled as not exact', async () => {
  // **The reported case.** No pin has the palm in it, so the sheet
  // shows pins with hands and hand accessories - and has to say
  // that is what it is doing.
  await renderWithProviders(
    <PictureResults
      result={{
        outfit: 'rings on a hand',
        subject: 'jewellery',
        close: [],
        loosely: [fit('1', 'gold rings')],
      }}
      onClose={noop}
    />,
  );

  expect(screen.getByText('Closest to your picture')).toBeTruthy();
  expect(screen.getByText(/Not exact/)).toBeTruthy();
});

test('exact matches lead, and the loose band sits under its own heading', async () => {
  await renderWithProviders(
    <PictureResults
      result={{
        outfit: 'a cream knit',
        subject: 'outfit',
        close: [fit('1', 'cream knit')],
        loosely: [fit('2', 'oatmeal jumper')],
      }}
      onClose={noop}
    />,
  );

  expect(screen.getByText('Matching your picture')).toBeTruthy();
  expect(screen.getByText('Also close to it')).toBeTruthy();
  // Never "Closest to your picture" when there are real matches: that
  // heading is the no-exact-match wording.
  expect(screen.queryByText('Closest to your picture')).toBeNull();
});

test('no result is no sheet', async () => {
  await renderWithProviders(<PictureResults result={null} onClose={noop} />);
  expect(screen.queryByText(/What I found/)).toBeNull();
});
