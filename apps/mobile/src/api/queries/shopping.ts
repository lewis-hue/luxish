/**
 * The curated shop.
 *
 * Every payload carries `provider: "curated"` and every offer carries
 * `availability: "unverified"` plus the date its price was last true.
 * The screens render those facts; nothing here may launder a curated
 * reference into a live quote. Buying is a link out to the retailer's
 * own site, which is also what both app stores require for physical
 * goods.
 */

import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/client';

export interface OfferMatch {
  productId: string;
  title: string;
  brand: string;
  categoryId: string;
  slot: string;
  colour: string | null;
  retailer: { name: string; homepage: string; verified: boolean };
  priceMinor: number;
  currency: string;
  availability: 'unverified' | 'in_stock' | 'out_of_stock';
  retrievedAt: string;
  stale: boolean;
  sourceUrl: string;
  matchLabel: 'confirmed_item' | 'likely_match' | 'similar_style';
}

/**
 * One place on the open web that sells this garment.
 *
 * Separate from `OfferMatch`, which is a row in the seeded
 * catalogue and carries a price, a retailer record and a
 * retrieved-at date. A web result has a title, a seller and a link
 * and claims nothing else - pretending otherwise would mean
 * inventing a price nobody checked.
 */
export interface ShopLink {
  title: string;
  url: string;
  seller: string;
}

/** The wire calls the shop `retailer`; the app calls it a seller. */
function mapLink(link: {
  title: string;
  retailer: string;
  url: string;
}): ShopLink {
  return { title: link.title, seller: link.retailer, url: link.url };
}

export interface ShopSection {
  key: string;
  title: string;
  reason: string;
  items: OfferMatch[];
  /**
   * Where to actually buy it, when the catalogue has nothing.
   *
   * **The catalogue is a seeded table of twenty-eight products**, so
   * for almost every real garment `items` is empty and this is the
   * whole answer. The server searched each piece the vision pass
   * named in the photograph - "brown top-handle handbag", not
   * "handbag" - which is what makes the shelf belong to this pin.
   */
  links: ShopLink[];
}

function mapItem(item: {
  product_id: string;
  title: string;
  brand: string;
  category_id: string;
  slot: string;
  colour?: string | null;
  retailer: { name: string; homepage: string; verified: boolean };
  price_minor: number;
  currency: string;
  availability: OfferMatch['availability'];
  retrieved_at: string;
  stale: boolean;
  source_url: string;
  match_label: OfferMatch['matchLabel'];
}): OfferMatch {
  return {
    productId: String(item.product_id),
    title: item.title,
    brand: item.brand,
    categoryId: item.category_id,
    slot: item.slot,
    colour: item.colour ?? null,
    retailer: item.retailer,
    priceMinor: item.price_minor,
    currency: item.currency,
    availability: item.availability,
    retrievedAt: item.retrieved_at,
    stale: item.stale,
    sourceUrl: item.source_url,
    matchLabel: item.match_label,
  };
}

export function useShopSearch(
  params: { category?: string; slot?: string; colour?: string },
  enabled: boolean,
) {
  return useQuery<OfferMatch[]>({
    queryKey: ['shopping', 'search', params] as const,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/shopping/search', {
        params: {
          query: {
            category: params.category,
            slot: params.slot,
            colour: params.colour,
          },
        },
      });
      return (data?.items ?? []).map(mapItem);
    },
  });
}

export function useShopRecommendations(enabled: boolean) {
  return useQuery<ShopSection[]>({
    queryKey: ['shopping', 'recommendations'] as const,
    enabled,
    queryFn: async () => {
      const { data } = await api.GET('/v1/shopping/recommendations');
      return (data?.sections ?? []).map((section) => ({
        key: section.key,
        title: section.title,
        reason: section.reason,
        items: (section.items ?? []).map(mapItem),
        links: (section.links ?? []).map(mapLink),
      }));
    },
  });
}

/**
 * Something like each garment in one posted fit, a section per piece.
 *
 * **What "shop the look" was always supposed to mean.** The row
 * pushed the generic recommendations - a shelf built from gaps in
 * your own wardrobe, which is a fine shelf and has nothing to do
 * with the photograph it was tapped from.
 *
 * The identification is already done: reading a fit writes down
 * each garment in it, once per post for everybody, because the
 * try-on and the caption both need that. So this costs no model
 * call.
 *
 * An empty list is a real answer - the catalogue has nothing like
 * those garments - and the screen says so rather than padding it.
 */
export function useShopForFit(postId: string | null, enabled: boolean) {
  return useQuery<ShopSection[]>({
    queryKey: ['shopping', 'for-fit', postId] as const,
    enabled: enabled && Boolean(postId),
    queryFn: async () => {
      const { data } = await api.GET('/v1/shopping/for-fit/{post_id}', {
        params: { path: { post_id: postId as string } },
      });
      return (data?.sections ?? []).map((section) => ({
        key: section.key,
        title: section.title,
        reason: section.reason,
        items: (section.items ?? []).map(mapItem),
        links: (section.links ?? []).map(mapLink),
      }));
    },
  });
}

/** "KSh 4,990", from integer minor units. Arithmetic on the integer,
 *  formatting by the locale, never a float in between. */
export function formatPrice(minor: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      maximumFractionDigits: 0,
    }).format(minor / 100);
  } catch {
    return `${currency} ${Math.round(minor / 100)}`;
  }
}

/** The provenance line every card carries: when the price was true, and
 *  that nothing has checked a shelf. */
export function checkedLine(match: Pick<OfferMatch, 'retrievedAt' | 'stale'>): string {
  const date = new Date(match.retrievedAt);
  const day = Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  const base = day ? `Curated reference, checked ${day}.` : 'Curated reference.';
  return match.stale ? `${base} May be out of date.` : base;
}
