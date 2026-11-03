import { Image } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
import { useMemo, useState } from 'react';
import { Alert, ScrollView, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  useDeleteBoard,
  useMoodboards,
  useUnpinPost,
} from '@/api/queries/moodboards';
import { usePostImage } from '@/api/queries/post-media';
import { ThemedText } from '@/components/themed-text';
import { usePullToRefresh } from '@/components/ui/pull-to-refresh';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton, SkeletonMasonry } from '@/components/ui/skeleton';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import {
  BottomTabInset,
  Colors,
  FontSize,
  ImageFade,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { useAuth } from '@/features/auth/session';
import { useScheme } from '@/hooks/use-theme';

/**
 * One board, and what is on it.
 *
 * Read from the boards list rather than a per-board request: the list already
 * carries every pin, so a second endpoint for data in hand would be one more
 * thing to keep in step and one more loading state to render.
 *
 * Pins keep the order they were arranged in, which is why the server stores
 * position as a column. A board is a composition.
 */
export default function BoardScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const refresh = usePullToRefresh();
  const { width } = useWindowDimensions();
  const { id } = useLocalSearchParams<{ id: string }>();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';

  const boards = useMoodboards(signedIn);
  const unpin = useUnpinPost();
  const remove = useDeleteBoard();
  const [editing, setEditing] = useState(false);

  const board = useMemo(
    () => (boards.data ?? []).find((item) => item.id === id),
    [boards.data, id],
  );

  const columns = width >= 700 ? 3 : 2;
  const gutter = Spacing.two;
  // In points rather than a percentage: the tile measures its own
  // picture, and a percentage width cannot be handed to a child that
  // needs a number to size an image against.
  const basis =
    (width - Spacing.three * 2 - gutter * (columns - 1)) / columns;

  if (!signedIn) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, justifyContent: 'center' }}>
        <EmptyState
          status="blocked"
          title="Sign in to see this board"
          body="Boards are kept with your account."
          action={{ label: 'Sign in', onPress: () => router.push('/sign-in') }}
        />
      </View>
    );
  }

  if (!board && boards.isPending) {
    // The board in outline rather than the word "Opening" over a blank
    // page: a shell the shape of what is coming means nothing jumps
    // when it arrives.
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: colors.background,
          paddingTop: insets.top + Spacing.three,
          paddingHorizontal: Spacing.three,
          gap: Spacing.three,
        }}>
        <Skeleton width={180} height={28} />
        <SkeletonMasonry
          count={6}
          columns={columns}
          gutter={gutter}
          label="Opening this board"
        />
      </View>
    );
  }

  if (!board) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, justifyContent: 'center' }}>
        <EmptyState
          status="error"
          title="That board is gone"
          body="It may have been deleted on another device."
          action={{ label: 'All boards', onPress: () => router.replace('/moodboards') }}
        />
      </View>
    );
  }

  const confirmDelete = () => {
    void tapFeedback();
    // A native alert rather than an in-page confirm: deleting a board takes
    // work away permanently, and this is the one pattern every person on the
    // platform already reads as "are you sure".
    Alert.alert(
      `Delete ${board.name}?`,
      'The looks stay where they are. Only the board goes.',
      [
        { text: 'Keep it', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: () => {
            remove.mutate(board.id);
            router.replace('/moodboards');
          },
        },
      ],
    );
  };

  return (
    <ScrollView
      refreshControl={refresh.control}
      style={{ backgroundColor: colors.background }}
      contentInsetAdjustmentBehavior="automatic"
      contentContainerStyle={{
        paddingHorizontal: Spacing.three,
        paddingBottom: BottomTabInset + insets.bottom + Spacing.six,
        gap: Spacing.three,
      }}
      showsVerticalScrollIndicator={false}>
      <View style={{ gap: Spacing.one }}>
        <ThemedText
          themeColor="textSecondary"
          style={labelType(FontSize.subhead, 400)}>
          {board.posts.length === 1 ? '1 fit' : `${board.posts.length} fits`}
        </ThemedText>
        <ThemedText
          accessibilityRole="header"
          style={{ ...labelType(32, 800), lineHeight: 38 }}>
          {board.name}
        </ThemedText>
        {board.note ? (
          <ThemedText type="small" themeColor="textSecondary">
            {board.note}
          </ThemedText>
        ) : null}
      </View>

      <View style={{ flexDirection: 'row', gap: Spacing.two }}>
        <Action
          label={editing ? 'Done' : 'Edit'}
          active={editing}
          onPress={() => setEditing((was) => !was)}
        />
        <Action label="Delete board" onPress={confirmDelete} />
      </View>

      {board.posts.length === 0 ? (
        <EmptyState
          status="empty"
          title="Nothing pinned yet"
          body="Save a fit to this board and it lands here."
          action={{ label: 'Find some', onPress: () => router.push('/') }}
        />
      ) : (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: gutter }}>
          {board.posts.map((pinned) => (
            <View key={pinned.postId} style={{ width: basis, gap: Spacing.one }}>
              <BoardTile
                postId={pinned.postId}
                assetId={pinned.coverAssetId}
                width={basis}
              />
              {editing ? (
                <MotionPressable
                  accessibilityRole="button"
                  accessibilityLabel="Unpin this fit"
                  animateEntrance={false}
                  onPress={() => {
                    void tapFeedback();
                    unpin.mutate({ id: board.id, postId: pinned.postId });
                  }}
                  style={{
                    minHeight: 32,
                    alignItems: 'center',
                    justifyContent: 'center',
                    borderRadius: Radius.full,
                    borderWidth: 1,
                    borderColor: colors.borderStrong,
                  }}>
                  <ThemedText style={labelType(FontSize.footnote, 400)}>
                    Unpin
                  </ThemedText>
                </MotionPressable>
              ) : null}
            </View>
          ))}
        </View>
      )}
    </ScrollView>
  );
}

function Action({
  label,
  active,
  onPress,
}: {
  label: string;
  active?: boolean;
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ selected: active }}
      animateEntrance={false}
      onPress={onPress}
      style={{
        flex: 1,
        minHeight: TapTarget,
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: Radius.md,
        borderCurve: 'continuous',
        backgroundColor: active ? colors.text : 'transparent',
        borderWidth: 1,
        borderColor: active ? colors.text : colors.borderStrong,
      }}>
      <ThemedText
        type="smallBold"
        style={{ color: active ? colors.background : colors.text }}>
        {label}
      </ThemedText>
    </MotionPressable>
  );
}

/**
 * One pinned fit.
 *
 * The picture and nothing else, like every other board in this app:
 * these are fits somebody already chose, and a row of controls under
 * each one is a decision nobody is taking here.
 */
function BoardTile({
  postId,
  assetId,
  width,
}: {
  postId: string;
  assetId: string | null;
  width: number;
}) {
  const colors = Colors[useScheme()];
  const uri = usePostImage(assetId).data ?? null;

  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel="Open this fit"
      animateEntrance={false}
      onPress={() => {
        void tapFeedback();
        router.push({ pathname: '/fit/[id]', params: { id: postId } });
      }}
      style={{
        width,
        aspectRatio: 3 / 4,
        borderRadius: Radius.lg,
        borderCurve: 'continuous',
        overflow: 'hidden',
        backgroundColor: colors.backgroundElement,
      }}>
      {uri ? (
        <Image
          source={{ uri }}
          recyclingKey={postId}
          contentFit="cover"
          transition={ImageFade}
          style={{ width: '100%', height: '100%' }}
        />
      ) : null}
    </MotionPressable>
  );
}
