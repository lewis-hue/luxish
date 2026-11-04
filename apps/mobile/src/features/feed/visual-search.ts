import { api } from '@/api/client';
import { toFeedFit, type FeedFit } from '@/api/queries/discover-feed';
import { uploadMedia } from '@/features/media/upload';

/**
 * Searching by picture.
 *
 * **It reads the clothes, then searches the words.** There is no image
 * index behind this: the picture goes to the same model that reads a
 * posted fit, and the tags it names are what gets searched. That is
 * the honest version of the camera in a search field, and it is also
 * explicable - the answer says what it thought it saw.
 *
 * **Five to nine seconds.** Reading a photograph costs that, and the
 * caller is given a state to show rather than a promise it will be
 * quick.
 */

/** How long to keep asking before giving up. */
const ATTEMPTS = 40;
const INTERVAL_MS = 700;

export class VisualSearchFailed extends Error {}

export interface VisualResult {
  /** Tags read out of the picture, best first. */
  tags: string[];
  /** What the reader thought the outfit was. */
  outfit: string;
  /**
   * Pins actually tagged with what the reader saw. Often empty: a
   * tag exists only if an author typed it.
   */
  close: FeedFit[];
  /**
   * The nearest pins by what they are *of*.
   *
   * **This is the half that makes the camera worth using.** Before
   * it, a picture nothing was tagged with produced an alert saying
   * "nothing to go on" and left the person exactly where they
   * started, having opened a camera, framed a shot and waited nine
   * seconds. Shown under its own heading, because "the nearest
   * thing" and "this is your picture" are different claims.
   */
  loosely: FeedFit[];
  /** What the picture was read as, for the heading. */
  subject: string;
}

/**
 * **One mapper, shared with the board.**
 *
 * These come back as full feed items from the same serialiser the
 * board uses, so a second mapper here would be a second place for a
 * field to be forgotten - which is the argument `toFeedFit`'s own
 * comment already makes about the tag page.
 */
const pin = (raw: Record<string, unknown>): FeedFit => toFeedFit(raw);

/**
 * Upload a picture and read it into tags.
 *
 * Returns when the reading lands. Throws with something a person can
 * read: a failure here is worth explaining, because they chose a
 * photograph and waited.
 */
export async function searchByPicture(uri: string): Promise<VisualResult> {
  const assetId = await uploadMedia({ uri, kind: 'outfit_photo' });

  const started = await api.POST('/v1/feed/search/visual', {
    body: { media_asset_id: assetId },
  });
  if (started.error || !started.data) {
    throw new VisualSearchFailed('That picture could not be read.');
  }

  const jobId = started.data.job_id;
  for (let attempt = 0; attempt < ATTEMPTS; attempt += 1) {
    const read = await api.GET('/v1/feed/search/visual/{job_id}', {
      params: { path: { job_id: jobId } },
    });
    if (read.error || !read.data) {
      throw new VisualSearchFailed('That search could not be read back.');
    }

    const { state, tags, outfit, error } = read.data;
    if (state === 'succeeded') {
      return {
        tags: tags ?? [],
        outfit: outfit ?? '',
        close: (read.data.close ?? []).map(pin),
        loosely: (read.data.loosely ?? []).map(pin),
        subject: read.data.subject ?? 'outfit',
      };
    }
    if (state === 'failed' || state === 'cancelled') {
      throw new VisualSearchFailed(
        error || 'That picture could not be read.',
      );
    }
    await new Promise((resolve) => setTimeout(resolve, INTERVAL_MS));
  }

  // Out of patience, not out of hope: the job is still running and the
  // reading will land. Said as the state it is rather than as a failure.
  throw new VisualSearchFailed('That is taking longer than usual. Try again.');
}
