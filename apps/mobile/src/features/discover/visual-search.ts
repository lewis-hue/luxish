import * as Linking from 'expo-linking';

/**
 * "Search the web for this garment" — the Chrome-style reverse image search.
 *
 * Uploads the image bytes directly from the device and opens the results in the
 * system browser. Three things decided this design, all verified rather than
 * assumed:
 *
 * 1. **Upload, not a URL.** The `uploadbyurl` variant requires a *publicly
 *    reachable* image — a server-side fetcher identifying as `Google-Lens` pulls it.
 *    Our images are bundled assets or private photos behind signed URLs, so that
 *    path would mean temporarily publishing a user's clothing. Uploading bytes
 *    sidesteps hosting, signed-URL expiry, and the query-encoding trap entirely.
 * 2. **`uploadbyurl` is also gated by User-Agent** and returns 404 to okhttp — which
 *    is React Native's HTTP stack on Android. It would have worked in development on
 *    iOS and failed on every Android device.
 * 3. **There is no native hand-off on either platform.** Android's Lens activity is
 *    behind a private allowlist and now crashes the Google app when launched
 *    directly; iOS documents no URL scheme and `lens.google.com` serves no
 *    apple-app-site-association. Opening the results URL in the browser is the only
 *    supported route.
 *
 * **Deliberate restraint, for terms-of-service reasons.** One user tap equals one
 * request. This module never batches, never polls, never parses or stores the
 * results page, and never renders results inside our own UI — the results page is
 * robots-disallowed, and presenting it as ours would misrepresent whose service it
 * is. The hand-off to the browser is the product.
 */

const UPLOAD_ENDPOINT = 'https://lens.google.com/v3/upload';

/** Observed: ~27 MB returns 413. Stay well under, and crop before calling. */
const MAX_UPLOAD_BYTES = 18 * 1024 * 1024;

/** Chromium's own accepted set. Note HEIC is absent — transcode first. */
const SUPPORTED_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/bmp'] as const;

export type VisualSearchFailure =
  | 'too_large'
  | 'unsupported_type'
  | 'not_decoded'
  | 'no_results_url'
  | 'network';

export class VisualSearchError extends Error {
  readonly reason: VisualSearchFailure;

  constructor(reason: VisualSearchFailure, message: string) {
    super(message);
    this.name = 'VisualSearchError';
    this.reason = reason;
  }
}

export interface VisualSearchInput {
  /** Local file URI of the image to search — crop it first. */
  uri: string;
  mimeType?: string;
  /** Used only for the multipart filename; never sent anywhere else. */
  filename?: string;
}

/**
 * Uploads the image and returns the results URL, without opening it.
 *
 * Separated from `searchOnWeb` so the result can be asserted in a test without a
 * browser, and so a caller can decide what to do with the URL.
 */
export async function resolveVisualSearchUrl(
  input: VisualSearchInput,
  deps: { fetch?: typeof globalThis.fetch } = {},
): Promise<string> {
  const doFetch = deps.fetch ?? globalThis.fetch;
  const mimeType = input.mimeType ?? 'image/jpeg';

  if (!SUPPORTED_TYPES.includes(mimeType as (typeof SUPPORTED_TYPES)[number])) {
    throw new VisualSearchError(
      'unsupported_type',
      `${mimeType} cannot be searched. Convert it to JPEG or PNG first.`,
    );
  }

  const form = new FormData();
  // The field name is `encoded_image`. Anything else uploads successfully and
  // produces a results page with no image attached, which looks like a bad match
  // rather than a bug.
  form.append('encoded_image', {
    uri: input.uri,
    type: mimeType,
    name: input.filename ?? 'garment.jpg',
  } as unknown as Blob);

  let response: Response;
  try {
    response = await doFetch(UPLOAD_ENDPOINT, {
      method: 'POST',
      body: form,
      // Read the 303 ourselves rather than following it: the Location carries the
      // decode evidence we check below, and following it would fetch a page we have
      // no business parsing.
      redirect: 'manual',
    });
  } catch (error) {
    throw new VisualSearchError(
      'network',
      error instanceof Error ? error.message : 'could not reach the search service',
    );
  }

  if (response.status === 413) {
    throw new VisualSearchError('too_large', 'That image is too large to search.');
  }

  const location =
    response.headers.get('location') ??
    // Some RN fetch implementations follow redirects regardless of `redirect`,
    // in which case the final URL is the results page.
    (response.url && response.url !== UPLOAD_ENDPOINT ? response.url : null);

  if (!location) {
    throw new VisualSearchError('no_results_url', 'The search service returned no result.');
  }

  // `vsdim` echoes the decoded pixel dimensions, so its presence proves the image
  // was actually read. Garbage bytes still redirect — without it. Treating the
  // redirect alone as success is how a broken upload reaches the user as "no
  // matches found".
  if (!location.includes('vsdim=')) {
    throw new VisualSearchError(
      'not_decoded',
      'That image could not be read. Try a clearer photo.',
    );
  }

  return location;
}

/**
 * Searches the web for this garment and hands the user to their browser.
 *
 * Always user-initiated: call this from a tap, never from a loop or a background
 * task.
 */
export async function searchOnWeb(
  input: VisualSearchInput,
  deps: { fetch?: typeof globalThis.fetch; openUrl?: (url: string) => Promise<unknown> } = {},
): Promise<void> {
  const url = await resolveVisualSearchUrl(input, deps);
  const open = deps.openUrl ?? Linking.openURL;
  await open(url);
}

/**
 * Text fallback, for when there is no image to send.
 *
 * Used for reference pieces the user does not own — we have a description but no
 * photograph of *their* item. An ordinary web search with the garment's attributes
 * is honest and works everywhere.
 */
export function webSearchUrlForDescription(parts: {
  name: string;
  colour?: string | null;
  category?: string | null;
}): string {
  const terms = [parts.colour, parts.name, parts.category]
    .filter((part): part is string => Boolean(part && part.trim()))
    // The name usually already contains the colour and category; de-duplicate so
    // the query is not "navy navy wool blazer blazer".
    .filter((part, index, all) => all.findIndex((other) => other.toLowerCase() === part.toLowerCase()) === index);

  return `https://www.google.com/search?tbm=shop&q=${encodeURIComponent(terms.join(' '))}`;
}

export const VISUAL_SEARCH_LIMITS = {
  maxBytes: MAX_UPLOAD_BYTES,
  supportedTypes: SUPPORTED_TYPES,
} as const;
