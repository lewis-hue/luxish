import { router } from 'expo-router';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { Alert, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import {
  MotionPressable,
  successFeedback,
  tapFeedback,
  useMotiTiming,
} from '@/components/ui/motion';
import {
  BottomTabInset,
  Colors,
  Motion,
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
import { useState } from 'react';
import { MotiView } from 'moti';
import { greetingName, useMe } from '@/api/queries/me';
import { useAuth } from '@/features/auth/session';
import { HistorySheet } from '@/features/stylist/history-sheet';
import { useChatHistory } from '@/features/stylist/use-history';

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
 * **The outfit and the figure render in place.** Both used to be on
 * other screens. An outfit is four garment names, which is a
 * description of a look rather than a look, so the stylist offers to
 * draw it on a figure right under the answer.
 *
 * **It opens on a greeting, not on a form.** An assistant whose empty
 * state is a title, a count and an input box reads as a search page.
 * One mark, one line naming the person, and the composer at the
 * bottom where the thumb is - everything else arrives as the
 * conversation does.
 *
 * **And it remembers.** The thread used to live in component state
 * and die with the screen, so leaving the tab threw away everything
 * that had been said. Conversations are kept on the device
 * (`features/stylist/history`), reachable from the button in the
 * header, and reopening one restores its turns so the next question
 * carries the same context it would have had.
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
  const timing = useMotiTiming();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';
  const me = useMe(signedIn);
  const name = greetingName(me.data ?? undefined);
  const history = useChatHistory();
  const [showHistory, setShowHistory] = useState(false);
  // The greeting stands only while nothing has been said. Derived
  // from the restored thread rather than from a flag, so a
  // conversation reopened from history never flashes it.
  const [saidAnything, setSaidAnything] = useState(false);

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
      {/* The header: the name of the page, the way back into an
          earlier conversation, and a clean slate.

          Three things, all of them small. An assistant screen earns
          its space by what the conversation puts there, so the chrome
          above it is a line of icons rather than a card. The count of
          pieces lives behind the hanger: it is the one fact worth
          knowing on a page that is not showing the clothes, and it is
          a destination rather than a statistic. */}
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: Spacing.two,
        }}>
        <ThemedText
          accessibilityRole="header"
          style={{ ...labelType(28, 800), lineHeight: 34 }}>
          Wardrobe
        </ThemedText>

        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <HeaderButton
            label={`Your clothes, ${owned.length} pieces`}
            hint="Opens all your pieces, where you can rename or remove them"
            icon={{ ios: 'hanger', android: 'apparel', web: 'apparel' }}
            onPress={() => router.push('/closet')}
          />
          <HeaderButton
            label="Earlier conversations"
            hint="Pick up a conversation you had before"
            icon={{
              ios: 'clock.arrow.circlepath',
              android: 'history',
              web: 'history',
            }}
            onPress={() => setShowHistory(true)}
          />
          <HeaderButton
            label="New conversation"
            hint="Starts an empty thread. The old one is kept."
            icon={{
              ios: 'square.and.pencil',
              android: 'edit_square',
              web: 'edit_square',
            }}
            onPress={() => {
              history.startNew();
              setSaidAnything(false);
            }}
          />
        </View>
      </View>

      {/* The greeting, while there is nothing else to show.

          It is the whole screen on arrival, and deliberately almost
          nothing: a mark, a line, and the composer waiting at the
          bottom. The alternative - a title, a count and an empty
          input - reads as a search page, which is what this screen
          was and what it is not any more.

          It goes the moment anything is said, rather than scrolling
          away above the conversation. */}
      {!saidAnything ? (
        <MotiView
          from={{ opacity: 0, translateY: 8 }}
          animate={{ opacity: 1, translateY: 0 }}
          transition={timing({ duration: Motion.slow, delay: 120 })}
          style={{
            alignItems: 'center',
            justifyContent: 'center',
            gap: Spacing.three,
            // Enough to sit in the middle of what is left once the
            // header and the composer have taken theirs, without
            // reaching for a measured height.
            paddingVertical: Spacing.six,
          }}>
          {/* No mark above the line.

              A maroon sparkle sat here and three more sat down the
              thread. They were decoration - they named nothing a
              person could read - and the greeting is stronger as one
              sentence on an empty page than as an icon with a
              caption. */}
          <ThemedText
            style={{
              ...labelType(22, 400),
              lineHeight: 28,
              color: colors.text,
              textAlign: 'center',
            }}>
            {name ? `Back at it, ${name}` : 'What are you wearing today?'}
          </ThemedText>
        </MotiView>
      ) : null}

      {/* The assistant. Idle it is one line and a `+`; the outfit and
          the picture of it worn appear beneath as they arrive. */}
      <StylistPanel
        embedded
        onAddGarment={add}
        sessionKey={history.sessionId}
        restored={history.restored}
        onTurns={(turns) => {
          setSaidAnything(turns.length > 0);
          history.remember(turns);
        }}
      />

      <HistorySheet
        open={showHistory}
        sessions={history.sessions}
        currentId={history.sessionId}
        onClose={() => setShowHistory(false)}
        onResume={(id) => void history.resume(id)}
        onForget={(id) => void history.forget(id)}
        onForgetAll={() => void history.forgetAll()}
        onStartNew={() => {
          history.startNew();
          setSaidAnything(false);
        }}
      />
    </ScrollView>
  );
}

/**
 * One icon in the header row.
 *
 * Icon-only, so each carries its own label and hint: without them a
 * screen reader announces three unnamed buttons. 44pt square even
 * though the glyph is 18, because the target is what has to be
 * tappable, not the drawing.
 */
function HeaderButton({
  label,
  hint,
  icon,
  onPress,
}: {
  label: string;
  hint: string;
  icon: SymbolViewProps['name'];
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={hint}
      animateEntrance={false}
      onPress={() => {
        void tapFeedback();
        onPress();
      }}
      style={{
        width: TapTarget,
        height: TapTarget,
        alignItems: 'center',
        justifyContent: 'center',
      }}>
      <SymbolView name={icon} size={18} tintColor={colors.text} />
    </MotionPressable>
  );
}
