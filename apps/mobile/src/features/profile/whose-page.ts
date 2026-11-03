/**
 * Whether the profile being opened is the viewer's own.
 *
 * **The member screen is written for a stranger.** It offers Follow
 * and Message, it reads `private` from the viewer's side, and it has
 * no way to edit anything - all correct for somebody else's page and
 * all wrong for your own. Nothing asked the question, so tapping your
 * own name anywhere in the app - on a fit you posted, in a follower
 * list, on your own comment - opened the visitor's view of yourself:
 * buttons to follow and message your own account, and "Their shelf is
 * private" about your own shelf.
 *
 * A function rather than a comparison written inline at the one call
 * site, because the comparison has two ways to be wrong and both are
 * silent. `undefined === undefined` is true, so a missing id on both
 * sides reads as "this is you" and would redirect a stranger's page
 * to your own; and a signed-out viewer has no id at all.
 */
export function isOwnPage(input: {
  /** The signed-in account, or null/undefined when not signed in. */
  viewerId?: string | null;
  /** The account whose page is being opened. */
  pageId?: string | null;
}): boolean {
  const viewer = input.viewerId?.trim();
  const page = input.pageId?.trim();
  // Both must be present. Two blanks are not a match.
  if (!viewer || !page) return false;
  return viewer === page;
}
