/**
 * Hashtags: a page per tag, and the tags worth offering.
 *
 * A tag page is a deliberate search rather than a glance, so it is its
 * own request rather than the board filtered client-side: most fits
 * under a tag are outside whatever slice the board happens to be
 * holding, and narrowing that would return a nearly empty page for a tag
 * with a hundred posts behind it.
 */

import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/client';
import { toFeedFit, type FeedFit } from '@/api/queries/discover-feed';

export const tagKeys = {
  all: ['feed', 'tags'] as const,
  one: (tag: string) => ['feed', 'tags', tag] as const,
  typed: (typed: string) => ['feed', 'tags', 'typed', typed] as const,
};

export interface TagPage {
  tag: string;
  fits: FeedFit[];
  /** Tags that appear alongside this one, most shared first. */
  related: readonly string[];
}

export interface TagCount {
  tag: string;
  posts: number;
}

/**
 * Everything under one hashtag.
 *
 * `photographsOnly` drops fits a machine drew — anything built on a
 * render, a studio shot or an avatar. It is part of the key, because
 * the filtered page is a different page and showing the unfiltered one
 * from cache while the other loads is the filter appearing not to work.
 */
export function useTagFeed(
  tag: string,
  enabled: boolean,
  photographsOnly = false,
) {
  return useQuery<TagPage>({
    queryKey: [...tagKeys.one(tag), photographsOnly] as const,
    enabled: enabled && tag.length > 0,
    queryFn: async () => {
      const { data } = await api.GET('/v1/feed/tags/{tag}', {
        params: {
          path: { tag },
          query: photographsOnly ? { photographs_only: true } : {},
        },
      });
      return {
        tag: data?.tag ?? tag,
        fits: (data?.items ?? []).map(toFeedFit),
        related: data?.related ?? [],
      };
    },
  });
}

/** The tags with the most behind them, for a search screen. */
export function usePopularTags(enabled: boolean) {
  return useQuery<TagCount[]>({
    queryKey: tagKeys.all,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/feed/tags');
      return (data?.items ?? []).map((item) => ({
        tag: item.tag,
        posts: item.posts ?? 0,
      }));
    },
  });
}

/**
 * What to offer while somebody is still typing.
 *
 * **The app's own hashtags, not a guessed vocabulary.** Every row has
 * fits behind it, so tapping one cannot land on the empty state — the
 * single worst thing a suggestion can do.
 *
 * Nothing is suggested for a single character: one letter matches most
 * of the tags there are, and a list that long is not a suggestion.
 */
export const MIN_SUGGEST = 2;

export function useTagSuggestions(typed: string, enabled: boolean) {
  const cleaned = typed.trim().replace(/^#/, '').toLowerCase();
  return useQuery<TagCount[]>({
    queryKey: tagKeys.typed(cleaned),
    enabled: enabled && cleaned.length >= MIN_SUGGEST,
    queryFn: async () => {
      const { data } = await api.GET('/v1/feed/tags', {
        params: { query: { q: cleaned, limit: 12 } },
      });
      return (data?.items ?? []).map((item) => ({
        tag: item.tag,
        posts: item.posts ?? 0,
      }));
    },
  });
}
