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
    'Two ways out:',
    `  - use another port:  LUXISH_API_PORT=${p + 1} ./scripts/review.sh`,
    '  - or reboot, which releases the orphaned socket',
    '',
    'To see who holds it (Windows):',
    `  Get-NetTCPConnection -LocalPort ${p} | Format-Table LocalAddress,State,OwningProcess`,
    'A PID with no process is the leak.',
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

  let intercepted = false;
  for (const [family, r] of results) {
    if (!r.spec) {
      // One family answering is normal: Docker publishes to whichever
      // it can get. Report it anyway, because it is the clue when the
      // other family turns out to be stale.
      console.log(`  ${family.padEnd(4)} no answer (${r.error})`);
      continue;
    }
    const stale = drift(r.spec, committed);
    if (stale.length === 0) {
      console.log(`  ${family.padEnd(4)} serving this checkout`);
      continue;
    }
    intercepted = true;
    console.error(
      `  ${family.padEnd(4)} serving a DIFFERENT build: ` +
        `${stale.length} schema(s) differ (${stale.slice(0, 4).join(', ')}` +
        `${stale.length > 4 ? ', ...' : ''})`,
    );
  }

  if (intercepted) {
    console.error(INTERCEPTED(port));
    return 1;
  }
  return 0;
}

// `exitCode` rather than `exit`, so pending handles unwind on their own.
process.exitCode = await main();
