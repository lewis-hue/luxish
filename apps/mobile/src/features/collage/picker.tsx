import { Image } from 'expo-image';
import * as ImagePicker from 'expo-image-picker';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { useMemo, useState } from 'react';
import { Alert, FlatList, TextInput, View, useWindowDimensions } from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useSavedFits } from '@/api/queries/discover-feed';
import { useMoodboards } from '@/api/queries/moodboards';
import { usePostImages } from '@/api/queries/post-media';
import { useTagFeed } from '@/api/queries/tags';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Colors,
  Motion,
  FontSize,
  ImageFade,
  Radius,
  Spacing,
  TapTarget,
} from '@/constants/theme';
import { dragTo, peekFor, settleTo } from '@/features/collage/drawer';
import { useScheme } from '@/hooks/use-theme';

type Source = 'saved' | 'boards' | 'photos';

/**
 * Where the pictures for a collage come from.
 *
 * Three sources, and they are the three a person actually has: fits
 * they kept, fits on their boards, and the camera roll. A fourth
 * sourced from everything on the app would be a way to build a
 * collage entirely out of other people's photographs, which is a
 * different product and a worse one.
 *
 * **Searching searches tags**, because that is what the fits here are
 * organised by. Typing filters what is on screen rather than asking
 * the server on every keystroke, except for a tag search, which is a
 * deliberate act and one request.
 */
export function CollagePicker({
  onPick,
  onClose,
}: {
  /** A local file URI, ready to place. */
  onPick: (uri: string) => void;
  onClose: () => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const [source, setSource] = useState<Source>('saved');
  const [query, setQuery] = useState('');

  const saved = useSavedFits(source === 'saved');
  const boards = useMoodboards(source === 'boards');
  const searched = useTagFeed(query.trim(), query.trim().length > 1);

  // Every fit the chosen source offers, as asset ids.
  const assetIds = useMemo(() => {
    if (query.trim().length > 1) {
      return searched.data?.fits.flatMap((fit) => fit.mediaAssetIds) ?? [];
    }
    if (source === 'saved') {
      return saved.data?.flatMap((fit) => fit.mediaAssetIds) ?? [];
    }
    if (source === 'boards') {
      // A board holds post ids; the pictures come back through the
      // same fetcher everything else uses.
      return (boards.data ?? []).flatMap((board) => board.postIds);
    }
    return [];
  }, [source, query, saved.data, boards.data, searched.data]);

  const images = usePostImages(assetIds);
  const loading =
    (source === 'saved' && saved.isPending) ||
    (source === 'boards' && boards.isPending) ||
    (query.trim().length > 1 && searched.isPending);

  const fromPhone = async () => {
    void tapFeedback();
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      Alert.alert(
        'Photo access needed',
        'Grant access in Settings to add your own pictures. Everything else keeps working.',
      );
      return;
    }
    try {
      const picked = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images'],
        // Several at once: a collage is made of pictures, plural, and
        // reopening the library for each one is five taps per piece.
        allowsMultipleSelection: true,
        selectionLimit: 10,
        quality: 0.9,
      });
      if (picked.canceled) return;
      for (const asset of picked.assets) onPick(asset.uri);
    } catch {
      // Said out loud rather than swallowed.
      //
      // The picker can fail for reasons that are not a refusal - the
      // library unavailable, the sheet already up - and an unawaited
      // rejection here is a button that does nothing at all, which
      // is how the camera read as broken everywhere else before the
      // same guard went in.
      Alert.alert(
        'That could not be opened',
        'Your photos are not available right now. The pictures you have saved still work.',
      );
    }
  };

  const { height: screenHeight } = useWindowDimensions();

  /**
   * How far down the sheet has been pulled, in points.
   *
   * Two stops: nothing, and far enough that only the handle and the
   * search box are left. A sheet parked at an arbitrary height is
   * one somebody has to keep adjusting.
   */
  //
  // Both decisions live in `./drawer` rather than in the callbacks
  // below. A worklet body only runs under a real touch on a real
  // device, so anything decided inside one is untestable; lifted out,
  // the bounds and the two stops have a test and the gesture is left
  // holding nothing but the wiring.
  const peek = peekFor(screenHeight);
  const down = useSharedValue(0);
  const start = useSharedValue(0);

  const settle = (to: number) => {
    down.value = withTiming(to, { duration: Motion.base });
  };

  const drag = Gesture.Pan()
    .onStart(() => {
      start.value = down.value;
    })
    .onUpdate((event) => {
      down.value = dragTo(start.value, event.translationY, peek);
    })
    .onEnd((event) => {
      settle(settleTo(down.value, event.velocityY, peek));
    });

  const slide = useAnimatedStyle(() => ({
    transform: [{ translateY: down.value }],
  }));

  return (
    <Animated.View
      style={[
        {
          maxHeight: '70%',
          paddingTop: Spacing.two,
          paddingBottom: insets.bottom + Spacing.two,
          gap: Spacing.two,
          backgroundColor: colors.background,
          borderTopLeftRadius: Radius.lg,
          borderTopRightRadius: Radius.lg,
          borderCurve: 'continuous',
        },
        slide,
      ]}>
      {/* **The grab handle, which now actually grabs.**
          It was drawn to make the sheet "read as one" and had no
          gesture on it at all: the sheet covered the bottom seventy
          per cent of the canvas, the handle said it could be pulled
          out of the way, and it could not. The only ways on were to
          pick something or close the whole thing, so the lower half
          of a collage could not be seen while adding to it.

          Two stops rather than free movement. A sheet left at an
          arbitrary height is a sheet somebody has to keep adjusting;
          these are "showing the pictures" and "out of the way". */}
      <GestureDetector gesture={drag}>
        <View
          accessible
          accessibilityRole="adjustable"
          accessibilityLabel="Picture drawer"
          accessibilityHint="Drag down to see the canvas, up to see more pictures"
          accessibilityActions={[
            { name: 'increment', label: 'Show pictures' },
            { name: 'decrement', label: 'Move out of the way' },
          ]}
          onAccessibilityAction={(event) =>
            settle(event.nativeEvent.actionName === 'increment' ? 0 : peek)
          }
          // A thin bar is a small target; the padding is the part a
          // finger actually lands on.
          style={{ paddingVertical: Spacing.two, alignItems: 'center' }}>
          <View
            style={{
              width: 36,
              height: 4,
              borderRadius: Radius.full,
              backgroundColor: colors.border,
            }}
          />
        </View>
      </GestureDetector>

      {/* **A way out, which this sheet did not have.**

          `onClose` was accepted as a prop and never called: the only
          ways off the sheet were picking a picture or Android's
          hardware back, so on iOS somebody who opened it and changed
          their mind was stuck on the screen. The drag handle above
          moves the sheet aside but does not dismiss it, and a sheet
          moved aside still covers the controls underneath. */}
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingHorizontal: Spacing.three,
          paddingBottom: Spacing.one,
        }}>
        <ThemedText type="smallBold">Add pictures</ThemedText>
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Close"
          animateEntrance={false}
          hitSlop={Spacing.two}
          onPress={() => {
            void tapFeedback();
            onClose();
          }}
          style={{
            width: TapTarget,
            height: TapTarget,
            alignItems: 'center',
            justifyContent: 'center',
            marginRight: -Spacing.two,
          }}>
          <SymbolView
            name={{ ios: 'xmark', android: 'close', web: 'close' }}
            size={20}
            tintColor={colors.text}
          />
        </MotionPressable>
      </View>

      <View style={{ paddingHorizontal: Spacing.three }}>
        <TextInput
          value={query}
          onChangeText={setQuery}
          placeholder="Find pictures by tag"
          placeholderTextColor={colors.textSecondary}
          autoCapitalize="none"
          autoCorrect={false}
          accessibilityLabel="Find pictures by tag"
          style={{
            minHeight: TapTarget,
            paddingHorizontal: Spacing.three,
            borderRadius: Radius.full,
            borderWidth: 1,
            borderColor: colors.borderStrong,
            color: colors.text,
            fontSize: FontSize.subhead,
          }}
        />
      </View>

      <View
        style={{
          flexDirection: 'row',
          gap: Spacing.two,
          paddingHorizontal: Spacing.three,
        }}>
        <SourceTile
          label="Saved"
          icon={{ ios: 'bookmark', android: 'bookmark_border', web: 'bookmark' }}
          active={source === 'saved' && !query.trim()}
          onPress={() => {
            setQuery('');
            setSource('saved');
          }}
        />
        <SourceTile
          label="Boards"
          icon={{ ios: 'pin', android: 'push_pin', web: 'push_pin' }}
          active={source === 'boards' && !query.trim()}
          onPress={() => {
            setQuery('');
            setSource('boards');
          }}
        />
        <SourceTile
          label="Photos"
          icon={{ ios: 'photo.on.rectangle', android: 'image', web: 'image' }}
          onPress={() => void fromPhone()}
        />
      </View>

      {loading ? (
        <View
          style={{
            flexDirection: 'row',
            gap: Spacing.one,
            paddingHorizontal: Spacing.three,
          }}>
          <Skeleton width={96} height={128} radius={Radius.sm} />
          <Skeleton width={96} height={128} radius={Radius.sm} />
          <Skeleton width={96} height={128} radius={Radius.sm} />
        </View>
      ) : (
        <FlatList
          data={assetIds}
          keyExtractor={(assetId, index) => `${assetId}-${index}`}
          numColumns={3}
          automaticallyAdjustKeyboardInsets
          keyboardDismissMode="interactive"
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{
            paddingHorizontal: Spacing.three,
            gap: Spacing.one,
          }}
          columnWrapperStyle={{ gap: Spacing.one }}
          ListEmptyComponent={
            <ThemedText
              type="small"
              themeColor="textSecondary"
              style={{ fontSize: FontSize.footnote }}>
              {query.trim()
                ? 'Nothing under that tag.'
                : source === 'saved'
                  ? 'Keep a few fits and they show up here.'
                  : 'Pin some fits to a board and they show up here.'}
            </ThemedText>
          }
          renderItem={({ item }) => {
            const uri = images.data?.[item] ?? null;
            if (!uri) return null;
            return (
              <MotionPressable
                accessibilityRole="button"
                accessibilityLabel="Add this picture to your collage"
                animateEntrance={false}
                scale={0.95}
                onPress={() => {
                  void tapFeedback();
                  onPick(uri);
                }}
                style={{ flex: 1 / 3 }}>
                <Image
                  source={{ uri }}
                  contentFit="cover"
                  transition={ImageFade}
                  style={{
                    width: '100%',
                    aspectRatio: 3 / 4,
                    borderRadius: Radius.sm,
                    backgroundColor: colors.backgroundElement,
                  }}
                />
                <View
                  pointerEvents="none"
                  style={{
                    position: 'absolute',
                    right: Spacing.half,
                    bottom: Spacing.half,
                    width: 24,
                    height: 24,
                    alignItems: 'center',
                    justifyContent: 'center',
                    borderRadius: Radius.full,
                    backgroundColor: '#000000A6',
                  }}>
                  <SymbolView
                    name={{ ios: 'plus', android: 'add', web: 'add' }}
                    size={14}
                    tintColor="#FFFFFF"
                  />
                </View>
              </MotionPressable>
            );
          }}
        />
      )}
    </Animated.View>
  );
}

function SourceTile({
  label,
  icon,
  active,
  onPress,
}: {
  label: string;
  icon: SymbolViewProps['name'];
  active?: boolean;
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityState={{ selected: Boolean(active) }}
      accessibilityLabel={label}
      animateEntrance={false}
      scale={0.95}
      onPress={() => {
        void tapFeedback();
        onPress();
      }}
      style={{
        flex: 1,
        minHeight: TapTarget + Spacing.two,
        alignItems: 'center',
        justifyContent: 'center',
        gap: Spacing.half,
        borderRadius: Radius.md,
        borderCurve: 'continuous',
        backgroundColor: active ? colors.text : colors.backgroundElement,
      }}>
      <SymbolView
        name={icon}
        size={18}
        tintColor={active ? colors.background : colors.text}
      />
      <ThemedText
        type="small"
        style={{
          fontSize: FontSize.meta,
          color: active ? colors.background : colors.text,
        }}>
        {label}
      </ThemedText>
    </MotionPressable>
  );
}
