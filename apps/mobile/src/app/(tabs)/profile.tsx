import { FlashList } from '@shopify/flash-list';
import { router } from 'expo-router';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { useState } from 'react';
import { ScrollView, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { greetingName, useMe } from '@/api/queries/me';
import { useMoodboards } from '@/api/queries/moodboards';
import { useSavedFits, type FeedFit } from '@/api/queries/discover-feed';
import { useMyPosts, type MinePost } from '@/api/queries/posts';
import { useMyProfile } from '@/api/queries/profile-identity';
import { useFollowCounts } from '@/api/queries/community';
import { useTaste } from '@/api/queries/taste';
import { ThemedText } from '@/components/themed-text';
import { usePullToRefresh } from '@/components/ui/pull-to-refresh';
import { BoardCover } from '@/components/ui/board-cover';
import { EmptyState } from '@/components/ui/empty-state';
import { SkeletonMasonry } from '@/components/ui/skeleton';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { PinActions, type PinSubject } from '@/components/ui/pin-actions';
import { FitCard } from '@/features/feed/fit-card';
import { IdentityHeader } from '@/features/profile/identity-header';
import { asFit, PostedBadge } from '@/features/profile/posted';
import {
  BottomTabInset,
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
} from '@/constants/theme';
import { useAuth } from '@/features/auth/session';
import { PlannerBoard } from '@/features/planner/board';
import { useScheme } from '@/hooks/use-theme';

type Tab = 'posted' | 'pins' | 'boards' | 'calendar';

/**
 * Posted first, and it is the one this screen opens on.
 *
 * What somebody made comes before what they kept. This screen used to
 * open on Pins and had no view of your own fits at all, so the only
 * way to see something you had posted was to find it on the board
 * among everybody else's - and the only way to take one down was not
 * to have posted it.
 */
const TABS: readonly { id: Tab; label: string }[] = [
  { id: 'posted', label: 'Posted' },
  { id: 'pins', label: 'Pins' },
  { id: 'boards', label: 'Boards' },
  { id: 'calendar', label: 'Calendar' },
];

/**
 * Your own library: what you kept, and how you filed it.
 *
 * **This screen used to be the account.** An identity block, then nine rows
 * of settings and legal links. The things somebody opens their own profile
 * to see — the looks they kept, the boards they made — were not on it at
 * all. Those are the screen now, and the account moved behind the gear,
 * which is where every app of this shape keeps it.
 *
 * **Pins and Boards are two views of the same keeping, so they are tabs
 * rather than two screens.** A pin is a look you kept; a board is a name
 * you put some of them under. Somebody looking for a thing they saved does
 * not know in advance which of the two they filed it as, and making them
 * guess from a menu is the common failure here.
 *
 * **The calendar is a row, not a third tab.** What is planned is a small
 * number of dated entries rather than a grid of pictures, so it does not
 * belong in a tab strip whose other two are boards of images — and the one
 * thing worth saying about it on this screen is how many days are spoken
 * for, which the row carries.
 */
export default function LibraryScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const refresh = usePullToRefresh();
  const { width } = useWindowDimensions();
  const [tab, setTab] = useState<Tab>('posted');
  const [acting, setActing] = useState<PinSubject | null>(null);

  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';
  const me = useMe(signedIn);
  const name = greetingName(me.data ?? undefined);
  const taste = useTaste(signedIn);
  const follows = useFollowCounts(signedIn);
  const profile = useMyProfile(signedIn);
  const boards = useMoodboards(signedIn);

  const columns = width >= 700 ? 4 : 3;
  const gutter = Spacing.two;

  /**
   * The fits this person kept, most recently kept first.
   *
   * **Other people's posts, not catalogue entries.** A pin is
   * something somebody saw on Discover and wanted again, and what is
   * on Discover is what people here wore — so the library holds the
   * same object the board does, counts and controls included.
   */
  const pins = useSavedFits(signedIn);

  /**
   * Your own fits, newest first, whatever state they are in.
   *
   * The one query that is meant to see everything: a fit you took
   * private is still here, and so is one the screen held - both say
   * so on the tile, because a fit nobody else can see must never look
   * to its author like one that is up.
   */
  const posted = useMyPosts(signedIn);

  const visibleBoards = boards.data ?? [];

  const header = (
    <View style={{ gap: Spacing.three, marginBottom: Spacing.two }}>
      {/* The account's own controls, above the identity rather than
          beside it: they are reached for, not read, and a row of icons
          level with somebody's name competes with it. */}
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'flex-end',
          gap: Spacing.one,
        }}>
        <IconButton
          label="Your avatar"
          icon={{ ios: 'figure.stand', android: 'person', web: 'person' }}
          onPress={() => router.push('/avatar')}
        />
        {/* The inbox is not here.

            It moved to the Discover masthead, where posting now lives
            too: that line is everything addressed to you or sent by
            you, and this screen is for who you are. Two places to find
            messages is one place too many. */}
        {/* What other people did with what you posted. It had no way
            in at all before: the screen existed and nothing linked to
            it. Here, beside the profile it reports on. */}
        <IconButton
          label="Insights"
          icon={{
            ios: 'chart.bar',
            android: 'bar_chart',
            web: 'bar_chart',
          }}
          onPress={() => router.push('/insights')}
        />
        <IconButton
          label="Settings"
          icon={{ ios: 'gearshape', android: 'settings', web: 'settings' }}
          onPress={() => router.push('/settings')}
        />
      </View>

      <IdentityHeader
        name={name ?? 'You'}
        handle={profile.data?.handle ?? null}
        // Your own page shows what you typed, not only what the screen
        // has approved — otherwise editing a bio would look like it
        // failed for as long as the check takes.
        bio={profile.data?.bio ?? null}
        links={profile.data?.links ?? []}
        // Not the drawn avatar: that is a figure the app generated,
        // and a profile picture is one somebody chose. With no photo
        // set this falls through to their initial.
        avatarUri={null}
        photoAssetId={me.data?.profilePhotoAssetId ?? null}
        email={me.data?.email}
        aesthetics={taste.data?.aesthetics ?? []}
        // Tappable on your own page. A count nobody can open is a
        // number somebody has to take on trust; a stranger's page keeps
        // the counts and does not open, because a follower list is a
        // list of real people and nobody agreed to be enumerated.
        counts={
          follows.data
            ? {
                followers: follows.data.followers,
                following: follows.data.following,
              }
            : null
        }
        onOpenPeople={(direction) =>
          router.push({
            pathname: '/people/[direction]',
            params: { direction },
          })
        }
        action={{
          label: 'Edit profile',
          onPress: () => router.push('/profile-edit'),
        }}
      />

      {/* Said only to its author: a bio in review or held is their
          business, and the public view simply does not show it. */}
      {profile.data?.bioState === 'pending_review' ? (
        <ThemedText
          type="small"
          themeColor="textSecondary"
          style={{ textAlign: 'center', fontSize: FontSize.meta }}>
          Your bio is being checked. Other people see the last approved one.
        </ThemedText>
      ) : profile.data?.bioState === 'held' ? (
        <ThemedText
          type="small"
          style={{
            textAlign: 'center',
            fontSize: FontSize.meta,
            color: colors.danger,
          }}>
          {profile.data.bioNote ?? 'Your bio was held.'}
        </ThemedText>
      ) : null}

      {/* Three, centred under the portrait and the button, which are
          both centred. A row of three pinned to the left read as the
          start of a longer list that had been cut off.

          A plain row rather than a scroller: three chips fit on the
          narrowest phone, and a horizontal ScrollView cannot centre
          content that does not overflow without a contentContainer that
          fights its own `flexGrow`. */}
      <View
        style={{
          flexDirection: 'row',
          justifyContent: 'center',
          gap: Spacing.two,
        }}>
        {TABS.map((option) => (
          <TabChip
            key={option.id}
            label={option.label}
            active={tab === option.id}
            onPress={() => setTab(option.id)}
          />
        ))}
      </View>

      {/* No search field.

          It was a second way to find your own things, on a screen whose
          whole job is to show them: a few dozen pins fit on two scrolls,
          and a field above them is a control that mostly sits empty. The
          `+` stays, because making a board is an action rather than a way
          of looking. */}
      {tab === 'boards' ? (
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="New board"
          animateEntrance={false}
          onPress={() => {
            void tapFeedback();
            router.push('/moodboards');
          }}
          style={{
            minHeight: TapTarget,
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'center',
            gap: Spacing.two,
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            backgroundColor: colors.backgroundElement,
          }}>
          <SymbolView
            name={{ ios: 'plus', android: 'add', web: 'add' }}
            size={18}
            tintColor={colors.text}
          />
          <ThemedText type="smallBold">New board</ThemedText>
        </MotionPressable>
      ) : null}
    </View>
  );

  if (tab === 'calendar') {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <ScrollView
          showsVerticalScrollIndicator={false}
          refreshControl={refresh.control}
          contentContainerStyle={{
            paddingTop: insets.top + Spacing.three,
            paddingHorizontal: Spacing.three,
            paddingBottom: BottomTabInset + insets.bottom + Spacing.five,
          }}>
          {header}
          {/* The calendar itself, not a summary of it. Tapping
              "Calendar" has to put the week in front of somebody; a
              screen that then asks them to open the calendar is the tap
              they already made. */}
          <PlannerBoard embedded />
        </ScrollView>
      </View>
    );
  }

  if (tab === 'posted') {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <FlashList
          data={posted.data ?? []}
          refreshControl={refresh.control}
          masonry
          keyExtractor={(item) => item.id}
          numColumns={columns}
          contentContainerStyle={{
            paddingTop: insets.top + Spacing.three,
            // Half a gutter back, so the outer margin still measures
            // `Spacing.three` to the edge of a tile.
            paddingHorizontal: Spacing.three - gutter / 2,
            paddingBottom: BottomTabInset + insets.bottom + Spacing.five,
          }}
          showsVerticalScrollIndicator={false}
          ListHeaderComponent={header}
          renderItem={({ item }: { item: MinePost }) => (
            <View
              style={{ paddingHorizontal: gutter / 2, paddingBottom: gutter }}>
            {/* No menu glyph here, the same as Pins.

                Taking a fit private or down lives on the fit itself,
                under the `...` that screen already has - which is
                where somebody deciding about a photograph is already
                looking. A second menu on the tile would put two ways
                to the same two actions on one screen and make this
                grid the odd one out. */}
              <FitCard
                fit={asFit(item)}
                onOpen={() =>
                  router.push({ pathname: '/fit/[id]', params: { id: item.id } })
                }
              />
              <PostedBadge post={item} />
            </View>
          )}
          ListEmptyComponent={
            posted.isPending ? (
              <SkeletonMasonry count={6} columns={columns} />
            ) : (
              <EmptyState
                status="empty"
                title="Nothing posted yet"
                body="Post a fit and it lands here, where you can take it private or take it down."
                action={{
                  label: 'Post a fit',
                  onPress: () => {
                    void tapFeedback();
                    router.push('/compose');
                  },
                }}
              />
            )
          }
        />

      </View>
    );
  }

  if (tab === 'boards') {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <FlashList
          data={visibleBoards}
          keyExtractor={(item) => item.id}
          numColumns={2}
          contentContainerStyle={{
            paddingTop: insets.top + Spacing.three,
            paddingHorizontal: Spacing.three,
            paddingBottom: BottomTabInset + insets.bottom + Spacing.five,
          }}
          showsVerticalScrollIndicator={false}
          ListHeaderComponent={header}
          renderItem={({ item, index }) => (
            <View
              style={{
                paddingLeft: index % 2 === 0 ? 0 : gutter,
                paddingBottom: gutter,
              }}>
              <MotionPressable
                index={index}
                accessibilityRole="button"
                accessibilityLabel={`${item.name}. ${item.posts.length} ${
                  item.posts.length === 1 ? 'fit' : 'fits'
                }.`}
                onPress={() => {
                  void tapFeedback();
                  router.push({
                    pathname: '/board/[id]',
                    params: { id: item.id },
                  });
                }}
                style={{ gap: Spacing.one }}>
                <BoardCover faces={item.posts} />
                <ThemedText type="smallBold" numberOfLines={1}>
                  {item.name}
                </ThemedText>
                <ThemedText
                  type="small"
                  themeColor="textSecondary"
                  style={{ fontSize: FontSize.meta }}>
                  {item.posts.length}{' '}
                  {item.posts.length === 1 ? 'fit' : 'fits'}
                </ThemedText>
              </MotionPressable>
            </View>
          )}
          ListEmptyComponent={
            boards.isPending ? (
              <View style={{ paddingHorizontal: Spacing.three }}>
                <SkeletonMasonry
                  count={4}
                  columns={columns}
                  gutter={gutter}
                  label="Loading your boards"
                />
              </View>
            ) : (
              <EmptyState
                status="empty"
                title="No boards yet"
                body="A board is a name you put a few fits under. Make one from any fit you save."
                action={{
                  label: 'Make a board',
                  onPress: () => {
                    void tapFeedback();
                    router.push('/moodboards');
                  },
                }}
              />
            )
          }
        />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <FlashList
        data={pins.data ?? []}
        refreshControl={refresh.control}
        masonry
        keyExtractor={(item) => item.id}
        numColumns={columns}
        contentContainerStyle={{
          paddingTop: insets.top + Spacing.three,
          // Half a gutter back, so the outer margin still measures
          // `Spacing.three` to the edge of a tile.
          paddingHorizontal: Spacing.three - gutter / 2,
          paddingBottom: BottomTabInset + insets.bottom + Spacing.five,
        }}
        showsVerticalScrollIndicator={false}
        ListHeaderComponent={header}
        renderItem={({ item }: { item: FeedFit }) => (
          <View
            style={{ paddingHorizontal: gutter / 2, paddingBottom: gutter }}>
            {/* The fit, not the person who posted it.

                This opened `/member/[id]`, so tapping something you
                had kept took you to a stranger's profile instead of
                to the picture you tapped. Everywhere else in the app
                a tile opens its own fit; the author is one more tap
                from there, on the fit itself. */}
            <FitCard
              fit={item}
              onOpen={() =>
                router.push({ pathname: '/fit/[id]', params: { id: item.id } })
              }
            />
          </View>
        )}
        ListEmptyComponent={
          <EmptyState
            status="empty"
            title="Nothing kept yet"
            body="Keep a fit from Discover and it lands here."
            action={{
              label: 'Go to Discover',
              onPress: () => {
                void tapFeedback();
                router.push('/');
              },
            }}
          />
        }
      />

      <PinActions
        subject={acting}
        visible={acting !== null}
        onClose={() => setActing(null)}
      />
    </View>
  );
}

/** One of the two library tabs. */
function TabChip({
  label,
  active,
  onPress,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="tab"
      accessibilityState={{ selected: active }}
      accessibilityLabel={label}
      animateEntrance={false}
      onPress={() => {
        void tapFeedback();
        onPress();
      }}
      style={{
        minHeight: 34,
        justifyContent: 'center',
        paddingHorizontal: Spacing.three,
        borderRadius: Radius.full,
        backgroundColor: active ? colors.text : 'transparent',
        borderWidth: 1,
        borderColor: active ? colors.text : colors.border,
      }}>
      <ThemedText
        type="small"
        style={{
          fontSize: FontSize.footnote,
          color: active ? colors.background : colors.textSecondary,
        }}>
        {label}
      </ThemedText>
    </MotionPressable>
  );
}

/** A square icon control, for the things in this header that are not read. */
function IconButton({
  label,
  icon,
  onPress,
}: {
  label: string;
  icon: SymbolViewProps['name'];
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      animateEntrance={false}
      scale={0.92}
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
      <SymbolView name={icon} size={22} tintColor={colors.text} />
    </MotionPressable>
  );
}
