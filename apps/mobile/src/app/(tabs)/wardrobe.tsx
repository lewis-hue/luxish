import { router } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { Alert, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import { MotionPressable, successFeedback, tapFeedback } from '@/components/ui/motion';
import {
  BottomTabInset,
  Colors,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { useFavouriteGarments } from '@/features/discover/saved';
import { StylistPanel } from '@/features/stylist/panel';
import { useGarmentCapture } from '@/features/wardrobe/capture';
import { useWardrobe } from '@/features/wardrobe/store';
import { usePullToRefresh } from '@/components/ui/pull-to-refresh';
import { useKeyboardInset } from '@/hooks/use-keyboard-inset';
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
  // What the keyboard is covering, so the composer sits above it.
  // Without this the box somebody is typing into is behind the
  // keyboard and they cannot see their own words - the screen is a
  // plain ScrollView, so nothing was getting out of the way.
  const keyboard = useKeyboardInset();

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
        // The tab bar drops out of the way when the keyboard is up, so
        // its inset is not owed on top of the keyboard's - counting
        // both leaves a tall empty band under the composer.
        paddingBottom:
          (keyboard > 0 ? keyboard : BottomTabInset + insets.bottom) +
          Spacing.five,
        gap: Spacing.three,
      }}>
      {/* The title and the way to the clothes, on one line.

          The count used to be a full-width filled card of its own
          under the heading - an icon, two lines of text and a
          chevron, about a tenth of the screen, repeating a number
          nobody came here to read. It is a link now, set beside the
          title at footnote size, and the conversation starts where
          the card used to.

          It is still the thing that tells somebody whether there is
          anything to style from, so it keeps the count and keeps its
          tap target; it just stops being furniture. */}
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          gap: Spacing.three,
        }}>
        <ThemedText
          accessibilityRole="header"
          style={{ ...labelType(28, 800), lineHeight: 34 }}>
          Wardrobe
        </ThemedText>

        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel={`Your clothes, ${owned.length} pieces`}
          accessibilityHint="Opens all your pieces, where you can rename or remove them"
          animateEntrance={false}
          onPress={() => {
            void tapFeedback();
            router.push('/closet');
          }}
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            gap: Spacing.one,
            // The row is short, so the tap target is widened rather
            // than made taller - a 44pt-tall link beside a title
            // would reintroduce the band this change removed.
            minHeight: TapTarget,
            paddingLeft: Spacing.two,
          }}>
          <ThemedText type="small" themeColor="textSecondary">
            {owned.length === 0
              ? 'Add clothes'
              : `${owned.length} ${owned.length === 1 ? 'piece' : 'pieces'}`}
          </ThemedText>
          <SymbolView
            name={{
              ios: 'chevron.right',
              android: 'chevron_right',
              web: 'chevron_right',
            }}
            size={14}
            tintColor={colors.textSecondary}
          />
        </MotionPressable>
      </View>

      {/* The assistant. Idle it is one line and a `+`; the outfit and
          the picture of it worn appear beneath as they arrive. */}
      <StylistPanel embedded onAddGarment={add} />
    </ScrollView>
  );
}
