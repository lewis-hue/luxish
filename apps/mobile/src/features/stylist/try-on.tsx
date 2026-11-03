import { Image } from 'expo-image';
import { useState } from 'react';
import { View } from 'react-native';

import {
  isWorking,
  outfitSentence,
  useAvatar,
  useRenders,
  useTryOn,
} from '@/api/queries/avatar';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import {
  Colors,
  FontSize,
  ImageFade,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import {
  OutfitFigure,
  type FigureSlot,
  type Presentation,
  type WornPiece,
} from '@/features/avatar/figure';
import { PictureActions } from '@/features/avatar/picture-actions';
import { PastLooks } from '@/features/avatar/past-looks';
import type { OutfitPiece } from '@/features/stylist/run';
import { slotFor } from '@/features/taxonomy';
import type { WardrobeEntry } from '@/features/wardrobe/store';
import { useScheme } from '@/hooks/use-theme';

/**
 * Dress the figure from the outfit and the wardrobe behind it.
 *
 * Exported because this is the join that decides whether anything is
 * shown at all: a piece the stylist named is only drawable if it is
 * one this person owns *and* the device holds a cut-out of it.
 *
 * Matched on `garmentId` against the wardrobe's `serverId`, never on
 * the name. Two black t-shirts have the same name and are different
 * garments, and dressing somebody in the wrong one is worse than
 * leaving the slot empty.
 */
/**
 * A posted fit's own garments, as the figure can wear them.
 *
 * **The clothes in the photograph, not a redrawing of them.** The
 * other way to put a fit on somebody here is to describe it in a
 * sentence and pay an image model to draw that - which produces
 * something *like* the outfit, with the logo moved and the pattern
 * changed. These are the garments themselves, cut out of the
 * photograph they were worn in by the server, so nothing is
 * reconstructed because nothing is redrawn.
 *
 * Free and immediate, unlike the render. A piece whose picture has
 * not arrived yet, or whose category maps to no slot on the figure,
 * is left out rather than guessed at: a jumper drawn where the
 * shoes go is worse than a figure wearing one thing less.
 */
export function wearCutPieces(
  pieces: readonly {
    mediaAssetId: string;
    category: string | null;
    position: number;
  }[],
  uris: Readonly<Record<string, string>>,
): WornPiece[] {
  return [...pieces]
    .sort((a, b) => a.position - b.position)
    .flatMap((piece) => {
      const uri = uris[piece.mediaAssetId];
      if (!uri) return [];
      const slot = piece.category ? slotFor(piece.category) : undefined;
      if (!slot) return [];
      return [{ id: piece.mediaAssetId, slot: slot as FigureSlot, uri }];
    });
}

export function dress(
  pieces: readonly OutfitPiece[],
  wardrobe: readonly WardrobeEntry[],
): WornPiece[] {
  const byId = new Map(
    wardrobe
      .filter((entry) => entry.serverId)
      .map((entry) => [entry.serverId as string, entry]),
  );

  return pieces.flatMap((piece) => {
    // Only clothes they own: a suggestion to go and buy something is
    // not in this picture, because the picture is of their wardrobe.
    if (!piece.owned || !piece.garmentId) return [];
    const entry = byId.get(piece.garmentId);
    if (!entry?.uri) return [];
    const slot = piece.category ? slotFor(piece.category) : undefined;
    if (!slot) return [];
    return [{ id: piece.garmentId, slot: slot as FigureSlot, uri: entry.uri }];
  });
}

/**
 * The outfit, worn.
 *
 * **Drawn on the phone, free, every time.** The figure and the
 * garments' own cut-outs are already on the device, so showing a look
 * costs nothing and appears at once. This replaced a billed render
 * that ran automatically on every outfit: at fifteen to twenty-seven
 * seconds and a model call each, the common question - does this top
 * go with those trousers - was the most expensive thing in the app
 * and the slowest.
 *
 * **Photoreal is still here, behind a button.** Some looks are worth
 * a real picture, and the fit somebody saw on Discover still gets
 * one. It is a choice now rather than a default, which is the whole
 * of the saving.
 *
 * **It appears with the answer, not with the question.** An earlier
 * version stood the frame up the moment a question was sent, on the
 * reasoning that holding the space stops the page jumping. In
 * practice that is half a minute of looking at an empty figure, and
 * an empty figure is not reassurance - the line saying a look is
 * being put together already does that job, in words, in one row.
 */
export function AvatarLook({
  pieces,
  wardrobe,
  signedIn,
}: {
  /** The outfit. Null until there is one, and then nothing renders. */
  pieces: readonly OutfitPiece[] | null;
  wardrobe: readonly WardrobeEntry[];
  signedIn: boolean;
}) {
  const colors = Colors[useScheme()];
  const avatar = useAvatar(signedIn);
  const renders = useRenders(signedIn);
  const tryOn = useTryOn();
  const [asked, setAsked] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  // Nothing to put on anybody yet. Nothing is drawn at all - not an
  // empty frame, not a skeleton figure.
  if (pieces === null) return null;

  const worn = dress(pieces, wardrobe);
  const presentation = (avatar.data?.appearance.presentation ??
    'unspecified') as Presentation;

  const mine = (renders.data ?? []).find((render) => render.id === asked);
  const photoreal = mine?.uri ?? null;
  const drawing = mine ? isWorking(mine.state) : tryOn.isPending;

  const askForReal = () => {
    void tapFeedback();
    setProblem(null);
    const owned = pieces.filter((piece) => piece.owned && piece.name);
    tryOn.mutate(
      {
        outfit: outfitSentence(
          owned.map((piece) => ({ name: piece.name as string, colour: null })),
        ),
        pieces: owned.map((piece) => ({
          name: piece.name as string,
          colour: null,
          category: piece.category,
        })),
      },
      {
        onSuccess: (id) => {
          if (id) setAsked(id);
          else setProblem('That could not be drawn. Try again.');
        },
        onError: () => setProblem('That could not be drawn. Try again.'),
      },
    );
  };

  return (
    <View style={{ gap: Spacing.two }}>
      {photoreal ? (
        <View
          style={{
            width: '100%',
            aspectRatio: 3 / 4,
            borderRadius: Radius.lg,
            borderCurve: 'continuous',
            overflow: 'hidden',
            backgroundColor: colors.backgroundElement,
          }}>
          {/* `contain`, not `cover`.

              The frame is 3:4 and a rendered figure is taller, so
              filling the frame took the head and the shoes off - the
              two things somebody is checking when they ask to see an
              outfit on themselves. Fitted inside, the whole figure is
              there and the frame letterboxes instead. */}
          <Image
            source={{ uri: photoreal }}
            contentFit="contain"
            transition={ImageFade}
            style={{ width: '100%', height: '100%' }}
          />
        </View>
      ) : (
        <OutfitFigure
          pieces={worn}
          presentation={presentation}
          label="The outfit, on a figure"
        />
      )}

      {/* Keep it, send it, or put it on the board. */}
      <PictureActions uri={photoreal} />

      {/* Every look drawn before this one.
          
          A render is a billed picture somebody waited half a minute
          for, and it was gone the moment they asked a second
          question. The server has kept them all along - this is the
          list it already serves, which is why recalling them costs
          nothing. */}
      <PastLooks renders={renders.data ?? []} skip={asked} />

      {problem ?? mine?.error ? (
        <ThemedText
          selectable
          style={{ ...labelType(FontSize.subhead, 400), color: colors.danger }}>
          {problem ?? mine?.error}
        </ThemedText>
      ) : null}

      {/* The billed picture, asked for rather than assumed. Offered
          only once there is an outfit worth spending one on, and only
          to somebody who has an avatar to put it on. */}
      {worn.length > 0 && !photoreal && avatar.data?.assetId ? (
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="See it photoreal"
          accessibilityHint="Draws this outfit on your avatar. Takes about half a minute."
          accessibilityState={{ busy: drawing, disabled: drawing }}
          animateEntrance={false}
          disabled={drawing}
          onPress={askForReal}
          style={{
            minHeight: TapTarget,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: Radius.full,
            borderWidth: 1,
            borderColor: colors.border,
            opacity: drawing ? 0.5 : 1,
          }}>
          <ThemedText type="smallBold">
            {drawing ? 'Drawing it on you' : 'See it photoreal'}
          </ThemedText>
        </MotionPressable>
      ) : null}
    </View>
  );
}

/**
 * The pieces a verdict named, as the figure can wear them.
 *
 * **Free, and the reason the stylist stopped billing for this.** The
 * verdict already names garment ids out of this person's own
 * wardrobe, and every one of those garments has a cut-out on the
 * device. Drawing them on the figure is a composite, not a
 * generation: it costs nothing, it appears at once, and the clothes
 * in the picture are the actual clothes rather than a model's
 * impression of a description of them.
 *
 * What it replaced was a round trip through the language model to
 * produce a prompt, then a billed image call and twenty to thirty
 * seconds of waiting, to show somebody garments that were already
 * sitting in their pocket.
 *
 * A garment with no cut-out yet, or whose category maps to no slot,
 * is left out rather than guessed at - a jumper drawn where the shoes
 * go is worse than a figure wearing one thing less.
 */
export function wearOwned(
  ids: readonly string[],
  wardrobe: readonly WardrobeEntry[],
): WornPiece[] {
  const byId = new Map(
    wardrobe
      .filter((entry) => entry.serverId)
      .map((entry) => [entry.serverId as string, entry]),
  );
  return ids.flatMap((id) => {
    const entry = byId.get(id);
    if (!entry?.uri) return [];
    const slot = entry.categoryId ? slotFor(entry.categoryId) : undefined;
    if (!slot) return [];
    return [{ id, slot: slot as FigureSlot, uri: entry.uri }];
  });
}
