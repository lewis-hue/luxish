import { router, usePathname } from 'expo-router';

import { EmptyState } from '@/components/ui/empty-state';

/**
 * A link that goes nowhere, caught.
 *
 * **Without this file, expo-router shows its own developer screen.**
 * A black page reading "Unmatched Route" with the raw `exp://` URL
 * under it, a "Sitemap" link, and no way back into the app. That is
 * the right screen for somebody building the app and the wrong one
 * for anybody using it, and it is what a tapped notification landed
 * on whenever its destination did not resolve.
 *
 * **It is reachable even with every route correct.** Notifications
 * already delivered carry whatever target the server sent when they
 * were written - two of those pointed at `/(tabs)/wardrobe` and
 * `/(tabs)/stylist`, which never resolved - and no fix to the server
 * reaches a banner already sitting in somebody's tray. A share link
 * from an older build is the same case. So this is not only a
 * developer safety net; it is the screen some real taps genuinely
 * arrive at, and it should offer the way on rather than a stack
 * trace.
 */
export default function NotFound() {
  const pathname = usePathname();

  return (
    <EmptyState
      status="empty"
      title="That link goes nowhere"
      // The path, because somebody reporting this needs to be able to
      // say which one, and because a dead end that will not even name
      // itself is worse than one that does.
      body={`Nothing here answers to ${pathname}. It may have moved, or been taken down.`}
      action={{
        label: 'Go to Discover',
        onPress: () => router.replace('/'),
      }}
    />
  );
}
