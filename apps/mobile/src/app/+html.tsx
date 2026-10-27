import { ScrollViewStyleReset } from 'expo-router/html';
import type { PropsWithChildren } from 'react';

import { BRAND } from '@/branding';

/**
 * The HTML document wrapping the web build.
 *
 * `web.output` is `server` on SDK 58, so this runs on the server at request time and
 * never in the browser — no hooks, no browser globals, no client state.
 *
 * It exists because the generated document had no `<title>`, which leaves a blank
 * browser tab, and no theme-aware background, which produces a white flash before
 * the app paints on a dark-mode device.
 */
export default function Root({ children }: PropsWithChildren) {
  return (
    <html lang="en">
      <head>
        <meta charSet="utf-8" />
        <meta httpEquiv="X-UA-Compatible" content="IE=edge" />
        {/* `viewport-fit=cover` is what makes the CSS safe-area insets resolve. */}
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1, shrink-to-fit=no, viewport-fit=cover"
        />
        {/* From branding.config.js, so a rebrand reaches the browser tab too. */}
        <title>{`${BRAND.name} — ${BRAND.tagline}`}</title>
        <meta name="description" content={BRAND.tagline} />
        {/* Lets the browser render form controls and scrollbars in the right scheme. */}
        <meta name="color-scheme" content="light dark" />

        {/* Disables body scrolling on web so ScrollView components behave natively. */}
        <ScrollViewStyleReset />

        {/*
          Paints the theme ground before React mounts. Without this a dark-mode
          device flashes white on every navigation, which is the single most
          noticeable web-preview defect.
        */}
        {/*
          Passed as children rather than via dangerouslySetInnerHTML: React renders
          style children as text, and avoiding that API means there is no path here
          for untrusted content to become markup, now or after a later edit.
        */}
        <style>{BACKGROUND_CSS}</style>
      </head>
      <body>{children}</body>
    </html>
  );
}

/**
 * A static constant — no interpolation, so nothing user-supplied can reach it.
 * Keep the values in sync with `Colors.light.background` / `Colors.dark.background`;
 * they are duplicated because this runs before the JS theme module loads.
 */
const BACKGROUND_CSS = `
body { background-color: #FAF7F2; }
@media (prefers-color-scheme: dark) {
  body { background-color: #121010; }
}
`;
