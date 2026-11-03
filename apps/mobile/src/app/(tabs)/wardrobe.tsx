import { router } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { Alert, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import { MotionPressable, successFeedback, tapFeedback } from '@/components/ui/motion';
import {
  BottomTabInset,
  Colors,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { useFavouriteGarments } from '@/features/discover/saved';
import { StylistPanel } from '@/features/stylist/panel';
import { useGarmentCapture } from '@/features/wardrobe/capture';
import { useWardrobe } from '@/features/wardrobe/store';
import { usePullToRefresh } from '@/components/ui/pull-to-refresh';
import { useScheme } from '@/hooks/use-theme';

/**
 * The assistant, on the page it belongs to.
 *
 * **The clothes moved off it, and that is the point.** This was a grid
 * of every garment somebody owns, which is fine at twelve and a wall
 * at a hundred and fifty - and once the stylist sat above it, the
 * answer it gave had to compete with the entire wardrobe underneath.
 * The grid is one tap away on `/closet`, where renaming, deleting and
 * filtering live, and the page somebody opens to *ask* is now about
 * asking.
 *
 * **The outfit and the avatar render in place.** Both used to be on
 * other screens. An outfit is four garment names, which is a
 * description of a look rather than a look, so the stylist offers to
 * draw it on this person's avatar right under the answer.
 */
export default function WardrobeScreen() {
  const colors = Colors[useScheme()];
  const refresh = usePullToRefresh();
  const insets = useSafeAreaInsets();
  const favourites = useFavouriteGarments();
  const wardrobe = useWardrobe(favourites.values);
  const capture = useGarmentCapture();

  const owned = wardrobe.entries.filter((entry) => !entry.isSample);

  /** Photograph a piece, or take some from the camera roll. */
  const add = async (source: 'camera' | 'library') => {
    const result =
      source === 'camera'
        ? await capture.photograph()
        : await capture.pickFromLibrary();
    if (result === 'denied') {
      Alert.alert(
        source === 'camera' ? 'Camera access needed' : 'Photo access needed',
        'Grant access in Settings to add your clothes. Everything else keeps working.',
      );
      return;
    }
    if (result === 'unavailable') {
      // Said out loud. This used to reject into nothing, and the
      // camera read as a button that did nothing at all.
      Alert.alert(
        'That could not be opened',
        'The camera is not available right now. Choosing from your photos still works.',
      );
      return;
    }
    if (result === 'cancelled' || typeof result === 'string') return;
    await wardrobe.addMany(result);
    void successFeedback();
  };

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      showsVerticalScrollIndicator={false}
      keyboardShouldPersistTaps="handled"
      refreshControl={refresh.control}
      contentContainerStyle={{
        paddingTop: insets.top + Spacing.three,
        paddingHorizontal: Spacing.three,
        paddingBottom: BottomTabInset + insets.bottom + Spacing.five,
        gap: Spacing.three,
      }}>
      <ThemedText
        accessibilityRole="header"
        style={{ ...labelType(28, 800), lineHeight: 34 }}>
        Wardrobe
      </ThemedText>

      {/* The clothes, one tap away rather than underneath.

          A count rather than a grid: it is the one thing worth saying
          about a wardrobe on a page that is not showing it, and it is
          also what tells somebody whether there is anything in there
          to style from. */}
      <MotionPressable
        accessibilityRole="button"
        accessibilityLabel={`Your wardrobe, ${owned.length} pieces`}
        accessibilityHint="Opens all your pieces, where you can rename or remove them"
        animateEntrance={false}
        onPress={() => {
          void tapFeedback();
          router.push('/closet');
        }}
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: Spacing.three,
          minHeight: TapTarget,
          paddingVertical: Spacing.two,
          paddingHorizontal: Spacing.three,
          borderRadius: Radius.lg,
          borderCurve: 'continuous',
          backgroundColor: colors.backgroundElement,
        }}>
        <SymbolView
          name={{ ios: 'hanger', android: 'apparel', web: 'apparel' }}
          size={22}
          tintColor={colors.text}
        />
        <View style={{ flex: 1, gap: Spacing.half }}>
          <ThemedText type="smallBold">Your wardrobe</ThemedText>
          <ThemedText type="small" themeColor="textSecondary">
            {owned.length === 0
              ? 'Nothing in it yet'
              : `${owned.length} ${owned.length === 1 ? 'piece' : 'pieces'}`}
          </ThemedText>
        </View>
        <SymbolView
          name={{
            ios: 'chevron.right',
            android: 'chevron_right',
            web: 'chevron_right',
          }}
          size={18}
          tintColor={colors.textSecondary}
        />
      </MotionPressable>

      {/* The assistant. Idle it is one line and a `+`; the outfit and
          the picture of it worn appear beneath as they arrive. */}
      <StylistPanel embedded onAddGarment={add} />
    </ScrollView>
  );
}
