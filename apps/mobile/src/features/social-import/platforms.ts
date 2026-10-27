/**
 * What we can honestly do with a link from each platform (§11, ADR-009).
 *
 * You asked that a user simply paste a link to a post — and that is exactly what
 * this supports. The link is kept as a reference with attribution, and the post can
 * be opened or embedded where the platform allows it.
 *
 * What a public link does *not* carry is permission to download the media behind it
 * and run garment analysis on it. So each platform declares its capabilities
 * separately, and when `canAnalyse` is false the UI says so and offers the path that
 * does work: media the user supplies themselves — a screenshot of the post, their
 * own photo, or a short clip they are entitled to provide.
 *
 * These flags are deliberately conservative defaults that hold without any platform
 * API credential. A signed agreement or an approved API scope raises them; nothing
 * in the app raises them implicitly.
 */

export type Platform = 'instagram' | 'tiktok' | 'pinterest' | 'direct' | 'unknown';

export interface PlatformCapability {
  /** Render the platform's official embed. */
  canEmbed: boolean;
  /** Read permitted metadata (title, author handle) without fetching media. */
  canReadMetadata: boolean;
  /** Fetch the media bytes. False everywhere without an agreement. */
  canAccessMedia: boolean;
  /** Run garment detection over the media. Requires `canAccessMedia`. */
  canAnalyse: boolean;
  /** Store a copy of the media on our infrastructure. */
  canStore: boolean;
  /** Whether current app credentials actually authorise the above right now. */
  authorisedNow: boolean;
}

export interface PlatformSupport {
  platform: Platform;
  label: string;
  capability: PlatformCapability;
  /** Plain explanation shown to the user when analysis is unavailable. */
  limitation: string | null;
}

const NO_MEDIA_ACCESS: PlatformCapability = {
  canEmbed: true,
  canReadMetadata: true,
  canAccessMedia: false,
  canAnalyse: false,
  canStore: false,
  authorisedNow: false,
};

const USER_SUPPLIED: PlatformCapability = {
  canEmbed: false,
  canReadMetadata: true,
  canAccessMedia: true,
  canAnalyse: true,
  canStore: true,
  authorisedNow: true,
};

/** Host suffixes, matched against the parsed hostname rather than the raw string. */
const HOSTS: readonly (readonly [Platform, readonly string[]])[] = [
  ['instagram', ['instagram.com', 'instagr.am']],
  ['tiktok', ['tiktok.com', 'vm.tiktok.com']],
  ['pinterest', ['pinterest.com', 'pin.it', 'pinterest.co.uk']],
];

export function detectPlatform(url: string): Platform {
  let host: string;
  try {
    const parsed = new URL(url.trim());
    // Only http(s) — a `javascript:` or `file:` URL is never a post link.
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return 'unknown';
    host = parsed.hostname.toLowerCase().replace(/^www\./, '');
  } catch {
    return 'unknown';
  }

  for (const [platform, suffixes] of HOSTS) {
    // Suffix match on a label boundary, so `evil-instagram.com` does not match.
    if (suffixes.some((s) => host === s || host.endsWith(`.${s}`))) return platform;
  }
  return 'unknown';
}

const LIMITATION =
  'We can save and open this link, but not download the media behind it. ' +
  'Add a screenshot or your own photo to identify the garments.';

export function supportFor(platform: Platform): PlatformSupport {
  switch (platform) {
    case 'instagram':
      return {
        platform,
        label: 'Instagram',
        capability: NO_MEDIA_ACCESS,
        limitation: LIMITATION,
      };
    case 'tiktok':
      return {
        platform,
        label: 'TikTok',
        capability: NO_MEDIA_ACCESS,
        limitation: LIMITATION,
      };
    case 'pinterest':
      return {
        platform,
        label: 'Pinterest',
        capability: NO_MEDIA_ACCESS,
        limitation: LIMITATION,
      };
    case 'direct':
      return {
        platform,
        label: 'Your photo or video',
        capability: USER_SUPPLIED,
        limitation: null,
      };
    default:
      return {
        platform: 'unknown',
        label: 'Link',
        capability: {
          canEmbed: false,
          canReadMetadata: false,
          canAccessMedia: false,
          canAnalyse: false,
          canStore: false,
          authorisedNow: false,
        },
        limitation:
          'That does not look like an Instagram, TikTok or Pinterest post link. You can still add a photo or a screenshot directly.',
      };
  }
}

/** The actions a reference supports, given what we may actually do with it. */
export function availableActions(support: PlatformSupport): readonly string[] {
  const actions = ['Save as inspiration'];
  if (support.capability.canEmbed) actions.push('Open original post');
  if (support.capability.canAnalyse) {
    actions.push(
      'Recreate using my wardrobe',
      'Find this item or similar pieces',
      'Complete the outfit',
      'Adapt to my occasion or budget',
    );
  }
  return actions;
}
