import { File, Paths } from 'expo-file-system';
import { Asset, requestPermissionsAsync } from 'expo-media-library';
import { isAvailableAsync, shareAsync } from 'expo-sharing';

/**
 * The same picture, at a path the photo library will accept.
 *
 * **Cached files are named by asset id, which is a bare UUID.** The
 * media library reads the kind of a file from its extension and
 * refuses one that has none:
 *
 *     Unable to create an asset
 *     File '3c3d7df2-...' has no extension
 *
 * Renaming the cache instead would be the wrong fix: the id is the
 * key those files are looked up by, and the server does not say what
 * kind they are. So the kind is read from the bytes - the two magic
 * numbers that matter here - and a copy is made under a name that
 * says so. The copy lands in the cache directory, where the system
 * reclaims it.
 */
/** What each extension means to the share sheet. */
const TYPES: Record<string, { mime: string; uti: string }> = {
  png: { mime: 'image/png', uti: 'public.png' },
  jpg: { mime: 'image/jpeg', uti: 'public.jpeg' },
  webp: { mime: 'image/webp', uti: 'org.webmproject.webp' },
  gif: { mime: 'image/gif', uti: 'com.compuserve.gif' },
  heic: { mime: 'image/heic', uti: 'public.heic' },
  avif: { mime: 'image/avif', uti: 'public.avif' },
};

/**
 * What kind of picture this is, from the first bytes of the file.
 *
 * Returns null when it does not recognise the header, which is not
 * the same as "not a picture" - see `withExtension`.
 */
function pictureKind(bytes: Uint8Array): string | null {
  const at = (i: number) => bytes[i] ?? -1;
  const ascii = (from: number, text: string) =>
    [...text].every((c, i) => at(from + i) === c.charCodeAt(0));

  if (at(0) === 0x89 && ascii(1, 'PNG')) return 'png';
  if (at(0) === 0xff && at(1) === 0xd8 && at(2) === 0xff) return 'jpg';
  // RIFF....WEBP
  if (ascii(0, 'RIFF') && ascii(8, 'WEBP')) return 'webp';
  if (ascii(0, 'GIF8')) return 'gif';
  // ....ftyp, then the brand: heic, heix, mif1, avif.
  if (ascii(4, 'ftyp')) {
    if (ascii(8, 'avif')) return 'avif';
    return 'heic';
  }
  return null;
}

async function withExtension(uri: string): Promise<string> {
  const source = new File(uri);
  if (source.extension) return uri;

  // **Never refuses.** The first version threw on anything that was
  // not PNG or JPEG, and the avatar renders came back in a third
  // format - so saving a picture the app had just drawn answered
  // "that file is not a picture this app can save", which was both
  // wrong and mine. An unrecognised header now falls back to jpg
  // rather than stopping: the photo library reads the file itself,
  // and the extension is only there because `Asset.create` insists
  // on one.
  let kind: string | null = null;
  try {
    kind = pictureKind(await source.bytes());
  } catch {
    // Unreadable here is not a reason to refuse either; the copy
    // below will fail honestly if the file is genuinely gone.
  }
  if (__DEV__ && kind === null) {
    console.warn('[keep] unrecognised picture header, saving as jpg:', uri);
  }

  const copy = new File(Paths.cache, `${source.name}.${kind ?? 'jpg'}`);
  if (copy.exists) copy.delete();
  source.copy(copy);
  return copy.uri;
}

/**
 * Save a picture of somebody's avatar to their photos.
 *
 * **Write-only permission.** `requestPermissionsAsync(true)` asks for the
 * narrowest thing that does the job. Saving one picture is no reason to
 * hold a key to somebody's entire camera roll, and on iOS the write-only
 * prompt is also the one people say yes to.
 *
 * **The file is already local.** Renders are downloaded and cached by
 * `useRenders` before they are ever shown, so what arrives here is a
 * `file://` URI and there is nothing to fetch. A remote URL is refused
 * rather than quietly downloaded: it would mean the caller handed over
 * something that has not been through the authenticated fetch, and
 * saving that is not a thing this function should invent a way to do.
 *
 * Throws with a readable message, so the caller can say what happened in
 * place rather than inferring it from a boolean.
 */
export async function keepToPhotos(uri: string): Promise<void> {
  if (!uri.startsWith('file://')) {
    throw new Error('That picture is not ready to save yet.');
  }

  const permission = await requestPermissionsAsync(true);
  if (!permission.granted) {
    throw new Error(
      'Saving needs permission to add to your photos. You can grant it in Settings.',
    );
  }

  await Asset.create(await withExtension(uri));
}

/**
 * Hand a picture to whatever the phone can send it with.
 *
 * **The system sheet, not a list of apps we chose.** Messages,
 * Instagram, email, AirDrop and a file manager are all in it already,
 * and every one somebody actually uses is there because it is
 * installed rather than because this app integrated with it.
 *
 * Posting it *here* is a different act and not this: a fit on the
 * board has an author, a caption and a screen, so it goes through
 * compose like anything else somebody publishes.
 *
 * Same local-file rule as `keepToPhotos`, for the same reason.
 */
export async function sharePicture(uri: string): Promise<void> {
  if (!uri.startsWith('file://')) {
    throw new Error('That picture is not ready to share yet.');
  }
  if (!(await isAvailableAsync())) {
    throw new Error('Sharing is not available on this device.');
  }
  // Same extension problem, different symptom: a share sheet with a
  // extension-less file offers the wrong apps, or none.
  const named = await withExtension(uri);
  const type = TYPES[named.slice(named.lastIndexOf('.') + 1)] ?? TYPES.jpg;
  await shareAsync(named, {
    mimeType: type.mime,
    UTI: type.uti,
    dialogTitle: 'Share this picture',
  });
}
