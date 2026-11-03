import * as Linking from 'expo-linking';
import { useLocalSearchParams } from 'expo-router';
import { ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  checkedLine,
  formatPrice,
  useShopForFit,
  useShopRecommendations,
  type OfferMatch,
} from '@/api/queries/shopping';
import { ThemedText } from '@/components/themed-text';
import { EmptyState } from '@/components/ui/empty-state';
import { SkeletonRows } from '@/components/ui/skeleton';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { useFitDetail } from '@/api/queries/discover-feed';
import type { PostItemTag } from '@/api/queries/posts';
import { useAuth } from '@/features/auth/session';
import { useScheme } from '@/hooks/use-theme';

/**
 * The shop: recommendations the app can explain.
 *
 * Two kinds of section and no third: slots the stylist could not fill
 * from the wardrobe, and pieces matching the aesthetics the person chose
 * in taste. Each section states its reason on the screen, because a
 * recommendation that cannot say why is advertising.
 *
 * Everything here is a curated reference with its provenance printed on
 * the card; buying is a link out to the retailer. See `shop/piece` for
 * the full honesty contract.
 */
export default function ShopScreen() {
  const colors = Colors[useScheme()];
  /**
   * The fit being shopped, when the menu sent one.
   *
   * **Without this the screen could not keep the promise its own
   * button made.** "Shop the look" pushed here with nothing
   * identifying the look, so every tap landed on the same generic
   * recommendations whichever fit it came from.
   */
  const { fit: fitId } = useLocalSearchParams<{ fit?: string }>();
  const insets = useSafeAreaInsets();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';
  const recommendations = useShopRecommendations(signedIn);
  // **Something like each garment in the fit, when one was named.**
  // The row that led here promised this fit; the recommendations
  // below are about the wardrobe in general, and are labelled as
  // such once there is something more specific to show.
  const forFit = useShopForFit(fitId ?? null, signedIn && Boolean(fitId));
  // Only when a fit was named. The screen is reached far more often
  // without one, and that case should cost no request.
  const look = useFitDetail(fitId ?? '', signedIn && Boolean(fitId));
  // A piece whose garment or product has gone is reported rather
  // than dropped, so a look does not lose a slot - but there is
  // nothing to shop in one.
  const pieces = (look.data?.items ?? []).filter((item) => item.kind !== 'gone');

  const sections = recommendations.data ?? [];
  const fitSections = forFit.data ?? [];

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.background }}
      contentInsetAdjustmentBehavior="automatic"
      contentContainerStyle={{
        paddingTop: Spacing.three,
        paddingBottom: insets.bottom + Spacing.five,
        gap: Spacing.five,
      }}
      showsVerticalScrollIndicator={false}>
      <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.half }}>
        <ThemedText accessibilityRole="header" style={{ ...labelType(40, 800), lineHeight: 44 }}>
          {fitId ? 'Shop the look' : 'Shop'}
        </ThemedText>
        <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: FontSize.footnote }}>
          Curated references from real shops, matched to your wardrobe and taste.
          Buying happens on each retailer site.
        </ThemedText>
      </View>

      {/* The look's own pieces, above anything matched to taste.
          These are what the button promised; the recommendations
          below are the next best thing, and are labelled as such. */}
      {fitId && pieces.length > 0 ? (
        <View style={{ gap: Spacing.one }}>
          <View style={{ paddingHorizontal: Spacing.three }}>
            <ThemedText type="smallBold">In this look</ThemedText>
          </View>
          {pieces.map((piece, at) => (
            <LookPiece key={`${piece.title ?? piece.categoryId}-${at}`} piece={piece} />
          ))}
        </View>
      ) : null}

      {/* Something like each garment, matched from the catalogue by
          what the fit was read as. This is the half that does not
          need anybody to have tagged anything. */}
      {fitSections.map((section) => (
        <View key={section.key} style={{ gap: Spacing.one }}>
          <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.half }}>
            <ThemedText type="smallBold">{section.title}</ThemedText>
            <ThemedText
              type="small"
              themeColor="textSecondary"
              style={{ fontSize: FontSize.meta }}>
              {section.reason}
            </ThemedText>
          </View>
          {section.items.map((item) => (
            <Card key={`${section.key}-${item.productId}`} item={item} />
          ))}
        </View>
      ))}

      {fitId && !look.isPending && !forFit.isPending &&
      pieces.length === 0 &&
      fitSections.length === 0 ? (
        <View style={{ paddingHorizontal: Spacing.three }}>
          <ThemedText type="small" themeColor="textSecondary">
            Nothing in the catalogue matches this fit yet. Below is what
            matches your wardrobe and taste.
          </ThemedText>
        </View>
      ) : null}

      {recommendations.isPending ? (
        <View style={{ paddingHorizontal: Spacing.three }}>
          <SkeletonRows count={5} avatar={false} label="Looking for pieces" />
        </View>
      ) : sections.length === 0 && !recommendations.isPending ? (
        <EmptyState
          status="empty"
          title="Nothing to point at yet"
          body="Recommendations come from two places: slots the stylist could not fill from your wardrobe, and the aesthetics you picked in taste. Answer taste, or ask the stylist for an outfit, and this fills in."
        />
      ) : (
        sections.map((section) => (
          <View key={section.key} style={{ gap: Spacing.one }}>
            <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.half }}>
              <ThemedText type="smallBold">{section.title}</ThemedText>
              <ThemedText
                type="small"
                themeColor="textSecondary"
                style={{ fontSize: FontSize.meta }}>
                {section.reason}
              </ThemedText>
            </View>
            {section.items.map((item) => (
              <Card key={`${section.key}-${item.productId}`} item={item} />
            ))}
          </View>
        ))
      )}
    </ScrollView>
  );
}

function Card({ item }: { item: OfferMatch }) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={`${item.brand} ${item.title}, ${formatPrice(item.priceMinor, item.currency)}, at ${item.retailer.name}`}
      animateEntrance={false}
      onPress={() => {
        void tapFeedback();
        void Linking.openURL(item.sourceUrl);
      }}
      style={{
        paddingHorizontal: Spacing.three,
        paddingVertical: Spacing.two,
        gap: Spacing.half,
        borderBottomWidth: 1,
        borderBottomColor: colors.border,
      }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: Spacing.two }}>
        <ThemedText type="small" numberOfLines={1} style={{ flex: 1 }}>
          {item.title}
        </ThemedText>
        <ThemedText type="smallBold">{formatPrice(item.priceMinor, item.currency)}</ThemedText>
      </View>
      <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: FontSize.meta }}>
        {item.brand} · at {item.retailer.name} · {checkedLine(item)}
      </ThemedText>
    </MotionPressable>
  );
}

/**
 * One piece the author tagged onto this fit.
 *
 * **Not a `Card`.** A recommendation is always a product with a
 * retailer, a price and somewhere to buy it. A tagged piece may be
 * any of three things: a product like that, a garment out of
 * somebody's own wardrobe - which has a category and a colour and
 * nothing to buy - or a piece whose garment or product has since
 * gone. Drawing all three as shop cards would put a price-shaped
 * hole under two of them.
 *
 * Garments carry taxonomy facts only. The free-text name an owner
 * typed is not screened and never leaves the server, so a wardrobe
 * piece is described by what it is rather than by what they called
 * it.
 */
function LookPiece({ piece }: { piece: PostItemTag }) {
  const colors = Colors[useScheme()];
  // Buyable means all three: a product, somewhere to go, and a price
  // to show. A card with a blank where the price belongs reads as a
  // loading state that never finishes.
  const buyable =
    piece.kind === 'product' &&
    Boolean(piece.sourceUrl) &&
    piece.priceMinor !== null &&
    Boolean(piece.currency);
  const price =
    piece.priceMinor !== null && piece.currency
      ? formatPrice(piece.priceMinor, piece.currency)
      : null;

  const name =
    piece.title ??
    [piece.colour, piece.categoryId].filter(Boolean).join(' ') ??
    'A piece';
  const under = buyable
    ? [piece.brand, piece.retailer].filter(Boolean).join(' · ')
    : 'From a wardrobe, not a shop';

  const body = (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.three,
        minHeight: TapTarget,
        marginHorizontal: Spacing.three,
        padding: Spacing.three,
        borderRadius: Radius.lg,
        borderCurve: 'continuous',
        backgroundColor: colors.backgroundElement,
      }}>
      <View style={{ flex: 1, gap: Spacing.half }}>
        <ThemedText type="smallBold" numberOfLines={1}>
          {name || 'A piece'}
        </ThemedText>
        <ThemedText
          type="small"
          themeColor="textSecondary"
          numberOfLines={1}
          style={{ fontSize: FontSize.meta }}>
          {under}
        </ThemedText>
      </View>
      {buyable ? (
        <ThemedText type="smallBold">{price}</ThemedText>
      ) : null}
    </View>
  );

  // Only a product with somewhere to go is a button. A wardrobe
  // garment is information, and a control that does nothing when
  // pressed is worse than a row that never offered to be pressed.
  if (!buyable) return body;

  return (
    <MotionPressable
      accessibilityRole="link"
      accessibilityLabel={`${name}, ${price}, at ${piece.retailer ?? 'the retailer'}`}
      animateEntrance={false}
      onPress={() => {
        void tapFeedback();
        if (piece.sourceUrl) void Linking.openURL(piece.sourceUrl);
      }}>
      {body}
    </MotionPressable>
  );
}
