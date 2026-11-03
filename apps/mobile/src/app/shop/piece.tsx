import { useLocalSearchParams } from 'expo-router';
import * as Linking from 'expo-linking';
import { ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  checkedLine,
  formatPrice,
  useShopSearch,
  type OfferMatch,
} from '@/api/queries/shopping';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { SkeletonRows } from '@/components/ui/skeleton';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { useAuth } from '@/features/auth/session';
import { webSearchUrlForDescription } from '@/features/discover/visual-search';
import { useScheme } from '@/hooks/use-theme';

/**
 * Where to buy one piece: curated references first, the open web second.
 *
 * **Every card says what it knows and no more.** The match label is
 * `Similar style` because resemblance is all the curated catalogue can
 * establish (§10 forbids anything stronger without identifier
 * agreement); the price carries the date it was checked; availability
 * is never claimed. Buying happens on the retailer's own site, through
 * a link out, which is also the only compliant route for physical goods
 * on either app store.
 *
 * The web search the Find button used to open is still here, as the
 * last row: the catalogue is a better first answer, not a wall.
 */
export default function ShopPieceScreen() {
  const params = useLocalSearchParams<{
    name?: string;
    category?: string;
    colour?: string;
    slot?: string;
  }>();
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';

  const search = useShopSearch(
    { category: params.category, slot: params.slot, colour: params.colour },
    signedIn,
  );
  const items = search.data ?? [];

  const webSearch = () => {
    void tapFeedback();
    void Linking.openURL(
      webSearchUrlForDescription({
        name: params.name ?? params.category ?? 'clothing',
        colour: params.colour,
        category: params.category,
      }),
    );
  };

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.background }}
      contentInsetAdjustmentBehavior="automatic"
      contentContainerStyle={{
        paddingTop: Spacing.three,
        paddingBottom: insets.bottom + Spacing.five,
        gap: Spacing.three,
      }}
      showsVerticalScrollIndicator={false}>
      <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.half }}>
        <ThemedText accessibilityRole="header" style={{ ...labelType(28, 800), lineHeight: 34 }}>
          {params.name ?? 'Find it'}
        </ThemedText>
        <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: FontSize.footnote }}>
          Curated references from real shops. Prices carry the date they were
          checked; stock is not tracked. Buying happens on each retailer site.
        </ThemedText>
      </View>

      <View>
        {search.isPending ? (
        <View style={{ paddingHorizontal: Spacing.three }}>
          <SkeletonRows count={5} avatar={false} label="Looking for pieces" />
        </View>
      ) : items.length === 0 && !search.isPending ? (
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ paddingHorizontal: Spacing.three }}>
            Nothing similar in the catalogue yet. The web search below still works.
          </ThemedText>
        ) : (
          items.map((item) => <OfferRow key={item.productId} item={item} />)
        )}
      </View>

      <View style={{ paddingHorizontal: Spacing.three }}>
        <MotionPressable
          accessibilityRole="button"
          animateEntrance={false}
          onPress={webSearch}
          style={{
            minHeight: TapTarget,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            borderWidth: 1,
            borderColor: colors.borderStrong,
          }}>
          <ThemedText type="smallBold">Search the web instead</ThemedText>
        </MotionPressable>
      </View>
    </ScrollView>
  );
}

function OfferRow({ item }: { item: OfferMatch }) {
  const colors = Colors[useScheme()];
  const open = () => {
    void tapFeedback();
    // The retailer's own site, in the system browser: a purchase is
    // theirs, and pretending otherwise helps nobody.
    void Linking.openURL(item.sourceUrl);
  };
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={`${item.brand} ${item.title}, ${formatPrice(item.priceMinor, item.currency)}, at ${item.retailer.name}`}
      animateEntrance={false}
      onPress={open}
      style={{
        paddingHorizontal: Spacing.three,
        paddingVertical: Spacing.two,
        gap: Spacing.half,
        borderBottomWidth: 1,
        borderBottomColor: colors.border,
      }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: Spacing.two }}>
        <ThemedText type="smallBold" numberOfLines={1} style={{ flex: 1 }}>
          {item.title}
        </ThemedText>
        <ThemedText type="smallBold">{formatPrice(item.priceMinor, item.currency)}</ThemedText>
      </View>
      <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: FontSize.footnote }}>
        {item.brand} · at {item.retailer.name} · similar style
      </ThemedText>
      <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: FontSize.meta }}>
        {checkedLine(item)}
      </ThemedText>
    </MotionPressable>
  );
}
