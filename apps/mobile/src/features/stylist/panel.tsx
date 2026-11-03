import { router, useLocalSearchParams } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  TextInput,
  View,
  type ScrollViewInstance,
} from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { EmptyState } from '@/components/ui/empty-state';
import {
  MotionPressable,
  successFeedback,
  tapFeedback,
} from '@/components/ui/motion';
import { Screen } from '@/components/ui/screen';
import { useDelayedVisible } from '@/components/ui/skeleton';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  toneColor,
  labelType,
} from '@/constants/theme';
import {
  hasAiConsent,
  useConsents,
  useSetConsent,
} from '@/api/queries/consents';
import { useAuth } from '@/features/auth/session';
import { useFavouriteGarments } from '@/features/discover/saved';
import { DRESS_CODES } from '@/features/taxonomy';
import { useRenders } from '@/api/queries/avatar';
import { askStylist } from '@/features/stylist/ask';
import {
  asked as chatAsked,
  begin as beginChat,
  decided as chatDecided,
  drawing as chatDrawing,
  failed as chatFailed,
  forget as chatForget,
  history as chatHistory,
  rewind as chatRewind,
  settled as chatSettled,
  shopped as chatShopped,
  streamed as chatStreamed,
  type Turn,
} from '@/features/stylist/conversation';
import { Thread } from '@/features/stylist/thread';
import {
  awaitRun,
  describeRunFailure,
  isAssistantAnswer,
  startRun,
  type StylistOutcome,
} from '@/features/stylist/run';
import {
  AttachButton,
  AttachedCard,
  type StylistAttachment,
} from '@/features/stylist/attachment';
import { MicButton } from '@/features/stylist/mic-button';
import { AvatarLook } from '@/features/stylist/try-on';
import { usePostImage } from '@/api/queries/post-media';
import { useWardrobe } from '@/features/wardrobe/store';
import { useScheme } from '@/hooks/use-theme';

/**
 * Ask for an outfit built from clothes the user already owns.
 *
 * The screen leads with the request rather than with a chat transcript. A
 * centred text box plus a row of suggestion chips is now the default shape of
 * every AI product, and it is the shape users have learned to ignore; what
 * makes this one different is that it opens already knowing the wardrobe it
 * will style from, and says so.
 *
 * It is also deliberately not called an assistant or a chatbot. NET-A-PORTER
 * and MR PORTER both frame the same capability as a Personal Shopper, which
 * is a service word rather than a technology word, and reads as something a
 * fashion house offers rather than a feature someone bolted on.
 */

/** Enough garments to combine into something worth showing. */
const MINIMUM_GARMENTS = 4;

const PROMPTS = [
  'Something for the office tomorrow',
  'Dinner, smart but not stiff',
  'Weekend, walking a lot',
  'Cold morning, warm evening',
] as const;

/**
 * What to say once there is a picture in hand.
 *
 * These are the studio capabilities, written as things to say rather than
 * rendered as buttons. The screen used to carry a row of treatment tiles
 * for exactly these; the functions are all still here, and a sentence is
 * how you reach them.
 */
const WITH_A_PICTURE = [
  'Shoot this on a model',
  'Cut it out on white',
  'Make me a lookbook for this',
  'Product shots for the catalogue',
  'Style an outfit around this',
] as const;

type RunState =
  | { status: 'idle' }
  | { status: 'needsConsent' }
  | { status: 'running' }
  /* A question being answered now lives in `conversation`, not in
     this union: an answer is a turn in a thread rather than the
     screen's one current state. */
  | { status: 'done'; outcome: StylistOutcome }
  | { status: 'failed'; title: string; body: string };

/**
 * Whether this is a question or an order.
 *
 * **The split is the repository's own rule**: the stylist is reached
 * by asking and the studio by choosing. A chip is a choice - it names
 * a treatment and should make the thing. Anything somebody typed
 * themselves is a question and should be answered before anything is
 * made, which is the whole of the bug this fixes: "Do I have any
 * outfits that could match the fit above?" produced an avatar and no
 * answer.
 *
 * Compared against the chip lists rather than sniffed for a question
 * mark: "what goes with this" has no question mark and is plainly a
 * question, and a keyword rule here would be a second, worse copy of
 * the classifier the server already runs.
 */
function isAQuestion(text: string): boolean {
  const said = text.trim().toLowerCase();
  if (!said) return false;
  const chips: readonly string[] = [...WITH_A_PICTURE, ...PROMPTS];
  return !chips.some((chip) => chip.toLowerCase() === said);
}

/**
 * The dress code named in a request, if one is.
 *
 * Matched against the app's own vocabulary so the value handed to the
 * server is one it knows, never a fragment of somebody's sentence. The
 * longest match wins, so "smart casual" is not read as "casual".
 */
function dressCodeIn(request: string): string | null {
  const said = ` ${request.toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ')} `;
  let best: { id: string; length: number } | null = null;
  for (const code of DRESS_CODES) {
    const needle = ` ${code.label.toLowerCase()} `;
    if (said.includes(needle) && (!best || needle.length > best.length)) {
      best = { id: code.id, length: needle.length };
    }
  }
  return best?.id ?? null;
}

export function StylistPanel({
  /**
   * Rendered inside somebody else's scroll view.
   *
   * The wardrobe page mounts this above its grid, which is where
   * people actually talk to it: the clothes it reasons about are on
   * that screen. Embedded it draws no scroll view of its own, no
   * title and no way back, because the page around it has all three.
   */
  embedded = false,
  /**
   * Add a garment to the wardrobe, when the page around this one can.
   *
   * Passed by the wardrobe so its two old header buttons live in the
   * composer's `+` rather than taking a row of their own. Absent
   * everywhere else, and the rows simply do not appear.
   */
  onAddGarment,
  /**
   * A conversation restored from the device's history.
   *
   * `null` means the history has not been read yet, which is not the
   * same as an empty thread: mounting with `[]` and then replacing it
   * a moment later would flash the greeting over a conversation that
   * was already there.
   */
  restored = null,
  /**
   * Called whenever the thread changes, so it can be written down.
   *
   * The panel does not know about SQLite and should not: it owns the
   * conversation, the caller owns whether conversations are kept.
   */
  onTurns,
  refreshControl,
  /**
   * Remounts the thread when it changes. The history screen hands back
   * a session id; this is what makes switching to it actually swap the
   * conversation rather than merging two.
   */
  sessionKey,
}: {
  embedded?: boolean;
  onAddGarment?: (source: 'camera' | 'library') => void;
  restored?: readonly Turn[] | null;
  onTurns?: (turns: readonly Turn[]) => void;
  sessionKey?: string;
  /**
   * The page's pull-to-refresh, for the scroll view this owns.
   *
   * The page used to own the scroll and therefore the gesture.
   * Now that the thread scrolls here, the control has to come
   * with it or pulling down on the wardrobe does nothing.
   */
  refreshControl?: React.ReactElement;
} = {}) {
  const scroller = useRef<ScrollViewInstance | null>(null);
  const [attachment, setAttachment] = useState<StylistAttachment | null>(null);
  const [attachedFor, setAttachedFor] = useState<string | null>(null);
  const colors = Colors[useScheme()];
  const favourites = useFavouriteGarments();
  const wardrobe = useWardrobe(favourites.values);

  // What was carried in from another screen. A garment from the
  // wardrobe or a fit from Discover; the curated look that used to
  // arrive here came from a page that no longer exists.
  const {
    garment: garmentParam,
    fit: fitParam,
    asset: fitAssetParam,
    ask: askParam,
  } = useLocalSearchParams<{
    garment?: string;
    /** A fit from Discover, carried so it can be tried on or referenced. */
    fit?: string;
    /** That fit's cover, so the chip can show it without a lookup. */
    asset?: string;
    /**
     * A question typed on the wardrobe page.
     *
     * The composer lives there now - it is one line and a `+`, beside
     * the clothes it is about - and this screen is where the answer
     * is worked out and shown. Seeding the field rather than running
     * on arrival keeps the sentence editable: somebody who mistyped
     * should not have to go back a screen to fix it.
     */
    ask?: string;
  }>();

  // The carried fit's cover, so the chip shows the picture somebody
  // was looking at rather than a bare label.
  const fitCover = usePostImage(fitAssetParam ?? null).data ?? null;

  const [request, setRequest] = useState(askParam ?? '');
  // Read out of the request rather than picked from a row of chips.
  //
  // The chips were a second way to say something the sentence already
  // says, and they were six more controls on the screen somebody is
  // trying to talk to. The server still gets the structured hint it uses
  // to resolve guidance; it just comes from the words now.
  const dressCode = dressCodeIn(request);
  const [run, setRun] = useState<RunState>({ status: 'idle' });

  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';
  const consents = useConsents(signedIn);

  /**
   * The conversation, rather than one result at a time.
   *
   * The panel held a single outcome: you asked, it answered, and
   * asking again discarded the answer - so "what about with the
   * boots instead" was impossible, because the thing being referred
   * to had already left the screen.
   */
  const [chat, setChat] = useState(beginChat());

  // **Restored turns replace the thread, once, per session.**
  //
  // Derived during render rather than copied in an effect: an effect
  // that calls setState on mount re-renders the screen a second time
  // and trips `react-hooks/set-state-in-effect`. `shownFor` is the
  // session the current `chat` belongs to, so switching sessions
  // swaps the thread and a re-render with the same session does not.
  const [shownFor, setShownFor] = useState<string | undefined>(sessionKey);
  if (sessionKey !== shownFor) {
    setShownFor(sessionKey);
    setChat(
      restored && restored.length
        ? { turns: [...restored], next: restored.length + 1 }
        : beginChat(),
    );
  }

  // Report the thread upward whenever it changes, so the caller can
  // write it down. Guarded on the turns themselves rather than on the
  // conversation object, which is new on every reducer call.
  const lastReported = useRef<readonly Turn[] | null>(null);
  useEffect(() => {
    if (!onTurns) return;
    if (lastReported.current === chat.turns) return;
    lastReported.current = chat.turns;
    onTurns(chat.turns);
  }, [chat.turns, onTurns]);
  /** Whether the "what can I ask?" suggestions are open. Closed. */

  /**
   * Any avatar a turn is waiting on.
   *
   * **Read, not copied.** Mirroring these into the conversation
   * meant setting state from an effect, which this repository lints
   * against and which duplicates a source of truth that already
   * polls itself. The thread looks a render up by id instead, so
   * there is one answer to "is it drawn yet" and it is the one
   * `useRenders` already maintains.
   *
   * Nothing was watching them at all before this: a try-on queued a
   * render, the thread drew a spinner, and eight of them had
   * already failed with "create your avatar first" while the wheel
   * kept turning.
   */
  const renders = useRenders(signedIn);
  const setConsent = useSetConsent();

  const wearable = wardrobe.entries.filter(
    (entry) => entry.availability === 'available' && !entry.isSample,
  );
  const ready = wearable.length >= MINIMUM_GARMENTS;
  const thinking = useDelayedVisible(run.status === 'running');

  // A request about a picture does not need a wardrobe: asking to
  // photograph an attached piece works on an empty account, and refusing
  // it because there are three garments rather than four would be a rule
  // about outfits applied to something that is not one.
  const canSend =
    run.status !== 'running' &&
    request.trim().length > 0 &&
    (ready || attachment !== null || Boolean(fitParam));

  /** Ask, and let the reply write itself into the thread. */
  const answer = async (said: string) => {
    const question = said.trim();
    if (!question) return;

    // The turns so far travel with it, so a follow-up is understood
    // as one. Taken before the new turn is added, because the new
    // question is sent separately from the history.
    const earlier = chatHistory(chat);
    // The picture goes into the turn, then off the composer.
    //
    // Both halves matter. In the transcript it shows that the pin and
    // the words were sent together, which is what somebody reading
    // back needs to know. Off the composer, because the model has the
    // conversation from here on: a card left pinned above the box
    // implied every later question was still about that one pin, and
    // it was the single biggest piece of furniture on the screen.
    const sentWith = attachment?.uri ?? undefined;
    setChat((was) => chatAsked(was, question, sentWith));
    // Emptied now rather than at the end: the question is on its
    // way, and a field still holding it invites a second send.
    setRequest('');
    setAttachment(null);

    await askStylist(
      { question, postId: fitParam ?? null, history: earlier },
      {
        onToken: (chunk) => setChat((was) => chatStreamed(was, chunk)),
        onVerdict: (verdict) => setChat((was) => chatDecided(was, verdict)),
        onShopping: (items) => setChat((was) => chatShopped(was, items)),
        onRender: (renderId) => setChat((was) => chatDrawing(was, renderId)),
        onError: () => setChat((was) => chatFailed(was)),
      },
    );
    setChat((was) => chatSettled(was));
    void successFeedback();
  };

  const ask = async () => {
    void tapFeedback();

    // Asked here, not at sign-up. A consent collected in a wall of toggles
    // before anyone has seen what the app does is a consent nobody read;
    // asked when somebody taps "Style me", it is a question about the thing
    // they are visibly trying to do, and the answer is actionable.
    if (signedIn && !hasAiConsent(consents.data)) {
      setRun({ status: 'needsConsent' });
      return;
    }

    // A question gets answered. Only an order gets queued.
    if (isAQuestion(request)) {
      await answer(request);
      return;
    }

    setRun({ status: 'running' });
    try {
      // Two calls, because styling takes seconds: the server accepts the
      // request and the client polls, so a slow network is distinguishable
      // from a broken one and a backgrounded app can pick the run up again.
      // What the request is about travels with it. The server decides
      // what was being asked for and re-validates every id against this
      // account before acting on any of them.
      const runId = await startRun({
        text: request,
        occasion: dressCode,
        garmentId: attachment?.garmentId ?? null,
        mediaAssetId: attachment?.mediaAssetId ?? null,
        postId: fitParam ?? null,
      });
      const outcome = await awaitRun(runId);
      setRun({ status: 'done', outcome });
      // An answer is an answer whether it is an outfit or a shoot that
      // has started.
      if (outcome.outfit || isAssistantAnswer(outcome)) void successFeedback();
      // The question has been asked, so the field empties. Keeping it
      // full means the next tap re-sends the last request.
      if (outcome.outfit || isAssistantAnswer(outcome)) setRequest('');
    } catch (error) {
      const described = describeRunFailure(error);
      setRun({ status: 'failed', ...described });
    }
  };

  // Arriving from a garment's sheet with `?garment=…` pre-attaches it, so
  // the treatments are already there. Tracked by id rather than a boolean
  // so opening a *different* garment re-attaches, while clearing the
  // attachment by hand stays cleared.
  if (garmentParam && attachedFor !== garmentParam) {
    const found = wardrobe.entries.find((entry) => entry.serverId === garmentParam);
    if (found) {
      setAttachedFor(garmentParam);
      setAttachment({
        uri: found.uri ?? null,
        garmentId: garmentParam,
        label: found.name,
      });
    }
  }

  // **And a fit carried in from Discover, which showed nothing.**
  //
  // `fit` was already read, already sent as `post_id`, and already
  // used on the server - the assistant describes the photograph and
  // answers about it. What was missing was any sign of that here:
  // the chip only ever rendered for a garment, so "Ask the stylist
  // about it" opened a field with nothing attached to look at, and
  // the obvious conclusion was that the picture had been dropped.
  //
  // Tracked by id for the same reason the garment is: opening a
  // different fit re-attaches, and clearing one by hand stays
  // cleared.
  if (fitParam && attachedFor !== fitParam) {
    setAttachedFor(fitParam);
    setAttachment({
      // A thumbnail only. `mediaAssetId` is deliberately left unset:
      // it is what the studio treatments work from, and they resolve
      // against assets the asker owns - offering them on somebody
      // else's photograph would be a row that always fails. The
      // context travels as `post_id`, which the server resolves
      // through the feed and so may read without owning.
      uri: fitCover,
      label: 'This fit',
    });
  }

  const chrome = (
    <View style={{ gap: Spacing.one, marginBottom: Spacing.four }}>
        {/* The way back, drawn here rather than by a native header.

            This screen moved out of the tab bar when the studio took
            its place, so it is pushed now and needs an exit. A native
            header would reserve a row above a title this screen
            already draws, which is why every other pushed screen in
            this app draws its own.

            `replace` to the wardrobe when there is nothing behind:
            the composer that sends people here lives there, and a
            back button that does nothing is worse than none. */}
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Back"
          animateEntrance={false}
          hitSlop={Spacing.two}
          onPress={() => {
            void tapFeedback();
            if (router.canGoBack()) router.back();
            else router.replace('/wardrobe');
          }}
          style={{
            width: TapTarget,
            height: TapTarget,
            marginLeft: -Spacing.two,
            justifyContent: 'center',
          }}>
          <SymbolView
            name={{
              ios: 'chevron.left',
              android: 'arrow_back',
              web: 'arrow_back',
            }}
            size={22}
            tintColor={colors.text}
          />
        </MotionPressable>
        <ThemedText
          accessibilityRole="header"
          style={{ ...labelType(28, 800), lineHeight: 34 }}>
          Stylist
        </ThemedText>
        {/* One line, and only when it changes what to expect.

            This was a bordered card with a status dot, above a second
            card, above two labelled sections and two rows of chips: six
            pieces of furniture before the thing somebody came to do. A
            full wardrobe needs no announcement. A thin one does, because
            it is the only case where the answer will disappoint and the
            only case the person can fix. */}
        <ThemedText
          themeColor="textSecondary"
          style={labelType(FontSize.subhead, 400)}>
          {ready
            ? 'Ask for an outfit, or show it a piece and say what you want.'
            : `Add ${MINIMUM_GARMENTS - wearable.length} more garments and I can style from your wardrobe.`}
        </ThemedText>
      </View>
  );

  const conversation = (
    <>
      {/* **The conversation, then the box under it.**

          The composer used to sit above the results, which is the
          wrong way round for a chat. The newest reply ended up
          furthest from the thumb, and the box walked down the page
          as the thread grew. Now the thread reads top to bottom and
          the box is the last thing on the screen, so what you just
          asked and what came back sit together above where you type
          next.

          Everything the stylist produces is a turn, including a
          picture: an avatar is the answer to "show me that on me",
          so it belongs beside the sentence that led to it rather
          than in a panel of its own. That is what lets somebody look
          at it and keep talking. */}
      <Thread
        turns={chat.turns}
        renders={renders.data ?? []}
        wardrobe={wardrobe.entries}
        onEdit={(turn) => {
          // The words come back to the composer and the thread is
          // wound back to before them, so asking again replaces the
          // exchange rather than appending a near-duplicate.
          void tapFeedback();
          setChat((was) => {
            const { state, text } = chatRewind(was, turn.id);
            setRequest(text);
            return state;
          });
        }}
        onForget={(turn) => {
          void tapFeedback();
          setChat((was) => chatForget(was, turn.id));
        }}
        onTryOn={(turn) => {
          // Asking for a picture is just another turn, so it goes
          // through the same path and lands in the same thread.
          void answer(
            turn.verdict?.hasMatch
              ? 'Show me that on me.'
              : 'Show me what those would look like on me.',
          );
        }}
      />

      <View style={{ marginTop: Spacing.four, gap: Spacing.three }}>
        {/* You, from the moment the question is sent.

            An outfit is four garment names, which is a description of
            a look rather than a look - and "what should I wear today"
            is a question about yourself. The figure holds the frame
            while the answer is worked out and fills in when it lands,
            so the page never jumps and the answer is never only
            words. */}
        <AvatarLook
          pieces={
            run.status === 'done' && run.outcome.outfit
              ? run.outcome.outfit.pieces
              : null
          }
          wardrobe={wardrobe.entries}
          signedIn={signedIn}
        />

        {/* Held back 400ms: under a second, a placeholder flashing in and out
            reads as a glitch rather than as progress. */}
        {thinking ? (
          /* A spinner and a line, not three grey bars.

             The bars were static - `Skeleton` does not shimmer, on
             purpose and for a recorded accessibility reason - so a
             run that takes half a minute looked like a page that had
             stopped. A placeholder standing in for text that is
             coming is one thing; a wait with nothing moving in it is
             another, and this is the second.

             The platform's own progress control rather than a
             pulsing shape of our own: it is the conventional,
             expected indicator, screen readers announce it, and the
             WCAG 2.2.2 reasoning written over `Skeleton` is about a
             page of large shimmering blocks under a live tab bar -
             not one small status element that says "still here". */
          <View
            accessible
            accessibilityRole="progressbar"
            accessibilityLabel={
              attachment ? 'Working on it' : 'Putting a look together'
            }
            accessibilityState={{ busy: true }}
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: Spacing.three,
              padding: Spacing.three,
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              backgroundColor: colors.backgroundElement,
            }}>
            <ActivityIndicator color={colors.accent} />
            <ThemedText type="small" themeColor="textSecondary">
              {attachment ? 'Working on it' : 'Putting a look together'}
            </ThemedText>
          </View>
        ) : null}

        {run.status === 'done' && run.outcome.outfit ? (
          <Outfit outcome={run.outcome} />
        ) : null}

        {/* It did something other than build an outfit.

            Asking it to photograph a piece or make a set of brand
            visuals comes back here: work has started and the answer says
            what and where to look for it. Rendering that through the
            no-outfit empty state would have reported a success as a
            failure. */}
        {/* The streamed reply used to be drawn here, as the
            screen's one current answer. It is a turn in `Thread`
            now, above the composer, so a second question does not
            erase the first. */}
        {run.status === 'done' && isAssistantAnswer(run.outcome) ? (
          <View
            style={{
              flexDirection: 'row',
              gap: Spacing.two,
              padding: Spacing.three,
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              backgroundColor: colors.backgroundElement,
            }}>
            <SymbolView
              name={{ ios: 'sparkles', android: 'auto_awesome', web: 'auto_awesome' }}
              size={18}
              tintColor={colors.accent}
            />
            <ThemedText type="small" style={{ flex: 1, fontSize: FontSize.subhead }}>
              {run.outcome.explanation}
            </ThemedText>
          </View>
        ) : null}

        {run.status === 'done' &&
        !run.outcome.outfit &&
        !isAssistantAnswer(run.outcome) ? (
          // Nothing it could build from what the user owns. That is an
          // answer, and a far better one than an outfit made of clothes they
          // do not have.
          <EmptyState
            status="empty"
            title="No outfit from this wardrobe yet"
            body={
              run.outcome.explanation ??
              'Nothing in your wardrobe fits that request. Add a few more pieces and ask again.'
            }
          />
        ) : null}

        {run.status === 'needsConsent' ? (
          <EmptyState
            status="blocked"
            title="Styling needs your say-so"
            body="To build an outfit, your wardrobe is sent to a model. Nothing is published, nothing trains it, and you can withdraw this in Profile at any time."
            action={{
              label: setConsent.isPending ? 'Agreeing' : 'Agree and continue',
              onPress: () => {
                void tapFeedback();
                setConsent.mutate(
                  { kind: 'ai_processing', granted: true, source: 'stylist' },
                  { onSuccess: () => void ask() },
                );
              },
            }}
          />
        ) : null}

        {run.status === 'failed' ? (
          <EmptyState status="blocked" title={run.title} body={run.body} />
        ) : null}

        {run.status === 'idle' && !ready && !attachment ? (
          // Only when there is nothing else to work from. Photographing
          // an attached piece needs no wardrobe at all, and telling a
          // brand with a product in hand to add garments would be wrong.
          <EmptyState
            status="empty"
            title="Your wardrobe is nearly ready"
            body="Add a few more garments to be styled from them. You can still show me a piece and ask me to photograph it."
          />
        ) : null}
      </View>

    </>
  );

  /**
   * The box, and only the box.
   *
   * **Separated from the thread so it can sit on the keyboard.** It
   * used to be the last child of one long scroll view, which means
   * it scrolled: typing pushed it up the page, a long thread left it
   * below the fold, and the keyboard covered whatever it had reached.
   * Pinned, it is always the thing above the keyboard and the thread
   * scrolls behind it - which is how every messaging app on the
   * phone behaves, and what the product owner asked for.
   */
  const composer = (
    <>
      <View style={{ gap: Spacing.three }}>
        {/* What it is being asked about, when there is something.

            Above the field rather than below it, because it is part of
            the question: "shoot this on a model" means nothing without
            the this. The way to *attach* is inside the box, beside
            the mic - it is one of the things you do to a request, not
            a row of its own above it. */}
        {attachment ? (
          <AttachedCard
            attachment={attachment}
            onClear={() => setAttachment(null)}
          />
        ) : null}

        {/* One box, and everything inside it.

            Attach, speak and send are the three things you do with a
            request, so they sit on its edge rather than stacking as
            three more rows down the page. */}
        <View
          style={{
            // One row, not two stacked ones.
            //
            // This was a 64pt-tall input with a separate row of
            // controls underneath, which made the composer about a
            // fifth of the screen before a single word was typed -
            // "so rigid and unnecessarily big", and on a phone with
            // the keyboard up it left almost nothing for the
            // conversation. Everything now sits on one line and the
            // box grows only when the sentence does.
            flexDirection: 'row',
            alignItems: 'flex-end',
            borderRadius: Radius.lg,
            borderCurve: 'continuous',
            borderWidth: 1,
            // An input is bounded by its border, so it needs 3:1 per WCAG
            // 1.4.11. The hairline `border` is 1.32:1 and fails it.
            borderColor: colors.borderStrong,
            backgroundColor: colors.backgroundElement,
            paddingHorizontal: Spacing.two,
            paddingVertical: Spacing.one,
            gap: Spacing.one,
          }}>
          <TextInput
            value={request}
            onChangeText={setRequest}
            placeholder="Ask for anything"
            placeholderTextColor={colors.textSecondary}
            multiline
            accessibilityLabel="Ask the stylist"
            style={{
              // One line to start. `maxHeight` is what keeps a long
              // request from eating the thread: past about five lines
              // the field scrolls inside itself instead of growing.
              flex: 1,
              minHeight: TapTarget,
              maxHeight: 132,
              paddingHorizontal: Spacing.one,
              paddingTop: Spacing.two,
              color: colors.text,
              fontSize: FontSize.body,
              textAlignVertical: 'center',
            }}
          />

          <View
            style={{ flexDirection: 'row', alignItems: 'center', gap: Spacing.one }}>
            {/* Say it, rather than typing a paragraph on a phone
                keyboard. The transcript lands in the field as editable
                text: what comes back is a guess at what was said, and
                somebody has to be able to fix it before it is sent. */}
            <AttachButton
              attachment={attachment}
              onAttach={setAttachment}
              onAddGarment={onAddGarment}
              wardrobe={wardrobe.entries}
            />

            <MicButton
              compact
              onText={(text) =>
                setRequest((current) => (current ? `${current} ${text}` : text))
              }
            />


            <MotionPressable
              accessibilityRole="button"
              accessibilityLabel="Send"
              accessibilityState={{
                disabled: !canSend,
                busy: run.status === 'running',
              }}
              disabled={!canSend}
              animateEntrance={false}
              scale={0.92}
              onPress={() => void ask()}
              style={{
                width: TapTarget,
                height: TapTarget,
                alignItems: 'center',
                justifyContent: 'center',
                borderRadius: Radius.full,
                backgroundColor: colors.accent,
                opacity: canSend ? 1 : 0.35,
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

        {/* The suggestion chips stood here.

            They were folded behind a "What can I ask?" control after
            the first complaint about clutter, which helped and did
            not fix it: the control itself still sat under the box,
            and opening it pushed a wall of chips between the
            composer and the bottom of the screen - so the box people
            type into was never actually the last thing on the page.

            Removed. An assistant screen is a thread and a box. What
            it can do is discovered by asking it, which is the whole
            premise, and a menu of example sentences is the kind of
            furniture that premise exists to avoid. */}
      </View>
    </>
  );

  // **Embedded, this owns the whole remaining height.**
  //
  // It used to return a bare fragment for the page to drop into its
  // own scroll view, which is what put the composer inside the
  // scroll. Now the thread scrolls and the box does not: one flex
  // column, the conversation taking what is left, the composer
  // sitting on the keyboard. The page above still owns the header.
  if (embedded) {
    return (
      <View style={{ flex: 1 }}>
        <ScrollView
          style={{ flex: 1 }}
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode="interactive"
          refreshControl={refreshControl}
          contentContainerStyle={{
            paddingBottom: Spacing.three,
            gap: Spacing.three,
          }}
          // Pinned to the newest turn, the way a thread behaves
          // everywhere else on the phone.
          ref={scroller}
          onContentSizeChange={() =>
            scroller.current?.scrollToEnd({ animated: true })
          }>
          {conversation}
        </ScrollView>
        <View style={{ paddingTop: Spacing.two }}>{composer}</View>
      </View>
    );
  }

  return (
    <Screen scroll>
      {chrome}
      {conversation}
      {composer}
    </Screen>
  );
}

/**
 * The outfit, and what it is built from.
 *
 * Every piece says whether it is one the user owns. That is the whole promise
 * of this feature — an outfit from the clothes you already have — so a piece
 * that is a suggestion rather than a possession has to be visibly different,
 * and in a word rather than only a colour (WCAG 1.4.1).
 */
function Outfit({ outcome }: { outcome: StylistOutcome }) {
  const colors = Colors[useScheme()];
  const outfit = outcome.outfit;
  if (!outfit) return null;

  return (
    <View style={{ gap: Spacing.three }}>
      <Label>Your look</Label>

      <View
        style={{
          borderRadius: Radius.md,
          borderCurve: 'continuous',
          backgroundColor: colors.backgroundElement,
          overflow: 'hidden',
        }}>
        {outfit.pieces.map((piece, index) => (
          <View
            key={`${piece.role}-${piece.garmentId ?? index}`}
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: Spacing.two,
              minHeight: TapTarget,
              paddingHorizontal: Spacing.three,
              paddingVertical: Spacing.two,
              borderBottomWidth: index === outfit.pieces.length - 1 ? 0 : 1,
              borderBottomColor: colors.border,
            }}>
            <View
              style={{
                width: 8,
                height: 8,
                borderRadius: Radius.full,
                backgroundColor: toneColor(colors, piece.owned ? 'success' : 'muted'),
              }}
            />
            <View style={{ flex: 1, gap: Spacing.half }}>
              <ThemedText type="small">{piece.name ?? piece.category ?? piece.role}</ThemedText>
              <ThemedText
                type="small"
                themeColor="textSecondary"
                style={{ fontSize: FontSize.meta, textTransform: 'capitalize' }}>
                {piece.role}
              </ThemedText>
            </View>
            <ThemedText
              type="small"
              themeColor="textSecondary"
              style={{ fontSize: FontSize.meta }}>
              {piece.owned ? 'Yours' : 'Suggested'}
            </ThemedText>
          </View>
        ))}
      </View>

      {outfit.rationale ? (
        <ThemedText type="small" themeColor="textSecondary">
          {outfit.rationale}
        </ThemedText>
      ) : null}

      {outfit.missingSlots.length > 0 ? (
        <View style={{ gap: Spacing.half }}>
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ fontSize: FontSize.footnote }}>
            Nothing in your wardrobe for: {outfit.missingSlots.join(', ')}.
          </ThemedText>
          {/* The honest shopping prompt: the stylist itself named the gap.
              Each slot opens the curated shop sheet, where provenance and
              the web fallback live. */}
          {outfit.missingSlots.map((slot) => (
            <MotionPressable
              key={slot}
              accessibilityRole="button"
              accessibilityLabel={`Find ${slot} at the shops`}
              animateEntrance={false}
              onPress={() => {
                void tapFeedback();
                router.push({ pathname: '/shop/piece', params: { name: slot, slot } });
              }}
              style={{ minHeight: TapTarget, justifyContent: 'center' }}>
              <ThemedText type="smallBold" style={{ fontSize: FontSize.footnote }}>
                Find {slot} at the shops
              </ThemedText>
            </MotionPressable>
          ))}
        </View>
      ) : null}
    </View>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <ThemedText
      type="label"
      themeColor="textSecondary">
      {children}
    </ThemedText>
  );
}

