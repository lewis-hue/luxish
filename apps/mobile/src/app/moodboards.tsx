import { router } from 'expo-router';
import { useState } from 'react';
import { ScrollView, TextInput, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useCreateBoard, useMoodboards } from '@/api/queries/moodboards';
import { ThemedText } from '@/components/themed-text';
import { usePullToRefresh } from '@/components/ui/pull-to-refresh';
import { BoardCover } from '@/components/ui/board-cover';
import { EmptyState } from '@/components/ui/empty-state';
import { SkeletonMasonry } from '@/components/ui/skeleton';
import { BOARDS_SHEET } from '@/features/discover/sheets';
import { MotionPressable, successFeedback, tapFeedback } from '@/components/ui/motion';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { useAuth } from '@/features/auth/session';
import { useScheme } from '@/hooks/use-theme';

/**
 * Boards: things you put together.
 *
 * **Separate from Saved on purpose.** Saving a look is a verdict on one
 * thing; putting it on a board is an argument about several. Folding them
 * together would mean either that liking something files it somewhere, or
 * that a board is only a filtered view of likes — and neither is what a
 * person means when they make one.
 *
 * A board shows what is on it rather than a cover somebody chose. That keeps
 * the act to one decision and keeps the board honest: it cannot look fuller
 * than it is.
 */
export default function MoodboardsScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const refresh = usePullToRefresh();
  const { width } = useWindowDimensions();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';

  const boards = useMoodboards(signedIn);
  const create = useCreateBoard();
  const [name, setName] = useState('');
  const [problem, setProblem] = useState<string | null>(null);

  const columns = width >= 700 ? 3 : 2;
  const gutter = Spacing.three;
  // The row has `columns - 1` gaps to give away before the tiles get their
  // share of it, and the screen's own edge padding before that.
  const tile = (width - Spacing.three * 2 - gutter * (columns - 1)) / columns;

  const make = async () => {
    const cleaned = name.trim();
    if (!cleaned) return;
    void tapFeedback();
    setProblem(null);
    try {
      await create.mutateAsync({ name: cleaned });
      setName('');
      void successFeedback();
    } catch (caught) {
      setProblem(
        caught instanceof Error && caught.message.trim()
          ? caught.message.trim()
          : 'That board could not be made. Try again in a moment.',
      );
    }
  };

  if (!signedIn) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, justifyContent: 'center' }}>
        <EmptyState
          status="blocked"
          title="Sign in to make boards"
          body="Boards are kept with your account, so they are there on any phone."
          action={{ label: 'Sign in', onPress: () => router.push('/sign-in') }}
        />
      </View>
    );
  }

  const items = boards.data ?? [];

  return (
    <ScrollView
      refreshControl={refresh.control}
      style={{ backgroundColor: colors.background }}
      contentInsetAdjustmentBehavior="automatic"
      automaticallyAdjustKeyboardInsets
      keyboardDismissMode="interactive"
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={{
        paddingHorizontal: Spacing.three,
        paddingBottom: insets.bottom + Spacing.six,
        gap: Spacing.four,
      }}
      showsVerticalScrollIndicator={false}>
      <View style={{ gap: Spacing.one }}>
        <ThemedText type="label" themeColor="textSecondary">
          {items.length === 1 ? '1 board' : `${items.length} boards`}
        </ThemedText>
        <ThemedText accessibilityRole="header" style={{ ...labelType(40, 800), lineHeight: 44 }}>
          Boards
        </ThemedText>

      </View>

      <View style={{ gap: Spacing.two }}>
        <View style={{ flexDirection: 'row', gap: Spacing.two }}>
          <TextInput
            value={name}
            onChangeText={setName}
            placeholder="Name a new board"
            placeholderTextColor={colors.textSecondary}
            returnKeyType="done"
            onSubmitEditing={() => void make()}
            accessibilityLabel="Name a new board"
            maxLength={80}
            style={{
              flex: 1,
              minHeight: TapTarget,
              paddingHorizontal: Spacing.three,
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              borderWidth: 1,
              // The control boundary needs the 3:1 WCAG 1.4.11 asks for,
              // which the hairline divider colour does not carry.
              borderColor: colors.borderStrong,
              color: colors.text,
              ...labelType(FontSize.subhead, 400),
            }}
          />
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Make this board"
            accessibilityState={{ disabled: !name.trim() || create.isPending }}
            disabled={!name.trim() || create.isPending}
            animateEntrance={false}
            onPress={() => void make()}
            style={{
              minHeight: TapTarget,
              paddingHorizontal: Spacing.four,
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              backgroundColor: colors.text,
              opacity: !name.trim() || create.isPending ? 0.4 : 1,
            }}>
            <ThemedText type="smallBold" style={{ color: colors.background }}>
              {create.isPending ? 'Making' : 'Make'}
            </ThemedText>
          </MotionPressable>
        </View>

        {problem ? (
          <ThemedText type="small" style={{ color: colors.danger }}>
            {problem}
          </ThemedText>
        ) : null}
      </View>

      {items.length === 0 && boards.isPending ? (
        <View style={{ paddingHorizontal: Spacing.three }}>
          <SkeletonMasonry
            count={4}
            columns={columns}
            gutter={gutter}
            label="Loading your boards"
          />
        </View>
      ) : items.length === 0 ? (
        <EmptyState
          status="empty"
          title="No boards yet"
          body="Name one above, then pin looks to it from anywhere you find them."
          sheet={BOARDS_SHEET}
          action={{ label: 'Browse looks', onPress: () => router.push('/') }}
        />
      ) : (
        <View
          style={{
            flexDirection: 'row',
            flexWrap: 'wrap',
            gap: gutter,
          }}>
          {items.map((board) => (
            <MotionPressable
              key={board.id}
              accessibilityRole="link"
              accessibilityLabel={`${board.name}, ${board.posts.length} pinned`}
              animateEntrance={false}
              scale={0.98}
              onPress={() =>
                router.push({ pathname: '/board/[id]', params: { id: board.id } })
              }
              style={{
                // A width in points, not a percentage.
                //
                // This was `flexBasis: 48%` with a 16pt `gap` between
                // tiles. Two of them come to 96% of the row *plus* the gap,
                // which on any phone is wider than the row — so they never
                // fit on a line together and the grid silently collapsed to
                // one tile per row. `width` and `flexBasis` were also both
                // set, and in a row `flexBasis` wins, so the `width` was
                // never doing anything.
                width: tile,
                flexGrow: 0,
                flexShrink: 0,
                gap: Spacing.one,
              }}>
              <BoardCover faces={board.posts} />
              <View style={{ gap: Spacing.half }}>
                <ThemedText type="smallBold" numberOfLines={1}>
                  {board.name}
                </ThemedText>
                <ThemedText
                  type="small"
                  themeColor="textSecondary"
                  style={{ fontSize: FontSize.meta }}>
                  {board.posts.length === 1
                    ? '1 fit'
                    : `${board.posts.length} fits`}
                </ThemedText>
              </View>
            </MotionPressable>
          ))}
        </View>
      )}
    </ScrollView>
  );
}
