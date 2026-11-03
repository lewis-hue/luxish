import { Image } from 'expo-image';
import { router } from 'expo-router';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { useEffect, useRef, useState } from 'react';
import { Alert, ScrollView, Share, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useFitDetail } from '@/api/queries/discover-feed';
import { useMessages, type ThreadSummary } from '@/api/queries/messages';
import { usePostImage } from '@/api/queries/post-media';
import {
  timeAgo,
  useInbox,
  useMarkInboxRead,
  type Notification,
} from '@/api/queries/notifications';
import { ThemedText } from '@/components/themed-text';
import { EmptyState } from '@/components/ui/empty-state';
import { SkeletonRows } from '@/components/ui/skeleton';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { Monogram } from '@/components/ui/monogram';
import { usePullToRefresh } from '@/components/ui/pull-to-refresh';
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

/** The thumbnail size the rows share. One number, so the column lines up. */
const THUMB = 56;

/** How many conversations stand on this screen before "See all". */
const SHOWN_THREADS = 3;

/**
 * The inbox: what people said, and what happened.
 *
 * **Two sections, because they are two different things.** A message
 * from a person is addressed to you and waits for a reply; an update
 * is something the app did. Sorting them together by time buries the
 * first under the second within a week.
 *
 * **Messages are real now**, and the section is the first few
 * conversations with a way through to the rest. It used to be one row
 * saying messages were not open — honest at the time, because direct
 * messages could not ship before blocking and reporting did, and both
 * now have.
 *
 * **Updates are derived from what already happened**, so nothing here
 * was invented to fill the screen.
 *
 * Opening marks everything read. There is one watermark per person
 * rather than a flag per item, and the list does not empty itself:
 * you opened it to find something.
 */
export default function InboxScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';
  const inbox = useInbox(signedIn);
  const messages = useMessages(signedIn);
  const markRead = useMarkInboxRead();
  const refresh = usePullToRefresh();

  // Once per visit, after the list has actually arrived. Marking read
  // before the fetch lands would clear a count for things never shown.
  const marked = useRef(false);
  const [hidden, setHidden] = useState<string[]>([]);

  useEffect(() => {
    if (!signedIn || !inbox.data) return;
    if (!marked.current && inbox.data.unread > 0) {
      marked.current = true;
      markRead.mutate();
    }
  }, [signedIn, inbox.data, markRead]);

  if (!signedIn) {
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: colors.background,
          justifyContent: 'center',
        }}>
        <EmptyState
          status="blocked"
          title="Sign in to see your inbox"
          body="It is built from your wardrobe, your stylist runs and the fits you kept."
          action={{ label: 'Sign in', onPress: () => router.push('/sign-in') }}
        />
      </View>
    );
  }

  const updates = (inbox.data?.items ?? []).filter(
    (item) => !hidden.includes(keyFor(item)),
  );
  const threads = messages.data?.threads ?? [];

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <View
        style={{
          minHeight: TapTarget,
          marginTop: insets.top + Spacing.one,
          justifyContent: 'center',
          paddingHorizontal: Spacing.three,
        }}>
        <ThemedText
          accessibilityRole="header"
          style={{ ...labelType(FontSize.body, 800), textAlign: 'center' }}>
          Inbox
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
            else router.replace('/');
          }}
          style={{
            position: 'absolute',
            left: Spacing.three,
            height: TapTarget,
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
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Write a new message"
          animateEntrance={false}
          scale={0.92}
          hitSlop={8}
          onPress={() => {
            void tapFeedback();
            router.push('/messages/new');
          }}
          style={{
            position: 'absolute',
            right: Spacing.three,
            height: TapTarget,
            justifyContent: 'center',
          }}>
          <SymbolView
            name={{ ios: 'square.and.pencil', android: 'edit', web: 'edit' }}
            size={20}
            tintColor={colors.text}
          />
        </MotionPressable>
      </View>

      <ScrollView
        refreshControl={refresh.control}
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{
          paddingTop: Spacing.four,
          paddingBottom: insets.bottom + Spacing.five,
          gap: Spacing.four,
        }}>
        <View style={{ gap: Spacing.one }}>
          <Heading
            title="Messages"
            action={{ label: 'See all', onPress: () => router.push('/messages') }}
          />
          {threads.slice(0, SHOWN_THREADS).map((thread) => (
            <ThreadRow key={thread.userId} thread={thread} />
          ))}
          <Row
            onPress={() => {
              void tapFeedback();
              void Share.share({
                message:
                  'I am keeping my outfits on LUXish. Come and see what I am wearing.',
              });
            }}
            thumbnail={
              <Glyph
                name={{
                  ios: 'person.badge.plus',
                  android: 'person_add',
                  web: 'person_add',
                }}
              />
            }
            title="Invite your friends"
          />
        </View>

        <View style={{ gap: Spacing.one }}>
          <Heading title="Updates" />
          {updates.length === 0 && inbox.isPending ? (
            <View style={{ paddingHorizontal: Spacing.three }}>
              <SkeletonRows
                count={3}
                round={false}
                size={56}
                label="Loading your updates"
              />
            </View>
          ) : updates.length === 0 ? (
            <ThemedText
              themeColor="textSecondary"
              style={{
                paddingHorizontal: Spacing.three,
                ...labelType(FontSize.subhead, 400),
              }}>
              {`Nothing in the last ${inbox.data?.windowDays ?? 14} days.`}
            </ThemedText>
          ) : (
            updates.map((item) => (
              <UpdateRow
                key={keyFor(item)}
                item={item}
                onHide={() => setHidden((was) => [...was, keyFor(item)])}
              />
            ))
          )}
        </View>

        <Row
          onPress={() => router.push('/notification-settings')}
          thumbnail={
            <Glyph
              name={{
                ios: 'bell',
                android: 'notifications',
                web: 'notifications',
              }}
            />
          }
          title="Notification settings"
          body="Plan reminders, and which updates appear here."
        />
      </ScrollView>
    </View>
  );
}

/** Stable enough to key and to hide by: kind, time and title. */
function keyFor(item: Notification): string {
  return `${item.kind}-${item.occurredAt}-${item.title}`;
}

function Heading({
  title,
  action,
}: {
  title: string;
  action?: { label: string; onPress: () => void };
}) {
  const colors = Colors[useScheme()];
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        paddingHorizontal: Spacing.three,
        paddingBottom: Spacing.one,
      }}>
      <ThemedText
        accessibilityRole="header"
        style={{ flex: 1, ...labelType(FontSize.title3, 800) }}>
        {title}
      </ThemedText>
      {action ? (
        <MotionPressable
          accessibilityRole="link"
          accessibilityLabel={action.label}
          animateEntrance={false}
          scale={0.96}
          hitSlop={8}
          onPress={() => {
            void tapFeedback();
            action.onPress();
          }}
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            gap: Spacing.half,
          }}>
          <ThemedText style={labelType(FontSize.subhead, 400)}>
            {action.label}
          </ThemedText>
          <SymbolView
            name={{
              ios: 'chevron.right',
              android: 'chevron_right',
              web: 'chevron_right',
            }}
            size={14}
            tintColor={colors.text}
          />
        </MotionPressable>
      ) : null}
    </View>
  );
}

/** One conversation, as the inbox shows it. */
function ThreadRow({ thread }: { thread: ThreadSummary }) {
  return (
    <Row
      onPress={() =>
        router.push({
          pathname: '/messages/[id]',
          params: { id: thread.userId, name: thread.name },
        })
      }
      thumbnail={
        <Monogram name={thread.name} id={thread.userId} size={THUMB} />
      }
      title={thread.name}
      body={thread.last ?? undefined}
      meta={thread.unread > 0 ? `${thread.unread} new` : undefined}
    />
  );
}

/**
 * One update.
 *
 * A thumbnail, a line, when it happened, and a way to be rid of it.
 * The picture is the look it is about where there is one, which is
 * what makes a list of these scannable: "four people reached for this
 * too" means nothing until you can see which look it was.
 */
function UpdateRow({
  item,
  onHide,
}: {
  item: Notification;
  onHide: () => void;
}) {
  // The fit it is about, read off the target the server set. One
  // place decides where a notice points, and this follows it rather
  // than keeping a second copy of the rule.
  const postId = item.target?.startsWith('/fit/')
    ? item.target.slice('/fit/'.length)
    : null;
  const detail = useFitDetail(postId ?? '', postId !== null);
  const uri =
    usePostImage(detail.data?.fit.mediaAssetIds[0] ?? null).data ?? null;

  return (
    <Row
      onPress={item.target ? () => router.push(item.target as never) : undefined}
      thumbnail={
        uri ? (
          <Image
            // A row thumbnail, 56 points.
            source={{ uri }}
            contentFit="cover"
            style={{ width: THUMB, height: THUMB }}
          />
        ) : (
          <Glyph
            name={
              item.kind === 'stylist_ready'
                ? { ios: 'sparkles', android: 'auto_awesome', web: 'auto_awesome' }
                : { ios: 'tshirt', android: 'apparel', web: 'apparel' }
            }
          />
        )
      }
      title={item.title}
      body={item.body}
      meta={timeAgo(item.occurredAt)}
      onMore={() =>
        Alert.alert(item.title, undefined, [
          { text: 'Cancel', style: 'cancel' },
          {
            // Local to this reading. Persisting it would need a table
            // nobody has asked for, and the copy does not promise more.
            text: 'Hide this update',
            onPress: onHide,
          },
          {
            text: 'Notification settings',
            onPress: () => router.push('/notification-settings'),
          },
        ])
      }
    />
  );
}

/** A tinted tile, for a row with no picture of its own. */
function Glyph({ name }: { name: SymbolViewProps['name'] }) {
  const colors = Colors[useScheme()];
  return (
    <View
      style={{
        width: THUMB,
        height: THUMB,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: colors.backgroundSelected,
      }}>
      <SymbolView name={name} size={22} tintColor={colors.textSecondary} />
    </View>
  );
}

function Row({
  thumbnail,
  title,
  body,
  meta,
  onPress,
  onMore,
}: {
  thumbnail: React.ReactNode;
  title: string;
  body?: string;
  meta?: string;
  onPress?: () => void;
  onMore?: () => void;
}) {
  const colors = Colors[useScheme()];
  const disabled = !onPress;

  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.two,
        paddingRight: onMore ? Spacing.two : 0,
      }}>
      <MotionPressable
        // A button, not a link: these open screens in this app, and
        // "link" sets a screen reader's expectation of a web page.
        accessibilityRole={disabled ? 'text' : 'button'}
        // Time last, after the event, which is the order a person wants
        // it in.
        accessibilityLabel={[title, body, meta].filter(Boolean).join('. ')}
        disabled={disabled}
        animatePress={!disabled}
        haptic={!disabled}
        animateEntrance={false}
        // A row is wide, so a visible scale reads as the whole screen
        // moving rather than as the row being pressed.
        scale={0.99}
        onPress={onPress}
        style={{
          flex: 1,
          minHeight: TapTarget,
          paddingHorizontal: Spacing.three,
          paddingVertical: Spacing.two,
          flexDirection: 'row',
          alignItems: 'center',
          gap: Spacing.three,
        }}>
        <View
          style={{
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            overflow: 'hidden',
          }}>
          {thumbnail}
        </View>

        <View style={{ flex: 1, gap: Spacing.half }}>
          <ThemedText style={labelType(FontSize.body, 800)} numberOfLines={2}>
            {title}
          </ThemedText>
          {body ? (
            <ThemedText
              themeColor="textSecondary"
              numberOfLines={2}
              style={labelType(FontSize.subhead, 400)}>
              {body}
            </ThemedText>
          ) : null}
        </View>

        {meta ? (
          <ThemedText
            themeColor="textSecondary"
            style={labelType(FontSize.footnote, 400)}>
            {meta}
          </ThemedText>
        ) : null}
      </MotionPressable>

      {onMore ? (
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel={`More about: ${title}`}
          animateEntrance={false}
          scale={0.9}
          hitSlop={8}
          onPress={() => {
            void tapFeedback();
            onMore();
          }}
          style={{
            width: TapTarget - Spacing.two,
            height: TapTarget,
            alignItems: 'center',
            justifyContent: 'center',
          }}>
          <SymbolView
            name={{ ios: 'ellipsis', android: 'more_horiz', web: 'more_horiz' }}
            size={18}
            tintColor={colors.textSecondary}
          />
        </MotionPressable>
      ) : null}
    </View>
  );
}
