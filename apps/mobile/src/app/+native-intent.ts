/**
 * Routes incoming native intents.
 *
 * `expo-sharing` delivers a share from another app (Instagram, TikTok, Pinterest,
 * Photos) as a deep link whose hostname is the literal `expo-sharing`. We send those
 * to the import sheet rather than letting them fall through to a 404.
 *
 * The payload itself is read on the other side with `useIncomingShare()`; this hook
 * only decides the destination, so it must stay cheap and must not throw — a throw
 * here loses the user's share.
 *
 * Docs: https://docs.expo.dev/versions/v58.0.0/sdk/sharing/
 */
export function redirectSystemPath({
  path,
}: {
  path: string;
  initial: boolean;
}): string {
  try {
    if (new URL(path).hostname === 'expo-sharing') {
      return '/import';
    }
  } catch {
    // Not a parseable URL (some platforms hand us a bare path). Leave it alone
    // rather than guessing — an unroutable path is better than a wrong route.
  }
  return path;
}
