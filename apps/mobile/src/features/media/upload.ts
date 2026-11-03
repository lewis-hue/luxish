/**
 * Putting a photograph on the server.
 *
 * **One upload path, used by everything that uploads.** This was the first
 * half of `uploadGarment`, and the profile photograph needed exactly the
 * same forty lines — the authorisation, the on-disk read, the foreground
 * session, the abort timer, the status check. Copying them would have made
 * two places to fix the next time one of those comments turns out to be
 * load-bearing, and every one of them already is: each describes a specific
 * way this silently failed.
 *
 * Returns the media asset id. What that asset then *becomes* — a garment, a
 * profile picture — is the caller's business and is deliberately not here.
 */

import { File, UploadType } from 'expo-file-system';

import { api, API_BASE_URL } from '@/api/client';
import { accessToken } from '@/features/auth/session';

/**
 * Thrown when there is no session to upload under.
 *
 * Lives here rather than in `wardrobe/sync`, which is where it started: the
 * two modules would otherwise each declare a class of the same name, and
 * `catch (e) { e instanceof NotSignedIn }` would be true for one of them and
 * false for the other depending on which module the thrower imported.
 */
export class NotSignedIn extends Error {
  constructor(message = 'Sign in to upload.') {
    super(message);
    this.name = 'NotSignedIn';
  }
}

/** How long a single PUT may take before it is abandoned. */
const UPLOAD_TIMEOUT_MS = 60_000;

/**
 * Content type from a file URI.
 *
 * The picker gives a path, not a MIME type, and the upload authorisation is
 * rejected for a type the server does not allow. Guessing from the extension
 * is sufficient because the server validates the bytes anyway.
 */
export function contentTypeFor(uri: string): string {
  const extension = uri.split('?')[0].split('.').pop()?.toLowerCase();
  if (extension === 'png') return 'image/png';
  if (extension === 'webp') return 'image/webp';
  if (extension === 'heic' || extension === 'heif') return 'image/heic';

  // **Video and sound, added when a thread learned to carry them.**
  // Everything fell through to `image/jpeg`, which is the right
  // default for a camera roll photograph and wrong for anything
  // else: a voice note uploaded as a JPEG is a file the app will
  // later try to draw.
  if (extension === 'mp4' || extension === 'm4v') return 'video/mp4';
  if (extension === 'mov') return 'video/quicktime';
  if (extension === 'm4a') return 'audio/m4a';
  if (extension === 'caf') return 'audio/x-caf';
  if (extension === 'mp3') return 'audio/mpeg';
  if (extension === 'wav') return 'audio/wav';

  return 'image/jpeg';
}

/**
 * Upload one image and return the media asset id it was stored under.
 *
 * `kind` is the server's media taxonomy, which decides size limits and which
 * derivative jobs run. It is not cosmetic: a `garment_photo` is cut out and
 * categorised, and a profile picture must not be.
 */
export async function uploadMedia(input: {
  uri: string;
  kind:
    | 'garment_photo'
    | 'outfit_photo'
    | 'inspiration'
    | 'avatar'
    //: A picture of the person, for building an avatar that looks
    //: like them. Behind its own `likeness` consent.
    | 'avatar_source'
    //: The picture across the top of a profile. Decoration, and
    //: screened like a caption because everybody who opens the
    //: page sees it.
    | 'profile_banner'
    //: A picture attached to a message. Private to the two people in
    //: that thread, and never read for clothes: a photograph sent to
    //: one person is not evidence of anything they own.
    | 'message_media';
}): Promise<string> {
  const token = await accessToken();
  if (!token) throw new NotSignedIn();

  // Read as a file on disk, never as a blob in JavaScript. `fetch(uri)` then
  // `.blob()` pulls the whole photograph into React Native's blob store and
  // back out through base64, which the runtime warns about and which silently
  // failed to produce a request body at all for camera-sized JPEGs: the
  // authorisation succeeded and the PUT never left the device.
  const file = new File(input.uri);
  if (!file.exists) {
    throw new Error('That photo is no longer on this device.');
  }
  // `size` is nullable because a `File` may point at a path that holds no
  // file. `exists` has already ruled that out, so a null here means the
  // platform could not stat it, which is not something to upload past.
  const byteSize = file.size;
  if (byteSize === null || byteSize === 0) {
    throw new Error('That photo could not be read.');
  }

  const contentType = contentTypeFor(input.uri);

  const authorized = await api.POST('/v1/uploads/authorize', {
    body: {
      // The caller's kind, not a constant. This hardcoded 'garment_photo'
      // once, which filed every profile picture under the taxonomy that
      // gets cut out and categorised — the opposite of what the docstring
      // above promises.
      kind: input.kind,
      content_type: contentType,
      content_length: byteSize,
    },
  });
  if (authorized.error || !authorized.data) {
    throw new Error('Could not authorise the upload.');
  }
  const { asset_id, upload_url, required_headers } = authorized.data;

  // Not sent through the typed client: the destination is a storage URL the
  // server chose, not an endpoint in our own contract, and in a deployment it
  // is object storage that knows nothing about our auth. The headers the
  // authorisation hands back are passed through unchanged for the same reason.
  //
  // `BINARY_CONTENT` puts the file in the request body as-is, which is what
  // both receivers expect; `MULTIPART` would wrap it in form framing that
  // neither one unwraps. The bytes go from disk to socket natively, so a 4 MB
  // photograph never occupies the JS heap.
  // A hung upload has to become an error. Without this the promise below can
  // stay unsettled indefinitely and the garment spins forever with nothing to
  // show the user and nothing in any log.
  const abort = new AbortController();
  const expiry = setTimeout(() => abort.abort(), UPLOAD_TIMEOUT_MS);

  let put;
  try {
    put = await file.upload(upload_url, {
      httpMethod: 'PUT',
      uploadType: UploadType.BINARY_CONTENT,
      mimeType: contentType,
      // Foreground, not the default background session. A background
      // URLSession is discretionary: iOS decides when to run it, and for a
      // plain-http address on the local network it defers the task instead of
      // sending it. The promise never settles, so the upload neither arrives
      // nor fails. Background scheduling is the right default for a large
      // upload to production object storage over https, and the wrong one for
      // every development build talking to a LAN API.
      sessionType: 'foreground',
      signal: abort.signal,
      headers: {
        ...(required_headers ?? {}),
        // Only the local development receiver needs this; a signed URL carries
        // its own authorisation in the query string and ignores it.
        ...(upload_url.startsWith(API_BASE_URL)
          ? { Authorization: `Bearer ${token}` }
          : {}),
      },
    });
  } catch (caught) {
    if (abort.signal.aborted) {
      throw new Error('The upload timed out. Check the connection and retry.');
    }
    throw caught;
  } finally {
    clearTimeout(expiry);
  }

  // Resolves with the status rather than throwing on a 4xx, so this is the
  // only place the upload's own failure is detected.
  if (put.status < 200 || put.status >= 300) {
    if (__DEV__) {
      console.error('[wardrobe] PUT rejected', put.status, put.body);
    }
    throw new Error(`The upload was rejected (${put.status}).`);
  }

  return asset_id;
}
