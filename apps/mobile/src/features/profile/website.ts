import * as WebBrowser from 'expo-web-browser';

/**
 * Somebody's own site, checked before it is opened.
 *
 * **The server already builds these, and this checks them anyway.** A
 * profile link is stored as a bare host and turned into a URL by one
 * table on the server, so the scheme is fixed at `https` by
 * construction — but "a string the server sent" is not a property
 * this file can see, and it is exactly the assumption that stops
 * being true when somebody adds a second way to set the field, or
 * when a row written before the rules tightened comes back up.
 *
 * **Two schemes, no exceptions.** A link that is not `http` or
 * `https` is not a website: on a phone a foreign scheme is a jump
 * into another app with a payload somebody else wrote.
 *
 * Returns the address to open, or nothing — so a caller can hide the
 * control rather than show a Visit button that silently does nothing.
 */
export function safeSite(raw: string | null | undefined): string | null {
  const text = (raw ?? '').trim();
  if (!text) return null;
  try {
    const parsed = new URL(text);
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return null;
    return parsed.toString();
  } catch {
    // Not a URL at all. Nothing to open and nothing to repair here:
    // the field is built from a host on the server, so a value that
    // will not parse is a bug to find rather than a string to guess at.
    return null;
  }
}

/** Open it, if it is the kind of thing this app opens. */
export function openSite(raw: string | null | undefined): void {
  const address = safeSite(raw);
  if (address) void WebBrowser.openBrowserAsync(address);
}
