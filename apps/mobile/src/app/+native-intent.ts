/**
 * Routes incoming native intents.
 *
 * `expo-sharing` delivers a share from another app (any supported
 * platform,
 * Photos) as a deep link whose hostname is the literal `expo-sharing`. We send those
 * to the import sheet rather than letting them fall through to a 404.
 *
 * **The payload travels with the redirect.** This used to return a bare
 * `/import`, which routed the share to the right screen and threw away the
 * thing being shared: the sheet opened on an empty field and the person had
 * to go back and copy the link by hand. (A comment here promised a
 * `useIncomingShare()` hook on the other side; no such hook was ever
 * written.) The whole original path is forwarded as `shared` and the import
 * screen pulls the link out of it, because the payload's shape differs by
 * platform and guessing at a single key here would drop the ones that do
 * not match.
 *
 * This hook only decides the destination, so it must stay cheap and must not
 * throw — a throw here loses the user's share.
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
      return `/import?shared=${encodeURIComponent(path)}`;
    }
  } catch {
    // Not a parseable URL (some platforms hand us a bare path). Leave it alone
    // rather than guessing — an unroutable path is better than a wrong route.
  }
  return path;
}
