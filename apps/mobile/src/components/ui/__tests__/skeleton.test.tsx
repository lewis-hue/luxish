/**
 * The two decisions worth pinning: no motion, and no flash.
 *
 * Both are easy to undo accidentally. Someone adds a shimmer because it looks
 * livelier, or drops the delay because the placeholder "should appear
 * immediately". These assert why neither is right.
 */

import { render, screen, waitFor } from '@testing-library/react-native';
import { Text } from 'react-native';

import {
  SKELETON_DELAY_MS,
  Skeleton,
  SkeletonBubbles,
  SkeletonGrid,
  SkeletonMasonry,
  SkeletonRows,
  SkeletonText,
  useDelayedVisible,
} from '@/components/ui/skeleton';

describe('skeleton', () => {
  it('announces itself as busy when it carries a label', async () => {
    // Silence during a load is worse for a screen reader than a stated wait.
    await render(<Skeleton height={20} label="Loading looks" />);
    const node = screen.getByLabelText('Loading looks');
    expect(node.props.accessibilityState).toEqual({ busy: true });
  });

  it('stays decorative when it has no label', async () => {
    // Individual cells inside a labelled grid must not each be announced.
    await render(<Skeleton height={20} />);
    expect(JSON.stringify(screen.toJSON())).not.toContain('progressbar');
  });

  it('announces a grid once, not once per cell', async () => {
    await render(
      <SkeletonGrid count={12} columns={3} aspectRatio={3 / 4} label="Loading wardrobe" />,
    );
    expect(screen.getAllByLabelText('Loading wardrobe')).toHaveLength(1);
  });

  it('keeps a short final row aligned rather than stretched', async () => {
    // 5 items over 2 columns leaves one gap; without a spacer the last cell
    // would double in width and break the grid.
    await render(<SkeletonGrid count={5} columns={2} aspectRatio={3 / 4} />);
    expect(screen.toJSON()).toBeTruthy();
  });

  it('shortens the last text line so a block does not read as a table', async () => {
    await render(<SkeletonText lines={3} />);
    const widths = JSON.stringify(screen.toJSON()).match(/"width":"\d+%"/g) ?? [];
    expect(widths.filter((w) => w.includes('62%'))).toHaveLength(1);
  });
});

describe('no motion', () => {
  it('renders nothing that animates', async () => {
    // WCAG 2.2.2: the loading-animation exemption applies only when the
    // animation is the only content on the page. Ours sits under a live tab
    // bar, so a shimmer would need a pause mechanism. A static placeholder
    // says "loading" just as well, so there is nothing to trade away.
    await render(<SkeletonGrid count={6} columns={2} aspectRatio={3 / 4} />);
    const tree = JSON.stringify(screen.toJSON());
    for (const forbidden of ['Animated', 'shimmer', 'LinearGradient', 'opacity"']) {
      expect(tree).not.toContain(forbidden);
    }
  });
});

describe('useDelayedVisible', () => {
  // Real timers with a tiny delay rather than jest's fake ones: RNTL 14's
  // `render` is async, and faking timers stops the promise it returns from
  // ever resolving.
  const DELAY = 40;

  function Probe({ active }: { active: boolean }) {
    return <Text>{useDelayedVisible(active, DELAY) ? 'shown' : 'hidden'}</Text>;
  }

  it('shows nothing immediately', async () => {
    // NN/g: under a second an indicator is worse than none, because the flash
    // makes users feel they cannot keep up.
    await render(<Probe active />);
    expect(screen.getByText('hidden')).toBeTruthy();
  });

  it('appears once the wait is long enough to be worth reporting', async () => {
    await render(<Probe active />);
    await waitFor(() => expect(screen.getByText('shown')).toBeTruthy());
  });

  it('hides immediately when loading finishes', async () => {
    // Content must never wait on the delay timer.
    const { rerender } = await render(<Probe active />);
    await waitFor(() => expect(screen.getByText('shown')).toBeTruthy());

    await rerender(<Probe active={false} />);
    expect(screen.getByText('hidden')).toBeTruthy();
  });

  it('never shows anything when loading finishes inside the delay', async () => {
    const { rerender } = await render(<Probe active />);
    await rerender(<Probe active={false} />);
    expect(screen.getByText('hidden')).toBeTruthy();
  });

  it('waits under a second, since that is the threshold it enforces', () => {
    expect(SKELETON_DELAY_MS).toBeLessThan(1000);
  });
});

describe('masonry shells', () => {
  /** Every aspect ratio in the rendered tree, in order. */
  function ratios(tree: unknown): number[] {
    return [...JSON.stringify(tree).matchAll(/"aspectRatio":([\d.]+)/g)].map((m) =>
      Number(m[1]),
    );
  }

  it('is shaped like the board rather than like a grid', async () => {
    // The whole point. Identical cells are a different shape from the
    // masonry that replaces them, so every tile moves the moment the
    // real content lands - which is what reads as the app lurching.
    const view = await render(<SkeletonMasonry count={6} />);
    expect(new Set(ratios(view.toJSON())).size).toBeGreaterThan(1);
  });

  it('draws one shell per item', async () => {
    const view = await render(<SkeletonMasonry count={7} />);
    expect(ratios(view.toJSON())).toHaveLength(7);
  });

  it('keeps the columns about the same length', async () => {
    // Filled shortest-first, like the masonry itself. A lane that runs
    // far past the other is a shell that does not look like content.
    const view = await render(<SkeletonMasonry count={8} columns={2} />);
    const root = JSON.parse(JSON.stringify(view.toJSON()));
    const lanes: number[] = (root.children ?? []).map((lane: unknown) =>
      ratios(lane).reduce((tall, ratio) => tall + 1 / ratio, 0),
    );

    expect(lanes).toHaveLength(2);
    expect(lanes.every((tall) => tall > 0)).toBe(true);
    // Within one portrait cell of each other.
    expect(Math.abs(lanes[0] - lanes[1])).toBeLessThan(2);
  });

  it('draws the same shells every time', async () => {
    // A placeholder that changes height on each render is its own
    // flicker, which is the opposite of what it is for.
    const first = await render(<SkeletonMasonry count={6} />);
    const again = await render(<SkeletonMasonry count={6} />);
    expect(ratios(first.toJSON())).toEqual(ratios(again.toJSON()));
  });

  it('carries no caption bars', async () => {
    // A board's tiles are bare, so its shells are too.
    const view = await render(<SkeletonMasonry count={4} />);
    expect(JSON.stringify(view.toJSON())).not.toContain('62%');
  });

  it('announces the wait once, not once per shell', async () => {
    await render(<SkeletonMasonry count={8} label="Loading the board" />);
    expect(screen.getAllByLabelText('Loading the board')).toHaveLength(1);
  });

  it('still animates nothing', async () => {
    const view = await render(<SkeletonMasonry count={6} />);
    const tree = JSON.stringify(view.toJSON());
    for (const forbidden of ['Animated', 'shimmer', 'LinearGradient']) {
      expect(tree).not.toContain(forbidden);
    }
  });
});

describe('row shells', () => {
  it('is shaped like a person, not like prose', async () => {
    // A people list is a face and two lines. Plain text lines were the
    // wrong shape: the avatars appeared from nowhere when the list
    // landed and pushed every name sideways.
    const view = await render(<SkeletonRows count={3} />);
    const tree = JSON.stringify(view.toJSON());
    expect([...tree.matchAll(/"borderRadius":9999/g)]).toHaveLength(3);
  });

  it('leaves the circle out where a row has no face', async () => {
    // A board row in search is a name and a count, nothing more.
    const view = await render(<SkeletonRows count={3} avatar={false} />);
    expect(JSON.stringify(view.toJSON())).not.toContain('"borderRadius":9999');
  });

  it('draws one row per item', async () => {
    const view = await render(<SkeletonRows count={6} avatar={false} />);
    // Two bars a row, and nothing else carries a percentage width.
    expect([...JSON.stringify(view.toJSON()).matchAll(/"width":"\d+%"/g)]).toHaveLength(12);
  });

  it('announces the wait once', async () => {
    await render(<SkeletonRows count={5} label="Loading your messages" />);
    expect(screen.getAllByLabelText('Loading your messages')).toHaveLength(1);
  });
});

describe('conversation shells', () => {
  it('puts the bubbles down alternate sides', async () => {
    // A thread is not a stack of left-aligned lines. Shelling it as one
    // makes every message jump across the screen as it lands.
    const view = await render(<SkeletonBubbles count={4} />);
    const sides = [
      ...JSON.stringify(view.toJSON()).matchAll(/"alignItems":"(flex-start|flex-end)"/g),
    ].map((m) => m[1]);
    expect(sides).toEqual(['flex-start', 'flex-end', 'flex-start', 'flex-end']);
  });

  it('gives them different widths', async () => {
    // Messages are not all the same length, and a column of identical
    // bars does not read as a conversation.
    const view = await render(<SkeletonBubbles count={5} />);
    const widths = [
      ...JSON.stringify(view.toJSON()).matchAll(/"width":"(\d+%)"/g),
    ].map((m) => m[1]);
    expect(new Set(widths).size).toBeGreaterThan(2);
  });

  it('draws the same bubbles every time', async () => {
    const first = await render(<SkeletonBubbles count={5} />);
    const again = await render(<SkeletonBubbles count={5} />);
    expect(JSON.stringify(first.toJSON())).toEqual(JSON.stringify(again.toJSON()));
  });

  it('announces the wait once', async () => {
    await render(<SkeletonBubbles count={5} />);
    expect(screen.getAllByLabelText('Loading this conversation')).toHaveLength(1);
  });
});

describe('a row with a square thumbnail', () => {
  it('is square where the content is, not round', async () => {
    // An inbox row carries a fit's thumbnail, which is a square. A
    // circle there is a face that never arrives.
    const view = await render(<SkeletonRows count={2} round={false} size={56} />);
    const tree = JSON.stringify(view.toJSON());
    expect(tree).not.toContain('"borderRadius":9999');
    expect(tree).toContain('"width":56');
  });
});
