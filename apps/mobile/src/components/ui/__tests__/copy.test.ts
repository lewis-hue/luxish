/**
 * House rules for user-facing copy, enforced rather than remembered.
 *
 * The brief is terse, warm and professional, with no "AI slop" tells. Those
 * are easy to agree with and easy to drift away from one string at a time, so
 * the two mechanical rules live here: no em dashes, and no small type.
 *
 * The patterns asserted below come from reading what premium retail actually
 * ships, not from taste. SSENSE, NET-A-PORTER, MR PORTER, COS, Everlane,
 * Arc'teryx, Aesop and Farfetch all converge on: a flat statement of fact,
 * then at most one line saying what will fill the space or what to do next.
 * None of them apologises for an empty bag, and none uses an em dash.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const SRC = join(__dirname, '..', '..', '..');

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      return entry === '__tests__' ? [] : sourceFiles(full);
    }
    return /\.(ts|tsx)$/.test(entry) ? [full] : [];
  });
}

/**
 * Lines with comments removed, so a rule about copy is not tripped by prose in
 * a docblock. Block comments are stripped first, then line comments.
 */
function codeLines(file: string): { line: string; number: number }[] {
  const withoutBlocks = readFileSync(file, 'utf8').replace(
    /\/\*[\s\S]*?\*\//g,
    (match) => match.replace(/[^\n]/g, ' '),
  );
  return withoutBlocks.split('\n').map((line, index) => ({
    // No `$` anchor: these files have CRLF endings, and `.` does not match
    // `\r`, so `.*$` can never reach the end of the string and the comment
    // survives the strip. This test reported ten comment lines until it was
    // dropped.
    line: line.replace(/\/\/.*/, ''),
    number: index + 1,
  }));
}

function offenders(test: (line: string) => boolean): string[] {
  return sourceFiles(SRC).flatMap((file) =>
    codeLines(file)
      .filter(({ line }) => test(line))
      .map(({ number }) => `${relative(SRC, file).replace(/\\/g, '/')}:${number}`),
  );
}

describe('copy', () => {
  it('uses no em dashes anywhere a user can read', () => {
    // The single most recognisable tell of machine-written copy. Every premium
    // retailer checked writes around it, with a colon, a comma, a middot or a
    // full stop. Comments are exempt; this is about the product's voice.
    expect(offenders((line) => line.includes('—'))).toEqual([]);
  });

  it('uses no en dashes in copy either', () => {
    // Same reason, and easier to introduce by accident on a Mac.
    expect(offenders((line) => line.includes('–'))).toEqual([]);
  });

  it('never renders type below the platform legibility floor', () => {
    // Apple publishes 11pt as the iOS minimum, independent of Caption 2 also
    // being 11pt by default. Anything under it is illegible by the platform's
    // own standard, and we had 9.5px and 10px labels before this test existed.
    const tooSmall = offenders((line) => {
      const match = /fontSize:\s*(\d+(?:\.\d+)?)/.exec(line);
      return match !== null && Number(match[1]) < 11;
    });
    expect(tooSmall).toEqual([]);
  });

  it('does not apologise for an empty screen', () => {
    // Verified across SSENSE, Zara, Everlane, COS and Farfetch: "Sorry"
    // appears on no-search-results and never on an empty container. An empty
    // wardrobe is not a failure, so saying sorry invents a problem.
    const apologies = offenders((line) => /(title|body)=["'][^"']*\bSorry\b/i.test(line));
    expect(apologies).toEqual([]);
  });

  it('keeps exclamation marks out of failure copy', () => {
    // Mailchimp's rule, and the one hard error-copy rule it states: "Never use
    // exclamation points in failure messages or alerts."
    const shouty = offenders((line) =>
      /(error|failed|unavailable|problem)[^"']*!["']/i.test(line),
    );
    expect(shouty).toEqual([]);
  });

  it('says "not valid" rather than "invalid"', () => {
    // Polaris: "Avoid using the word 'invalid' to define an error. When
    // appropriate, use 'not valid' instead." It reads as jargon to everyone
    // who has not written a form validator.
    const jargon = offenders((line) => /["'][^"']*\binvalid\b/i.test(line));
    expect(jargon).toEqual([]);
  });

  it('does not say "please" in button labels', () => {
    // Zero instances across the four premium apps surveyed. A control says
    // what happens; politeness in a label reads as padding.
    const polite = offenders((line) => /label=["'][^"']*\bplease\b/i.test(line));
    expect(polite).toEqual([]);
  });

  it('does not open copy with "Let\'s"', () => {
    // The chirpy-onboarding tell. One surveyed retailer uses it and is the
    // outlier; the premium houses never do.
    const chirpy = offenders((line) =>
      /(title|body|label)=["']\s*Let['’]s\b/i.test(line),
    );
    expect(chirpy).toEqual([]);
  });
});
