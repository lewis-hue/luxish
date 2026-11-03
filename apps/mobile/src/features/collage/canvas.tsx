import { Image } from 'expo-image';
import { useEffect } from 'react';
import { SymbolView } from 'expo-symbols';
import {
  Gesture,
  GestureDetector,
  GestureHandlerRootView,
} from 'react-native-gesture-handler';
import Animated, {
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  type SharedValue,
} from 'react-native-reanimated';
import { Pressable, View } from 'react-native';

import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { Colors, Radius, Spacing, TapTarget } from '@/constants/theme';
import {
  backgroundColour,
  type Collage,
  type Piece,
} from '@/features/collage/model';
import { useScheme } from '@/hooks/use-theme';

/**
 * The canvas: pictures you can drag, pinch and turn.
 *
 * **Gestures run on the UI thread, state lands on commit.** A drag
 * updates shared values at sixty frames a second and writes one
 * change to the model when the finger lifts. Writing every frame into
 * React state would make the undo stack a frame-by-frame recording and
 * the drag itself stutter.
 *
 * **Selection is the top of the stack.** Tapping a piece brings it
 * forward, which is both how it gets picked up and how overlapping
 * pictures are reordered - two behaviours from one gesture, and the
 * one people expect from every editor they have used.
 */
export function Canvas({
  collage,
  width,
  height,
  selected,
  onSelect,
  onChange,
  onCommit,
}: {
  collage: Collage;
  width: number;
  height: number;
  selected: string | null;
  onSelect: (id: string | null) => void;
  /** Called continuously while a gesture runs. Not recorded. */
  onChange: (id: string, patch: Partial<Piece>) => void;
  /** Called once when a gesture ends. This is what undo remembers. */
  onCommit: () => void;
}) {
  return (
    <GestureHandlerRootView style={{ width, height }}>
      <Pressable
        accessibilityRole="none"
        onPress={() => onSelect(null)}
        style={{
          width,
          height,
          overflow: 'hidden',
          borderRadius: Radius.lg,
          borderCurve: 'continuous',
          backgroundColor: backgroundColour(collage.background),
        }}>
        {collage.pieces.map((piece) => (
          <Placed
            key={piece.id}
            piece={piece}
            canvasWidth={width}
            canvasHeight={height}
            selected={piece.id === selected}
            onSelect={() => onSelect(piece.id)}
            onChange={(patch) => onChange(piece.id, patch)}
            onCommit={onCommit}
          />
        ))}
      </Pressable>
    </GestureHandlerRootView>
  );
}

/** One picture on the canvas, under a finger. */
/**
 * Write a shared value from inside a worklet.
 *
 * The indirection is deliberate and is the same one `feed/zoomable`
 * uses: `react-hooks/immutability` refuses a direct `.value =` on a
 * shared value that is also assigned outside the worklet, which
 * these four are - an undo has to be able to move a piece back.
 */
function write<T>(shared: SharedValue<T>, next: T): void {
  'worklet';
  shared.value = next;
}

function Placed({
  piece,
  canvasWidth,
  canvasHeight,
  selected,
  onSelect,
  onChange,
  onCommit,
}: {
  piece: Piece;
  canvasWidth: number;
  canvasHeight: number;
  selected: boolean;
  onSelect: () => void;
  onChange: (patch: Partial<Piece>) => void;
  onCommit: () => void;
}) {
  const colors = Colors[useScheme()];

  // Live values the gestures write to. Seeded from the model and
  // reset by it, so an undo moves the picture back.
  const x = useSharedValue(piece.x);
  const y = useSharedValue(piece.y);
  const scale = useSharedValue(piece.width);
  const rotation = useSharedValue(piece.rotation);

  // **Synced in an effect, never during render.**
  //
  // These four lines used to run in the render body, and that was
  // the bug behind "I can add a picture but I cannot move it". A
  // gesture's `onStart` calls `onSelect`, which sets React state,
  // which re-renders - and the re-render slammed `x.value` back to
  // the model's value while the finger was still down. The piece
  // fought every drag.
  //
  // It looked like it worked after adding a second picture because
  // by then the first was already selected, so `onSelect` changed
  // nothing, no re-render happened, and nothing reset the value.
  //
  // Keyed on the model's own numbers, so an undo still moves the
  // picture back but a re-render for any other reason does not
  // touch it.
  useEffect(() => {
    x.value = piece.x;
    y.value = piece.y;
    scale.value = piece.width;
    rotation.value = piece.rotation;
  }, [piece.x, piece.y, piece.width, piece.rotation, x, y, scale, rotation]);

  const startX = useSharedValue(0);
  const startY = useSharedValue(0);
  const startScale = useSharedValue(0);
  const startRotation = useSharedValue(0);

  const drag = Gesture.Pan()
    .onStart(() => {
      startX.value = x.value;
      startY.value = y.value;
      runOnJS(onSelect)();
    })
    .onUpdate((event) => {
      write(x, startX.value + event.translationX / canvasWidth);
      write(y, startY.value + event.translationY / canvasHeight);
    })
    .onEnd(() => {
      runOnJS(onChange)({ x: x.value, y: y.value });
      runOnJS(onCommit)();
    });

  const pinch = Gesture.Pinch()
    .onStart(() => {
      startScale.value = scale.value;
      runOnJS(onSelect)();
    })
    .onUpdate((event) => {
      // Bounded: a picture scaled to nothing cannot be grabbed again,
      // and one scaled past the canvas hides everything under it.
      const next = startScale.value * event.scale;
      write(scale, Math.min(2.5, Math.max(0.08, next)));
    })
    .onEnd(() => {
      runOnJS(onChange)({ width: scale.value });
      runOnJS(onCommit)();
    });

  const turn = Gesture.Rotation()
    .onStart(() => {
      startRotation.value = rotation.value;
      runOnJS(onSelect)();
    })
    .onUpdate((event) => {
      write(rotation, startRotation.value + event.rotation);
    })
    .onEnd(() => {
      runOnJS(onChange)({ rotation: rotation.value });
      runOnJS(onCommit)();
    });

  const tap = Gesture.Tap().onEnd(() => {
    runOnJS(onSelect)();
  });

  // Simultaneous, because pinching and turning are one gesture to a
  // person: two fingers moving. Racing them means one always loses.
  const gestures = Gesture.Simultaneous(
    Gesture.Exclusive(drag, tap),
    pinch,
    turn,
  );

  const style = useAnimatedStyle(() => {
    const w = scale.value * canvasWidth;
    const h = w / (piece.ratio || 1);
    return {
      position: 'absolute',
      width: w,
      height: h,
      left: x.value * canvasWidth - w / 2,
      top: y.value * canvasHeight - h / 2,
      transform: [{ rotate: `${rotation.value}rad` }],
    };
  });

  return (
    <GestureDetector gesture={gestures}>
      <Animated.View style={style}>
        <Image
          source={{ uri: piece.uri }}
          contentFit="contain"
          transition={0}
          accessible
          accessibilityLabel="A picture on your collage"
          style={{ width: '100%', height: '100%' }}
        />
        {/* The selection ring. Drawn over the picture rather than
            around it, so a piece at the canvas edge still shows it. */}
        {selected ? (
          <View
            pointerEvents="none"
            style={{
              position: 'absolute',
              width: '100%',
              height: '100%',
              borderWidth: 2,
              borderColor: colors.accent,
              borderRadius: Radius.sm,
            }}
          />
        ) : null}
      </Animated.View>
    </GestureDetector>
  );
}

/**
 * What can be done to the selected piece.
 *
 * Only shown when something is selected: a row of controls for
 * nothing is a row of controls that do nothing.
 */
export function PieceTools({
  onDelete,
  onForward,
}: {
  onDelete: () => void;
  onForward: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <View
      style={{
        flexDirection: 'row',
        gap: Spacing.two,
        padding: Spacing.one,
        borderRadius: Radius.full,
        backgroundColor: colors.backgroundElement,
      }}>
      <Tool
        label="Bring to front"
        icon={{
          ios: 'square.3.layers.3d.top.filled',
          android: 'flip_to_front',
          web: 'flip_to_front',
        }}
        onPress={onForward}
      />
      <Tool
        label="Remove this piece"
        icon={{ ios: 'trash', android: 'delete', web: 'delete' }}
        destructive
        onPress={onDelete}
      />
    </View>
  );
}

function Tool({
  label,
  icon,
  destructive,
  onPress,
}: {
  label: string;
  icon: Parameters<typeof SymbolView>[0]['name'];
  destructive?: boolean;
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      animateEntrance={false}
      scale={0.9}
      onPress={() => {
        void tapFeedback();
        onPress();
      }}
      style={{
        width: TapTarget,
        height: TapTarget,
        alignItems: 'center',
        justifyContent: 'center',
      }}>
      <SymbolView
        name={icon}
        size={20}
        tintColor={destructive ? colors.danger : colors.text}
      />
    </MotionPressable>
  );
}
