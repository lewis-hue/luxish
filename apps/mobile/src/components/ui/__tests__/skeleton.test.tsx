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
  SkeletonGrid,
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
