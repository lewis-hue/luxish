/**
 * Raw brand values. The one place a rebrand is edited (ADR-002).
 *
 * Deliberately CommonJS with no imports and no path aliases, because it is consumed
 * from two different runtimes that cannot share module resolution:
 *   - `app.config.ts`, evaluated by the Expo CLI in Node at build time, where the
 *     values are baked into the native binary;
 *   - `src/branding/index.ts`, bundled into the app by Metro.
 *
 * Anything that needs to differ per environment reads from `EXPO_PUBLIC_*` so a
 * rename needs no code change at all.
 */

const BRAND_NAME = 'LUXish';
const WEB_ORIGIN = process.env.EXPO_PUBLIC_WEB_ORIGIN || 'https://luxish.example';

/**
 * Lowercased, URL/scheme-safe form of the display name.
 *
 * "LUXish" slugs to "luxish", which is also the deep-link scheme and the
 * default bundle id suffix. Keep it a single word: a scheme with a hyphen is
 * legal but reads badly in the iOS permission prompt.
 */
const slug = (process.env.EXPO_PUBLIC_BRAND_NAME || BRAND_NAME)
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, '-')
  .replace(/^-|-$/g, '');

module.exports = {
  name: process.env.EXPO_PUBLIC_BRAND_NAME || BRAND_NAME,
  slug,
  scheme: slug,
  tagline: process.env.EXPO_PUBLIC_BRAND_TAGLINE || 'Dress well, daily',

  /**
   * False: "LUXish" is the chosen name, not a placeholder, so the dev-only
   * working-name badge stays off.
   */
  isWorkingName: false,

  legalEntity: 'TBD — must be registered before store submission',

  support: {
    email: process.env.EXPO_PUBLIC_SUPPORT_EMAIL || 'support@luxish.example',
    url: `${WEB_ORIGIN}/support`,
  },

  urls: {
    web: WEB_ORIGIN,
    privacy: `${WEB_ORIGIN}/privacy`,
    terms: `${WEB_ORIGIN}/terms`,
    contentPolicy: `${WEB_ORIGIN}/content-policy`,
    /** Google Play requires this to work without installing the app (§13). */
    accountDeletion: `${WEB_ORIGIN}/delete-account`,
  },

  ids: {
    iosBundle: process.env.EXPO_PUBLIC_IOS_BUNDLE_ID || `com.${slug}.app`,
    androidPackage: process.env.EXPO_PUBLIC_ANDROID_PACKAGE || `com.${slug}.app`,
  },
};
