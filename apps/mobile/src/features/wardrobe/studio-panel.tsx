import { Image } from 'expo-image';
import { SymbolView } from 'expo-symbols';
import { useState } from 'react';
import { Alert, Modal, Pressable, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  shotLine,
  useDiscardShot,
  useRequestShot,
  useShotImages,
  useShots,
  useTreatments,
  type Shot,
} from '@/api/queries/garment-studio';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, successFeedback, tapFeedback } from '@/components/ui/motion';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
} from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/**
 * The studio, on the garment's own page.
 *
 * **Here, because this is what it acts on.** A treatment edits *this
 * garment's stored photograph*, so the place to ask for one is the page
 * showing that photograph. It was briefly only reachable by talking to
 * the stylist, which is fine for somebody who thinks to ask and
 * invisible to everybody else.
 *
 * **What it produces, kept under what produced it.** A shot appears in
 * the strip as it is taken, so the answer lands where the question was
 * asked rather than on another screen.
 *
 * **Offered only once the garment is on the server.** The studio edits
 * the stored photograph; a garment still uploading has none, and a
 * button that cannot work yet is worse than no button.
 */
export function StudioPanel({ garmentId }: { garmentId: string }) {
  const colors = Colors[useScheme()];
  const treatments = useTreatments(true);
  const shots = useShots(garmentId, true);
  const request = useRequestShot(garmentId);
  const list = shots.data ?? [];
  const images = useShotImages(list);
  const [viewing, setViewing] = useState<Shot | null>(null);

  const working = list.filter(
    (shot) => shot.state === 'queued' || shot.state === 'running',
  );
  const available = treatments.data?.items ?? [];

  return (
    <View style={{ gap: Spacing.two }}>
      <View
        style={{ flexDirection: 'row', alignItems: 'center', gap: Spacing.one }}>
        <ThemedText type="label" themeColor="textSecondary">
          Studio
        </ThemedText>
        {working.length > 0 ? (
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ fontSize: FontSize.meta }}>
            {working.length === 1 ? 'taking one' : `taking ${working.length}`}
          </ThemedText>
        ) : null}
      </View>

      {/* What it can do, as four verbs rather than a paragraph each.

          The hint is the accessibility description rather than visible
          text: four treatments with a line of prose under each turns
          the bottom of this sheet into more reading than anywhere else
          in the app, under a photograph of the thing being described. */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ gap: Spacing.one, paddingRight: Spacing.three }}>
        {available.map((treatment) => {
          const busy = working.some((shot) => shot.treatment === treatment.id);
          return (
            <MotionPressable
              key={treatment.id}
              accessibilityRole="button"
              accessibilityLabel={treatment.label}
              accessibilityHint={treatment.description}
              accessibilityState={{ busy, disabled: busy }}
              disabled={busy}
              animateEntrance={false}
              scale={0.95}
              onPress={() => {
                void tapFeedback();
                request.mutate(treatment.id, {
                  onSuccess: () => void successFeedback(),
                  onError: () =>
                    Alert.alert(
                      'Could not start that',
                      'Try again in a moment.',
                    ),
                });
              }}
              style={{
                minHeight: 36,
                justifyContent: 'center',
                paddingHorizontal: Spacing.three,
                borderRadius: Radius.full,
                borderWidth: 1,
                borderColor: colors.border,
                opacity: busy ? 0.5 : 1,
              }}>
              <ThemedText type="small" style={{ fontSize: FontSize.footnote }}>
                {busy ? 'Taking' : treatment.label}
              </ThemedText>
            </MotionPressable>
          );
        })}
      </ScrollView>

      {/* Said once, under the controls, because it decides what the
          results look like and somebody will otherwise wonder why the
          model is a stranger. */}
      {treatments.data?.note ? (
        <ThemedText
          type="small"
          themeColor="textSecondary"
          style={{ fontSize: FontSize.meta }}>
          {treatments.data.note}
        </ThemedText>
      ) : null}

      {list.length > 0 ? (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ gap: Spacing.two, paddingRight: Spacing.three }}>
          {list.map((shot) => (
            <ShotThumb
              key={shot.id}
              shot={shot}
              uri={images.data?.[shot.id] ?? null}
              label={shotLine(shot, available)}
              onPress={() => {
                if (shot.state !== 'ready') return;
                void tapFeedback();
                setViewing(shot);
              }}
            />
          ))}
        </ScrollView>
      ) : null}

      <ShotViewer
        shot={viewing}
        uri={viewing ? (images.data?.[viewing.id] ?? null) : null}
        label={viewing ? shotLine(viewing, available) : ''}
        garmentId={garmentId}
        onClose={() => setViewing(null)}
      />
    </View>
  );
}

/** One shot, at strip size, in whatever state it is in. */
function ShotThumb({
  shot,
  uri,
  label,
  onPress,
}: {
  shot: Shot;
  uri: string | null;
  label: string;
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];

  if (shot.state === 'queued' || shot.state === 'running') {
    return <Skeleton width={72} height={96} radius={Radius.sm} label={label} />;
  }

  if (shot.state === 'failed' || !uri) {
    return (
      <View
        accessible
        accessibilityLabel={label}
        style={{
          width: 72,
          height: 96,
          alignItems: 'center',
          justifyContent: 'center',
          padding: Spacing.one,
          borderRadius: Radius.sm,
          borderWidth: 1,
          borderColor: colors.border,
        }}>
        <SymbolView
          name={{ ios: 'exclamationmark', android: 'error', web: 'error' }}
          size={16}
          tintColor={colors.textSecondary}
        />
        <ThemedText
          type="small"
          themeColor="textSecondary"
          numberOfLines={2}
          style={{ fontSize: FontSize.meta, textAlign: 'center' }}>
          Did not come back
        </ThemedText>
      </View>
    );
  }

  return (
    <MotionPressable
      accessibilityRole="imagebutton"
      accessibilityLabel={label}
      animateEntrance={false}
      scale={0.95}
      onPress={onPress}>
      <Image
        source={{ uri }}
        contentFit="cover"
        transition={140}
        style={{
          width: 72,
          height: 96,
          borderRadius: Radius.sm,
          backgroundColor: colors.backgroundElement,
        }}
      />
    </MotionPressable>
  );
}

/**
 * One shot, full size, with the one thing to do about it.
 *
 * Discarding lives here rather than on the thumbnail: a strip of
 * pictures each carrying a delete control is a strip somebody deletes
 * from by accident.
 */
function ShotViewer({
  shot,
  uri,
  label,
  garmentId,
  onClose,
}: {
  shot: Shot | null;
  uri: string | null;
  label: string;
  garmentId: string;
  onClose: () => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const discard = useDiscardShot(garmentId);

  if (!shot) return null;

  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Close"
        onPress={onClose}
        style={{
          flex: 1,
          justifyContent: 'center',
          padding: Spacing.three,
          paddingBottom: insets.bottom + Spacing.three,
          backgroundColor: '#000000D9',
          gap: Spacing.three,
        }}>
        {uri ? (
          <Image
            source={{ uri }}
            contentFit="contain"
            transition={160}
            accessible
            accessibilityLabel={label}
            style={{ width: '100%', flex: 1, borderRadius: Radius.md }}
          />
        ) : null}

        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            gap: Spacing.two,
          }}>
          <ThemedText
            type="small"
            numberOfLines={1}
            style={{ flex: 1, color: '#FFFFFF' }}>
            {label}
          </ThemedText>
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Discard this shot"
            animateEntrance={false}
            scale={0.95}
            onPress={() => {
              void tapFeedback();
              Alert.alert(
                'Discard this shot?',
                'The garment and its photograph are not affected.',
                [
                  { text: 'Keep', style: 'cancel' },
                  {
                    text: 'Discard',
                    style: 'destructive',
                    onPress: () => {
                      discard.mutate(shot.id);
                      onClose();
                    },
                  },
                ],
              );
            }}
            style={{
              minHeight: TapTarget,
              justifyContent: 'center',
              paddingHorizontal: Spacing.three,
              borderRadius: Radius.full,
              backgroundColor: colors.danger,
            }}>
            <ThemedText type="small" style={{ color: '#FFFFFF' }}>
              Discard
            </ThemedText>
          </MotionPressable>
        </View>
      </Pressable>
    </Modal>
  );
}
