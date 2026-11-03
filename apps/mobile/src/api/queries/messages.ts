/**
 * Direct messages.
 *
 * Addressed by the other person rather than a thread id: a screen
 * always knows who it is writing to, so there is never an id to
 * resolve before the first message can be sent.
 *
 * **A sent message lands in the list before the server answers.** A
 * chat that waits a round trip to show what you typed feels broken on
 * a slow connection, and the correction if it fails is small: the line
 * is rolled back and the field keeps the text.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';

export const messageKeys = {
  all: ['messages'] as const,
  thread: (userId: string) => ['messages', 'thread', userId] as const,
};

export interface Line {
  id: string;
  senderId: string;
  body: string;
  sentAt: string;
  /** Written by you. The server decides this, so no client compares ids. */
  mine: boolean;
  /** An attachment, as a media asset id. */
  assetId: string | null;
  /**
   * What `assetId` is: `image`, `video` or `audio`.
   *
   * Null with no attachment, or when its type is one this app cannot
   * present. Without it a client has to assume, and the thread
   * assumed every attachment was a photograph - so a video would
   * have been drawn as a broken picture.
   */
  mediaKind: 'image' | 'video' | 'audio' | null;
  /**
   * Whether the other person has seen it.
   *
   * Only ever true on a message you sent. The server will not say
   * whether you have read theirs: that is reporting on somebody's
   * reading to them, and your own thread already shows it.
   */
  read: boolean;
}

export interface Thread {
  userId: string;
  name: string;
  handle: string | null;
  /** Whether you follow them, so an empty thread can offer it. */
  followed: boolean;
  items: Line[];
  notifies: boolean;
  hidden: boolean;
}

export interface ThreadSummary {
  userId: string;
  name: string;
  handle: string | null;
  last: string | null;
  lastAt: string | null;
  unread: number;
}

export interface Contact {
  userId: string;
  name: string;
  handle: string | null;
}

export interface Messages {
  threads: ThreadSummary[];
  contacts: Contact[];
}

export function useMessages(enabled: boolean) {
  return useQuery<Messages>({
    queryKey: messageKeys.all,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/messages');
      return {
        threads: (data?.threads ?? []).map((item) => ({
          userId: String(item.user_id),
          name: item.name,
          handle: item.handle ?? null,
          last: item.last ?? null,
          lastAt: item.last_at ?? null,
          unread: item.unread ?? 0,
        })),
        contacts: (data?.contacts ?? []).map((item) => ({
          userId: String(item.user_id),
          name: item.name,
          handle: item.handle ?? null,
        })),
      };
    },
  });
}

function toThread(data: Record<string, unknown>): Thread {
  const items = (data.items ?? []) as Record<string, unknown>[];
  return {
    userId: String(data.user_id),
    name: String(data.name),
    handle: (data.handle as string | null) ?? null,
    followed: Boolean(data.followed),
    items: items.map((item) => ({
      id: String(item.id),
      senderId: String(item.sender_id),
      body: String(item.body),
      sentAt: String(item.sent_at),
      mine: Boolean(item.mine),
      assetId: item.asset_id ? String(item.asset_id) : null,
      mediaKind:
        item.media_kind === 'image' ||
        item.media_kind === 'video' ||
        item.media_kind === 'audio'
          ? item.media_kind
          : null,
      read: Boolean(item.read),
    })),
    notifies: data.notifies !== false,
    hidden: Boolean(data.hidden),
  };
}

export function useThread(userId: string, enabled: boolean) {
  return useQuery<Thread>({
    queryKey: messageKeys.thread(userId),
    enabled: enabled && userId.length > 0,
    // A conversation is the one screen where staleness is visible, so
    // it refetches while it is open rather than on focus alone.
    refetchInterval: 15_000,
    queryFn: async () => {
      const { data, error } = await api.GET('/v1/messages/{user_id}', {
        params: { path: { user_id: userId } },
      });
      if (error || !data) throw new Error('No such account.');
      return toThread(data as unknown as Record<string, unknown>);
    },
  });
}

export interface Outgoing {
  body: string;
  /** A picture already uploaded under `message_media`. */
  assetId?: string;
}

export function useSendMessage(userId: string) {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async ({ body, assetId }: Outgoing) => {
      const { data, error } = await api.POST('/v1/messages/{user_id}', {
        params: { path: { user_id: userId } },
        body: assetId ? { body, asset_id: assetId } : { body },
      });
      if (error || !data) throw new Error('That did not send.');
      return data;
    },
    onMutate: async ({ body, assetId }: Outgoing) => {
      await queries.cancelQueries({ queryKey: messageKeys.thread(userId) });
      const before = queries.getQueryData<Thread>(messageKeys.thread(userId));
      if (before) {
        queries.setQueryData<Thread>(messageKeys.thread(userId), {
          ...before,
          items: [
            ...before.items,
            {
              // Local only, and replaced by the server's row on the
              // next read. Prefixed so nothing mistakes it for one.
              id: `pending-${before.items.length}-${body.length}`,
              senderId: 'me',
              body,
              sentAt: new Date().toISOString(),
              mine: true,
              assetId: assetId ?? null,
              // Not known until the server has classified it.
              mediaKind: assetId ? 'image' : null,
              // Nobody has seen a message that has not arrived yet.
              read: false,
            },
          ],
        });
      }
      return { before };
    },
    onError: (_error, _outgoing, context) => {
      if (context?.before) {
        queries.setQueryData(messageKeys.thread(userId), context.before);
      }
    },
    onSettled: () => {
      void queries.invalidateQueries({ queryKey: messageKeys.thread(userId) });
      void queries.invalidateQueries({ queryKey: messageKeys.all });
    },
  });
}

export function useMarkThreadRead() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (userId: string) => {
      await api.PUT('/v1/messages/{user_id}/read', {
        params: { path: { user_id: userId } },
      });
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: messageKeys.all });
    },
  });
}

export function useThreadSettings(userId: string) {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (next: { notifies?: boolean; hidden?: boolean }) => {
      await api.PATCH('/v1/messages/{user_id}/settings', {
        params: { path: { user_id: userId } },
        body: next,
      });
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: messageKeys.thread(userId) });
      void queries.invalidateQueries({ queryKey: messageKeys.all });
    },
  });
}

/**
 * Take back a message you sent.
 *
 * Both copies: a message is its sender's, and a delete that left it
 * standing in the other person's conversation would be a button that
 * lies.
 */
export function useUnsend(userId: string) {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (messageId: string) => {
      const { error } = await api.DELETE(
        '/v1/messages/{user_id}/messages/{message_id}',
        { params: { path: { user_id: userId, message_id: messageId } } },
      );
      if (error) throw new Error('That could not be deleted.');
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: messageKeys.thread(userId) });
      void queries.invalidateQueries({ queryKey: messageKeys.all });
    },
  });
}

/**
 * Take one message out of your own copy of the thread.
 *
 * **Not the same as unsending, and offered to the other person.**
 * `useUnsend` belongs to whoever wrote the message and removes it
 * from both conversations. This belongs to whoever is reading: the
 * sender's copy is untouched and they are not told, because
 * somebody choosing not to look at something is not an event in
 * their conversation.
 *
 * Before this, a person who received something they would rather
 * not scroll past again could only clear the entire thread, which
 * takes every other message with it.
 */
export function useHideMessage(userId: string) {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (messageId: string) => {
      const { error } = await api.PUT(
        '/v1/messages/{user_id}/messages/{message_id}/hide',
        { params: { path: { user_id: userId, message_id: messageId } } },
      );
      if (error) throw new Error('That could not be removed.');
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: messageKeys.thread(userId) });
      void queries.invalidateQueries({ queryKey: messageKeys.all });
    },
  });
}

/**
 * Delete this conversation, for you.
 *
 * Their copy is theirs. This draws a line under what you have seen
 * rather than reaching into somebody else's phone, and anything that
 * arrives afterwards arrives normally - clearing is not a way to stop
 * hearing from somebody, which is what blocking is for.
 */
export function useClearThread() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (userId: string) => {
      await api.DELETE('/v1/messages/{user_id}', {
        params: { path: { user_id: userId } },
      });
    },
    onSuccess: (_result, userId) => {
      void queries.invalidateQueries({ queryKey: messageKeys.thread(userId) });
      void queries.invalidateQueries({ queryKey: messageKeys.all });
    },
  });
}
