import { useEffect, useRef } from 'react';
import { AppState, type AppStateStatus } from 'react-native';

/**
 * Run something when the app comes back from the background.
 *
 * **Not the same as focus, and the difference is the whole point.**
 * `AppState` fires `active` for several things that are not somebody
 * returning to the app - an alert being dismissed, a permission
 * sheet closing, the share sheet going away. Treating every
 * `active` as a return means a screen reloads because somebody
 * cancelled a dialog, which is the behaviour this hook exists to
 * avoid. So the previous state is held and the callback runs only on
 * a genuine `background | inactive -> active` transition.
 *
 * `inactive` is included because iOS passes through it on the way
 * back from the app switcher; Android goes straight to `background`.
 * Excluding it would make this work on one platform.
 */
export function useReturnedToApp(onReturn: () => void): void {
  // In a ref so a caller passing an inline arrow does not tear down
  // and re-add the listener on every render - which would both leak
  // subscriptions and miss transitions during the gap.
  //
  // Written in an effect rather than during render: a ref assigned
  // mid-render is a side effect in the render pass, which this
  // repository lints against and React may run twice.
  const latest = useRef(onReturn);
  useEffect(() => {
    latest.current = onReturn;
  }, [onReturn]);

  useEffect(() => {
    // `currentState` is typed as possibly null or undefined: on a
    // cold start the native module may not have reported yet. Null
    // is not a state we return *from*, so it starts as 'active' and
    // the first real transition sets it properly.
    // Typed as a plain string, not `AppStateStatus`: this React
    // Native version declares `currentState` that way, and the
    // comparisons below only ever test it against known literals.
    let previous: string = AppState.currentState ?? 'active';
    const subscription = AppState.addEventListener('change', (next: AppStateStatus) => {
      const returning =
        next === 'active' &&
        (previous === 'background' || previous === 'inactive');
      previous = next;
      if (returning) latest.current();
    });
    return () => subscription.remove();
  }, []);
}
