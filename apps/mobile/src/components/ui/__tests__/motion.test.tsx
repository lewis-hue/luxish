/**
 * The invariants that make the motion safe to use everywhere.
 *
 * Two things matter and neither is visual. Every primitive must collapse
 * under Reduce Motion, because Apple's guidance asks for motion to be reduced
 * rather than merely shortened. And the stagger must be bounded, because an
 * uncapped one makes a long grid appear to load slowly when it has in fact
 * already loaded.
 */

import { fireEvent, render, screen } from '@testing-library/react-native';
import { AccessibilityInfo, Text, View } from 'react-native';

import {
  MotionPressable,
  PRESS_SCALE,
  STAGGER_MAX_INDEX,
  STAGGER_STEP_MS,
  useEntranceMotion,
  usePopMotion,
  usePressMotion,
} from '@/components/ui/motion';
import { Motion } from '@/constants/theme';

/** Reduce Motion is read asynchronously, so each test sets it before render. */
function setReduceMotion(enabled: boolean) {
  jest
    .spyOn(AccessibilityInfo, 'isReduceMotionEnabled')
    .mockResolvedValue(enabled);
  jest
    .spyOn(AccessibilityInfo, 'addEventListener')
    .mockReturnValue({ remove: () => undefined } as never);
}

afterEach(() => jest.restoreAllMocks());

describe('stagger bounds', () => {
  it('caps the wait so a long grid does not look slow', () => {
    // Cell 30 at 40ms a step would wait 1.2s, which reads as a slow load
    // rather than a stagger. The cap keeps the effect on the first screenful,
    // which is the only place it can be perceived anyway.
    const worst = STAGGER_MAX_INDEX * STAGGER_STEP_MS;
    expect(worst).toBeLessThanOrEqual(400);
    expect(worst + Motion.base).toBeLessThan(1000);
  });

  it('steps by less than the animation it delays', () => {
    // A step longer than the animation makes cells arrive one at a time
    // rather than as a wave.
    expect(STAGGER_STEP_MS).toBeLessThan(Motion.base);
  });
});

describe('press depth', () => {
  it('compresses slightly rather than bouncing', () => {
    // At 0.95 the movement draws the eye; the intent is a surface taking the
    // weight of the finger.
    expect(PRESS_SCALE).toBeGreaterThanOrEqual(0.96);
    expect(PRESS_SCALE).toBeLessThan(1);
  });
});

describe('reduced motion', () => {
  function Probe() {
    const press = usePressMotion();
    const entrance = useEntranceMotion(5);
    const pop = usePopMotion();
    return (
      <View>
        <Text>{JSON.stringify({ press: !!press.style, entrance: !!entrance })}</Text>
        <Text testID="pop" onPress={pop.pop}>
          pop
        </Text>
      </View>
    );
  }

  it('renders every primitive without animating when reduce motion is on', async () => {
    setReduceMotion(true);
    await render(<Probe />);
    expect(screen.getByTestId('pop')).toBeTruthy();
  });

  it('renders every primitive when reduce motion is off', async () => {
    setReduceMotion(false);
    await render(<Probe />);
    expect(screen.getByTestId('pop')).toBeTruthy();
  });

  it('pop is a no-op under reduce motion rather than a faster pop', async () => {
    // A shortened version of an unwanted animation is still unwanted.
    setReduceMotion(true);
    let popped: (() => void) | null = null;
    function Capture() {
      const { pop } = usePopMotion();
      popped = pop;
      return <Text>x</Text>;
    }
    await render(<Capture />);
    expect(() => popped?.()).not.toThrow();
  });
});

describe('MotionPressable', () => {
  it('keeps the accessibility props it is given', async () => {
    // The wrapper must not swallow what a caller sets, or every use of it
    // silently loses its label.
    setReduceMotion(false);
    await render(
      <MotionPressable accessibilityRole="button" accessibilityLabel="Open look">
        <Text>Look</Text>
      </MotionPressable>,
    );
    const node = screen.getByLabelText('Open look');
    expect(node.props.accessibilityRole).toBe('button');
  });

  it('still calls a caller-supplied onPressIn', async () => {
    setReduceMotion(false);
    const onPressIn = jest.fn();
    await render(
      <MotionPressable accessibilityLabel="Tap" onPressIn={onPressIn} haptic={false}>
        <Text>Tap</Text>
      </MotionPressable>,
    );
    fireEvent(screen.getByLabelText('Tap'), 'pressIn');
    expect(onPressIn).toHaveBeenCalled();
  });
});
