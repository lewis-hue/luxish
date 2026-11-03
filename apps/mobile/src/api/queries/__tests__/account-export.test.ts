/**
 * What the export row says about itself.
 *
 * The row is one control with four states behind it, and the words
 * are the only thing telling somebody which one they are in. A wrong
 * line here is a person tapping "Save my copy" at a file that is not
 * there yet, or waiting on an archive that failed an hour ago.
 *
 * The cap in particular: an archive that left pictures out is still
 * worth downloading, and somebody has to be told so they can ask for
 * another to get the rest. Silence there reads as a complete copy.
 */

import { exportLine, readableSize } from '@/api/queries/account-export';
import type { DataExport } from '@/api/queries/account-export';

function row(over: Partial<DataExport>): DataExport {
  return {
    id: 'e1',
    state: 'ready',
    byteSize: null,
    picturesIncluded: 0,
    picturesOmitted: 0,
    failure: null,
    expiresAt: null,
    createdAt: '2026-11-03T00:00:00Z',
    ...over,
  };
}

describe('exportLine', () => {
  it('invites somebody who has never asked', () => {
    expect(exportLine(null)).toContain('Get a copy');
    expect(exportLine(undefined)).toContain('Get a copy');
  });

  it('says it is working, not that it is ready', () => {
    const line = exportLine(row({ state: 'gathering' }));
    expect(line).toContain('ready');
    expect(line).toContain('Getting');
  });

  it('names the size once there is a file', () => {
    expect(exportLine(row({ byteSize: 2_300_000 }))).toContain('2.2 MB');
  });

  it('says when pictures were left out', () => {
    // **The cap, reported.** An archive that silently dropped half a
    // wardrobe reads as a complete copy of an account, and somebody
    // would find out it was not at the worst possible time.
    const line = exportLine(row({ byteSize: 1024, picturesOmitted: 12 }));
    expect(line).toContain('12 pictures left out');
  });

  it('says nothing about omissions when there were none', () => {
    expect(exportLine(row({ byteSize: 1024 }))).not.toContain('left out');
  });

  it('tells somebody to ask again rather than leaving a dead row', () => {
    expect(exportLine(row({ state: 'expired' }))).toContain('another');
  });

  it("uses the server's own words for a failure", () => {
    // The server writes the reason in the owner's terms; the client
    // must not replace it with a generic one.
    expect(
      exportLine(row({ state: 'failed', failure: 'This account no longer exists.' })),
    ).toBe('This account no longer exists.');
  });

  it('still says something useful when a failure has no reason', () => {
    expect(exportLine(row({ state: 'failed' }))).toContain('Try again');
  });
});

describe('readableSize', () => {
  it('reads as somebody would say it', () => {
    expect(readableSize(512)).toBe('512 B');
    expect(readableSize(2048)).toBe('2 KB');
    expect(readableSize(1_500_000)).toBe('1.4 MB');
  });

  it('drops the decimal once it stops being information', () => {
    // "142.3 MB" is three characters of noise.
    expect(readableSize(149_000_000)).toBe('142 MB');
  });
});
