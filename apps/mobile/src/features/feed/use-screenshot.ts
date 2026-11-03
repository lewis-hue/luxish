import * as ScreenCapture from 'expo-screen-capture';
import { useEffect } from 'react';

/**
 * Catch a screenshot and offer the real picture instead.
 *
 * **A screenshot is a request, not a problem.** Somebody capturing the
 * screen wants to keep or send what is on it, and the OS screenshot is
 * the worst version of both: it carries the status bar, the app's own
 * chrome, and none of the author's credit. Noticing the gesture and
 * offering a clean file is strictly better for the person taking it and
 * for the person who made the picture.
 *
 * **Nothing is blocked.** `preventScreenCaptureAsync` exists and is not
 * used: refusing to let somebody photograph their own screen is hostile,
 * and they would just use another phone.
 *
 * iOS and Android only. The listener needs permission on Android and
 * simply never fires without it, which is a quiet no-op rather than a
 * failure — the app works identically, it just cannot offer the better
 * file.
 */
export function useScreenshotPrompt(onShot: () => void): void {
  useEffect(() => {
    let cancelled = false;
    let subscription: { remove: () => void } | undefined;

    const listen = async () => {
      try {
        const { granted } = await ScreenCapture.requestPermissionsAsync();
        if (cancelled || !granted) return;
        subscription = ScreenCapture.addScreenshotListener(() => onShot());
      } catch {
        // Unsupported platform, or permission refused. Both mean the
        // same thing here: no prompt, and nothing else changes.
      }
    };
    void listen();

    return () => {
      cancelled = true;
      subscription?.remove();
    };
    // `onShot` is re-created each render by callers; subscribing once
    // per mount is the intent, and the callback reads fresh state
    // through the closure the caller gives it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
