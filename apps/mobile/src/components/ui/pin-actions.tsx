import { Image } from 'expo-image';
import { router } from 'expo-router';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { Alert, Modal, Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useTryOnFit } from '@/api/queries/avatar';
import { usePostImage } from '@/api/queries/post-media';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { PinToBoard } from '@/components/ui/pin-to-board';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
} from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';
import { useState } from 'react';

export type PinSubject = {
  /** The fit this sheet is about. */
  postId: string;
  title: string;
  /**
   * The fit's own cover, so the thumbnail above the sheet is the
   * photograph that was pressed.
   *
   * It used to be artwork looked up from the curated look a fit was
   * tagged with, which meant no thumbnail at all once fits stopped
   * carrying one - the sheet opened over a stranger's board with
   * nothing in it answering "which one did I press?".
   */
  coverAssetId: string | null;
  aesthetics?: readonly string[];
  /** Set for a fit somebody published, which can be reported. */
  authorId?: string | null;
};

/** The photograph the sheet is about, riding above it. */
function Thumbnail({ assetId }: { assetId: string | null }) {
  const uri = usePostImage(assetId).data ?? null;
  if (!uri) return null;
  return (
    <Image
      source={{ uri }}
      recyclingKey={assetId ?? undefined}
      contentFit="cover"
      transition={0}
      style={{
        width: 96,
        height: 128,
        borderRadius: Radius.md,
        borderCurve: 'continuous',
      }}
    />
  );
}

/**
 * What you can do with a pin, without leaving the board.
 *
 * **The two things this app is for go at the top, at full size.** Boards
 * elsewhere open this sheet onto feed controls — show me more of this, show
 * me less. LUXish has something better to offer at that moment: you are
 * looking at an outfit, so the two large buttons put it on you and hand it
 * to the stylist. The quieter row underneath is everything else you might
 * want: keep it, buy it, wear it on a date, or flag it.
 *
 * **Nothing here is a count.** A tally of likes under a stranger's outfit
 * measures the outfit's popularity, which is not what anybody opened a
 * wardrobe app to find out. Every line is a verb.
 *
 * **The picture rides above the sheet.** It is small, and it is the only
 * answer to "which one did I press?" on a board where the tiles are a
 * thumb-width apart.
 */
export function PinActions({
  subject,
  visible,
  onClose,
}: {
  subject: PinSubject | null;
  visible: boolean;
  onClose: () => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const [boarding, setBoarding] = useState(false);
  const tryOn = useTryOnFit();

  if (!subject) return null;

  // Every action leaves the sheet behind: it answered its question the
  // moment it was pressed, and a sheet still open over the destination is
  // one the user has to dismiss before they can use what they asked for.
  const go = (run: () => void) => {
    void tapFeedback();
    onClose();
    run();
  };

  return (
    <>
      <Modal
        visible={visible && !boarding}
        transparent
        animationType="slide"
        onRequestClose={onClose}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Close"
          onPress={onClose}
          style={{ flex: 1, justifyContent: 'flex-end', backgroundColor: '#00000066' }}>
          {/* The thumbnail sits in the gap above the sheet, half over it. */}
          <View style={{ alignItems: 'center', marginBottom: -Spacing.five }}>
            <Thumbnail assetId={subject.coverAssetId} />
          </View>

          <Pressable
            // Swallows taps so pressing the sheet does not close it.
            onPress={() => {}}
            style={{
              paddingTop: Spacing.five + Spacing.three,
              paddingHorizontal: Spacing.three,
              paddingBottom: insets.bottom + Spacing.three,
              gap: Spacing.three,
              backgroundColor: colors.background,
              borderTopLeftRadius: Radius.lg,
              borderTopRightRadius: Radius.lg,
              borderCurve: 'continuous',
            }}>
            <ThemedText
              type="small"
              themeColor="textSecondary"
              numberOfLines={1}
              style={{ textAlign: 'center', fontSize: FontSize.footnote }}>
              {subject.title}
            </ThemedText>

            <View style={{ flexDirection: 'row', gap: Spacing.two }}>
              <BigAction
                label={tryOn.isPending ? 'Starting' : 'Try it on'}
                busy={tryOn.isPending}
                icon={{ ios: 'figure.stand', android: 'person', web: 'person' }}
                onPress={() => {
                  // A fit is a photograph, so it goes through the
                  // pipeline that reads the clothes out of it and draws
                  // them on this person.
                  void tapFeedback();
                  void tryOn
                    .mutateAsync(subject.postId)
                    .then(() => {
                      onClose();
                      router.push('/avatar');
                    })
                    .catch(() => {
                      Alert.alert(
                        'Could not start that',
                        'Try again in a moment.',
                      );
                    });
                }}
              />
              <BigAction
                label="Ask the stylist"
                icon={{ ios: 'sparkles', android: 'auto_awesome', web: 'auto_awesome' }}
                onPress={() =>
                  go(() =>
                    router.push({
                      // The assistant lives on the wardrobe tab now, and
                  // `(tabs)` is a route group that never appears in
                  // a path - so this resolved to nothing twice over
                  // and the row did nothing at all.
                  pathname: '/wardrobe',
                      // The cover too, so the chip can show the
                      // picture rather than a bare label.
                      params: {
                        fit: subject.postId,
                        asset: subject.coverAssetId ?? '',
                      },
                    }),
                  )
                }
              />
            </View>

            <View style={{ gap: Spacing.half }}>
              <RowAction
                label="Save to a board"
                icon={{ ios: 'pin', android: 'push_pin', web: 'push_pin' }}
                onPress={() => {
                  void tapFeedback();
                  setBoarding(true);
                }}
              />
              {/* **The tile knows the pin, and that is now enough.**

                  This said "Similar" and pushed the generic shelf,
                  on the reasoning that a board tile does not carry
                  what a fit is made of - only the fit's own page
                  asks for that. True then, and the consequence was
                  that every pin in the app offered the same handful
                  of things.

                  The identification moved to the server: the
                  garments in a photograph are read once per pin, by
                  id, and shared by everybody who opens it. So the
                  tile does not need to know what is in the picture -
                  it only needs to say which picture. */}
              <RowAction
                label="Shop this look"
                icon={{ ios: 'bag', android: 'shopping_bag', web: 'shopping_bag' }}
                onPress={() =>
                  go(() =>
                    router.push({
                      pathname: '/shop',
                      params: { fit: subject.postId },
                    }),
                  )
                }
              />
              {/* **"Plan a day for it" was removed here.**

                A plan is made of garments from somebody's own
                wardrobe, and a pin is a photograph of somebody
                else's outfit. Offering it on a pin promised
                something the planner cannot do with that pin, so
                the option is gone rather than left to disappoint.
                The planner itself is unchanged and still works from
                the wardrobe. */}
              {subject.authorId ? (
                <RowAction
                  label="Report"
                  icon={{ ios: 'flag', android: 'flag', web: 'flag' }}
                  onPress={() =>
                    go(() =>
                      router.push({
                        pathname: '/member/[id]',
                        params: { id: subject.authorId as string, report: '1' },
                      }),
                    )
                  }
                />
              ) : null}
            </View>
          </Pressable>
        </Pressable>
      </Modal>

      {/* The board picker is its own sheet, opened in place of this one so
          two never stack. Closing it closes the whole stack, because the
          pin has by then been made. */}
      <PinToBoard
        postId={subject.postId}
        title={subject.title}
        visible={boarding}
        onClose={() => {
          setBoarding(false);
          onClose();
        }}
      />
    </>
  );
}

/** One of the two headline actions. */
function BigAction({
  label,
  icon,
  busy,
  onPress,
}: {
  label: string;
  icon: SymbolViewProps['name'];
  /** Work has started. Dimmed and unpressable until it settles. */
  busy?: boolean;
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ busy: Boolean(busy), disabled: Boolean(busy) }}
      disabled={busy}
      animateEntrance={false}
      scale={0.97}
      onPress={onPress}
      style={{
        flex: 1,
        opacity: busy ? 0.6 : 1,
        gap: Spacing.one,
        paddingVertical: Spacing.three,
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: Radius.lg,
        borderCurve: 'continuous',
        backgroundColor: colors.backgroundElement,
      }}>
      <SymbolView name={icon} size={22} tintColor={colors.text} />
      <ThemedText type="smallBold">{label}</ThemedText>
    </MotionPressable>
  );
}

/** One of the quieter actions beneath. */
function RowAction({
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
      scale={0.98}
      onPress={onPress}
      style={{
        minHeight: TapTarget,
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.three,
        paddingHorizontal: Spacing.one,
      }}>
      <SymbolView name={icon} size={20} tintColor={colors.text} />
      <ThemedText>{label}</ThemedText>
    </MotionPressable>
  );
}
