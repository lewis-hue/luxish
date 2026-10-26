/**
 * Typed view of the brand configuration. (ADR-002)
 *
 * Values come from `branding.config.js` at the app root, which `app.config.ts` also
 * reads — so the native binary and the JS bundle cannot drift apart. Edit the brand
 * there, never here.
 */

// eslint-disable-next-line @typescript-eslint/no-require-imports
const brand = require('../../branding.config.js');

export interface Brand {
  /** Display name. A working name until the brand is decided. */
  readonly name: string;
  readonly slug: string;
  /** Deep-link scheme; identical to the `scheme` in the Expo config. */
  readonly scheme: string;
  readonly tagline: string;
  /** True while the name is a placeholder. */
  readonly isWorkingName: boolean;
  readonly legalEntity: string;
  readonly support: { readonly email: string; readonly url: string };
  readonly urls: {
    readonly web: string;
    readonly privacy: string;
    readonly terms: string;
    readonly contentPolicy: string;
    readonly accountDeletion: string;
  };
  readonly ids: {
    readonly iosBundle: string;
    readonly androidPackage: string;
    readonly scheme: string;
  };
}

export const BRAND: Brand = {
  name: brand.name,
  slug: brand.slug,
  scheme: brand.scheme,
  tagline: brand.tagline,
  isWorkingName: brand.isWorkingName,
  legalEntity: brand.legalEntity,
  support: brand.support,
  urls: brand.urls,
  ids: { ...brand.ids, scheme: brand.scheme },
};
