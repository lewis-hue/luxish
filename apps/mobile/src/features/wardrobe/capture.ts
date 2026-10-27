// `ImageManipulator` is a named export carrying the contextual API; `manipulate`
// is a method on it, not a module-level function. `manipulateAsync` is deprecated
// on SDK 58 in favour of this.
import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import * as ImagePicker from 'expo-image-picker';
import { useCallback, useState } from 'react';

/**
 * Getting garment photos off the device and ready to upload.
 *
 * Three jobs, in order: ask for permission at the point of use, let the user pick or
 * shoot, then compress before anything leaves the phone.
 *
 * Compression is not an optimisation here, it is a correctness requirement. A modern
 * phone camera produces 4–8 MB images; twenty of those is well over 100 MB, which on
 * a mobile connection is a failed upload and a flat battery. We resize to a long edge
 * the model and the UI both work from, and keep enough detail for garment attributes
 * to be readable.
 *
 * SDK 58 notes: `manipulateAsync` is deprecated in favour of the
 * `useImageManipulator`/`manipulate()` context API, which is what this uses. HEIC is
 * transcoded to JPEG — iOS shoots HEIC by default and several downstream services,
 * including reverse image search, reject it.
 */

/**
 * 1600px long edge. Enough for colour, pattern and construction to be legible, and
 * roughly a fifth of the bytes of an untouched camera original.
 */
const MAX_EDGE = 1600;

/** Quality 0.8 is the knee of the curve — below it, fabric texture starts to go. */
const QUALITY = 0.8;

/** Matches the backend's bulk endpoint cap. */
export const MAX_BULK_ITEMS = 20;

export interface CapturedPhoto {
  uri: string;
  width: number;
  height: number;
  mimeType: string;
  /** Original filename where the picker supplied one. Used as a name suggestion. */
  suggestedName: string | null;
}

/** Turns a picker asset into something uploadable. */
async function prepare(asset: ImagePicker.ImagePickerAsset): Promise<CapturedPhoto> {
  const longest = Math.max(asset.width, asset.height);
  const scale = longest > MAX_EDGE ? MAX_EDGE / longest : 1;

  const context = ImageManipulator.manipulate(asset.uri);
  if (scale < 1) {
    context.resize({
      width: Math.round(asset.width * scale),
      height: Math.round(asset.height * scale),
    });
  }

  const image = await context.renderAsync();
  // Always JPEG: it transcodes HEIC, which iOS shoots by default and which several
  // downstream services reject outright.
  const saved = await image.saveAsync({
    compress: QUALITY,
    format: SaveFormat.JPEG,
  });

  return {
    uri: saved.uri,
    width: saved.width,
    height: saved.height,
    mimeType: 'image/jpeg',
    suggestedName: asset.fileName ? stripExtension(asset.fileName) : null,
  };
}

function stripExtension(filename: string): string {
  return filename.replace(/\.[^.]+$/, '');
}

export type PermissionOutcome = 'granted' | 'denied' | 'cancelled';

export function useGarmentCapture() {
  const [cameraPermission, requestCamera] = ImagePicker.useCameraPermissions();
  const [libraryPermission, requestLibrary] = ImagePicker.useMediaLibraryPermissions();
  const [busy, setBusy] = useState(false);

  /**
   * Photograph one garment.
   *
   * Permission is requested here, at the moment the user asked for the camera, not
   * at launch — §13 requires that, and a cold permission prompt is also the single
   * most common reason a user declines.
   */
  const photograph = useCallback(async (): Promise<CapturedPhoto[] | PermissionOutcome> => {
    if (!cameraPermission?.granted) {
      const result = await requestCamera();
      if (!result.granted) return 'denied';
    }

    setBusy(true);
    try {
      const picked = await ImagePicker.launchCameraAsync({
        mediaTypes: ['images'],
        quality: 1,
        exif: false, // Strip location before it ever reaches us (§13).
      });
      if (picked.canceled) return 'cancelled';
      return [await prepare(picked.assets[0])];
    } finally {
      setBusy(false);
    }
  }, [cameraPermission?.granted, requestCamera]);

  /**
   * Pick up to {@link MAX_BULK_ITEMS} garments from the library.
   *
   * Multi-select is the bulk upload: asking someone to add forty garments one at a
   * time is the reason wardrobe apps go unused after the first evening.
   */
  const pickFromLibrary = useCallback(
    async (limit = MAX_BULK_ITEMS): Promise<CapturedPhoto[] | PermissionOutcome> => {
      if (!libraryPermission?.granted) {
        const result = await requestLibrary();
        if (!result.granted) return 'denied';
      }

      setBusy(true);
      try {
        const picked = await ImagePicker.launchImageLibraryAsync({
          mediaTypes: ['images'],
          allowsMultipleSelection: true,
          selectionLimit: Math.min(limit, MAX_BULK_ITEMS),
          quality: 1,
          exif: false,
        });
        if (picked.canceled) return 'cancelled';
        // Sequential rather than parallel: twenty concurrent decode-and-resize
        // operations will out-of-memory a mid-range Android device.
        const prepared: CapturedPhoto[] = [];
        for (const asset of picked.assets) {
          prepared.push(await prepare(asset));
        }
        return prepared;
      } finally {
        setBusy(false);
      }
    },
    [libraryPermission?.granted, requestLibrary],
  );

  return {
    photograph,
    pickFromLibrary,
    busy,
    cameraDenied: cameraPermission?.granted === false && !cameraPermission.canAskAgain,
    libraryDenied: libraryPermission?.granted === false && !libraryPermission.canAskAgain,
  };
}

export const CAPTURE_LIMITS = { maxEdge: MAX_EDGE, quality: QUALITY, maxBulk: MAX_BULK_ITEMS };
