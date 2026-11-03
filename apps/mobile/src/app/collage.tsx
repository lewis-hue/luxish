import { Image } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Modal, ScrollView, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { captureRef } from 'react-native-view-shot';

import { ThemedText } from '@/components/themed-text';
import { MotionPressable, successFeedback, tapFeedback } from '@/components/ui/motion';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
} from '@/constants/theme';
import { useAuth } from '@/features/auth/session';
import { canvasBox } from '@/features/collage/box';
import { Canvas, PieceTools } from '@/features/collage/canvas';
import {
  BACKGROUNDS,
  HISTORY,
  MAX_PIECES,
  begin,
  bringForward,
  canRedo,
  canUndo,
  commit,
  place,
  redo,
  remove,
  undo,
  update,
  type Collage,
  type Piece,
  type Session,
} from '@/features/collage/model';
import { CollagePicker } from '@/features/collage/picker';
import { usePostImage } from '@/api/queries/post-media';
import { useScheme } from '@/hooks/use-theme';

/**
 * The collage editor.
 *
 * **One canvas, one sheet, one row of tools.** Pictures come in from
 * the sheet, get dragged and turned on the canvas, and leave as a
 * single flattened photograph - which is the only thing the rest of
 * the app needs to understand. A collage is posted as a picture, so
 * every surface that can show a fit can show one without knowing what
 * a collage is.
 *
 * **Undo is a stack of whole states.** See `model.ts` for why. The
 * canvas writes continuously while a finger is down and records once
 * when it lifts, so undo steps through gestures rather than frames.
 *
 * **Exported at the canvas's own size.** `captureRef` photographs the
 * view, so what is saved is exactly what was arranged - no second
 * layout engine to disagree with the first.
 */
export default function CollageScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';

  // Read here rather than beside the seeding effect below, because
  // whether this screen opens with the picker up depends on it.
  const { asset: seedAsset } = useLocalSearchParams<{ asset?: string }>();

  const [session, setSession] = useState<Session>(() => begin());
  const [selected, setSelected] = useState<string | null>(null);
  /**
   * Whether the picture picker is up.
   *
   * **Closed when a picture came with you.** The picker is a
   * `Modal`, and nothing underneath a modal receives touches - so
   * arriving from a pin's menu put the picture on the canvas behind
   * a sheet and left it impossible to move, resize or turn. The only
   * thing that closed the sheet was picking a *second* picture,
   * which is exactly how the bug was described: it could not be
   * dragged until another was added below it.
   *
   * Somebody who arrived with a picture came to arrange it, not to
   * choose one. The "Add pictures" button is right there when they
   * want more.
   */
  const [picking, setPicking] = useState(!seedAsset);
  const [saving, setSaving] = useState(false);
  // Typed as the host element the new architecture hands back, which
  // is what `captureRef` wants. `useRef<View>` types it as the
  // component rather than the thing on screen.
  const canvas = useRef<React.ComponentRef<typeof View>>(null);

  const collage = session.present;
  // **The shape a pin is drawn in, from the same constant the board
  // uses.** It was 4:5 against a comment claiming that was the app's
  // shape; the app's shape is `UNKNOWN_SHAPE`, and the two had
  // drifted. A collage composed at one ratio and posted into a shell
  // of another is cropped at the edges somebody arranged. The
  // arithmetic sits in `./box` so a test can hold it and the shell to
  // the same answer rather than trusting this comment.
  const { width: canvasWidth, height: canvasHeight } = canvasBox(width);

  // The state as it was when the current gesture started.
  //
  // A drag writes to `present` on every frame so the picture tracks
  // the finger, which destroys the thing undo needs to go back to. So
  // the first write of a gesture stashes it here, and the commit at
  // the end pushes *that* onto the history rather than the state from
  // one frame ago - otherwise undo steps backwards through a
  // recording of the drag.
  const before = useRef<Collage | null>(null);

  const change = (id: string, patch: Partial<Piece>) =>
    setSession((was) => {
      if (before.current === null) before.current = was.present;
      return { ...was, present: update(was.present, id, patch) };
    });

  const record = () =>
    setSession((was) => {
      const start = before.current;
      before.current = null;
      if (start === null || start === was.present) return was;
      return {
        past: [...was.past, start].slice(-HISTORY),
        present: was.present,
        future: [],
      };
    });

  const add = useCallback((uri: string) => {
    if (collage.pieces.length >= MAX_PIECES) {
      Alert.alert(
        'That is a full canvas',
        `A collage holds ${MAX_PIECES} pictures. Remove one to add another.`,
      );
      return;
    }
    // The ratio is read off the file so a picture is never squashed.
    Image.loadAsync({ uri })
      .then((loaded) => {
        const ratio =
          loaded?.width && loaded?.height ? loaded.width / loaded.height : 1;
        setSession((was) => commit(was, place(was.present, uri, ratio)));
      })
      .catch(() => {
        setSession((was) => commit(was, place(was.present, uri, 1)));
      });
    // `collage.pieces.length` is read for the cap, so the callback
    // has to see the current one.
  }, [collage.pieces.length]);

  const save = async () => {
    if (collage.pieces.length === 0 || saving) return;
    void tapFeedback();
    setSelected(null);
    setSaving(true);
    try {
      // A frame, so the selection ring is gone from the picture that
      // gets captured rather than baked into it.
      await new Promise((resolve) => setTimeout(resolve, 60));
      const uri = await captureRef(canvas, { format: 'png', quality: 1 });
      void successFeedback();
      // Posting is the composer's job: a collage is a photograph by
      // the time it leaves here, and it goes through the same caption,
      // tags and screening every other fit does.
      router.replace({ pathname: '/compose', params: { photo: uri } });
    } catch {
      Alert.alert('Could not save', 'That collage did not flatten. Try again.');
    } finally {
      setSaving(false);
    }
  };

  /**
   * The picture somebody came here to use.
   *
   * **"Add to a collage" used to open an empty canvas.** The name of
   * the action says which picture it is about and the screen then
   * asked for one, so the first thing anybody had to do was find the
   * photograph they had just been looking at. Undo, Redo and Next
   * were all disabled on arrival as well, because they are correctly
   * disabled on an empty canvas - which made the whole screen read
   * as broken rather than as waiting.
   *
   * Placed once. `seeded` is what stops a re-render, a rotation or a
   * returning navigation dropping a second copy on top of the first.
   */
  const seedUri = usePostImage(seedAsset ?? null).data ?? null;
  const seeded = useRef(false);

  useEffect(() => {
    if (seeded.current || !seedUri) return;
    seeded.current = true;
    add(seedUri);
  }, [seedUri, add]);

  const leave = () => {
    void tapFeedback();
    if (collage.pieces.length === 0) {
      if (router.canGoBack()) router.back();
      else router.replace('/');
      return;
    }
    Alert.alert('Discard this collage?', 'It has not been saved anywhere.', [
      { text: 'Keep editing', style: 'cancel' },
      {
        text: 'Discard',
        style: 'destructive',
        onPress: () => {
          if (router.canGoBack()) router.back();
          else router.replace('/');
        },
      },
    ]);
  };

  if (!signedIn) {
    router.replace('/sign-in');
    return null;
  }

  return (
    <View
      style={{
        flex: 1,
        backgroundColor: colors.background,
        paddingTop: insets.top + Spacing.two,
      }}>
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: Spacing.two,
          paddingHorizontal: Spacing.three,
          paddingBottom: Spacing.two,
        }}>
        <Chip label="Close" icon={{ ios: 'xmark', android: 'close', web: 'close' }} onPress={leave} />
        <Chip
          label="Undo"
          icon={{ ios: 'arrow.uturn.backward', android: 'undo', web: 'undo' }}
          disabled={!canUndo(session)}
          onPress={() => setSession(undo)}
        />
        <Chip
          label="Redo"
          icon={{ ios: 'arrow.uturn.forward', android: 'redo', web: 'redo' }}
          disabled={!canRedo(session)}
          onPress={() => setSession(redo)}
        />
        <View style={{ flex: 1 }} />
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Save this collage"
          accessibilityState={{
            disabled: collage.pieces.length === 0 || saving,
            busy: saving,
          }}
          disabled={collage.pieces.length === 0 || saving}
          animateEntrance={false}
          scale={0.95}
          onPress={() => void save()}
          style={{
            minHeight: 36,
            justifyContent: 'center',
            paddingHorizontal: Spacing.three,
            borderRadius: Radius.full,
            backgroundColor: colors.accent,
            opacity: collage.pieces.length > 0 && !saving ? 1 : 0.35,
          }}>
          <ThemedText type="smallBold" style={{ color: colors.accentText }}>
            {saving ? 'Saving' : 'Next'}
          </ThemedText>
        </MotionPressable>
      </View>

      <View style={{ alignItems: 'center', gap: Spacing.two }}>
        <View ref={canvas} collapsable={false}>
          <Canvas
            collage={collage}
            width={canvasWidth}
            height={canvasHeight}
            selected={selected}
            onSelect={setSelected}
            onChange={change}
            onCommit={record}
          />
        </View>

        {selected ? (
          <PieceTools
            onForward={() => {
              setSession((was) => commit(was, bringForward(was.present, selected)));
            }}
            onDelete={() => {
              setSession((was) => commit(was, remove(was.present, selected)));
              setSelected(null);
            }}
          />
        ) : collage.pieces.length === 0 ? (
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ fontSize: FontSize.footnote }}>
            Add pictures below. Drag to move, pinch to size, twist to turn.
          </ThemedText>
        ) : null}
      </View>

      {/* The paper. Few colours, all quiet: a collage is the pictures,
          and a loud ground competes with every one of them. */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{
          gap: Spacing.one,
          paddingHorizontal: Spacing.three,
          paddingVertical: Spacing.two,
        }}>
        {BACKGROUNDS.map((paper) => (
          <MotionPressable
            key={paper.id}
            accessibilityRole="button"
            accessibilityState={{ selected: collage.background === paper.id }}
            accessibilityLabel={`${paper.label} background`}
            animateEntrance={false}
            scale={0.9}
            onPress={() => {
              void tapFeedback();
              setSession((was) =>
                commit(was, { ...was.present, background: paper.id }),
              );
            }}
            style={{
              width: 32,
              height: 32,
              borderRadius: Radius.full,
              backgroundColor: paper.colour,
              borderWidth: collage.background === paper.id ? 2 : 1,
              borderColor:
                collage.background === paper.id ? colors.accent : colors.border,
            }}
          />
        ))}
      </ScrollView>

      <View style={{ flex: 1 }} />

      <MotionPressable
        accessibilityRole="button"
        accessibilityLabel="Add pictures"
        animateEntrance={false}
        scale={0.95}
        onPress={() => {
          void tapFeedback();
          setPicking(true);
        }}
        style={{
          alignSelf: 'center',
          minHeight: TapTarget,
          flexDirection: 'row',
          alignItems: 'center',
          gap: Spacing.one,
          paddingHorizontal: Spacing.four,
          marginBottom: insets.bottom + Spacing.three,
          borderRadius: Radius.full,
          backgroundColor: colors.backgroundElement,
        }}>
        <SymbolView
          name={{ ios: 'plus', android: 'add', web: 'add' }}
          size={18}
          tintColor={colors.text}
        />
        <ThemedText type="smallBold">Add pictures</ThemedText>
      </MotionPressable>

      <Modal
        visible={picking}
        transparent
        animationType="slide"
        onRequestClose={() => setPicking(false)}>
        <View style={{ flex: 1, justifyContent: 'flex-end' }}>
          <CollagePicker
            onPick={(uri) => {
              add(uri);
              setPicking(false);
            }}
            onClose={() => setPicking(false)}
          />
        </View>
      </Modal>
    </View>
  );
}

/** One round control in the editor's top bar. */
function Chip({
  label,
  icon,
  disabled,
  onPress,
}: {
  label: string;
  icon: Parameters<typeof SymbolView>[0]['name'];
  disabled?: boolean;
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: Boolean(disabled) }}
      disabled={disabled}
      animateEntrance={false}
      scale={0.9}
      onPress={onPress}
      style={{
        width: 36,
        height: 36,
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: Radius.full,
        backgroundColor: colors.backgroundElement,
        opacity: disabled ? 0.4 : 1,
      }}>
      <SymbolView name={icon} size={16} tintColor={colors.text} />
    </MotionPressable>
  );
}
