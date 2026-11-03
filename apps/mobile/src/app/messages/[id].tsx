import { Image } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  FlatList,
  KeyboardAvoidingView,
  ScrollView,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import * as ImagePicker from 'expo-image-picker';
import {
  RecordingPresets,
  requestRecordingPermissionsAsync,
  useAudioRecorder,
} from 'expo-audio';

import { useSetFollowing } from '@/api/queries/community';
import { greetingName, useMe } from '@/api/queries/me';
import {
  useMarkThreadRead,
  useSendMessage,
  useThread,
  useHideMessage,
  useUnsend,
  type Line,
} from '@/api/queries/messages';
import { usePostImage } from '@/api/queries/post-media';
import { ThemedText } from '@/components/themed-text';
import { EmptyState } from '@/components/ui/empty-state';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { Monogram } from '@/components/ui/monogram';
import { SkeletonBubbles } from '@/components/ui/skeleton';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { useAuth } from '@/features/auth/session';
import { uploadMedia } from '@/features/media/upload';
import { backToPlayback, openForRecording } from '@/features/audio/session';
import { Attachment } from '@/features/messages/attachment';
import { MessageSettings } from '@/features/messages/settings';
import { useScheme } from '@/hooks/use-theme';

/** Openers, for a conversation with nothing in it yet. */
const OPENERS = ['Hello!', '👋', 'Hi!', '🙂', 'How are you?'];

/**
 * One conversation.
 *
 * **The empty state is the invitation.** A blank thread with a
 * keyboard under it is a question nobody knows how to answer, so this
 * says whose thread it is, offers to follow them, and puts five
 * openers within reach. Tapping one sends it: an opener that only
 * fills the field is a second decision about a greeting.
 *
 * **What you typed appears at once.** The line is added locally and
 * rolled back if the send fails, because a chat that waits a round
 * trip to show your own message reads as broken on a slow connection.
 *
 * **Everything else is behind the three dots**, which is the one
 * place a conversation keeps blocking, reporting and hiding — the
 * controls that were always the condition for having messages at all.
 */
export default function ThreadScreen() {
  const params = useLocalSearchParams<{ id: string; name?: string }>();
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';

  const id = params.id ?? '';
  const me = useMe(signedIn);
  const thread = useThread(id, signedIn);
  const send = useSendMessage(id);
  const markRead = useMarkThreadRead();
  const unsend = useUnsend(id);
  const hide = useHideMessage(id);
  const follow = useSetFollowing();
  const [draft, setDraft] = useState('');
  const [menu, setMenu] = useState(false);
  // A picture takes a second or two to upload; the control says so
  // for the whole wait rather than looking unpressed.
  const [attaching, setAttaching] = useState(false);
  /**
   * A picture chosen but not sent yet.
   *
   * **Waiting is the point.** Picking one used to post it the
   * instant its upload finished, so there was no moment at which
   * somebody could say what it was, and no way back from the wrong
   * one. It waits with the composer now and goes when they send.
   *
   * The local `uri` is kept beside the id so the preview draws from
   * the file already on the phone rather than fetching back what was
   * just uploaded.
   */
  const [pending, setPending] = useState<{
    assetId: string;
    uri: string;
  } | null>(null);
  const list = useRef<FlatList<Line>>(null);

  // Memoised because the `?? []` makes a new array every render,
  // which would make the receipt below recompute on each one.
  const lines = useMemo(() => thread.data?.items ?? [], [thread.data?.items]);

  /**
   * The newest message of mine they have read.
   *
   * Computed once for the list rather than asked per bubble: every
   * row would otherwise scan the whole thread to find out whether
   * it is the last one.
   */
  const lastReadMine = useMemo(() => {
    for (let at = lines.length - 1; at >= 0; at -= 1) {
      const line = lines[at];
      if (line.mine && line.read) return line.id;
    }
    return null;
  }, [lines]);
  const name = thread.data?.name ?? params.name ?? 'Them';

  // Opening a conversation is reading it. Once per arrival rather than
  // per render: this writes, and writing on every render is a loop.
  const marked = useRef(false);
  useEffect(() => {
    if (!marked.current && thread.data && lines.length > 0) {
      marked.current = true;
      markRead.mutate(id);
    }
  }, [thread.data, lines.length, id, markRead]);

  const say = (body: string) => {
    const text = body.trim();
    // A picture on its own is a message; so is a line on its own.
    // Only both empty is nothing to send.
    if ((!text && !pending) || send.isPending) return;
    void tapFeedback();
    const held = pending;
    setDraft('');
    setPending(null);
    send.mutate(
      { body: text, assetId: held?.assetId },
      {
        onError: () => {
          // Both back, so a failure costs the tap and nothing else.
          setDraft(text);
          setPending(held);
        },
      },
    );
  };

  /**
   * A picture off this phone.
   *
   * The `+` used to open Discover to pick a fit, which was a guess at
   * what the control means. It means what it means everywhere else.
   * The picture goes up under its own media kind, so nothing that
   * reads clothes can pick up something sent to one person.
   */
  const attach = async () => {
    if (attaching || send.isPending) return;
    void tapFeedback();
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      Alert.alert(
        'Photos access needed',
        'Grant access in Settings to send a picture. Everything else keeps working.',
      );
      return;
    }
    const picked = await ImagePicker.launchImageLibraryAsync({
      // **Both, now that a thread can carry either.** It was
      // `['images']`, so a video could not be chosen at all - and
      // had one been, every upload was labelled `image/jpeg` and
      // the thread tried to draw it as a photograph.
      mediaTypes: ['images', 'videos'],
      quality: 0.9,
    });
    if (picked.canceled || !picked.assets[0]) return;

    setAttaching(true);
    try {
      const assetId = await uploadMedia({
        uri: picked.assets[0].uri,
        kind: 'message_media',
      });
      // **Held, not sent.** Picking a picture used to post it the
      // instant the upload finished, which meant there was no
      // moment at which somebody could say what it was - and no way
      // back if they picked the wrong one. It waits with the
      // composer now, exactly like typed text does, and goes when
      // they decide it goes.
      setPending({ assetId, uri: picked.assets[0].uri });
    } catch (caught) {
      Alert.alert(
        'That did not send',
        caught instanceof Error ? caught.message : 'Try again in a moment.',
      );
    } finally {
      setAttaching(false);
    }
  };

  /**
   * A voice note, recorded here and sent like any other attachment.
   *
   * **Tap to start, tap to stop, rather than hold to talk.** Holding
   * means the message is lost if the finger slips, and it cannot be
   * done at all one-handed while walking - which is most of when
   * somebody would rather speak than type. It also makes the length
   * of a message a test of how long you can hold still.
   *
   * It lands in the same pending slot a picture does, so it can be
   * reviewed, removed, or sent with a line of text beside it.
   */
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const [recording, setRecording] = useState(false);

  const speak = async () => {
    if (attaching || send.isPending) return;
    void tapFeedback();

    if (recording) {
      setRecording(false);
      setAttaching(true);
      try {
        await recorder.stop();
        await backToPlayback();
        const uri = recorder.uri;
        if (!uri) throw new Error('Nothing was recorded.');
        const assetId = await uploadMedia({ uri, kind: 'message_media' });
        setPending({ assetId, uri });
      } catch (caught) {
        Alert.alert(
          'That did not record',
          caught instanceof Error ? caught.message : 'Try again in a moment.',
        );
      } finally {
        setAttaching(false);
      }
      return;
    }

    const permission = await requestRecordingPermissionsAsync();
    if (!permission.granted) {
      Alert.alert(
        'Microphone access needed',
        'Grant access in Settings to send a voice note. Everything else keeps working.',
      );
      return;
    }
    try {
      // Nothing records until the session allows it, and nothing
      // raises when it does not. See `features/audio/session`.
      await openForRecording();
      await recorder.prepareToRecordAsync();
      recorder.record();
      setRecording(true);
    } catch (caught) {
      Alert.alert(
        'That did not start',
        caught instanceof Error ? caught.message : 'Try again in a moment.',
      );
    }
  };

  if (!signedIn) {
    return (
      <EmptyState
        status="blocked"
        title="Sign in to send messages"
        body="Writing to somebody is part of an account."
        action={{ label: 'Sign in', onPress: () => router.push('/sign-in') }}
      />
    );
  }

  if (thread.isError) {
    return (
      <EmptyState
        status="empty"
        title="No such conversation"
        body="The account may have gone, or one of you may have blocked the other."
        action={{
          label: 'Back',
          onPress: () =>
            router.canGoBack() ? router.back() : router.replace('/messages'),
        }}
      />
    );
  }

  return (
    <KeyboardAvoidingView
      behavior={process.env.EXPO_OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={0}
      style={{ flex: 1, backgroundColor: colors.background }}>
      {/* Who you are writing to, and the way out of it. */}
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: Spacing.two,
          marginTop: insets.top + Spacing.one,
          paddingHorizontal: Spacing.three,
          minHeight: TapTarget,
        }}>
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Back"
          animateEntrance={false}
          scale={0.92}
          hitSlop={8}
          onPress={() => {
            void tapFeedback();
            if (router.canGoBack()) router.back();
            else router.replace('/messages');
          }}
          style={{ height: TapTarget, justifyContent: 'center' }}>
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
          accessibilityRole="link"
          accessibilityLabel={`${name}'s page`}
          animateEntrance={false}
          onPress={() => {
            void tapFeedback();
            router.push({ pathname: '/member/[id]', params: { id } });
          }}
          style={{
            flex: 1,
            flexDirection: 'row',
            alignItems: 'center',
            gap: Spacing.two,
          }}>
          <Monogram name={name} id={id} size={36} />
          <ThemedText style={labelType(FontSize.body, 800)} numberOfLines={1}>
            {name}
          </ThemedText>
        </MotionPressable>

        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Message settings"
          animateEntrance={false}
          scale={0.92}
          hitSlop={8}
          onPress={() => {
            void tapFeedback();
            setMenu(true);
          }}
          style={{ height: TapTarget, justifyContent: 'center' }}>
          <SymbolView
            name={{ ios: 'ellipsis', android: 'more_horiz', web: 'more_horiz' }}
            size={20}
            tintColor={colors.text}
          />
        </MotionPressable>
      </View>

      {thread.isPending ? (
        <View style={{ padding: Spacing.three }}>
          <SkeletonBubbles count={5} />
        </View>
      ) : lines.length === 0 ? (
        <View
          style={{
            flex: 1,
            alignItems: 'center',
            justifyContent: 'center',
            gap: Spacing.two,
            paddingHorizontal: Spacing.five,
          }}>
          {/* Two monograms, overlapping: the picture of a conversation
              is two people, and there is nothing else to show yet. */}
          <View style={{ flexDirection: 'row', alignItems: 'center' }}>
            <Monogram name={name} id={id} size={72} />
            <View style={{ marginLeft: -Spacing.three }}>
              <Monogram
                name={greetingName(me.data ?? undefined) ?? 'You'}
                id={me.data?.userId}
                size={72}
              />
            </View>
          </View>
          <ThemedText style={labelType(FontSize.title3, 800)}>{name}</ThemedText>
          <ThemedText
            themeColor="textSecondary"
            style={{
              ...labelType(FontSize.body, 400),
              textAlign: 'center',
            }}>
            This could be the beginning of something good
          </ThemedText>
          {thread.data && !thread.data.followed ? (
            <MotionPressable
              accessibilityRole="button"
              accessibilityLabel={`Follow ${name}`}
              animateEntrance={false}
              scale={0.96}
              onPress={() => {
                void tapFeedback();
                follow.mutate({ userId: id, follow: true });
                void thread.refetch();
              }}
              style={{
                minHeight: TapTarget,
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
                Follow
              </ThemedText>
            </MotionPressable>
          ) : null}
        </View>
      ) : (
        <FlatList
          ref={list}
          data={lines}
          keyExtractor={(line) => line.id}
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{
            padding: Spacing.three,
            gap: Spacing.one,
          }}
          onContentSizeChange={() =>
            list.current?.scrollToEnd({ animated: false })
          }
          renderItem={({ item }) => (
            <Bubble
              line={item}
              // **Only under the last one they have seen.** A
              // "Read" beneath every bubble is the same fact
              // repeated down the whole thread; under the last it
              // says exactly where their reading got to.
              showRead={item.id === lastReadMine}
              // **Both people can remove a message; they are
              // different acts.** Yours goes from their conversation
              // too, because it is yours to take back. Theirs goes
              // from your copy only - the alternative would let
              // anybody edit anybody's record of a conversation, and
              // until now the only way to be rid of one line
              // somebody sent you was to clear the whole thread.
              onDelete={
                item.id.startsWith('pending-')
                  ? undefined
                  : item.mine
                    ? () =>
                        Alert.alert(
                          'Delete this message?',
                          'It goes from their conversation as well as yours.',
                          [
                            { text: 'Keep', style: 'cancel' },
                            {
                              text: 'Delete',
                              style: 'destructive',
                              onPress: () => unsend.mutate(item.id),
                            },
                          ],
                        )
                    : () =>
                        Alert.alert(
                          'Remove this message?',
                          'It goes from your copy. They keep theirs, and are not told.',
                          [
                            { text: 'Keep', style: 'cancel' },
                            {
                              text: 'Remove',
                              style: 'destructive',
                              onPress: () => hide.mutate(item.id),
                            },
                          ],
                        )
              }
            />
          )}
        />
      )}

      <View
        style={{
          borderTopWidth: 1,
          borderTopColor: colors.border,
          paddingTop: Spacing.two,
          paddingBottom: insets.bottom + Spacing.two,
          gap: Spacing.two,
        }}>
        {lines.length === 0 ? (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={{
              gap: Spacing.one,
              paddingHorizontal: Spacing.three,
            }}>
            {OPENERS.map((opener) => (
              <MotionPressable
                key={opener}
                accessibilityRole="button"
                accessibilityLabel={`Send ${opener}`}
                animateEntrance={false}
                scale={0.95}
                onPress={() => say(opener)}
                style={{
                  minHeight: 38,
                  justifyContent: 'center',
                  paddingHorizontal: Spacing.three,
                  borderRadius: Radius.full,
                  backgroundColor: colors.backgroundElement,
                }}>
                <ThemedText style={labelType(FontSize.subhead, 400)}>
                  {opener}
                </ThemedText>
              </MotionPressable>
            ))}
          </ScrollView>
        ) : null}

        {/* The picture waiting to go, with a way to change your mind.
            A chosen attachment with no preview and no remove is a
            decision somebody cannot see or undo. */}
        {pending ? (
          <View
            style={{
              flexDirection: 'row',
              alignItems: 'flex-end',
              paddingHorizontal: Spacing.three,
              paddingBottom: Spacing.two,
            }}>
            <View>
              <Image
                source={{ uri: pending.uri }}
                contentFit="cover"
                accessible
                accessibilityLabel="The picture you are about to send"
                style={{
                  width: 72,
                  height: 96,
                  borderRadius: Radius.md,
                  borderCurve: 'continuous',
                  backgroundColor: colors.backgroundElement,
                }}
              />
              <MotionPressable
                accessibilityRole="button"
                accessibilityLabel="Remove this picture"
                animateEntrance={false}
                scale={0.9}
                hitSlop={10}
                onPress={() => {
                  void tapFeedback();
                  setPending(null);
                }}
                style={{
                  position: 'absolute',
                  top: -Spacing.one,
                  right: -Spacing.one,
                  width: 24,
                  height: 24,
                  alignItems: 'center',
                  justifyContent: 'center',
                  borderRadius: Radius.full,
                  backgroundColor: colors.text,
                }}>
                <SymbolView
                  name={{ ios: 'xmark', android: 'close', web: 'close' }}
                  size={12}
                  weight="semibold"
                  tintColor={colors.background}
                />
              </MotionPressable>
            </View>
          </View>
        ) : null}

        <View
          style={{
            flexDirection: 'row',
            alignItems: 'flex-end',
            gap: Spacing.two,
            paddingHorizontal: Spacing.three,
          }}>
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Send a picture"
            accessibilityState={{ busy: attaching, disabled: attaching }}
            disabled={attaching}
            animateEntrance={false}
            scale={0.9}
            hitSlop={8}
            onPress={() => void attach()}
            style={{
              width: TapTarget - Spacing.two,
              height: TapTarget,
              alignItems: 'center',
              justifyContent: 'center',
              opacity: attaching ? 0.5 : 1,
            }}>
            <SymbolView
              name={
                attaching
                  ? { ios: 'hourglass', android: 'hourglass_empty', web: 'hourglass_empty' }
                  : { ios: 'plus', android: 'add', web: 'add' }
              }
              size={24}
              tintColor={colors.text}
            />
          </MotionPressable>

          {/* Speak instead of typing. Beside the `+` rather than
              behind it: a voice note is a way of writing a message,
              not a kind of file to attach. */}
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel={
              recording ? 'Stop recording' : 'Record a voice note'
            }
            accessibilityState={{ busy: recording, disabled: attaching }}
            disabled={attaching}
            animateEntrance={false}
            scale={0.9}
            hitSlop={8}
            onPress={() => void speak()}
            style={{
              width: TapTarget - Spacing.two,
              height: TapTarget,
              alignItems: 'center',
              justifyContent: 'center',
              opacity: attaching ? 0.5 : 1,
            }}>
            <SymbolView
              name={
                recording
                  ? { ios: 'stop.fill', android: 'stop', web: 'stop' }
                  : { ios: 'mic', android: 'mic', web: 'mic' }
              }
              size={22}
              tintColor={recording ? colors.accent : colors.text}
            />
          </MotionPressable>

          <TextInput
            value={draft}
            onChangeText={setDraft}
            placeholder={recording ? 'Recording...' : 'Type a message...'}
            placeholderTextColor={colors.textSecondary}
            accessibilityLabel="Your message"
            multiline
            maxLength={2000}
            onSubmitEditing={() => say(draft)}
            style={{
              flex: 1,
              minHeight: TapTarget,
              maxHeight: 120,
              paddingHorizontal: Spacing.three,
              paddingTop: Spacing.two,
              paddingBottom: Spacing.two,
              borderRadius: Radius.full,
              borderWidth: 1,
              borderColor: colors.borderStrong,
              color: colors.text,
              ...labelType(FontSize.body, 400),
            }}
          />

          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel={draft.trim() ? 'Send' : 'Send a heart'}
            accessibilityState={{ disabled: send.isPending }}
            disabled={send.isPending}
            animateEntrance={false}
            scale={0.92}
            onPress={() => say(draft.trim() ? draft : '❤️')}
            style={{
              width: TapTarget,
              height: TapTarget,
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              backgroundColor: colors.text,
              opacity: send.isPending ? 0.5 : 1,
            }}>
            <SymbolView
              name={
                draft.trim()
                  ? { ios: 'arrow.up', android: 'arrow_upward', web: 'arrow_upward' }
                  : { ios: 'heart.fill', android: 'favorite', web: 'favorite' }
              }
              size={20}
              tintColor={colors.background}
            />
          </MotionPressable>
        </View>
      </View>

      <MessageSettings
        userId={id}
        name={name}
        visible={menu}
        onClose={() => setMenu(false)}
      />
    </KeyboardAvoidingView>
  );
}

/**
 * One message. Yours on the right, theirs on the left.
 *
 * **Hold your own to take it back.** A delete button on every bubble
 * is four controls per exchange for an act people take once a week;
 * a hold is where that lives on every phone, and it is offered only
 * on messages the server would actually let you remove.
 */
function Bubble({
  line,
  onDelete,
  showRead,
}: {
  line: Line;
  onDelete?: () => void;
  /** Set on the newest message of yours they have seen. */
  showRead?: boolean;
}) {
  const colors = Colors[useScheme()];
  const uri = usePostImage(line.assetId).data ?? null;

  return (
    <MotionPressable
      accessibilityRole={onDelete ? 'button' : 'text'}
      accessibilityLabel={line.body || (line.assetId ? 'A picture' : '')}
      accessibilityHint={
        onDelete
          ? line.mine
            ? 'Hold to delete this message'
            : 'Hold to remove this message from your copy'
          : undefined
      }
      animateEntrance={false}
      animatePress={false}
      onLongPress={onDelete}
      style={{
        alignSelf: line.mine ? 'flex-end' : 'flex-start',
        maxWidth: '78%',
        gap: Spacing.half,
      }}>
      {/* Whatever they attached, drawn as the thing it is. This
          assumed a photograph and rendered an `Image`, so a video
          would have arrived as a broken picture and a voice note as
          nothing at all. */}
      <Attachment
        uri={uri}
        kind={line.mediaKind}
        label={line.body || 'A picture in this conversation'}
      />

      {line.body ? (
        <View
          style={{
            alignSelf: line.mine ? 'flex-end' : 'flex-start',
            paddingHorizontal: Spacing.three,
            paddingVertical: Spacing.two,
            borderRadius: Radius.lg,
            borderCurve: 'continuous',
            backgroundColor: line.mine ? colors.text : colors.backgroundElement,
          }}>
          <ThemedText
            selectable
            style={{
              ...labelType(FontSize.body, 400),
              color: line.mine ? colors.background : colors.text,
            }}>
            {line.body}
          </ThemedText>
        </View>
      ) : null}
    </MotionPressable>
  );
}
