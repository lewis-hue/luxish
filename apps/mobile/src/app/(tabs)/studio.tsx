import { Image } from 'expo-image';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Modal,
  Pressable,
  ScrollView,
  TextInput,
  View,
  useWindowDimensions,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  shotLine,
  useAllShots,
  useShootAsset,
  useShootEachItem,
  useShotImages,
  useTreatments,
} from '@/api/queries/garment-studio';
import { ThemedText } from '@/components/themed-text';
import { EmptyState } from '@/components/ui/empty-state';
import {
  MotionPressable,
  successFeedback,
  tapFeedback,
} from '@/components/ui/motion';
import { Skeleton } from '@/components/ui/skeleton';
import {
  BottomTabInset,
  Colors,
  FontSize,
  ImageFade,
  Motion,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { PictureActions } from '@/features/avatar/picture-actions';
import { useAuth } from '@/features/auth/session';
import { uploadMedia } from '@/features/media/upload';
import { useGarmentCapture } from '@/features/wardrobe/capture';
import { usePullToRefresh } from '@/components/ui/pull-to-refresh';
import { useScheme } from '@/hooks/use-theme';

/**
 * The studio: a photograph you have, shot four ways, with your own
 * direction on it.
 *
 * **This replaced the stylist tab, and the two are not the same
 * thing.** The stylist answers "what should I wear", which is a
 * question about a wardrobe; it now sits on the wardrobe page, where
 * the clothes it reasons about already are. This screen answers
 * "make me a picture of this", which needs no wardrobe at all - most
 * of what arrives here is a photograph straight off the phone.
 *
 * **Modes are shown, not asked for.** Everywhere else in this app a
 * capability is reached by saying what you want, and that is still
 * true of the stylist. It is deliberately not true here: the four
 * treatments are the product, the way they are at every tool this
 * competes with, and burying them behind a sentence would mean
 * somebody had to already know the word "packshot" to find the
 * packshot. The prompt box is on top of them, not instead of them.
 *
 * **Stills only, and the reason is said out loud.** Every image model
 * this app can reach takes video in and emits none, so a clip is not
 * something a prompt can ask for. The capability endpoint carries that
 * sentence; this screen shows it rather than offering a button that
 * cannot work.
 */
/**
 * How long a split may stay invisible before the button gives up on it.
 *
 * A split has to run a vision call over the photograph and segment
 * the first garment out of it before any shot row exists, which is
 * tens of seconds. This is the deadline on *that* window only - once
 * a row appears the list below reports progress - and it exists so a
 * job that dies without writing anything cannot leave the button
 * busy for the rest of the session.
 */
const SPLIT_SHOWS_UP_WITHIN = 90_000;

export default function StudioScreen() {
  const colors = Colors[useScheme()];
  const refresh = usePullToRefresh();
  const insets = useSafeAreaInsets();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';

  const treatments = useTreatments(signedIn);
  const shots = useAllShots(signedIn);
  const images = useShotImages(shots.data ?? []);
  const shoot = useShootAsset();
  const shootEach = useShootEachItem();
  /**
   * Whether to make one picture per garment instead of one of the lot.
   *
   * **Off by default, and that is the product decision.** A studio
   * shot is one picture: handed a photograph of a shirt and trousers,
   * the packshot that comes back has both in it, laid out together,
   * which is what somebody making an image came here for. Splitting
   * is the other job - the same photograph wanted as two catalogue
   * images - and it costs a picture per garment, so it is asked for
   * rather than assumed.
   */
  const [eachItem, setEachItem] = useState(false);
  /**
   * Whether to keep the wide frame a flat-lay comes back in.
   *
   * **Off, because upright is the app.** Only the two flat-lay
   * treatments are stood upright in the first place, so this is shown
   * only for those - offered against a treatment it does not affect,
   * a control that does nothing is worse than no control.
   */
  const [landscape, setLandscape] = useState(false);
  const capture = useGarmentCapture();

  /** The picture being worked on, before it has an id on the server. */
  const [picked, setPicked] = useState<{ uri: string } | null>(null);
  /** Its id once uploaded, so a second treatment does not re-upload it. */
  const [assetId, setAssetId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [treatment, setTreatment] = useState<string | null>(null);
  /**
   * Whether the chosen treatment is one that is stood upright at all.
   *
   * The two flat-lay treatments are the only ones forced into the
   * app's upright shell, so they are the only ones the option above
   * changes anything for. Named here rather than inline so the
   * control and the request agree on one answer.
   */
  const flatLay = treatment === 'packshot' || treatment === 'cutout';
  const [brief, setBrief] = useState('');
  const [choosing, setChoosing] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  /** Which finished shot is open full size. */
  const [viewing, setViewing] = useState<string | null>(null);
  /** Whether the gallery below the controls is showing. */
  const [showPictures, setShowPictures] = useState(true);

  // Three states, three treatments. A shot still being taken needs
  // words; a finished one needs only to be seen; a failed one needs
  // to be counted and not take a tile.
  const all = shots.data ?? [];
  const working = all.filter(
    (shot) => shot.state === 'queued' || shot.state === 'running',
  );
  const done = all.filter((shot) => shot.state === 'ready');
  const failed = all.filter((shot) => shot.state === 'failed');

  /**
   * Whether a split has been asked for and produced nothing yet.
   *
   * **A split is invisible for its first half-minute.** The ordinary
   * shot writes its row before the request returns, so the list
   * below knows about it immediately. A split cannot: how many
   * pictures there will be is however many garments a vision call
   * finds, so the worker has to look at the photograph first and
   * only then creates any rows at all. For those ten to thirty
   * seconds there is nothing anywhere to show, and without this the
   * button would read "Make the picture" throughout.
   *
   * **Derived rather than cleared.** Once a shot exists the list
   * below is what reports progress, so the end of this window is a
   * fact about `working` and not a second piece of state that has to
   * be kept in step with it - which would also mean writing state
   * from an effect.
   */
  const [splitRequested, setSplitRequested] = useState(false);
  const awaitingSplit = splitRequested && working.length === 0;

  useEffect(() => {
    if (!splitRequested) return;
    // A deadline, because a job that dies without writing a row would
    // otherwise leave the button busy for the rest of the session.
    // Generous: the detection and the first segmentation both have to
    // finish before anything appears.
    const timer = setTimeout(
      () => setSplitRequested(false),
      SPLIT_SHOWS_UP_WITHIN,
    );
    return () => clearTimeout(timer);
  }, [splitRequested]);

  const fromPhone = async (source: 'camera' | 'library') => {
    const result =
      source === 'camera'
        ? await capture.photograph()
        : await capture.pickFromLibrary();
    if (result === 'denied') {
      Alert.alert(
        source === 'camera' ? 'Camera access needed' : 'Photo access needed',
        'Grant access in Settings to work on a picture here. Everything else keeps working.',
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
    const first = result[0];
    if (!first) return;

    void successFeedback();
    // Shown immediately from the local file, uploaded behind it: the
    // picture is the thing somebody just chose, and making them watch
    // a spinner before they can see it is the upload's problem, not
    // theirs.
    setPicked({ uri: first.uri });
    setAssetId(null);
    setProblem(null);
    setUploading(true);
    try {
      setAssetId(await uploadMedia({ uri: first.uri, kind: 'garment_photo' }));
    } catch {
      setProblem('That picture could not be uploaded. Try again.');
      setPicked(null);
    } finally {
      setUploading(false);
    }
  };

  const generate = () => {
    if (!assetId || !treatment) return;
    void tapFeedback();
    setProblem(null);
    // `landscape` only where it means anything: asked for against a
    // treatment that is never stood upright, it would read as a
    // request the server then appeared to ignore.
    const ask = {
      mediaAssetId: assetId,
      treatment,
      brief,
      landscape: flatLay && landscape,
    };
    const done = {
      onSuccess: () => {
        void successFeedback();
        // The direction is kept, not cleared: the common next move
        // is the same sentence against a different treatment.
        setTreatment(null);
      },
      onError: () => setProblem('That did not start. Try again in a moment.'),
    };
    if (eachItem) {
      setSplitRequested(true);
      shootEach.mutate(ask, {
        ...done,
        onError: () => {
          // The wait is over before it began, so the button must not
          // sit busy until the deadline for a request that was
          // refused in a second.
          setSplitRequested(false);
          done.onError();
        },
      });
    } else {
      shoot.mutate(ask, done);
    }
  };

  if (!signedIn) {
    return (
      <EmptyState
        status="blocked"
        title="Sign in to use the studio"
        body="Pictures are made from photographs on your own account."
      />
    );
  }

  /**
   * Whether a picture is being made right now.
   *
   * **Not `isPending`, which was the bug.** The request returns the
   * moment the server has written the row - a couple of hundred
   * milliseconds - and the work then happens on a worker for fifteen
   * to thirty seconds. So the button flashed a spinner, went back to
   * reading "Make the picture", and sat there looking idle for half
   * a minute while the model drew. Pressing it again in that gap is
   * the obvious thing to do and costs a second billed call.
   *
   * The shots list already polls while anything is queued or
   * running, so it is the thing that knows. `isPending` stays in the
   * test because between the tap and the first poll there is a
   * moment when the row does not exist yet.
   */

  const makingPicture =
    shoot.isPending || shootEach.isPending || awaitingSplit || working.length > 0;
  const ready = Boolean(assetId) && Boolean(treatment) && !makingPicture;

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
        refreshControl={refresh.control}
        // The prompt is the last field on a long page, so the
        // keyboard covered the thing being typed into. This insets
        // the scroll by the keyboard's real height and scrolls the
        // focused field clear of it.
        automaticallyAdjustKeyboardInsets
        keyboardDismissMode="interactive"
        contentContainerStyle={{
          paddingTop: insets.top + Spacing.three,
          paddingHorizontal: Spacing.three,
          paddingBottom: BottomTabInset + insets.bottom + Spacing.five,
          gap: Spacing.four,
        }}>
        {/* The same header the wardrobe tab draws: 28 over a 34
            line. At 34 with no line height the glyphs were clipped
            at the top of their own line box, which is what cut the
            word in half. A tab title should not be a different size
            on every tab either. */}
        <ThemedText
          accessibilityRole="header"
          style={{ ...labelType(28, 800), lineHeight: 34 }}>
          Studio
        </ThemedText>

        {problem ? (
          <ThemedText
            selectable
            style={{ ...labelType(FontSize.subhead, 400), color: colors.danger }}>
            {problem}
          </ThemedText>
        ) : null}

        {/* The picture, or the one control that gets one. */}
        {picked ? (
          <View style={{ gap: Spacing.two }}>
            <View
              style={{
                borderRadius: Radius.lg,
                borderCurve: 'continuous',
                overflow: 'hidden',
                backgroundColor: colors.backgroundElement,
              }}>
              <Image
                source={{ uri: picked.uri }}
                contentFit="cover"
                transition={ImageFade}
                style={{ width: '100%', aspectRatio: 3 / 4 }}
              />
            </View>
            <View style={{ flexDirection: 'row', gap: Spacing.two }}>
              <ThemedText
                type="small"
                themeColor="textSecondary"
                style={{ flex: 1 }}>
                {uploading ? 'Uploading…' : 'Ready to shoot'}
              </ThemedText>
              <MotionPressable
                accessibilityRole="button"
                accessibilityLabel="Use a different picture"
                animateEntrance={false}
                onPress={() => {
                  void tapFeedback();
                  setPicked(null);
                  setAssetId(null);
                  setTreatment(null);
                }}>
                <ThemedText type="smallBold" style={{ color: colors.accent }}>
                  Change
                </ThemedText>
              </MotionPressable>
            </View>
          </View>
        ) : (
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Add a picture"
            accessibilityHint="Upload one from this phone, or take one now"
            animateEntrance={false}
            onPress={() => {
              void tapFeedback();
              setChoosing(true);
            }}
            style={{
              minHeight: 160,
              alignItems: 'center',
              justifyContent: 'center',
              gap: Spacing.two,
              borderRadius: Radius.lg,
              borderCurve: 'continuous',
              borderWidth: 1,
              borderStyle: 'dashed',
              borderColor: colors.borderStrong,
            }}>
            <View
              style={{
                width: TapTarget,
                height: TapTarget,
                borderRadius: Radius.full,
                alignItems: 'center',
                justifyContent: 'center',
                backgroundColor: colors.backgroundElement,
              }}>
              <SymbolView
                name={{ ios: 'plus', android: 'add', web: 'add' }}
                size={22}
                tintColor={colors.text}
              />
            </View>
            <ThemedText type="smallBold">Add a picture</ThemedText>
          </MotionPressable>
        )}

        {/* What to do with it. */}
        <View style={{ gap: Spacing.two }}>
          <ThemedText
            accessibilityRole="header"
            style={{ ...labelType(20, 800), lineHeight: 26 }}>
            Style
          </ThemedText>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two }}>
            {(treatments.data?.items ?? []).map((item) => {
              const on = treatment === item.id;
              return (
                <MotionPressable
                  key={item.id}
                  accessibilityRole="button"
                  accessibilityLabel={item.label}
                  accessibilityHint={item.description}
                  accessibilityState={{ selected: on }}
                  animateEntrance={false}
                  onPress={() => {
                    void tapFeedback();
                    setTreatment(on ? null : item.id);
                  }}
                  style={{
                    paddingVertical: Spacing.two,
                    paddingHorizontal: Spacing.three,
                    minHeight: TapTarget,
                    justifyContent: 'center',
                    borderRadius: Radius.full,
                    borderWidth: 1,
                    borderColor: on ? colors.accent : colors.border,
                    backgroundColor: on ? colors.accent : 'transparent',
                  }}>
                  <ThemedText
                    type="smallBold"
                    style={{ color: on ? colors.accentText : colors.text }}>
                    {item.label}
                  </ThemedText>
                </MotionPressable>
              );
            })}
          </View>
          {/* The one-image note used to sit here. It was a paragraph
              under four buttons explaining a limit nobody had hit
              yet, and it cost more room than the controls it
              explained. The server still sends it; the screen that
              needs it is the one where somebody asks for a model. */}

          {/* Grouped or separate.
              A picture of a shirt and trousers together is one
              image, which is what this tool makes and so what it
              does by default. Wanting them as two catalogue images
              is a different job, it costs a picture per garment, and
              so it is asked for rather than assumed. */}
          <CheckRow
            label="A separate picture for each item"
            hint="When on, every item in the photograph is shot on its own"
            whenOff="Off, everything is shot together"
            whenOn="On, one picture per item"
            checked={eachItem}
            onToggle={() => setEachItem((was) => !was)}
          />

          {/* Upright or wide.
              Every picture this app draws sits in one upright shell,
              and the two flat-lay treatments are forced into it
              because a flat-lay comes back wide. That is right for
              the feed and wrong as an absolute: somebody making a
              banner has a reason to want the frame they asked for.
              Nothing is lost by offering it - a wide picture posted
              to the feed is stood upright on its way in, so this
              cannot put a sideways card on anybody's board. */}
          {flatLay ? (
            <CheckRow
              label="A wide picture"
              hint="When on, the picture comes back wide instead of upright"
              whenOff="Off, upright like the rest of the app"
              whenOn="On, wide"
              checked={landscape}
              onToggle={() => setLandscape((was) => !was)}
            />
          ) : null}
        </View>

        {/* The direction, in their own words. */}
        <View style={{ gap: Spacing.two }}>
          <ThemedText
            accessibilityRole="header"
            style={{ ...labelType(20, 800), lineHeight: 26 }}>
            Prompt
          </ThemedText>
          <TextInput
            accessibilityLabel="What you want in the picture"
            placeholder="On a rooftop at dusk, warm light"
            placeholderTextColor={colors.textSecondary}
            value={brief}
            onChangeText={setBrief}
            multiline
            maxLength={600}
            style={{
              minHeight: 88,
              padding: Spacing.three,
              borderRadius: Radius.lg,
              borderCurve: 'continuous',
              backgroundColor: colors.backgroundElement,
              color: colors.text,
              ...labelType(FontSize.body, 400),
            }}
          />
        </View>

        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel={
            makingPicture ? 'Making your picture' : 'Make the picture'
          }
          accessibilityState={{ disabled: !ready, busy: makingPicture }}
          animateEntrance={false}
          disabled={!ready}
          onPress={generate}
          style={{
            minHeight: TapTarget,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: Radius.full,
            opacity: ready ? 1 : 0.4,
            backgroundColor: colors.accent,
          }}>
          {makingPicture ? (
            <View
              style={{
                flexDirection: 'row',
                alignItems: 'center',
                gap: Spacing.two,
              }}>
              <ActivityIndicator color={colors.accentText} />
              <ThemedText
                type="smallBold"
                style={{ color: colors.accentText }}>
                Making your picture
              </ThemedText>
            </View>
          ) : (
            <ThemedText type="smallBold" style={{ color: colors.accentText }}>
              Make the picture
            </ThemedText>
          )}
        </MotionPressable>

        {/* What has come back. */}
        <View style={{ gap: Spacing.two }}>
          {/* Collapsible, because this grows forever.

              Everything above it is the thing somebody came here to
              do; this is everything they have already done. After a
              few sessions it is the longest part of the page, and a
              gallery nobody is looking at should not be what they
              scroll past to reach the controls. */}
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel={`Your pictures, ${all.length}`}
            accessibilityState={{ expanded: showPictures }}
            accessibilityHint={showPictures ? 'Hides them' : 'Shows them'}
            animateEntrance={false}
            onPress={() => {
              void tapFeedback();
              setShowPictures((open) => !open);
            }}
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: Spacing.two,
              minHeight: TapTarget,
            }}>
            <ThemedText
            accessibilityRole="header"
            style={{ ...labelType(20, 800), lineHeight: 26 }}>
              Your pictures
            </ThemedText>
            {all.length > 0 ? (
              <ThemedText type="small" themeColor="textSecondary">
                {all.length}
              </ThemedText>
            ) : null}
            <View style={{ flex: 1 }} />
            <SymbolView
              name={
                showPictures
                  ? { ios: 'chevron.up', android: 'expand_less', web: 'expand_less' }
                  : {
                      ios: 'chevron.down',
                      android: 'expand_more',
                      web: 'expand_more',
                    }
              }
              size={18}
              tintColor={colors.textSecondary}
            />
          </MotionPressable>
          {!showPictures ? null : shots.isPending ? (
            <Skeleton height={120} radius={Radius.lg} />
          ) : (shots.data ?? []).length === 0 ? (
            <ThemedText type="small" themeColor="textSecondary">
              Nothing yet.
            </ThemedText>
          ) : (
            <>
              {/* Still being taken, as rows.

                  A row can say what is happening and roughly how
                  long; a thumbnail with nothing in it cannot. These
                  move into the grid below the moment they land. */}
              {working.length > 0 || awaitingSplit ? (
                <View style={{ gap: Spacing.two }}>
                  {working.map((shot) => (
                    <ShotRow
                      key={shot.id}
                      line={shotLine(shot, treatments.data?.items ?? [])}
                    />
                  ))}
                  {/* The split's own blind window. It has to read the
                      photograph before it knows how many pictures
                      there will be, so for the first half-minute
                      there is no shot to draw a row from - and this
                      list, which is where somebody is watching, would
                      otherwise be empty while the work ran. One row
                      standing in for however many are coming. */}
                  {awaitingSplit ? (
                    <ShotRow line="Looking at what is in the photograph" />
                  ) : null}
                </View>
              ) : null}

              {/* Finished, as a grid.

                  This was a stack of wide cards with a small picture
                  on each - a list of rows about pictures rather than
                  the pictures. A gallery is what somebody is looking
                  for here, so the picture is the whole tile and the
                  label it had is read out instead. */}
              {done.length > 0 ? (
                <View
                  style={{
                    flexDirection: 'row',
                    flexWrap: 'wrap',
                    gap: Spacing.two,
                  }}>
                  {done.map((shot) => (
                    <ShotTile
                      key={shot.id}
                      label={shotLine(shot, treatments.data?.items ?? [])}
                      brief={shot.brief}
                      uri={images.data?.[shot.id] ?? null}
                      onOpen={() => setViewing(shot.id)}
                    />
                  ))}
                </View>
              ) : null}

              {/* The ones that did not come back, said once rather
                  than as an empty tile each. */}
              {failed.length > 0 ? (
                <ThemedText
                  selectable
                  type="small"
                  style={{ color: colors.danger }}>
                  {failed.length === 1
                    ? (failed[0].error ?? 'One picture did not come back.')
                    : `${failed.length} pictures did not come back.`}
                </ThemedText>
              ) : null}
            </>
          )}
        </View>
      </ScrollView>

      {/* One shot, full size, with the ways out of the app.

          The file behind this is what the model returned, downloaded
          once and cached - nothing here resizes or re-encodes it, so
          saving gives the picture at the resolution it was made at. */}
      <Modal
        visible={viewing !== null}
        transparent
        animationType="fade"
        onRequestClose={() => setViewing(null)}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Close"
          onPress={() => setViewing(null)}
          style={{
            flex: 1,
            justifyContent: 'center',
            padding: Spacing.three,
            paddingBottom: insets.bottom + Spacing.three,
            // Near-opaque. At 80% the page behind read straight
            // through and every label on top of it had two
            // backgrounds to fight.
            backgroundColor: '#000000F5',
          }}>
          {/* Swallows taps so pressing the sheet does not close it. */}
          <Pressable onPress={() => {}} style={{ gap: Spacing.three }}>
            {viewing && images.data?.[viewing] ? (
              <Image
                source={{ uri: images.data[viewing] }}
                contentFit="contain"
                transition={ImageFade}
                style={{
                  width: '100%',
                  aspectRatio: 3 / 4,
                  borderRadius: Radius.lg,
                }}
              />
            ) : null}
            <PictureActions
              uri={viewing ? images.data?.[viewing] ?? null : null}
              on="dark"
              onLeave={() => setViewing(null)}
            />
          </Pressable>
        </Pressable>
      </Modal>

      {/* Where a picture comes from. Only asked once somebody taps. */}
      <Modal
        visible={choosing}
        transparent
        animationType="slide"
        onRequestClose={() => setChoosing(false)}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Close"
          onPress={() => setChoosing(false)}
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
              paddingHorizontal: Spacing.three,
              paddingBottom: insets.bottom + Spacing.three,
              gap: Spacing.one,
              backgroundColor: colors.background,
              borderTopLeftRadius: Radius.lg,
              borderTopRightRadius: Radius.lg,
              borderCurve: 'continuous',
            }}>
            <SourceRow
              label="Upload a photo"
              hint="A picture already on this phone"
              icon={{ ios: 'photo', android: 'image', web: 'image' }}
              onPress={() => {
                closeThen(
                  () => setChoosing(false),
                  () => void fromPhone('library'),
                );
              }}
            />
            <SourceRow
              label="Take a picture"
              hint="Open the camera now"
              icon={{ ios: 'camera', android: 'photo_camera', web: 'photo_camera' }}
              onPress={() => {
                closeThen(
                  () => setChoosing(false),
                  () => void fromPhone('camera'),
                );
              }}
            />
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}

/**
 * Close the sheet, then do the thing.
 *
 * **Two native presentations must not race.** Launching the image
 * picker - or raising an alert - in the same tick as a `Modal`
 * dismissal leaves iOS presenting onto a view controller that is
 * being torn down. The result is an invisible window over the app:
 * the screen looks normal and nothing responds to a tap, which is
 * exactly what "it failed and then froze" is.
 *
 * The wait is a plain timer against the sheet's own slide. RN 0.88
 * no longer exports `InteractionManager`, which is what this would
 * otherwise use, and `Modal`'s `onDismiss` is iOS-only - a timer is
 * the one mechanism that behaves the same on both.
 */
function closeThen(close: () => void, run: () => void): void {
  close();
  setTimeout(run, Motion.slow);
}

/**
 * One checkable option, with its own explanation under it.
 *
 * Extracted because there are two of them and the control is sixty
 * lines of box-drawing - a second copy is where the two quietly stop
 * matching. It lives here rather than in `components/ui` because this
 * screen is the only place that asks a question this way; the moment a
 * second screen needs it, it moves.
 */
function CheckRow({
  label,
  hint,
  whenOff,
  whenOn,
  checked,
  onToggle,
}: {
  label: string;
  /** Spoken, for somebody who cannot see the box. */
  hint: string;
  /**
   * What the row says about itself, in each state.
   *
   * It was one fixed string describing the *off* state, so ticking the
   * box turned it maroon and left "Off, everything is shot together"
   * sitting under it. The control worked; its own caption contradicted
   * it, which is indistinguishable from the control being broken and
   * is how it was reported.
   */
  whenOff: string;
  whenOn: string;
  checked: boolean;
  onToggle: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="switch"
      accessibilityLabel={label}
      accessibilityHint={hint}
      accessibilityState={{ checked }}
      animateEntrance={false}
      onPress={() => {
        void tapFeedback();
        onToggle();
      }}
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.three,
        minHeight: TapTarget,
        paddingVertical: Spacing.two,
      }}>
      <View
        style={{
          width: 22,
          height: 22,
          borderRadius: Radius.sm,
          borderCurve: 'continuous',
          borderWidth: 2,
          borderColor: checked ? colors.accent : colors.border,
          backgroundColor: checked ? colors.accent : 'transparent',
          alignItems: 'center',
          justifyContent: 'center',
        }}>
        {checked ? (
          <SymbolView
            name={{ ios: 'checkmark', android: 'check', web: 'check' }}
            size={14}
            weight="semibold"
            tintColor={colors.accentText}
          />
        ) : null}
      </View>
      <View style={{ flex: 1, gap: Spacing.half }}>
        <ThemedText type="smallBold">{label}</ThemedText>
        <ThemedText
          themeColor="textSecondary"
          style={labelType(FontSize.footnote, 400)}>
          {checked ? whenOn : whenOff}
        </ThemedText>
      </View>
    </MotionPressable>
  );
}

function SourceRow({
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
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.three,
        minHeight: TapTarget,
        paddingVertical: Spacing.two,
        paddingHorizontal: Spacing.three,
        borderRadius: Radius.lg,
        borderCurve: 'continuous',
      }}>
      <SymbolView name={icon} size={22} tintColor={colors.text} />
      <View style={{ flex: 1, gap: Spacing.half }}>
        <ThemedText type="smallBold">{label}</ThemedText>
        <ThemedText type="small" themeColor="textSecondary">
          {hint}
        </ThemedText>
      </View>
    </MotionPressable>
  );
}

/** One picture still being taken. */
function ShotRow({ line }: { line: string }) {
  const colors = Colors[useScheme()];
  return (
    <View
      accessible
      accessibilityLabel={line}
      accessibilityState={{ busy: true }}
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.three,
        padding: Spacing.two,
        borderRadius: Radius.lg,
        borderCurve: 'continuous',
        backgroundColor: colors.backgroundElement,
      }}>
      <Skeleton height={48} width={36} radius={Radius.md} />
      <View style={{ flex: 1, gap: Spacing.half }}>
        <ThemedText type="smallBold">{line}</ThemedText>
        <ThemedText type="small" themeColor="textSecondary">
          About half a minute.
        </ThemedText>
      </View>
    </View>
  );
}

/**
 * One finished picture, as a tile.
 *
 * The treatment and the direction are the accessibility label rather
 * than type under the picture: four shots of one photograph differ by
 * a sentence, and four sentences under four thumbnails is a list
 * again. Anybody who wants the words opens the picture.
 */
function ShotTile({
  label,
  brief,
  uri,
  onOpen,
}: {
  label: string;
  brief: string | null;
  uri: string | null;
  onOpen: () => void;
}) {
  const colors = Colors[useScheme()];
  const { width } = useWindowDimensions();

  // Three across, inside the screen's own padding and the gaps.
  const across = 3;
  const size =
    (width - Spacing.three * 2 - Spacing.two * (across - 1)) / across;

  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={brief ? `${label}. ${brief}` : label}
      accessibilityHint="Opens it full size, to save or share"
      animateEntrance={false}
      onPress={() => {
        void tapFeedback();
        onOpen();
      }}
      style={{
        width: size,
        aspectRatio: 3 / 4,
        borderRadius: Radius.md,
        borderCurve: 'continuous',
        overflow: 'hidden',
        backgroundColor: colors.backgroundElement,
      }}>
      {uri ? (
        <Image
          source={{ uri }}
          contentFit="cover"
          transition={ImageFade}
          style={{ width: '100%', height: '100%' }}
        />
      ) : null}
    </MotionPressable>
  );
}
