import { Image } from 'expo-image';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { useState } from 'react';
import { Alert, Modal, Pressable, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  useShotImages,
  useShots,
  type Shot,
} from '@/api/queries/garment-studio';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, successFeedback, tapFeedback } from '@/components/ui/motion';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Colors,
  FontSize,
  Motion,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { useGarmentCapture } from '@/features/wardrobe/capture';
import type { WardrobeEntry } from '@/features/wardrobe/store';
import { useScheme } from '@/hooks/use-theme';

/** What the stylist is holding: a garment you own, or a photograph. */
export type StylistAttachment = {
  /** Local URI, for showing the thumbnail without a round trip. */
  uri: string | null;
  /** Set when it came from the wardrobe. */
  garmentId?: string | null;
  /** Set when it is a photograph already on the server. */
  mediaAssetId?: string | null;
  label: string;
};

/**
 * The attachment row under the stylist's field.
 *
 * **Two ways in, because there are two things people have.** Something in
 * the wardrobe, which the stylist already knows about; or a picture on the
 * phone of something it does not. Both end up as the same thing — a
 * photograph the studio can work from — so they share one strip.
 *
 * **The studio lives here rather than on its own screen.** Shooting a
 * garment on a model is a thing you ask for *about a picture you are
 * already holding*, which is exactly the moment this row exists for.
 * Sending somebody to a separate page to do it would be a redirect away
 * from the context that prompted it, and back again afterwards.
 */
export function AttachButton({
  attachment,
  onAttach,
  onAddGarment,
  wardrobe,
}: {
  attachment: StylistAttachment | null;
  onAttach: (next: StylistAttachment) => void;
  /**
   * Put a picture in the wardrobe, rather than in the question.
   *
   * Only the wardrobe page passes this, and it is why that page has
   * one `+` instead of three controls. The two acts are genuinely
   * different - one adds a garment you own, the other shows the
   * stylist something - so they are two labelled groups in the sheet
   * rather than one ambiguous list.
   */
  onAddGarment?: (source: 'camera' | 'library') => void;
  wardrobe: readonly WardrobeEntry[];
}) {
  const [picking, setPicking] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const capture = useGarmentCapture();

  const fromPhone = async (source: 'camera' | 'library') => {
    const result =
      source === 'camera' ? await capture.photograph() : await capture.pickFromLibrary();
    if (result === 'denied') {
      Alert.alert(
        source === 'camera' ? 'Camera access needed' : 'Photo access needed',
        'Grant access in Settings to show the stylist a picture. Everything else keeps working.',
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
    onAttach({ uri: first.uri, label: 'Your photograph' });
  };

  // The card showing what is attached lives above the box; this is
  // only the way to attach something, and it sits inside it.
  if (attachment) return null;

  return (
    <>
      {/* One button, not three.

          Wardrobe, Photo and Camera each had a labelled tile the width
          of a third of the screen, stacked above the field - which is
          a lot of room spent on a question nobody has asked yet, and
          the reason this did not fit on the wardrobe page beside the
          clothes. They are the same three choices, behind the one
          glyph every composer uses for exactly this. */}
      <MotionPressable
        accessibilityRole="button"
        accessibilityLabel="Attach something"
        accessibilityHint="Choose from your wardrobe, your photos, or the camera"
        animateEntrance={false}
        onPress={() => {
          void tapFeedback();
          setChoosing(true);
        }}
        // Transparent, like the mic beside it: inside the box, a
        // filled circle in the box's own colour is invisible anyway,
        // and one in any other colour is a second button competing
        // with send.
        style={{
          width: TapTarget,
          height: TapTarget,
          borderRadius: Radius.full,
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: 'transparent',
        }}>
        <SymbolView
          name={{ ios: 'plus', android: 'add', web: 'add' }}
          size={22}
          tintColor={colors.textSecondary}
        />
      </MotionPressable>

      {/* The three, said plainly, only once somebody has asked. */}
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
            {onAddGarment ? (
              <>
                <GroupLabel>Add to your wardrobe</GroupLabel>
                <SourceRow
                  label="Take a picture"
                  hint="Photograph a piece and keep it"
                  icon={{
                    ios: 'camera',
                    android: 'photo_camera',
                    web: 'photo_camera',
                  }}
                  onPress={() => {
                    closeThen(
                      () => setChoosing(false),
                      () => onAddGarment('camera'),
                    );
                  }}
                />
                <SourceRow
                  label="From your photos"
                  hint="Add pieces from pictures on this phone"
                  icon={{ ios: 'photo', android: 'image', web: 'image' }}
                  onPress={() => {
                    closeThen(
                      () => setChoosing(false),
                      () => onAddGarment('library'),
                    );
                  }}
                />
                <GroupLabel>Show the stylist</GroupLabel>
              </>
            ) : null}
            <SourceRow
              label="A piece you own"
              hint="Something the stylist already knows about"
              icon={{ ios: 'hanger', android: 'apparel', web: 'apparel' }}
              onPress={() => {
                closeThen(
                  () => setChoosing(false),
                  () => setPicking(true),
                );
              }}
            />
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

      <Modal
        visible={picking}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setPicking(false)}>
        <WardrobePicker
          wardrobe={wardrobe}
          onClose={() => setPicking(false)}
          onPick={(entry) => {
            setPicking(false);
            onAttach({
              uri: entry.uri ?? null,
              garmentId: entry.serverId ?? null,
              label: entry.name,
            });
          }}
        />
      </Modal>
    </>
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

/** What the rows under it are for. Only shown when there are two groups. */
function GroupLabel({ children }: { children: React.ReactNode }) {
  return (
    <ThemedText
      themeColor="textSecondary"
      style={{ ...labelType(FontSize.meta, 800), paddingHorizontal: Spacing.three }}>
      {children}
    </ThemedText>
  );
}

/** One source, as a row in the sheet behind the `+`. */
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

/**
 * The attached picture, and what can be asked of it.
 *
 * The treatments sit directly under the thumbnail because that is what
 * they act on. A shot appears in the same strip while it is being taken,
 * so the answer arrives where the question was asked.
 */
export function AttachedCard({
  attachment,
  onClear,
}: {
  attachment: StylistAttachment;
  onClear: () => void;
}) {
  const colors = Colors[useScheme()];
  // Shots are listed per garment; a loose photograph has none until it has
  // been uploaded, which the stylist run does.
  const shots = useShots(attachment.garmentId ?? '', Boolean(attachment.garmentId));
  const list = shots.data ?? [];
  const images = useShotImages(list);
  const working = list.filter((s) => s.state === 'queued' || s.state === 'running');

  return (
    <View style={{ gap: Spacing.two }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: Spacing.three }}>
        {attachment.uri ? (
          <Image
            source={{ uri: attachment.uri }}
            contentFit="cover"
            transition={120}
            accessible
            accessibilityLabel={attachment.label}
            style={{
              width: 56,
              height: 72,
              borderRadius: Radius.sm,
              backgroundColor: colors.backgroundElement,
            }}
          />
        ) : null}
        <View style={{ flex: 1, gap: Spacing.half }}>
          <ThemedText type="smallBold" numberOfLines={1}>
            {attachment.label}
          </ThemedText>
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ fontSize: FontSize.meta }}>
            {working.length > 0
              ? 'Working on it'
              : attachment.garmentId
                ? 'Ask me to shoot it, or style around it'
                : 'Add it to your wardrobe to shoot it'}
          </ThemedText>
        </View>
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Remove the attachment"
          animateEntrance={false}
          scale={0.9}
          hitSlop={8}
          onPress={() => {
            void tapFeedback();
            onClear();
          }}
          style={{
            width: TapTarget - Spacing.two,
            height: TapTarget - Spacing.two,
            alignItems: 'center',
            justifyContent: 'center',
          }}>
          <SymbolView
            name={{ ios: 'xmark', android: 'close', web: 'close' }}
            size={16}
            tintColor={colors.textSecondary}
          />
        </MotionPressable>
      </View>

      {/* Pictures that came back, and nothing else.
 
          There was a row of treatment buttons here: on a model, packshot,
          cutout, in a scene. It was a menu of the backend's functions on
          the one screen somebody is trying to talk to, and it made the
          whole surface read as a control panel. Those capabilities are
          all still here; they are reached by saying what you want, which
          is what the input box above is for. What stays is the output,
          because an answer belongs where the question was asked. */}
      {list.length > 0 ? (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ gap: Spacing.two }}>
          {list.map((shot) => (
            <ShotThumb key={shot.id} shot={shot} uri={images.data?.[shot.id] ?? null} />
          ))}
        </ScrollView>
      ) : null}
    </View>
  );
}

/** One shot, at strip size, in whatever state it is in. */
function ShotThumb({ shot, uri }: { shot: Shot; uri: string | null }) {
  const colors = Colors[useScheme()];
  const pending = shot.state === 'queued' || shot.state === 'running';
  if (pending || !uri) {
    return <Skeleton width={72} height={96} radius={Radius.sm} label="Being taken" />;
  }
  if (shot.state === 'failed') {
    return (
      <View
        style={{
          width: 72,
          height: 96,
          borderRadius: Radius.sm,
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: colors.backgroundElement,
        }}>
        <SymbolView
          name={{ ios: 'exclamationmark.triangle', android: 'warning', web: 'warning' }}
          size={18}
          tintColor={colors.textSecondary}
        />
      </View>
    );
  }
  return (
    <Image
      source={{ uri }}
      contentFit="cover"
      transition={120}
      accessible
      accessibilityLabel={shot.treatment}
      style={{ width: 72, height: 96, borderRadius: Radius.sm }}
    />
  );
}

/** Pick something out of the wardrobe, as a board rather than a list. */
function WardrobePicker({
  wardrobe,
  onClose,
  onPick,
}: {
  wardrobe: readonly WardrobeEntry[];
  onClose: () => void;
  onPick: (entry: WardrobeEntry) => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <ScrollView
        contentInsetAdjustmentBehavior="automatic"
        contentContainerStyle={{
          padding: Spacing.three,
          paddingBottom: insets.bottom + Spacing.four,
          gap: Spacing.three,
        }}>
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}>
          <ThemedText type="smallBold">Pick a piece</ThemedText>
          <Pressable accessibilityRole="button" onPress={onClose} hitSlop={10}>
            <ThemedText type="small" themeColor="textSecondary">
              Close
            </ThemedText>
          </Pressable>
        </View>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          {wardrobe.map((entry, index) => (
            <MotionPressable
              key={entry.id}
              index={index}
              accessibilityRole="button"
              accessibilityLabel={entry.name}
              onPress={() => {
                void tapFeedback();
                onPick(entry);
              }}
              style={{
                width: '33.33%',
                paddingHorizontal: Spacing.one,
                paddingBottom: Spacing.three,
                gap: Spacing.one,
              }}>
              <Image
                source={entry.image ?? (entry.uri ? { uri: entry.uri } : null)}
                placeholder={entry.thumbhash ? { thumbhash: entry.thumbhash } : undefined}
                contentFit="cover"
                transition={0}
                style={{
                  width: '100%',
                  aspectRatio: 3 / 4,
                  borderRadius: Radius.sm,
                  backgroundColor: colors.backgroundElement,
                }}
              />
              <ThemedText
                type="small"
                numberOfLines={1}
                style={{ fontSize: FontSize.meta }}>
                {entry.name}
              </ThemedText>
            </MotionPressable>
          ))}
        </View>
      </ScrollView>
    </View>
  );
}
