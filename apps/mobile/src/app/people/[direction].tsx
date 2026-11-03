import { router, useLocalSearchParams } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { useMemo, useState } from 'react';
import { FlatList, Share, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  useFollowCounts,
  useFollowList,
  useMember,
  useMemberFollowList,
  useSetFollowing,
  type FoundPerson,
} from '@/api/queries/community';
import { useMoodboards } from '@/api/queries/moodboards';
import { ThemedText } from '@/components/themed-text';
import { usePullToRefresh } from '@/components/ui/pull-to-refresh';
import { EmptyState } from '@/components/ui/empty-state';
import { Monogram } from '@/components/ui/monogram';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { SkeletonRows } from '@/components/ui/skeleton';
import {
  BottomTabInset,
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { useAuth } from '@/features/auth/session';
import { useScheme } from '@/hooks/use-theme';

type Direction = 'followers' | 'following';

/**
 * Who follows somebody, and who they follow.
 *
 * **Anybody's, not only your own.** The server used to serve this for
 * the caller alone, which left the most ordinary question about a
 * person you just found - who else is here - with no answer anywhere
 * in the app. The accounts in the list chose to be public; the switch
 * for not appearing in one is the account itself being private, which
 * is a choice its owner makes rather than one made for them.
 *
 * **Two tabs on one screen, not two screens.** Somebody checking who
 * follows them is one tap from wondering who they follow.
 *
 * **Boards are only ever your own.** A board here is a private
 * composition - there is no sharing to opt into yet - so the section
 * appears on your own list and is absent from somebody else's rather
 * than standing there empty, which would read as "they have none".
 *
 * **Filtered on the device.** The list is everybody with a relationship
 * to one account, which is small enough to hold and search locally.
 *
 * **A monogram, not a face.** Carrying profile photographs between
 * accounts needs a consent this app does not collect.
 */
export default function PeopleScreen() {
  const params = useLocalSearchParams<{
    direction?: string;
    user?: string;
    name?: string;
  }>();
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';

  const subject = params.user ?? null;
  const mine = subject === null;
  const [tab, setTab] = useState<Direction>(
    params.direction === 'following' ? 'following' : 'followers',
  );
  const [query, setQuery] = useState('');

  const counts = useFollowCounts(signedIn && mine);
  const member = useMember(subject ?? '', signedIn && !mine);
  const ownList = useFollowList(tab, signedIn && mine);
  const theirList = useMemberFollowList(subject ?? '', tab, signedIn && !mine);
  const boards = useMoodboards(signedIn && mine);
  const refresh = usePullToRefresh();

  const loading = mine ? ownList.isPending : theirList.isPending;
  const withheld =
    !mine && Boolean(theirList.data?.private ?? member.data?.private);
  const title = mine ? 'You' : (member.data?.name ?? params.name ?? 'Them');

  const followers = mine
    ? (counts.data?.followers ?? 0)
    : (member.data?.followerCount ?? 0);
  const following = mine
    ? (counts.data?.following ?? 0)
    : (member.data?.followingCount ?? 0);

  const needle = query.trim().toLowerCase();
  const shown = useMemo(() => {
    const people = mine ? (ownList.data ?? []) : (theirList.data?.people ?? []);
    return needle
      ? people.filter((person) => person.name.toLowerCase().includes(needle))
      : people;
  }, [mine, ownList.data, theirList.data, needle]);
  const shownBoards = useMemo(() => {
    const all = boards.data ?? [];
    return needle
      ? all.filter((b) => b.name.toLowerCase().includes(needle))
      : all;
  }, [boards.data, needle]);

  if (!signedIn) {
    return (
      <EmptyState
        status="blocked"
        title="Sign in to see this"
        body="Following is part of an account."
        action={{ label: 'Sign in', onPress: () => router.push('/sign-in') }}
      />
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <View
        style={{
          paddingTop: insets.top + Spacing.two,
          paddingHorizontal: Spacing.three,
          gap: Spacing.three,
        }}>
        {/* Whose lists these are, centred, with the way back beside it.
            A title naming the person is the one thing that stops two
            identical-looking screens from being confusable. */}
        <View style={{ minHeight: TapTarget, justifyContent: 'center' }}>
          <ThemedText
            accessibilityRole="header"
            numberOfLines={1}
            style={{
              ...labelType(17, 800),
              lineHeight: 22,
              textAlign: 'center',
              paddingHorizontal: TapTarget,
            }}>
            {title}
          </ThemedText>
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Back"
            animateEntrance={false}
            scale={0.92}
            hitSlop={8}
            onPress={() => {
              void tapFeedback();
              if (router.canGoBack()) router.back();
              else router.replace('/profile');
            }}
            style={{
              position: 'absolute',
              left: 0,
              width: TapTarget,
              height: TapTarget,
              alignItems: 'flex-start',
              justifyContent: 'center',
            }}>
            <SymbolView
              name={{
                ios: 'chevron.left',
                android: 'arrow_back',
                web: 'arrow_back',
              }}
              size={20}
              tintColor={colors.text}
            />
          </MotionPressable>
        </View>

        {/* Both counts, both tappable. The inactive one is the question
            somebody asks next. */}
        <View
          style={{
            flexDirection: 'row',
            justifyContent: 'center',
            gap: Spacing.five,
          }}>
          {(['followers', 'following'] as const).map((which) => {
            const active = tab === which;
            const count = which === 'followers' ? followers : following;
            return (
              <MotionPressable
                key={which}
                accessibilityRole="tab"
                accessibilityState={{ selected: active }}
                accessibilityLabel={`${count} ${which}`}
                animateEntrance={false}
                onPress={() => {
                  void tapFeedback();
                  setTab(which);
                  setQuery('');
                }}
                style={{
                  minHeight: TapTarget,
                  justifyContent: 'center',
                  borderBottomWidth: 2,
                  borderBottomColor: active ? colors.text : 'transparent',
                }}>
                <ThemedText
                  style={{
                    ...labelType(17, active ? 800 : 400),
                    color: active ? colors.text : colors.textSecondary,
                  }}>
                  {count} {which}
                </ThemedText>
              </MotionPressable>
            );
          })}
        </View>

        {withheld ? null : (
          <TextInput
            value={query}
            onChangeText={setQuery}
            placeholder={`Search ${tab}`}
            placeholderTextColor={colors.textSecondary}
            autoCapitalize="none"
            autoCorrect={false}
            accessibilityLabel={`Search ${tab}`}
            style={{
              minHeight: TapTarget + Spacing.one,
              paddingHorizontal: Spacing.three,
              borderRadius: Radius.full,
              borderWidth: 1,
              borderColor: colors.borderStrong,
              color: colors.text,
              ...labelType(FontSize.body, 400),
            }}
          />
        )}
      </View>

      {withheld ? (
        <EmptyState
          status="blocked"
          title="This account is private"
          body={`${title} keeps their fits and the people they are connected to to themselves.`}
        />
      ) : loading ? (
        <View style={{ padding: Spacing.three, gap: Spacing.three }}>
          <SkeletonRows count={4} label="Loading this list" />
        </View>
      ) : (
        <FlatList
          data={shown}
          refreshControl={refresh.control}
          keyExtractor={(person) => person.userId}
          contentInsetAdjustmentBehavior="automatic"
          automaticallyAdjustKeyboardInsets
          keyboardDismissMode="interactive"
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{
            paddingTop: Spacing.three,
            paddingHorizontal: Spacing.three,
            paddingBottom: BottomTabInset + insets.bottom + Spacing.five,
            gap: Spacing.two,
          }}
          ListHeaderComponent={
            /* Boards belong to following and nowhere else.

               Following a board is a thing you do; a board cannot
               follow you back, so the followers tab has nothing to
               put under that heading and showing it there asked a
               question with no answer. The heading appears only when
               there are boards: an empty section under a name is a
               statement that something is missing. */
            <View style={{ gap: Spacing.two, paddingBottom: Spacing.one }}>
              <>
                {tab === 'following' && mine && shownBoards.length > 0 ? (
                  <Heading>Boards</Heading>
                ) : null}
                {tab !== 'following' || !mine
                  ? null
                  : shownBoards.map((board) => (
                      <MotionPressable
                        key={board.id}
                        accessibilityRole="link"
                        accessibilityLabel={`${board.name}, ${
                          board.posts.length
                        } pins`}
                        animateEntrance={false}
                        onPress={() => {
                          void tapFeedback();
                          router.push({
                            pathname: '/board/[id]',
                            params: { id: board.id },
                          });
                        }}
                        style={{
                          minHeight: TapTarget,
                          justifyContent: 'center',
                        }}>
                        <ThemedText
                          style={labelType(FontSize.body, 800)}
                          numberOfLines={1}>
                          {board.name}
                        </ThemedText>
                      </MotionPressable>
                    ))}
              </>
              {tab === 'following' ? <Heading>People</Heading> : null}
            </View>
          }
          ListEmptyComponent={
            <Nobody
              needle={needle}
              tab={tab}
              mine={mine}
              name={title}
              handle={member.data?.handle ?? null}
            />
          }
          renderItem={({ item }) => <PersonRow person={item} />}
        />
      )}
    </View>
  );
}

/**
 * An empty list, and the one thing that would fill it.
 *
 * **Centred, with the action in it.** "No followers yet" over nothing
 * is a dead end; the reason somebody has none is almost always that
 * nobody has their page, so the way out of the state is in the state.
 *
 * Only on your own list: offering to share somebody else's profile
 * from their empty follower list is the app inviting you to promote a
 * stranger.
 */
function Nobody({
  needle,
  tab,
  mine,
  name,
  handle,
}: {
  needle: string;
  tab: Direction;
  mine: boolean;
  name: string;
  handle: string | null;
}) {
  const colors = Colors[useScheme()];

  const title = needle
    ? 'Nobody by that name'
    : tab === 'followers'
      ? 'No followers yet'
      : mine
        ? 'Not following anyone yet'
        : `${name} is not following anyone yet`;
  const body = needle
    ? 'Try a different name.'
    : tab === 'followers'
      ? mine
        ? 'Share your profile so people can follow you.'
        : 'Nobody follows them yet.'
      : mine
        ? "When you follow people or boards, they'll appear here"
        : ' ';

  return (
    <View
      style={{
        alignItems: 'center',
        gap: Spacing.two,
        paddingTop: Spacing.six,
        paddingHorizontal: Spacing.four,
      }}>
      <ThemedText
        accessibilityRole="header"
        style={{ ...labelType(FontSize.title3, 800), textAlign: 'center' }}>
        {title}
      </ThemedText>
      <ThemedText
        themeColor="textSecondary"
        style={{ ...labelType(FontSize.body, 400), textAlign: 'center' }}>
        {body}
      </ThemedText>
      {mine && !needle && tab === 'followers' ? (
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Share your profile"
          animateEntrance={false}
          scale={0.96}
          onPress={() => {
            void tapFeedback();
            void Share.share({
              message: handle
                ? `Find me on LUXish: @${handle}`
                : 'Find me on LUXish.',
            });
          }}
          style={{
            marginTop: Spacing.two,
            minHeight: TapTarget + Spacing.one,
            justifyContent: 'center',
            paddingHorizontal: Spacing.five,
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            backgroundColor: colors.accent,
          }}>
          <ThemedText
            style={{
              ...labelType(FontSize.body, 800),
              color: colors.accentText,
            }}>
            Share profile
          </ThemedText>
        </MotionPressable>
      ) : null}
    </View>
  );
}

/** A section name, in the grotesque the reference sets these in. */
function Heading({ children }: { children: string }) {
  return (
    <ThemedText
      accessibilityRole="header"
      style={{ ...labelType(20, 800), lineHeight: 26 }}>
      {children}
    </ThemedText>
  );
}

/** One person: who they are, and the one thing to do about it. */
function PersonRow({ person }: { person: FoundPerson }) {
  const colors = Colors[useScheme()];
  const setFollowing = useSetFollowing();

  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.two,
        minHeight: TapTarget + Spacing.one,
      }}>
      <MotionPressable
        accessibilityRole="link"
        accessibilityLabel={`${person.name}'s page`}
        animateEntrance={false}
        onPress={() => {
          void tapFeedback();
          router.push({
            pathname: '/member/[id]',
            params: { id: person.userId },
          });
        }}
        style={{
          flex: 1,
          flexDirection: 'row',
          alignItems: 'center',
          gap: Spacing.two,
        }}>
        <Monogram name={person.name} id={person.userId} />
        <View style={{ flex: 1, gap: Spacing.half }}>
          <ThemedText style={labelType(FontSize.body, 800)} numberOfLines={1}>
            {person.name}
          </ThemedText>
          <ThemedText
            themeColor="textSecondary"
            style={labelType(FontSize.subhead, 400)}>
            {person.followerCount === 1
              ? '1 follower'
              : `${person.followerCount} followers`}
          </ThemedText>
        </View>
      </MotionPressable>

      <MotionPressable
        accessibilityRole="button"
        accessibilityState={{ selected: person.followed }}
        accessibilityLabel={
          person.followed ? `Unfollow ${person.name}` : `Follow ${person.name}`
        }
        animateEntrance={false}
        scale={0.95}
        onPress={() => {
          void tapFeedback();
          setFollowing.mutate({
            userId: person.userId,
            follow: !person.followed,
          });
        }}
        style={{
          minHeight: 40,
          justifyContent: 'center',
          paddingHorizontal: Spacing.four,
          borderRadius: Radius.md,
          borderCurve: 'continuous',
          backgroundColor: person.followed
            ? colors.text
            : colors.backgroundElement,
        }}>
        <ThemedText
          style={{
            ...labelType(FontSize.subhead, 800),
            color: person.followed ? colors.background : colors.text,
          }}>
          {person.followed ? 'Following' : 'Follow'}
        </ThemedText>
      </MotionPressable>
    </View>
  );
}
