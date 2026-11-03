/**
 * A copy of everything you put into this app.
 *
 * Settings has carried a dead "Export my data" row since the account
 * section was built - a control somebody looking for it finds, taps,
 * and nothing happens. This is the live version.
 *
 * **Three steps, because gathering is slow.** Asking answers at once
 * with a row to watch; the server reads every picture the account
 * owns out of object storage and zips them with a JSON of everything
 * else; the file is then downloaded and handed to the OS share sheet.
 * The polling only runs while something is gathering, so an idle
 * Settings screen makes no requests.
 *
 * **The file goes to the share sheet rather than to a folder.** An
 * archive written into the app's own cache is a file nobody can get
 * to - the point is to take the data somewhere else, which on a phone
 * means Files, Mail or Drive, and that is the share sheet.
 */

import { Directory, File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, API_BASE_URL } from '@/api/client';
import { accessToken } from '@/features/auth/session';

export const exportKeys = { latest: ['account-export'] as const };

/** `gathering` is the only state that is not final. */
export type ExportState = 'gathering' | 'ready' | 'failed' | 'expired';

export interface DataExport {
  id: string;
  state: ExportState;
  byteSize: number | null;
  /** How many pictures went in, and how many did not. */
  picturesIncluded: number;
  picturesOmitted: number;
  /** Why it failed, in your own terms. Null unless it did. */
  failure: string | null;
  /** When the download stops working. */
  expiresAt: string | null;
  createdAt: string;
}

function mapExport(row: {
  id: string;
  state: string;
  byte_size?: number | null;
  pictures_included?: number;
  pictures_omitted?: number;
  failure?: string | null;
  expires_at?: string | null;
  created_at: string;
}): DataExport {
  return {
    id: row.id,
    state: row.state as ExportState,
    byteSize: row.byte_size ?? null,
    picturesIncluded: row.pictures_included ?? 0,
    picturesOmitted: row.pictures_omitted ?? 0,
    failure: row.failure ?? null,
    expiresAt: row.expires_at ?? null,
    createdAt: row.created_at,
  };
}

/**
 * The export you have, if any.
 *
 * Polls only while one is gathering. A Settings screen with no export
 * in flight should cost nothing, and an interval that runs regardless
 * is a request every few seconds for the life of the screen.
 */
export function useDataExport(enabled: boolean) {
  return useQuery<DataExport | null>({
    queryKey: exportKeys.latest,
    enabled,
    queryFn: async () => {
      const { data, error } = await api.GET('/v1/account/export', {});
      if (error) throw new Error('Could not check on your copy.');
      return data ? mapExport(data as never) : null;
    },
    refetchInterval: (query) =>
      query.state.data?.state === 'gathering' ? 3000 : false,
    // Always refetched on mount: the state changes on a worker, so
    // whatever is cached from the last visit is a guess.
    refetchOnMount: 'always',
    staleTime: 0,
  });
}

/** Start gathering. Returns the row to watch. */
export function useAskForDataExport() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST('/v1/account/export', {});
      if (error || !data) {
        throw new Error('That could not be started. Try again in a moment.');
      }
      return mapExport(data as never);
    },
    onSuccess: (row) => {
      // Written straight in rather than invalidated, so the screen
      // says "getting your copy ready" on the tap rather than a
      // request later.
      queries.setQueryData<DataExport | null>(exportKeys.latest, row);
    },
  });
}

function directory(): Directory {
  const dir = new Directory(Paths.cache, 'exports');
  if (!dir.exists) dir.create({ intermediates: true });
  return dir;
}

/**
 * Download the archive and offer it to the share sheet.
 *
 * Named for what somebody asked for rather than for the two steps it
 * takes: tapping "Save my copy" should end with the OS asking where
 * to put it, and a download that finished without offering it
 * anywhere would look like a button that did nothing.
 */
export function useSaveDataExport() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (exportId: string) => {
      const token = await accessToken();
      if (!token) throw new Error('Sign in again to download your copy.');

      const target = new File(directory(), `luxish-my-data-${exportId}.zip`);
      // Deleted first rather than reused. The archive behind an id is
      // written once, but a previous attempt can leave a truncated
      // file, and a half-zip that opens to nothing is worse than a
      // second download.
      if (target.exists) target.delete();

      const got = await File.downloadFileAsync(
        `${API_BASE_URL}/v1/account/export/${exportId}/file`,
        target,
        { headers: { Authorization: `Bearer ${token}` }, idempotent: true },
      );

      if (!(await Sharing.isAvailableAsync())) {
        // Honest rather than silent. The file is on the device, and
        // saying where is the only useful thing left to say.
        throw new Error(
          'Your copy downloaded, but this device has nowhere to send it.',
        );
      }
      await Sharing.shareAsync(got.uri, {
        mimeType: 'application/zip',
        dialogTitle: 'Your LUXish data',
        UTI: 'public.zip-archive',
      });
      return got.uri;
    },
    onError: () => {
      // The server may have expired it between the screen rendering
      // and the tap, and the row is the only thing that knows.
      void queries.invalidateQueries({ queryKey: exportKeys.latest });
    },
  });
}

/** What the row says about itself, in the owner's terms. */
export function exportLine(row: DataExport | null | undefined): string {
  if (!row) return 'Get a copy of everything you have added';
  switch (row.state) {
    case 'gathering':
      return 'Getting your copy ready';
    case 'ready': {
      const size = row.byteSize ? ` (${readableSize(row.byteSize)})` : '';
      // "left out for size", not "ask again for the rest": the cap
      // is deterministic, so a second export leaves out the same
      // pictures. They are still in the app, which is the true and
      // useful thing to say.
      const short = row.picturesOmitted
        ? `, ${row.picturesOmitted} pictures left out for size`
        : '';
      return `Your copy is ready${size}${short}`;
    }
    case 'expired':
      return 'That copy has expired. Ask for another';
    case 'failed':
      return row.failure ?? 'That did not finish. Try again';
  }
}

/** Bytes as somebody would say them. */
export function readableSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  const mb = bytes / (1024 * 1024);
  // One decimal below ten, none above: "1.4 MB" is useful and
  // "142.3 MB" is three characters of noise.
  return mb < 10 ? `${mb.toFixed(1)} MB` : `${Math.round(mb)} MB`;
}
