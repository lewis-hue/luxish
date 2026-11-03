import { Image } from 'expo-image';
import { Redirect, Stack, router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import {
  Alert,
  Modal,
  Pressable,
  ScrollView,
  View,
  useWindowDimensions,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  useMember,
  type MemberFit,
  useReport,
  useSetBlocked,
  useSetFollowing,
  type ReportReason,
} from '@/api/queries/community';
import { useMe } from '@/api/queries/me';
import { usePostImages } from '@/api/queries/post-media';
import { SymbolView } from 'expo-symbols';
import { ThemedText } from '@/components/themed-text';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton, SkeletonMasonry } from '@/components/ui/skeleton';
import { Monogram } from '@/components/ui/monogram';
import { openSite, safeSite } from '@/features/profile/website';
import { isOwnPage } from '@/features/profile/whose-page';
import { usePullToRefresh } from '@/components/ui/pull-to-refresh';
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
 * One other person, as far as they have agreed to be seen.
 *
 * **What they posted leads the page.** Publishing is an affirmative
 * public act: a fit on Discover is already in front of strangers, so
 * showing it here discloses nothing new. The page used to open on a
 * follower count while saying nothing about the hundreds of
 * photographs its subject had published, which made it a worse view
 * of information the viewer already had.
 *
 * **The banner and bio are theirs, and screened.** Both are shown to
 * everybody who opens the page, so both go through the same screen a
 * caption does, and this view never renders one still in review.
 *
 * **The shelf is a separate thing.** With `community_sharing` granted,
 * what they *kept* of other people's appears too. Without the grant
 * the page says the shelf is private, which is a state, not a failure.
 *
 * No photograph of them: being shown to strangers needs a consent that
 * does not exist yet, so a monogram stands in.
 *
 * **Report and block live here**, because both stores require them before
 * any composer ships and this is the screen that shows a person. A report
 * is recorded for a human to read, and the confirmation says exactly that.
 * A block severs follows both ways, hides them everywhere, and is never
 * announced to them.
 */
/**
 * A grid of somebody's fits.
 *
 * Three across rather than the two Discover uses: this is a page about
 * a person, and the point is how much they have made rather than what
 * any single picture looks like. Tapping one opens it where every
 * other fit in the app opens.
 */
function FitGrid({
  fits,
  width,
}: {
  fits: readonly MemberFit[];
  width: number;
}) {
  const colors = Colors[useScheme()];
  // By asset id. Asking for pictures by *post* id is why this drew a
  // grid of grey boxes the first time.
  const images = usePostImages(
    fits.map((fit) => fit.coverAssetId).filter(Boolean) as string[],
  );
  const gutter = Spacing.half;
  const side = (width - Spacing.three * 2 - gutter * 2) / 3;

  return (
    <View
      style={{
        flexDirection: 'row',
        flexWrap: 'wrap',
        gap: gutter,
        paddingHorizontal: Spacing.three,
      }}>
      {fits.map((fit) => {
        const uri = fit.coverAssetId
          ? (images.data?.[fit.coverAssetId] ?? null)
          : null;
        return (
          <MotionPressable
            key={fit.postId}
            accessibilityRole="imagebutton"
            accessibilityLabel="Open this fit"
            animateEntrance={false}
            scale={0.97}
            onPress={() => {
              void tapFeedback();
              router.push({
                pathname: '/fit/[id]',
                params: { id: fit.postId },
              });
            }}>
            {uri ? (
              <Image
                source={{ uri }}
                // The grid recycles; without this a reused tile shows
                // the previous person's fit until the new one loads.
                recyclingKey={fit.postId}
                contentFit="cover"
                transition={ImageFade}
                style={{
                  width: side,
                  height: side * 1.25,
                  borderRadius: Radius.sm,
                  backgroundColor: colors.backgroundElement,
                }}
              />
            ) : (
              <View
                style={{
                  width: side,
                  height: side * 1.25,
                  borderRadius: Radius.sm,
                  backgroundColor: colors.backgroundElement,
                }}
              />
            )}
          </MotionPressable>
        );
      })}
    </View>
  );
}

export default function MemberScreen() {
  const params = useLocalSearchParams<{ id: string; report?: string }>();
  const id = params.id;
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const refresh = usePullToRefresh();
  const { width } = useWindowDimensions();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';

  // **Your own page is never somebody else's page.**
  //
  // This screen is written for a stranger, and nothing in it asked
  // whether the stranger is you. Searching your own name and opening
  // the result therefore gave you the visitor's view of yourself:
  // Follow and Message buttons pointed at your own account, no way to
  // edit anything, and - because `Profile.private` is answered from
  // the viewer's side - "Their shelf is private" about your own
  // shelf. The tab bar lit Discover too, since this route is not the
  // profile tab.
  //
  // One redirect fixes all of it rather than teaching this screen a
  // second mode: `/profile` is already the owner's view of exactly
  // this account, and it is a tab, so the bar lights correctly by
  // construction.
  const me = useMe(signedIn);
  const mine = isOwnPage({ viewerId: me.data?.userId, pageId: id });

  const member = useMember(id ?? '', signedIn && Boolean(id) && !mine);

  // Their banner, through the same authenticated fetcher every other
  // picture here uses: served behind a bearer token and cached to disk
  // once rather than refetched on every render.
  const banner = usePostImages(
    member.data?.bannerAssetId ? [member.data.bannerAssetId] : [],
  );
  const bannerUri = member.data?.bannerAssetId
    ? (banner.data?.[member.data.bannerAssetId] ?? null)
    : null;
  const shownPosts = member.data?.posts ?? [];

  // A link they published. Built from the stored platform and handle
  // rather than from a URL they typed, so it can only point where it
  // says it does.
  // Built from the stored host, then checked like any other link
  // before it is offered. The server fixes the scheme by
  // construction; this file cannot see that, and the check is a
  // function call.
  const stored = (member.data?.links ?? {}).website?.trim();
  const website = safeSite(stored ? `https://${stored.replace(/^https?:\/\//i, '')}` : null);
  const [shelf, setShelf] = useState<'created' | 'saved'>('created');
  // Opened straight into the report list when a comment's menu sent
  // somebody here to report its author.
  const [menu, setMenu] = useState(params.report === '1');
  const setFollowing = useSetFollowing();
  const setBlocked = useSetBlocked();

  // Before every other branch, so not one frame of the visitor's view
  // of your own account is ever painted. `replace`, not `push`: this
  // page is not somewhere to go back to.
  if (mine) return <Redirect href="/profile" />;

  // `me` is part of the wait, not just `member`. Until identity has
  // arrived `mine` is false, and rendering on that would show the
  // visitor's view of your own account for a frame before the
  // redirect above caught it.
  if (member.isPending || (signedIn && me.isPending)) {
    // Their page in outline. It used to render nothing until the whole
    // profile arrived, so opening somebody dropped a blank screen and
    // then everything at once.
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: colors.background,
          paddingTop: insets.top + Spacing.three,
          paddingHorizontal: Spacing.three,
          gap: Spacing.three,
        }}>
        <Skeleton width={96} height={96} radius={Radius.full} />
        <Skeleton width={180} height={24} />
        <Skeleton width={240} height={14} />
        <SkeletonMasonry count={6} label="Opening this profile" />
      </View>
    );
  }

  if (member.isError) {
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: colors.background,
          justifyContent: 'center',
        }}>
        <EmptyState
          status="empty"
          title="No such account"
          body="It may have been deleted."
        />
      </View>
    );
  }

  const data = member.data;

  const confirmBlock = () => {
    if (!data) return;
    Alert.alert(
      `Block ${data.name}?`,
      'They stop appearing anywhere in your app, and any follows between you end. They are not told.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Block',
          style: 'destructive',
          onPress: () =>
            setBlocked.mutate({ userId: data.userId, blocked: true }),
        },
      ],
    );
  };

  return (
    <>
      <Stack.Screen
        options={{
          headerRight: () =>
            data ? (
              /* Report and block, behind three dots.

                 Both stores require them and this is the screen that
                 shows a person, so they cannot simply go. They also
                 cannot stand at the bottom of the page as two plain
                 rows: that puts "Block" one scroll below somebody's
                 photographs on every profile anybody ever opens. */
              <MotionPressable
                accessibilityRole="button"
                accessibilityLabel={`More about ${data.name}`}
                animateEntrance={false}
                scale={0.92}
                hitSlop={8}
                onPress={() => {
                  void tapFeedback();
                  setMenu(true);
                }}
                // Centred in its own box, with no padding of its own.
                // iOS draws a header button inside a round chip and
                // centres *the box*, so a glyph pinned to the end of a
                // tap-target-wide one sits off-centre in the circle.
                style={{ alignItems: 'center', justifyContent: 'center' }}>
                <SymbolView
                  name={{
                    ios: 'ellipsis',
                    android: 'more_horiz',
                    web: 'more_horiz',
                  }}
                  size={20}
                  tintColor={colors.text}
                />
              </MotionPressable>
            ) : null,
        }}
      />
      <ScrollView
        style={{ flex: 1, backgroundColor: colors.background }}
        refreshControl={refresh.control}
        contentInsetAdjustmentBehavior="automatic"
        contentContainerStyle={{
          paddingTop: Spacing.three,
          paddingBottom: BottomTabInset + insets.bottom + Spacing.five,
          gap: Spacing.five,
        }}
        showsVerticalScrollIndicator={false}>
        {!data ? null : (
          <>
            {/* Their banner, when the screen passed one. Full bleed and
              behind everything else, which is what a banner is. */}
            {bannerUri ? (
              <Image
                source={{ uri: bannerUri }}
                contentFit="cover"
                transition={ImageFade}
                accessible
                accessibilityLabel={`${data.name}'s banner`}
                style={{
                  width,
                  height: 160,
                  marginTop: -Spacing.three,
                  backgroundColor: colors.backgroundElement,
                }}
              />
            ) : null}

            <View
              style={{ gap: Spacing.two, paddingHorizontal: Spacing.three }}>
              <View
                style={{
                  flexDirection: 'row',
                  alignItems: 'center',
                  gap: Spacing.two,
                }}>
                {/* A letter, not a face. Carrying somebody's photograph
                  between accounts needs a consent this app does not
                  collect, and a monogram is honest about that. */}
              <Monogram name={data.name} id={data.userId} size={56} />
                <View style={{ flex: 1, gap: Spacing.half }}>
                  {/* The grotesque, not the display serif. The Bodoni
                    is the product's voice - a screen title, the
                    wordmark - and setting a person's name in it made
                    their page read as a chapter opening. */}
                  <ThemedText
                    accessibilityRole="header"
                    numberOfLines={1}
                    style={{ ...labelType(26, 800), lineHeight: 30 }}>
                    {data.name}
                  </ThemedText>
                  {data.handle ? (
                    <ThemedText
                      type="small"
                      themeColor="textSecondary"
                      style={{ fontSize: FontSize.footnote }}>
                      @{data.handle}
                    </ThemedText>
                  ) : null}
                </View>
              </View>

              {/* The two counts are questions, so they are tappable.
                A follower count that cannot be opened is the app
                declining to answer the most ordinary thing anybody
                asks about a person they just found. */}
              <View
                style={{
                  flexDirection: 'row',
                  alignItems: 'center',
                  gap: Spacing.three,
                }}>
                {(['followers', 'following'] as const).map((which) => (
                  <MotionPressable
                    key={which}
                    accessibilityRole="link"
                    accessibilityLabel={`${
                      which === 'followers'
                        ? data.followerCount
                        : data.followingCount
                    } ${which} of ${data.name}`}
                    animateEntrance={false}
                    scale={0.96}
                    hitSlop={6}
                    onPress={() => {
                      void tapFeedback();
                      router.push({
                        pathname: '/people/[direction]',
                        params: {
                          direction: which,
                          user: data.userId,
                          name: data.name,
                        },
                      });
                    }}
                    style={{ minHeight: 32, justifyContent: 'center' }}>
                    <ThemedText style={labelType(FontSize.subhead, 800)}>
                      {which === 'followers'
                        ? data.followerCount
                        : data.followingCount}{' '}
                      <ThemedText
                        themeColor="textSecondary"
                        style={labelType(FontSize.subhead, 400)}>
                        {which}
                      </ThemedText>
                    </ThemedText>
                  </MotionPressable>
                ))}
                {data.postCount > 0 ? (
                  <ThemedText
                    themeColor="textSecondary"
                    style={labelType(FontSize.subhead, 400)}>
                    {data.postCount === 1 ? '1 fit' : `${data.postCount} fits`}
                  </ThemedText>
                ) : null}
                {data.followsYou ? (
                  <ThemedText
                    themeColor="textSecondary"
                    style={labelType(FontSize.subhead, 400)}>
                    follows you
                  </ThemedText>
                ) : null}
              </View>

              {data.bio ? (
                <ThemedText type="small" style={{ fontSize: FontSize.subhead }}>
                  {data.bio}
                </ThemedText>
              ) : null}
            </View>

            {data.blocked ? (
              <View
                style={{ paddingHorizontal: Spacing.three, gap: Spacing.two }}>
                <ThemedText
                  type="small"
                  themeColor="textSecondary"
                  style={{ textAlign: 'center' }}>
                  You blocked this account. They appear nowhere else in your
                  app.
                </ThemedText>
                <MotionPressable
                  accessibilityRole="button"
                  animateEntrance={false}
                  onPress={() => {
                    void tapFeedback();
                    setBlocked.mutate({ userId: data.userId, blocked: false });
                  }}
                  style={{
                    minHeight: TapTarget,
                    alignItems: 'center',
                    justifyContent: 'center',
                    borderRadius: Radius.md,
                    borderCurve: 'continuous',
                    borderWidth: 1,
                    borderColor: colors.borderStrong,
                  }}>
                  <ThemedText type="smallBold">Unblock</ThemedText>
                </MotionPressable>
              </View>
            ) : (
              /* Follow, then the two things you do with somebody you
               follow. Left-aligned and sized to their words rather
               than stretched across the page: a full-width Follow
               reads as the only thing on offer. */
              <View
                style={{
                  flexDirection: 'row',
                  gap: Spacing.two,
                  paddingHorizontal: Spacing.three,
                }}>
                <MotionPressable
                  accessibilityRole="button"
                  accessibilityState={{ selected: data.followed }}
                  accessibilityLabel={
                    data.followed
                      ? `Unfollow ${data.name}`
                      : `Follow ${data.name}`
                  }
                  animateEntrance={false}
                  scale={0.96}
                  onPress={() => {
                    void tapFeedback();
                    setFollowing.mutate({
                      userId: data.userId,
                      follow: !data.followed,
                    });
                    // The member page carries its own copy of the state.
                    void member.refetch();
                  }}
                  style={{
                    minHeight: TapTarget,
                    justifyContent: 'center',
                    paddingHorizontal: Spacing.four,
                    borderRadius: Radius.full,
                    backgroundColor: data.followed
                      ? colors.backgroundElement
                      : colors.accent,
                  }}>
                  <ThemedText
                    type="smallBold"
                    style={{
                      color: data.followed ? colors.text : colors.accentText,
                    }}>
                    {data.followed ? 'Following' : 'Follow'}
                  </ThemedText>
                </MotionPressable>

                <MotionPressable
                  accessibilityRole="button"
                  accessibilityLabel={`Message ${data.name}`}
                  animateEntrance={false}
                  scale={0.96}
                  onPress={() => {
                    void tapFeedback();
                    router.push({
                      pathname: '/messages/[id]',
                      params: { id: data.userId, name: data.name },
                    });
                  }}
                  style={{
                    minHeight: TapTarget,
                    justifyContent: 'center',
                    paddingHorizontal: Spacing.four,
                    borderRadius: Radius.full,
                    backgroundColor: colors.backgroundElement,
                  }}>
                  <ThemedText type="smallBold">Message</ThemedText>
                </MotionPressable>

                {/* Only for somebody who put a link on their profile.
                  A Visit button on a page with nowhere to go is a
                  control that does nothing. */}
                {website ? (
                  <MotionPressable
                    accessibilityRole="link"
                    accessibilityLabel={`Visit ${data.name}'s site`}
                    animateEntrance={false}
                    scale={0.96}
                    onPress={() => {
                      void tapFeedback();
                      openSite(website);
                    }}
                    style={{
                      minHeight: TapTarget,
                      justifyContent: 'center',
                      paddingHorizontal: Spacing.four,
                      borderRadius: Radius.full,
                      backgroundColor: colors.backgroundElement,
                    }}>
                    <ThemedText type="smallBold">Visit</ThemedText>
                  </MotionPressable>
                ) : null}
              </View>
            )}

            {/* A private account: the counts above stay, the pictures
              do not. Said in words rather than left as an empty grid,
              because an empty grid and a withheld one look identical
              and mean opposite things. */}
            {data.private ? (
              <View
                style={{ paddingHorizontal: Spacing.three, gap: Spacing.one }}>
                <ThemedText style={labelType(FontSize.body, 800)}>
                  This account is private
                </ThemedText>
                <ThemedText
                  themeColor="textSecondary"
                  style={labelType(FontSize.subhead, 400)}>
                  {data.name} keeps their fits and the people they are connected
                  to to themselves.
                </ThemedText>
              </View>
            ) : null}

            {/* What they made, and what they kept.

              Two tabs rather than two stacked sections: they are
              alternatives, and stacking them makes the second one
              something you only find by scrolling past the first. */}
            <View
              style={{
                gap: Spacing.three,
                display: data.private ? 'none' : 'flex',
              }}>
              <View
                style={{
                  flexDirection: 'row',
                  justifyContent: 'center',
                  gap: Spacing.four,
                }}>
                {(['created', 'saved'] as const).map((which) => {
                  const active = shelf === which;
                  return (
                    <MotionPressable
                      key={which}
                      accessibilityRole="tab"
                      accessibilityState={{ selected: active }}
                      accessibilityLabel={
                        which === 'created'
                          ? 'Fits they posted'
                          : 'Fits they kept'
                      }
                      animateEntrance={false}
                      onPress={() => {
                        void tapFeedback();
                        setShelf(which);
                      }}
                      style={{
                        minHeight: TapTarget,
                        justifyContent: 'center',
                        borderBottomWidth: 2,
                        borderBottomColor: active ? colors.text : 'transparent',
                      }}>
                      <ThemedText
                        type={active ? 'smallBold' : 'small'}
                        themeColor={active ? 'text' : 'textSecondary'}>
                        {which === 'created' ? 'Created' : 'Saved'}
                      </ThemedText>
                    </MotionPressable>
                  );
                })}
              </View>

              {shelf === 'created' ? (
                shownPosts.length === 0 ? (
                  <ThemedText
                    type="small"
                    themeColor="textSecondary"
                    style={{
                      paddingHorizontal: Spacing.three,
                      fontSize: FontSize.footnote,
                    }}>
                    Nothing posted yet.
                  </ThemedText>
                ) : (
                  <FitGrid fits={shownPosts} width={width} />
                )
              ) : !data.shares ? (
                <ThemedText
                  type="small"
                  themeColor="textSecondary"
                  style={{
                    paddingHorizontal: Spacing.three,
                    fontSize: FontSize.footnote,
                  }}>
                  Their shelf is private. What somebody keeps only appears once
                  they let it.
                </ThemedText>
              ) : data.savedPosts.length === 0 ? (
                <ThemedText
                  type="small"
                  themeColor="textSecondary"
                  style={{
                    paddingHorizontal: Spacing.three,
                    fontSize: FontSize.footnote,
                  }}>
                  Nothing kept yet.
                </ThemedText>
              ) : (
                <FitGrid fits={data.savedPosts} width={width} />
              )}
            </View>
          </>
        )}
      </ScrollView>

      {data ? (
        <MemberMenu
          userId={data.userId}
          name={data.name}
          blocked={data.blocked}
          visible={menu}
          onClose={() => setMenu(false)}
          onBlock={confirmBlock}
          onUnblock={() =>
            setBlocked.mutate({ userId: data.userId, blocked: false })
          }
        />
      ) : null}
    </>
  );
}

/** The reason list the stores require, opened in place rather than behind
 *  a hidden menu: a control the reviewer cannot find might as well not
 *  exist, and neither might one the person reporting cannot. */
const REASONS: { id: ReportReason; label: string }[] = [
  { id: 'impersonation', label: 'Pretending to be someone' },
  { id: 'inappropriate', label: 'Inappropriate' },
  { id: 'spam', label: 'Spam' },
  { id: 'other', label: 'Something else' },
];

function ReportSection({ userId, name }: { userId: string; name: string }) {
  const colors = Colors[useScheme()];
  const report = useReport();
  const [open, setOpen] = useState(false);
  const [sent, setSent] = useState(false);

  if (sent) {
    return (
      <View style={{ paddingHorizontal: Spacing.three }}>
        <ThemedText
          type="small"
          themeColor="textSecondary"
          style={{ fontSize: FontSize.footnote }}>
          Reported. A person reviews these, so it is read rather than acted on
          automatically.
        </ThemedText>
      </View>
    );
  }

  return (
    <View style={{ gap: Spacing.one }}>
      <View style={{ paddingHorizontal: Spacing.three }}>
        <MotionPressable
          accessibilityRole="button"
          accessibilityState={{ expanded: open }}
          animateEntrance={false}
          onPress={() => setOpen((current) => !current)}
          style={{ minHeight: TapTarget, justifyContent: 'center' }}>
          <ThemedText type="small">Report {name}</ThemedText>
        </MotionPressable>
      </View>
      {open
        ? REASONS.map((reason) => (
            <MotionPressable
              key={reason.id}
              accessibilityRole="button"
              accessibilityLabel={`Report for ${reason.label}`}
              animateEntrance={false}
              disabled={report.isPending}
              onPress={() => {
                void tapFeedback();
                report.mutate(
                  {
                    subjectKind: 'account',
                    subjectUserId: userId,
                    reason: reason.id,
                  },
                  { onSuccess: () => setSent(true) },
                );
              }}
              style={{
                minHeight: TapTarget,
                paddingHorizontal: Spacing.three,
                justifyContent: 'center',
                borderBottomWidth: 1,
                borderBottomColor: colors.border,
              }}>
              <ThemedText type="small" themeColor="textSecondary">
                {reason.label}
              </ThemedText>
            </MotionPressable>
          ))
        : null}
    </View>
  );
}

/**
 * What can be done about a person, other than follow them.
 *
 * **Report first, block second.** They are different sizes of the same
 * instinct, and an app that offers only the larger one makes people
 * reach for it. Reporting is read by a person; blocking is immediate,
 * severs follows both ways, and is never announced.
 *
 * The reasons open in place rather than behind a second screen: a
 * report form somebody has to navigate to is a report that does not
 * get filed.
 */
function MemberMenu({
  userId,
  name,
  blocked,
  visible,
  onClose,
  onBlock,
  onUnblock,
}: {
  userId: string;
  name: string;
  blocked: boolean;
  visible: boolean;
  onClose: () => void;
  onBlock: () => void;
  onUnblock: () => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Close"
        onPress={onClose}
        style={{
          flex: 1,
          justifyContent: 'flex-end',
          backgroundColor: '#00000066',
        }}>
        <Pressable
          // Swallows taps so pressing the sheet does not close it.
          onPress={() => {}}
          style={{
            paddingTop: Spacing.three,
            paddingBottom: insets.bottom + Spacing.three,
            backgroundColor: colors.background,
            borderTopLeftRadius: Radius.lg,
            borderTopRightRadius: Radius.lg,
            borderCurve: 'continuous',
            gap: Spacing.one,
          }}>
          <ThemedText
            accessibilityRole="header"
            style={{
              ...labelType(FontSize.body, 800),
              paddingHorizontal: Spacing.three,
              paddingBottom: Spacing.one,
            }}>
            {name}
          </ThemedText>

          <ReportSection userId={userId} name={name} />

          <View style={{ paddingHorizontal: Spacing.three }}>
            <MotionPressable
              accessibilityRole="button"
              accessibilityLabel={blocked ? `Unblock ${name}` : `Block ${name}`}
              animateEntrance={false}
              onPress={() => {
                void tapFeedback();
                onClose();
                if (blocked) onUnblock();
                else onBlock();
              }}
              style={{ minHeight: TapTarget, justifyContent: 'center' }}>
              <ThemedText
                style={{
                  ...labelType(FontSize.subhead, 800),
                  color: blocked ? colors.text : colors.danger,
                }}>
                {blocked ? `Unblock ${name}` : `Block ${name}`}
              </ThemedText>
            </MotionPressable>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
