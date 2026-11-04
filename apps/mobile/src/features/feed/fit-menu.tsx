import { router } from 'expo-router';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { Alert, Modal, Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { FeedFit } from '@/api/queries/discover-feed';
import type { PostItemTag } from '@/api/queries/posts';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, successFeedback, tapFeedback } from '@/components/ui/motion';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
} from '@/constants/theme';
import { keepToPhotos } from '@/features/avatar/keep';
import { useScheme } from '@/hooks/use-theme';

/**
 * Everything a fit can do, behind one control.
 *
 * The corner carried a share button, which is one capability wearing
 * the slot where all of them belong. Three dots is the convention for
 * "there is more here", and what is behind it is the full list rather
 * than a second copy of what is already on screen.
 *
 * **Destructive things sit at the bottom and confirm.** Hiding is
 * reversible and quiet; reporting and blocking are neither, so they
 * are last and they ask.
 */
export function FitMenu({
  fit,
  uri,
  visible,
  link,
  onClose,
  onHide,
  onShare,
  mine,
  items = [],
  cutPieces = 0,
}: {
  fit: FeedFit;
  /** The local file, for saving and for the collage. */
  uri: string | null;
  visible: boolean;
  /** Where the fit lives, when the server has somewhere to point. */
  link?: string;
  /**
   * What the look is made of.
   *
   * Defaults to none, which is the honest reading while the detail
   * response is still in flight: a tile does not carry pieces, so
   * offering to shop them before they have arrived would promise a
   * shelf that may not exist.
   */
  items?: readonly PostItemTag[];
  /**
   * How many garments the server cut out of this fit.
   *
   * Enough on its own to shop it: the catalogue is searched per
   * identified garment, so nothing has to have been tagged.
   */
  cutPieces?: number;
  onClose: () => void;
  /** Hides this fit from this reader's board. */
  onHide: () => void;
  onShare: () => void;
  /**
   * The author's own two actions, when the reader is the author.
   *
   * Absent for everybody else, and when they are absent the reader's
   * three - hide, report, block - take their place. Nobody needs to
   * report their own fit, and "Block yourself" is not a thing to put
   * in front of somebody.
   */
  mine?: {
    visibility: 'public' | 'private';
    onSetVisibility: (next: 'public' | 'private') => void;
    onDelete: () => void;
  };
}) {
  // A piece whose garment or product has since gone is reported
  // rather than dropped, so a look does not quietly lose a slot - but
  // there is nothing to shop in one, and counting it would promise a
  // shelf item that cannot be opened.
  const shoppable = items.filter((item) => item.kind !== 'gone');

  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();

  const act = (run: () => void) => {
    void tapFeedback();
    onClose();
    run();
  };

  const download = async () => {
    void tapFeedback();
    if (!uri) {
      Alert.alert('Not ready yet', 'That picture is still loading.');
      return;
    }
    try {
      await keepToPhotos(uri);
      void successFeedback();
      onClose();
      Alert.alert('Saved', `It is in your photos, with ${fit.authorName}'s name on it.`);
    } catch (caught) {
      Alert.alert(
        'Could not save',
        caught instanceof Error ? caught.message : 'Try again in a moment.',
      );
    }
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
            type="small"
            themeColor="textSecondary"
            numberOfLines={1}
            style={{
              textAlign: 'center',
              paddingHorizontal: Spacing.three,
              paddingBottom: Spacing.two,
              fontSize: FontSize.footnote,
            }}>
            {fit.caption ?? `${fit.authorName}'s fit`}
          </ThemedText>

          <Row
            label="Try it on"
            icon={{ ios: 'figure.stand', android: 'person', web: 'person' }}
            onPress={() =>
              act(() =>
                // **Straight to the figure, not to the fit's page.**
                //
                // This opened `/fit/[id]`, which is the pin again with
                // the try-on one tap further in - so "Try it on" did
                // not try anything on. The avatar screen already reads
                // `?fit=`, cuts that fit's garments out of the
                // photograph and dresses the figure with them, which
                // is both the fast path and the real clothes rather
                // than a model's impression of them.
                router.push({ pathname: '/avatar', params: { fit: fit.id } }),
              )
            }
          />
          <Row
            label="Ask the stylist about it"
            icon={{ ios: 'sparkles', android: 'auto_awesome', web: 'auto_awesome' }}
            onPress={() =>
              act(() =>
                router.push({
                  // The assistant lives on the wardrobe tab now, and
                  // `(tabs)` is a route group that never appears in
                  // a path - so this resolved to nothing twice over
                  // and the row did nothing at all.
                  pathname: '/wardrobe',
                  // The cover travels too, so the chip shows the
                  // picture being asked about rather than a label.
                  params: { fit: fit.id, asset: fit.mediaAssetIds[0] ?? '' },
                }),
              )
            }
          />
          <Row
            label="Add to a collage"
            icon={{
              ios: 'square.on.square.dashed',
              android: 'auto_awesome_mosaic',
              web: 'auto_awesome_mosaic',
            }}
            // **The picture travels with the action.** It opened an
            // empty canvas, so the first thing anybody had to do was
            // go and find the photograph they had just been looking
            // at - and the canvas being empty is also why Undo,
            // Redo and Next all arrived disabled.
            onPress={() =>
              act(() =>
                router.push({
                  pathname: '/collage',
                  params: { asset: fit.mediaAssetIds[0] ?? '' },
                }),
              )
            }
          />
          {/* **The label follows what is actually there.**
              It always read "Shop the look" and always pushed the
              generic recommendations screen, which is a promise
              about this fit answered with a shelf about nothing in
              particular. Nothing had been tagged onto a fit, so it
              was never anything else.
              Given pieces it now opens them; given none it says what
              it will really do. Either way the tap is honest. */}
          {/* **Always this fit, never the generic shelf.**

              The row only passed the fit when the pin had tagged
              products or cut-outs, and almost no pin had either - so
              nearly every pin fell through to `/shop` with no fit at
              all, which is a shelf built from gaps in your own
              wardrobe. The same handful of things appeared under
              every pin in the app, which is exactly how it was
              reported.

              The fit always travels now. What is behind it is a
              vision reading of that photograph - the garments it
              actually contains, named once per pin and shared by
              everybody who opens it - and the catalogue and the open
              web are searched per garment from there. */}
          <Row
            label="Shop this look"
            hint={
              shoppable.length > 0
                ? shoppable.length === 1
                  ? 'The piece in this fit'
                  : `The ${shoppable.length} pieces in this fit`
                : 'Matched to the garments in this picture'
            }
            icon={{ ios: 'bag', android: 'shopping_bag', web: 'shopping_bag' }}
            onPress={() =>
              act(() =>
                router.push({ pathname: '/shop', params: { fit: fit.id } }),
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
          <Row
            label="Save the picture"
            icon={{
              ios: 'square.and.arrow.down',
              android: 'download',
              web: 'download',
            }}
            onPress={() => void download()}
          />
          <Row
            label={link ? 'Share with a link' : 'Share'}
            icon={{
              ios: 'square.and.arrow.up',
              android: 'ios_share',
              web: 'ios_share',
            }}
            onPress={() => act(onShare)}
          />

          <Divider />

          {mine ? (
            <>
              <Row
                label={
                  mine.visibility === 'private'
                    ? 'Make it public'
                    : 'Make it private'
                }
                hint={
                  mine.visibility === 'private'
                    ? 'Back on the board, and in other people’s feeds'
                    : 'Only you see it. It stays on your profile'
                }
                icon={
                  mine.visibility === 'private'
                    ? { ios: 'eye', android: 'visibility', web: 'visibility' }
                    : {
                        ios: 'lock',
                        android: 'lock',
                        web: 'lock',
                      }
                }
                onPress={() =>
                  act(() =>
                    mine.onSetVisibility(
                      mine.visibility === 'private' ? 'public' : 'private',
                    ),
                  )
                }
              />
              <Row
                label="Delete this fit"
                hint="Gone from everywhere, and not recoverable"
                icon={{ ios: 'trash', android: 'delete', web: 'delete' }}
                destructive
                onPress={() => act(mine.onDelete)}
              />
            </>
          ) : (
            <>
          <Row
            label="Show fewer like this"
            hint="It stops appearing on your board"
            icon={{ ios: 'eye.slash', android: 'visibility_off', web: 'visibility_off' }}
            onPress={() =>
              act(() => {
                onHide();
                void successFeedback();
              })
            }
          />
          <Row
            label="Report this fit"
            icon={{ ios: 'flag', android: 'flag', web: 'flag' }}
            onPress={() =>
              act(() =>
                router.push({
                  pathname: '/member/[id]',
                  params: { id: fit.authorId, report: '1' },
                }),
              )
            }
          />
          <Row
            label={`Block ${fit.authorName}`}
            icon={{ ios: 'hand.raised', android: 'block', web: 'block' }}
            destructive
            onPress={() =>
              act(() =>
                router.push({
                  pathname: '/member/[id]',
                  params: { id: fit.authorId, block: '1' },
                }),
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

function Divider() {
  const colors = Colors[useScheme()];
  return (
    <View
      style={{
        height: 1,
        marginVertical: Spacing.one,
        marginHorizontal: Spacing.three,
        backgroundColor: colors.border,
      }}
    />
  );
}

/** One line in the menu: a glyph, a verb, and nothing else. */
function Row({
  label,
  hint,
  icon,
  destructive,
  onPress,
}: {
  label: string;
  hint?: string;
  icon: SymbolViewProps['name'];
  destructive?: boolean;
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={hint}
      animateEntrance={false}
      scale={0.99}
      onPress={onPress}
      style={{
        minHeight: TapTarget + Spacing.one,
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.three,
        paddingHorizontal: Spacing.three,
      }}>
      <SymbolView
        name={icon}
        size={20}
        tintColor={destructive ? colors.danger : colors.text}
      />
      <ThemedText
        type="small"
        style={{
          fontSize: FontSize.subhead,
          color: destructive ? colors.danger : colors.text,
        }}>
        {label}
      </ThemedText>
    </MotionPressable>
  );
}
