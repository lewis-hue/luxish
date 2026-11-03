import { useEffect, useState } from 'react';
import { Keyboard, Platform } from 'react-native';

/**
 * How much of the bottom of the screen the keyboard is covering.
 *
 * **Measured, not inferred from a frame.** `KeyboardAvoidingView`
 * works out its own offset from where it sits in the window, and
 * inside a `pageSheet` modal that arithmetic is wrong: the sheet is
 * not the window, and the composer ended up part-covered by the
 * keyboard with the line somebody was typing hidden behind it.
 *
 * This is the number itself, so there is nothing to get wrong about
 * where the view happens to be.
 *
 * **Not a violation of the house rule.** `AGENTS.md` says never to
 * use `Keyboard.addListener` plus a timing animation to track the
 * keyboard's frame - that rule is about animating against a moving
 * keyboard, which wants `react-native-keyboard-controller`. Nothing
 * here animates: it reports a height, and the layout follows it the
 * way layout follows any other number. The floating tab bar already
 * reads the keyboard the same way, for the same reason.
 */
export function useKeyboardInset(): number {
  const [inset, setInset] = useState(0);

  useEffect(() => {
    // `Will` on iOS so the space is there as the keyboard arrives
    // rather than a beat behind it; Android only emits `Did`.
    const show = Keyboard.addListener(
      Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow',
      (event) => setInset(event.endCoordinates?.height ?? 0),
    );
    const hide = Keyboard.addListener(
      Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide',
      () => setInset(0),
    );
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);

  return inset;
}

/**
 * The padding a bottom-pinned composer needs.
 *
 * With the keyboard down it is the safe-area inset, so the composer
 * clears the home indicator. With it up the keyboard covers that
 * area entirely, so adding both would lift the composer a
 * finger's width above the keys for no reason.
 */
export function composerInset(input: {
  keyboard: number;
  safeArea: number;
}): number {
  return input.keyboard > 0 ? input.keyboard : input.safeArea;
}
