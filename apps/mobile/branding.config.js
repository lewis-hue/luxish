/**
 * Raw brand values — the one place a rebrand is edited. (ADR-002)
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

const WORKING_NAME = 'Atelier';
const WEB_ORIGIN = process.env.EXPO_PUBLIC_WEB_ORIGIN || 'https://atelier.example';

/** Lowercased, URL/scheme-safe form of the display name. */
const slug = (process.env.EXPO_PUBLIC_BRAND_NAME || WORKING_NAME)
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, '-')
  .replace(/^-|-$/g, '');

module.exports = {
  name: process.env.EXPO_PUBLIC_BRAND_NAME || WORKING_NAME,
  slug,
  scheme: slug,
  tagline: process.env.EXPO_PUBLIC_BRAND_TAGLINE || 'Your wardrobe, styled',

  /** True while the name is a placeholder; surfaces a dev-only badge. */
  isWorkingName: !process.env.EXPO_PUBLIC_BRAND_NAME,

  legalEntity: 'TBD — must be registered before store submission',

  support: {
    email: process.env.EXPO_PUBLIC_SUPPORT_EMAIL || 'support@atelier.example',
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
