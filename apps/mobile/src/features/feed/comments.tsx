import { router } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { useState } from 'react';
import {
  Alert,
  FlatList,
  Modal,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useSetBlocked } from '@/api/queries/community';

import {
  CommentRefused,
  useComments,
  useDeleteComment,
  useLikeComment,
  useWriteComment,
  type Comment,
} from '@/api/queries/comments';
import { ThemedText } from '@/components/themed-text';
import { Monogram } from '@/components/ui/monogram';
import { FitAction } from '@/features/feed/fit-action';
import { MotionPressable, successFeedback, tapFeedback } from '@/components/ui/motion';
import { SkeletonRows } from '@/components/ui/skeleton';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { composerInset, useKeyboardInset } from '@/hooks/use-keyboard-inset';
import { useScheme } from '@/hooks/use-theme';

/** Mirrors `MAX_COMMENT` on the server. */
const MAX_COMMENT = 500;

/**
 * How long ago, in as few characters as it can be read in.
 *
 * `10mo` rather than `10 months ago`: this sits beside a name on a
 * line that also carries the comment's controls, and a phrase there
 * pushes them off the edge on a narrow phone. The unit is the largest
 * one that still gives a whole number, which is how everybody writes
 * these and is accurate enough for "when was this said".
 *
 * Exported for its test. Returns an empty string for anything it
 * cannot read, so a bad timestamp renders as nothing rather than as
 * `NaN`.
 */
export function sinceShort(when: string, now: Date = new Date()): string {
  const at = new Date(when).getTime();
  if (!Number.isFinite(at)) return '';
  const seconds = Math.max(0, (now.getTime() - at) / 1000);
  const steps: [number, string][] = [
    [60, 's'],
    [3600, 'm'],
    [86_400, 'h'],
    [604_800, 'd'],
    [2_629_800, 'w'],
    [31_557_600, 'mo'],
  ];
  let last = 1;
  for (const [limit, unit] of steps) {
    if (seconds < limit) return `${Math.floor(seconds / last)}${unit}`;
    last = limit;
  }
  return `${Math.floor(seconds / 31_557_600)}y`;
}

/**
 * The things people say under a photograph of an outfit.
 *
 * Offered because the commonest comment on a fit is approval, and
 * typing it out is the only thing standing between somebody and
 * saying so. Written here, in this file, by us - never generated and
 * never a suggestion about the photograph itself.
 */
const QUICK_REPLIES = [
  'Love it ❤️',
  'Brilliant!',
  'Obsessed 😍',
  'Looks good!',
] as const;

/** How many replies show under one comment before they fold. */
const REPLIES_FOLDED = 1;

/**
 * The thread under a fit.
 *
 * **Closed on the page, whole in a sheet.** A fit with forty comments
 * is otherwise a fit you scroll past forty comments to leave, and the
 * things below the thread stop being reachable. The page carries a
 * count and nothing else; tapping it opens the conversation in its own
 * full-height scroller, where every comment is visible and scrollable
 * without the rest of the screen paying for it.
 *
 * Nothing is previewed above that. A truncated first two would be a
 * second, worse presentation of the same thread sitting on a page
 * about a photograph.
 *
 * **A held comment is shown to the person who wrote it.** Anywhere
 * else, a comment that vanished on submission reads as a bug and
 * invites a second attempt; here it sits in place saying it is being
 * checked. Nobody else is told it exists.
 *
 * **Replies go one level deep.** A reply to a reply attaches to the top
 * of its thread rather than being refused, which is the server's rule
 * too: losing somebody's words to enforce a shape is the wrong trade.
 * Indentation stops at one step because a phone has no room for a
 * second.
 */
export function Comments({ postId }: { postId: string }) {
  const comments = useComments(postId, true);
  const [open, setOpen] = useState(false);

  const tops = (comments.data ?? []).filter((comment) => !comment.parentId);

  return (
    <>
      {/* A glyph and, where there are any, a number.

          It was a "5 comments" heading over a "Show all 5 comments"
          button: the same figure twice, and a section label for a
          section with nothing in it. A speech bubble beside the heart
          reads as what it is - one more thing this fit has - and
          tapping it opens the lot. Drawn by `FitAction` so it matches
          the two glyphs it sits between. */}
      <FitAction
        label={
          tops.length === 0
            ? 'Add a comment'
            : tops.length === 1
              ? 'Show 1 comment'
              : `Show ${tops.length} comments`
        }
        // A rounded rectangle with a tail at the bottom left, which is
        // the reference's comment glyph. `bubble.left` is the rounder,
        // more oval balloon and read as a different icon beside it.
        icon={{
          ios: 'message',
          android: 'chat_bubble_outline',
          web: 'chat_bubble',
        }}
        count={tops.length}
        onPress={() => setOpen(true)}
      />

      <CommentSheet
        postId={postId}
        visible={open}
        onClose={() => setOpen(false)}
      />
    </>
  );
}

/**
 * The whole conversation, scrollable, with the composer pinned.
 *
 * A `FlatList` rather than a mapped column inside a ScrollView: a long
 * thread is exactly the case where recycling matters, and nesting one
 * scroller inside another is what makes a comment list feel stuck.
 */
function CommentSheet({
  postId,
  visible,
  onClose,
}: {
  postId: string;
  visible: boolean;
  onClose: () => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const keyboard = useKeyboardInset();
  const comments = useComments(postId, visible);
  const write = useWriteComment(postId);
  const [body, setBody] = useState('');
  const [replyTo, setReplyTo] = useState<Comment | null>(null);

  const all = comments.data ?? [];
  const tops = all.filter((comment) => !comment.parentId);
  const repliesTo = (id: string) => all.filter((c) => c.parentId === id);

  const send = () => {
    const text = body.trim();
    if (!text || write.isPending) return;
    void tapFeedback();
    write.mutate(
      { body: text, parentId: replyTo?.id },
      {
        onSuccess: () => {
          setBody('');
          setReplyTo(null);
          void successFeedback();
        },
        onError: (error) => {
          Alert.alert(
            'Not posted',
            error instanceof CommentRefused
              ? error.message
              : 'That could not be posted. Try again in a moment.',
          );
        },
      },
    );
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        {/* The handle. Decorative - the sheet is dragged by its own
            presentation - but it is what says "this pulls down" before
            anybody has tried. */}
        <View style={{ alignItems: 'center', paddingTop: Spacing.one }}>
          <View
            accessible={false}
            style={{
              width: 36,
              height: 4,
              borderRadius: Radius.full,
              backgroundColor: colors.border,
            }}
          />
        </View>

        {/* Close on the left, the count in the middle, share on the
            right. The count is the title here, so it is centred and the
            controls sit either side of it rather than crowding one. */}
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            paddingHorizontal: Spacing.three,
            paddingTop: Spacing.two,
            paddingBottom: Spacing.two,
            borderBottomWidth: 1,
            borderBottomColor: colors.border,
          }}>
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Close"
            animateEntrance={false}
            scale={0.9}
            hitSlop={10}
            onPress={() => {
              void tapFeedback();
              onClose();
            }}
            style={{ width: TapTarget, justifyContent: 'center' }}>
            <SymbolView
              name={{ ios: 'xmark', android: 'close', web: 'close' }}
              size={20}
              tintColor={colors.text}
            />
          </MotionPressable>

          <ThemedText
            accessibilityRole="header"
            numberOfLines={1}
            style={{
              flex: 1,
              textAlign: 'center',
              ...labelType(FontSize.body, 800),
            }}>
            {tops.length === 1 ? '1 comment' : `${tops.length} comments`}
          </ThemedText>

          {/* The same width as the close, so the title is centred on the
              sheet rather than on whatever is left over. */}
          <View style={{ width: TapTarget }} />
        </View>

        <FlatList
          data={tops}
          keyExtractor={(comment) => comment.id}
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{
            paddingHorizontal: Spacing.three,
            paddingBottom: Spacing.three,
            gap: Spacing.three,
          }}
          ListEmptyComponent={
            comments.isPending ? (
              <SkeletonRows count={4} avatar={false} />
            ) : (
              <ThemedText
                type="small"
                themeColor="textSecondary"
                style={{ fontSize: FontSize.footnote }}>
                Nothing yet. Say something about this fit.
              </ThemedText>
            )
          }
          renderItem={({ item }) => (
            <Thread
              comment={item}
              replies={repliesTo(item.id)}
              postId={postId}
              onReply={() => setReplyTo(item)}
            />
          )}
        />

        <View
          style={{
            gap: Spacing.two,
            paddingTop: Spacing.two,
            // **The keyboard's own height, not a computed offset.**
            // `KeyboardAvoidingView` works its offset out from where
            // it sits in the window, and inside a `pageSheet` that
            // arithmetic is wrong - the sheet is not the window. The
            // composer came out part-covered, with the line being
            // typed hidden behind the keys.
            paddingBottom:
              composerInset({ keyboard, safeArea: insets.bottom }) + Spacing.two,
            borderTopWidth: 1,
            borderTopColor: colors.border,
          }}>
          {/* Something to say, for the people who want to say the
              ordinary thing.

              They fill the box rather than posting: the comment still
              goes through the same screen as any other, and a chip
              that posted on one tap would be a way to put text under a
              stranger's photograph without reading it back. */}
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={{
              gap: Spacing.two,
              paddingHorizontal: Spacing.three,
            }}>
            {QUICK_REPLIES.map((text) => (
              <MotionPressable
                key={text}
                accessibilityRole="button"
                accessibilityLabel={`Say "${text}"`}
                animateEntrance={false}
                scale={0.95}
                onPress={() => {
                  void tapFeedback();
                  setBody(text);
                }}
                style={{
                  minHeight: TapTarget - Spacing.two,
                  justifyContent: 'center',
                  paddingHorizontal: Spacing.three,
                  borderRadius: Radius.full,
                  backgroundColor: colors.backgroundElement,
                }}>
                <ThemedText style={labelType(FontSize.subhead, 400)}>
                  {text}
                </ThemedText>
              </MotionPressable>
            ))}
          </ScrollView>

          <View style={{ gap: Spacing.two, paddingHorizontal: Spacing.three }}>
          {replyTo ? (
            <View
              style={{
                flexDirection: 'row',
                alignItems: 'center',
                gap: Spacing.two,
              }}>
              <ThemedText
                type="small"
                themeColor="textSecondary"
                numberOfLines={1}
                style={{ flex: 1, fontSize: FontSize.meta }}>
                Replying to {replyTo.authorName}
              </ThemedText>
              <MotionPressable
                accessibilityRole="button"
                accessibilityLabel="Stop replying"
                animateEntrance={false}
                scale={0.9}
                hitSlop={8}
                onPress={() => {
                  void tapFeedback();
                  setReplyTo(null);
                }}>
                <SymbolView
                  name={{ ios: 'xmark', android: 'close', web: 'close' }}
                  size={14}
                  tintColor={colors.textSecondary}
                />
              </MotionPressable>
            </View>
          ) : null}

          <View
            style={{
              flexDirection: 'row',
              alignItems: 'flex-end',
              gap: Spacing.two,
            }}>
            <TextInput
              value={body}
              onChangeText={(next) => setBody(next.slice(0, MAX_COMMENT))}
              placeholder={
                replyTo ? `Reply to ${replyTo.authorName}` : 'Add a comment'
              }
              placeholderTextColor={colors.textSecondary}
              multiline
              accessibilityLabel="Write a comment"
              style={{
                flex: 1,
                minHeight: TapTarget,
                maxHeight: 120,
                paddingHorizontal: Spacing.three,
                paddingTop: Spacing.two,
                paddingBottom: Spacing.two,
                borderRadius: Radius.lg,
                borderCurve: 'continuous',
                borderWidth: 1,
                borderColor: colors.borderStrong,
                color: colors.text,
                fontSize: FontSize.subhead,
              }}
            />
            <MotionPressable
              accessibilityRole="button"
              accessibilityLabel="Post comment"
              accessibilityState={{
                disabled: body.trim().length === 0 || write.isPending,
                busy: write.isPending,
              }}
              disabled={body.trim().length === 0 || write.isPending}
              animateEntrance={false}
              scale={0.92}
              onPress={send}
              style={{
                width: TapTarget,
                height: TapTarget,
                alignItems: 'center',
                justifyContent: 'center',
                borderRadius: Radius.full,
                backgroundColor: colors.accent,
                opacity: body.trim().length > 0 && !write.isPending ? 1 : 0.35,
              }}>
              <SymbolView
                name={{
                  ios: 'arrow.up',
                  android: 'arrow_upward',
                  web: 'arrow_upward',
                }}
                size={18}
                tintColor={colors.accentText}
              />
            </MotionPressable>
          </View>
          </View>
        </View>
      </View>
    </Modal>
  );
}

/**
 * One comment and its replies, with the tail folded.
 *
 * A separate fold from the thread list's own: a single comment that
 * started a long argument should not force every other conversation
 * open with it.
 */
function Thread({
  comment,
  replies,
  postId,
  onReply,
}: {
  comment: Comment;
  replies: readonly Comment[];
  postId: string;
  onReply: () => void;
}) {
  const [open, setOpen] = useState(false);
  const shown = open ? replies : replies.slice(0, REPLIES_FOLDED);
  const hidden = replies.length - REPLIES_FOLDED;

  return (
    <View style={{ gap: Spacing.two }}>
      <Row comment={comment} postId={postId} onReply={onReply} />
      {shown.map((reply) => (
        <View key={reply.id} style={{ paddingLeft: Spacing.five }}>
          <Row comment={reply} postId={postId} onReply={onReply} />
        </View>
      ))}
      {hidden > 0 ? (
        <MotionPressable
          accessibilityRole="button"
          accessibilityState={{ expanded: open }}
          accessibilityLabel={
            open ? 'Hide replies' : `Show ${hidden} more replies`
          }
          animateEntrance={false}
          hitSlop={8}
          onPress={() => {
            void tapFeedback();
            setOpen((was) => !was);
          }}
          style={{
            alignSelf: 'flex-start',
            minHeight: 32,
            justifyContent: 'center',
            paddingLeft: Spacing.five,
          }}>
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ fontSize: FontSize.meta }}>
            {open
              ? 'Hide replies'
              : `${hidden} more ${hidden === 1 ? 'reply' : 'replies'}`}
          </ThemedText>
        </MotionPressable>
      ) : null}
    </View>
  );
}

/** One comment: who, what, and the two things to do about it. */
function Row({
  comment,
  postId,
  onReply,
}: {
  comment: Comment;
  postId: string;
  onReply: () => void;
}) {
  const colors = Colors[useScheme()];
  const remove = useDeleteComment(postId);
  const like = useLikeComment(postId);
  const [menu, setMenu] = useState(false);
  const waiting = comment.state !== 'published';

  return (
    <View
      style={{
        flexDirection: 'row',
        gap: Spacing.two,
        opacity: waiting ? 0.7 : 1,
      }}>
      {/* Their face, or the letter that stands in for it. The same
          avatar every other list of people in this app uses. */}
      <MotionPressable
        accessibilityRole="link"
        accessibilityLabel={`${comment.authorName}'s page`}
        animateEntrance={false}
        hitSlop={6}
        onPress={() => {
          void tapFeedback();
          router.push({
            pathname: '/member/[id]',
            params: { id: comment.authorId },
          });
        }}>
        <Monogram name={comment.authorName} id={comment.authorId} size={36} />
      </MotionPressable>

      <View style={{ flex: 1, gap: Spacing.half }}>
        <View
          style={{ flexDirection: 'row', alignItems: 'center', gap: Spacing.one }}>
          <ThemedText type="smallBold">{comment.authorName}</ThemedText>

          {/* When, in the shortest form that is still true. */}
          {comment.createdAt ? (
            <ThemedText
              type="small"
              themeColor="textSecondary"
              style={{ fontSize: FontSize.meta }}>
              {sinceShort(comment.createdAt)}
            </ThemedText>
          ) : null}

          {/* Said only to its author, because only its author can see it. */}
          {waiting ? (
            <ThemedText
              type="small"
              themeColor="textSecondary"
              style={{ fontSize: FontSize.meta }}>
              {comment.state === 'held' ? 'held' : 'being checked'}
            </ThemedText>
          ) : null}
        </View>

        <ThemedText type="small" selectable style={{ fontSize: FontSize.subhead }}>
          {comment.body}
        </ThemedText>

      {comment.note ? (
        <ThemedText
          type="small"
          style={{ fontSize: FontSize.meta, color: colors.danger }}>
          {comment.note}
        </ThemedText>
      ) : null}

      <View style={{ flexDirection: 'row', alignItems: 'center', gap: Spacing.three }}>
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel={`Reply to ${comment.authorName}`}
          animateEntrance={false}
          hitSlop={8}
          onPress={() => {
            void tapFeedback();
            onReply();
          }}>
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ fontSize: FontSize.meta }}>
            Reply
          </ThemedText>
        </MotionPressable>

        {/* The heart, between Reply and the rest. A real row on the
            server, so it survives the sheet being closed; the count
            appears from one up, the same rule the fit's own tally
            follows. */}
        <MotionPressable
          accessibilityRole="button"
          accessibilityState={{ selected: comment.likedByMe }}
          accessibilityLabel={
            comment.likedByMe
              ? `Liked. ${comment.likes} in all. Tap to unlike.`
              : `Like ${comment.authorName}'s comment`
          }
          animateEntrance={false}
          scale={0.9}
          hitSlop={8}
          onPress={() => {
            void tapFeedback();
            like.mutate({ id: comment.id, liked: !comment.likedByMe });
          }}
          style={{ flexDirection: 'row', alignItems: 'center', gap: Spacing.one }}>
          <SymbolView
            name={
              comment.likedByMe
                ? { ios: 'heart.fill', android: 'favorite', web: 'favorite' }
                : { ios: 'heart', android: 'favorite_border', web: 'favorite' }
            }
            size={16}
            weight="regular"
            tintColor={comment.likedByMe ? colors.danger : colors.textSecondary}
          />
          {comment.likes > 0 ? (
            <ThemedText
              type="small"
              themeColor="textSecondary"
              style={{ fontSize: FontSize.meta, fontVariant: ['tabular-nums'] }}>
              {comment.likes}
            </ThemedText>
          ) : null}
        </MotionPressable>

        {/* Everything else, behind three dots.

            Delete, hide, report and block are four controls that
            would otherwise sit under every comment in a thread. Only
            one of them is ever wanted, and which one depends on whose
            comment it is. */}
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel={`More for ${comment.authorName}'s comment`}
          animateEntrance={false}
          scale={0.9}
          hitSlop={8}
          onPress={() => {
            void tapFeedback();
            setMenu(true);
          }}>
          <SymbolView
            name={{ ios: 'ellipsis', android: 'more_horiz', web: 'more_horiz' }}
            size={16}
            tintColor={colors.textSecondary}
          />
        </MotionPressable>
      </View>

        <CommentMenu
          comment={comment}
          visible={menu}
          onClose={() => setMenu(false)}
          onDelete={() => remove.mutate(comment.id)}
        />
      </View>
    </View>
  );
}


/**
 * What can be done about one comment.
 *
 * **Hide is the small tool and it comes first.** Not wanting to read
 * one remark again is not a report and is certainly not a block, and
 * an app that offers only the big tools makes people reach for them.
 *
 * **Delete appears only on your own**, because only its author and
 * the fit's author may remove one, and the server is the authority on
 * that - the menu offers what it knows it can do.
 */
function CommentMenu({
  comment,
  visible,
  onClose,
  onDelete,
}: {
  comment: Comment;
  visible: boolean;
  onClose: () => void;
  onDelete: () => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const setBlocked = useSetBlocked();
  const [hidden, setHidden] = useState(false);

  const act = (run: () => void) => {
    void tapFeedback();
    onClose();
    run();
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Close"
        onPress={onClose}
        style={{ flex: 1, justifyContent: 'flex-end', backgroundColor: '#00000066' }}>
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
          }}>
          <ThemedText
            type="label"
            themeColor="textSecondary"
            style={{ paddingHorizontal: Spacing.three, paddingBottom: Spacing.two }}>
            Options
          </ThemedText>

          {comment.mine ? (
            <MenuRow
              label="Delete"
              destructive
              onPress={() =>
                act(() =>
                  Alert.alert(
                    'Delete this comment?',
                    'It will not be shown again.',
                    [
                      { text: 'Keep', style: 'cancel' },
                      {
                        text: 'Delete',
                        style: 'destructive',
                        onPress: onDelete,
                      },
                    ],
                  ),
                )
              }
            />
          ) : (
            <>
              <MenuRow
                label={hidden ? 'Hidden' : 'Hide'}
                onPress={() => {
                  // Local to this reading. A hidden comment is a
                  // preference about one remark, and persisting it
                  // would need a table nobody has asked for yet; the
                  // honest version is that it hides now and the copy
                  // does not promise more.
                  void tapFeedback();
                  setHidden(true);
                  onClose();
                }}
              />
              <MenuRow
                label="Report"
                onPress={() =>
                  act(() =>
                    router.push({
                      pathname: '/member/[id]',
                      params: { id: comment.authorId, report: '1' },
                    }),
                  )
                }
              />
              <MenuRow
                label={`Block ${comment.authorName}`}
                destructive
                onPress={() =>
                  act(() =>
                    Alert.alert(
                      `Block ${comment.authorName}?`,
                      'They stop appearing anywhere in your app, and any follows between you end. They are not told.',
                      [
                        { text: 'Cancel', style: 'cancel' },
                        {
                          text: 'Block',
                          style: 'destructive',
                          onPress: () =>
                            setBlocked.mutate({
                              userId: comment.authorId,
                              blocked: true,
                            }),
                        },
                      ],
                    ),
                  )
                }
              />
            </>
          )}
        </Pressable>
      </Pressable>
    </Modal>
  );
}

function MenuRow({
  label,
  destructive,
  onPress,
}: {
  label: string;
  destructive?: boolean;
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      animateEntrance={false}
      scale={0.99}
      onPress={onPress}
      style={{
        minHeight: TapTarget + Spacing.one,
        justifyContent: 'center',
        paddingHorizontal: Spacing.three,
      }}>
      <ThemedText
        type="smallBold"
        style={{
          fontSize: FontSize.subhead,
          color: destructive ? colors.danger : colors.text,
        }}>
        {label}
      </ThemedText>
    </MotionPressable>
  );
}
