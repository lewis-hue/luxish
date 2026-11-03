/**
 * How many pictures download at once, and which goes first.
 *
 * Both answers are about one symptom: a board that loads in a jumble.
 * Every mounted tile asks for its own picture, so without a cap a fast
 * scroll fires a download per tile and they all compete for the same
 * connection - the first row then arrives later than it would have if
 * six had gone at a time. And a scroll leaves a trail of requests for
 * tiles already off screen, so arrival order makes the picture somebody
 * is looking at wait behind a dozen they have passed.
 *
 * The queue is tested directly rather than through the hook: the cap and
 * the order are the behaviour, and a filesystem in the way would only
 * test the mock.
 */

import { downloadLoad, queued } from '@/api/queries/post-media';

interface Job {
  work: () => Promise<string>;
  finish: () => void;
  started: () => boolean;
  finished: () => boolean;
}

/** A download that finishes when the test says so. */
function pending(): Job {
  let begun = false;
  let ended = false;
  let done: (value: string) => void = () => {};
  const work = () => {
    begun = true;
    return new Promise<string>((resolve) => {
      done = resolve;
    });
  };
  return {
    work,
    finish: () => {
      if (!begun || ended) return;
      ended = true;
      done('file:///cache/x');
    },
    started: () => begun,
    finished: () => ended,
  };
}

/** Let every microtask the queue uses run. */
async function settle(): Promise<void> {
  for (let at = 0; at < 6; at += 1) await Promise.resolve();
}

/**
 * Finish everything, including what has not started yet.
 *
 * A queued job cannot be finished before it begins - there is nothing to
 * resolve - so the drain goes round until every one has had its turn,
 * which is also how the queue would be emptied in practice.
 */
async function drain(jobs: Job[]): Promise<void> {
  for (let round = 0; round <= jobs.length; round += 1) {
    if (jobs.every((job) => job.finished())) return;
    jobs.forEach((job) => job.finish());
    await settle();
  }
  throw new Error('the queue did not drain');
}

beforeEach(async () => {
  // The queue is module state, so a leaked slot would fail the next test
  // for the wrong reason. Asserted rather than reset: a leak is the bug.
  expect(downloadLoad()).toEqual({ active: 0, waiting: 0 });
});

describe('how many download at once', () => {
  it('runs no more than six and queues the rest', async () => {
    const jobs = Array.from({ length: 10 }, pending);
    const asked = jobs.map((job) => queued(job.work));
    await settle();

    expect(jobs.filter((job) => job.started())).toHaveLength(6);
    expect(downloadLoad()).toEqual({ active: 6, waiting: 4 });

    await drain(jobs);
    await Promise.all(asked);
  });

  it('serves the newest waiter first, because that is what is on screen', async () => {
    const jobs = Array.from({ length: 8 }, pending);
    const asked = jobs.map((job) => queued(job.work));
    await settle();

    // Six running, two waiting: the seventh and the eighth to ask.
    expect(jobs[6].started()).toBe(false);
    expect(jobs[7].started()).toBe(false);

    // One finishes, so one slot frees. The last to ask takes it.
    jobs[0].finish();
    await settle();

    expect(jobs[7].started()).toBe(true);
    expect(jobs[6].started()).toBe(false);

    await drain(jobs);
    await Promise.all(asked);
  });

  it('hands the slot over without ever exceeding the cap', async () => {
    const jobs = Array.from({ length: 9 }, pending);
    const asked = jobs.map((job) => queued(job.work));
    await settle();

    for (let round = 0; round <= jobs.length; round += 1) {
      expect(downloadLoad().active).toBeLessThanOrEqual(6);
      if (jobs.every((job) => job.finished())) break;
      jobs.forEach((job) => job.finish());
      await settle();
    }
    await Promise.all(asked);
    expect(downloadLoad().active).toBeLessThanOrEqual(6);
  });

  it('gives every slot back when the downloads finish', async () => {
    const jobs = Array.from({ length: 9 }, pending);
    const asked = jobs.map((job) => queued(job.work));
    await settle();
    await drain(jobs);
    await Promise.all(asked);
    await settle();

    // The next screen starts from six, not from whatever this one leaked.
    expect(downloadLoad()).toEqual({ active: 0, waiting: 0 });
  });

  it('gives the slot back when a download fails', async () => {
    // A picture that cannot be fetched must not hold a slot for ever, or
    // a handful of failures starves the board.
    const failing = Array.from({ length: 7 }, () => () => Promise.reject(new Error('no')));
    await Promise.all(failing.map((work) => queued(work).catch(() => null)));
    await settle();

    expect(downloadLoad()).toEqual({ active: 0, waiting: 0 });
  });
});
