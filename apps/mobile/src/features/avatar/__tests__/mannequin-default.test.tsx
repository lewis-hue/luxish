/**
 * The mannequin is what "your avatar" means until somebody asks otherwise.
 *
 * **Three ways this app shows an outfit, and only one of them costs.**
 * A cut-out composite is free and instant. The mannequin is a figure
 * that ships inside this app, also free. A photorealistic likeness is
 * a paid generation that takes about half a minute.
 *
 * The avatar screen had only the expensive one. With no likeness it
 * said "Nothing drawn yet" above a button that spent a generation, so
 * the only avatar anybody could have was the one that cost money - on
 * the screen whose whole job is to answer "what would this look like
 * on me".
 *
 * The server never asked for that. `AvatarOut.on_my_avatar` is
 * documented as "the client shows the mannequin unless this is true",
 * and `figure_to_dress` has defaulted to the mannequin for try-ons
 * from the start. The client simply never drew one.
 */

import { render, screen } from '@testing-library/react-native';

import {
  OutfitFigure,
  figureFor,
  figureKeyFor,
  type WornPiece,
} from '@/features/avatar/figure';

const PRESENTATIONS = [
  'unspecified',
  'womenswear',
  'menswear',
  'feminine',
  'masculine',
  'androgynous',
] as const;

function worn(slot: WornPiece['slot']): WornPiece {
  return { id: slot, slot, uri: `file://${slot}.png` };
}

test('there is a figure for every presentation, including none given', () => {
  // The fallback has to work for somebody who answered nothing,
  // which is the state every account starts in.
  for (const presentation of PRESENTATIONS) {
    expect(figureFor(presentation as never)).toBeTruthy();
  }
});

test('saying nothing about yourself still picks a figure', () => {
  expect(figureKeyFor('unspecified' as never)).toBeTruthy();
});

test('a figure draws with no clothes on it at all', async () => {
  // The empty case is the one that used to read "Nothing drawn yet".
  // It is not an empty state: it is the avatar.
  await render(<OutfitFigure pieces={[]} presentation="unspecified" />);
  expect(screen.getByLabelText('The outfit, on a figure')).toBeTruthy();
});

test('it carries whatever label the screen gives it', async () => {
  // The pictures say nothing on their own, so the screen names what
  // is being shown rather than leaving a screen reader with "image".
  await render(
    <OutfitFigure
      pieces={[]}
      presentation="unspecified"
      label="Your figure. Put something on it to see a look."
    />,
  );
  expect(
    screen.getByLabelText('Your figure. Put something on it to see a look.'),
  ).toBeTruthy();
});

test('cut-outs go onto the figure, free, with no render involved', async () => {
  // This is the composite: the real garments, laid on the mannequin.
  // Nothing here reaches the network.
  await render(
    <OutfitFigure
      pieces={[worn('tops'), worn('bottoms'), worn('shoes')]}
      presentation="menswear"
      label="Your figure, wearing the pieces"
    />,
  );
  expect(screen.getByLabelText('Your figure, wearing the pieces')).toBeTruthy();
});

test('the avatar screen draws a figure instead of an empty state', () => {
  // **The guard for the regression, not the component.**
  //
  // The tests above prove a figure can be drawn with nothing on it.
  // This proves the screen reaches for it, which is the part that was
  // wrong: `OutfitFigure` already existed and the avatar screen
  // rendered the words "Nothing drawn yet" instead.
  //
  // Read as source because the screen pulls in expo-router, the auth
  // session and six queries; mocking all of that to assert one
  // fallback would test the mocks.
  const fs = require('fs') as typeof import('fs');
  const path = require('path') as typeof import('path');
  const screenSource = fs.readFileSync(
    path.join(__dirname, '..', '..', '..', 'app', 'avatar.tsx'),
    'utf8',
  );

  expect(screenSource).toContain('<OutfitFigure');
  // Matched as rendered text, between tags, rather than as a bare
  // phrase: the comment above the fix explains the old empty state by
  // quoting it, and a guard that flags its own rationale is the kind
  // that gets deleted.
  expect(screenSource).not.toMatch(/>\s*Nothing drawn yet\s*</);
});

test('the paid action is named for what it costs', () => {
  // It read "Draw my avatar", which is what the free figure is. A
  // button that spends a generation has to say so, or the expensive
  // path is the one people take by default.
  const fs = require('fs') as typeof import('fs');
  const path = require('path') as typeof import('path');
  const screenSource = fs.readFileSync(
    path.join(__dirname, '..', '..', '..', 'app', 'avatar.tsx'),
    'utf8',
  );

  expect(screenSource).toContain('photorealistic');
});
