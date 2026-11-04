/**
 * Is the thing answering on the API port the build we just started?
 *
 * **Not a paranoid question.** A dead process left a socket listening
 * on `0.0.0.0:8010`. Docker could not bind that address, so it took
 * `[::]:8010` and reported the publish as successful. Every IPv4
 * client reached the leaked socket instead, and it answered: a
 * months-old build of this same API, with no workers behind it. The
 * phone signed in, browsed, and queued avatar renders that nothing
 * ever picked up, so the app looked slow rather than misrouted. It
 * cost hours, twice, because every layer reported success.
 *
 * The check is to compare what the port serves against
 * `packages/contracts/openapi.json`, which the suite already pins to
 * the code. A mismatch means the answer came from something other
 * than this checkout.
 *
 * **Over IPv4 on purpose.** `localhost` resolves to `::1` first on
 * Windows, which would have reached the container and found nothing
 * wrong, while the phone - IPv4 over the LAN - got the leaked socket.
 * A check that cannot see the fault is worse than none, because it
 * certifies it.
 *
 *   node scripts/verify-api.mjs [port]
 */

import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, '..');
const CONTRACT = join(REPO, 'packages', 'contracts', 'openapi.json');

const port = Number(process.argv[2] || process.env.LUXISH_API_PORT || 8010);

/** Both families, reported separately: the difference is the diagnosis. */
const HOSTS = [
  ['IPv4', `http://127.0.0.1:${port}/openapi.json`],
  ['IPv6', `http://[::1]:${port}/openapi.json`],
];

async function fetchSpec(url) {
  // **An owned controller, cleared in `finally`.**
  //
  // `AbortSignal.timeout` leaves a libuv timer alive, and exiting
  // while it is pending aborts the process:
  //
  //   Assertion failed: !(handle->flags & UV_HANDLE_CLOSING)
  //
  // which surfaced as exit code 127 - unreadable to a caller looking
  // for 0 or 1, from a script whose whole job is a clear verdict.
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), 10_000);
  try {
    const reply = await fetch(url, { signal: stop.signal });
    if (!reply.ok) return { error: `HTTP ${reply.status}` };
    return { spec: await reply.json() };
  } catch (caught) {
    return { error: caught.cause?.code || caught.name || String(caught) };
  } finally {
    clearTimeout(timer);
  }
}

/** The shapes the mobile client is generated from. */
const schemasOf = (spec) => spec?.components?.schemas ?? {};

function drift(served, committed) {
  const a = schemasOf(served);
  const b = schemasOf(committed);
  const names = [...new Set([...Object.keys(a), ...Object.keys(b)])].sort();
  return names.filter((n) => JSON.stringify(a[n]) !== JSON.stringify(b[n]));
}

const INTERCEPTED = (p) =>
  [
    '',
    `Something other than this checkout is answering on port ${p}.`,
    '',
    'Almost always a socket left behind by a process that has exited.',
    'It keeps listening, Docker quietly publishes to the other address',
    'family, and IPv4 clients - your phone over the LAN - reach the dead',
    'one. It accepts requests and has no workers, so renders queue and',
    'never finish.',
    '',
    'The giveaway is above: one address family serves this checkout and',
    'the other does not. Two of them cannot be the same process.',
    '',
    'Two ways out:',
    `  - use another port:  LUXISH_API_PORT=${p + 1} ./scripts/review.sh`,
    '  - or reboot, which releases the orphaned socket',
    '',
    'To see who holds it (Windows):',
    `  Get-NetTCPConnection -LocalPort ${p} | Format-Table LocalAddress,State,OwningProcess`,
    'A PID with no process is the leak.',
  ].join('\n');

/**
 * **The same drift on every address family is a stale file, not a
 * stranger on the port.**
 *
 * One process cannot answer two ways, so when IPv4 and IPv6 disagree
 * with the contract *identically*, the process is fine and
 * `packages/contracts/openapi.json` is behind the code. Reporting that
 * as an intercepted port sends somebody hunting a leaked socket over a
 * file they have not regenerated - which is exactly what it did the
 * first time this fired.
 */
const STALE_CONTRACT = [
  '',
  'The API is answering, and it is not what the committed contract says.',
  '',
  'Every address family reports the same difference, so this is one',
  'process serving code that is newer than',
  '`packages/contracts/openapi.json` - the file the mobile types are',
  'generated from. Nothing is intercepting the port.',
  '',
  'Regenerate it, from packages/contracts:',
  '  npm run fetch-spec && npm run generate',
  '',
  'Then commit both openapi.json and src/schema.d.ts.',
].join('\n');

async function main() {
  const committed = JSON.parse(await readFile(CONTRACT, 'utf8'));

  const results = [];
  for (const [family, url] of HOSTS) {
    results.push([family, await fetchSpec(url)]);
  }

  if (!results.some(([, r]) => r.spec)) {
    console.error(`Nothing answers on port ${port}.`);
    for (const [family, r] of results) console.error(`  ${family}: ${r.error}`);
    console.error('\nIs the stack up? `./scripts/review.sh doctor`');
    return 1;
  }

  // Each answering family's drift, so the two can be compared: that
  // comparison is what separates a stale file from a stranger.
  const drifts = new Map();
  for (const [family, r] of results) {
    if (!r.spec) {
      // One family answering is normal: Docker publishes to whichever
      // it can get. Report it anyway, because it is the clue when the
      // other family turns out to be stale.
      console.log(`  ${family.padEnd(4)} no answer (${r.error})`);
      continue;
    }
    const stale = drift(r.spec, committed);
    drifts.set(family, stale);
    if (stale.length === 0) {
      console.log(`  ${family.padEnd(4)} serving this checkout`);
      continue;
    }
    console.error(
      `  ${family.padEnd(4)} serving a DIFFERENT build: ` +
        `${stale.length} schema(s) differ (${stale.slice(0, 4).join(', ')}` +
        `${stale.length > 4 ? ', ...' : ''})`,
    );
  }

  const answered = [...drifts.values()];
  if (answered.every((stale) => stale.length === 0)) return 0;

  // **Two families agreeing is evidence; one family is not.**
  //
  // In the incident this was written for, both answered and they
  // disagreed - IPv4 from the dead listener, IPv6 from the container -
  // and two different answers cannot come from one process. Identical
  // drift on both is the opposite: one process, newer than the file.
  //
  // With only one family answering there is nothing to compare, so the
  // honest report names both causes rather than picking the likelier
  // and sending somebody down it.
  const shapes = new Set(answered.map((stale) => JSON.stringify(stale)));
  if (answered.length < 2) {
    console.error(STALE_CONTRACT);
    console.error(
      [
        '',
        'Only one address family answered, so this cannot be told apart',
        'from a leaked socket holding the port. If regenerating does not',
        'settle it, read the note in INTERCEPTED below.',
        INTERCEPTED(port),
      ].join('\n'),
    );
  } else {
    console.error(shapes.size === 1 ? STALE_CONTRACT : INTERCEPTED(port));
  }
  return 1;
}

// `exitCode` rather than `exit`, so pending handles unwind on their own.
process.exitCode = await main();
