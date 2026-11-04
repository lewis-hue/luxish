import { router } from 'expo-router';
import { FlatList, Modal, Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import { Colors, FontSize, Radius, Spacing, labelType } from '@/constants/theme';
import type { FeedFit } from '@/api/queries/discover-feed';
import { FitCard } from '@/features/feed/fit-card';
import { useScheme } from '@/hooks/use-theme';

/**
 * What the camera found, as a sheet over the search screen.
 *
 * **It used to be an alert and a redirect.** A picture whose tags
 * matched something jumped straight to that tag's page, losing both
 * the photograph and every other reading; a picture whose tags
 * matched nothing produced "Nothing to go on" and left the person
 * exactly where they started. Neither is an answer to "find me
 * things like this".
 *
 * **Two bands, labelled, never merged.** The close band is pins
 * actually tagged with what was seen. The loose band is the nearest
 * pins by what they are *of* - the instruction's own example, where
 * a photograph of a palm finds the pins with hands and hand
 * accessories in them. Presenting those as exact matches would make
 * the app look wrong rather than helpful, so they sit under their
 * own heading saying what they are.
 *
 * A sheet rather than a page because the search screen is still the
 * thing underneath: dismissing it puts somebody back where they
 * were, with their query intact.
 */
export function PictureResults({
  result,
  onClose,
}: {
  result: {
    outfit: string;
    subject: string;
    close: FeedFit[];
    loosely: FeedFit[];
  } | null;
  onClose: () => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  if (!result) return null;

  const { close, loosely } = result;
  const nothing = close.length === 0 && loosely.length === 0;

  // One list, two sections, so the whole sheet scrolls as one thing.
  const heading = (key: string, text: string, note?: string): Row => ({
    kind: 'heading',
    key,
    text,
    note,
  });
  const tile = (pin: FeedFit): Row => ({ kind: 'pin', key: pin.id, pin });

  const rows: Row[] = [
    ...(close.length
      ? [heading('h-close', 'Matching your picture'), ...close.map(tile)]
      : []),
    ...(loosely.length
      ? [
          heading(
            'h-loose',
            close.length ? 'Also close to it' : 'Closest to your picture',
            // Said plainly rather than left to be inferred from the
            // ordering, which nobody reads as a claim about accuracy.
            'Not exact. These are the nearest things here.',
          ),
          ...loosely.map(tile),
        ]
      : []),
  ];

  return (
    <Modal visible transparent animationType="slide" statusBarTranslucent>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Close the results"
        onPress={onClose}
        style={{ flex: 1, backgroundColor: colors.scrim }}
      />
      <View
        style={{
          maxHeight: '82%',
          backgroundColor: colors.background,
          borderTopLeftRadius: Radius.lg,
          borderTopRightRadius: Radius.lg,
          borderCurve: 'continuous',
          paddingTop: Spacing.two,
        }}>
        {/* The grabber. The sheet is dismissed by tapping the scrim,
            and without this it does not look dismissible at all. */}
        <View
          style={{
            alignSelf: 'center',
            width: 36,
            height: 4,
            borderRadius: 2,
            backgroundColor: colors.border,
            marginBottom: Spacing.two,
          }}
        />

        <View
          style={{
            paddingHorizontal: Spacing.three,
            paddingBottom: Spacing.two,
            gap: Spacing.half,
          }}>
          <ThemedText accessibilityRole="header" style={labelType(22, 800)}>
            {nothing ? 'Nothing like it here yet' : 'What I found'}
          </ThemedText>
          {/* What it thought it saw. The answer explains itself
              rather than only jumping somewhere, which is also how
              somebody tells a wrong reading from a thin board. */}
          {result.outfit ? (
            <ThemedText
              type="small"
              themeColor="textSecondary"
              numberOfLines={2}
              style={{ fontSize: FontSize.footnote }}>
              {`I saw: ${result.outfit}`}
            </ThemedText>
          ) : null}
        </View>

        {nothing ? (
          <View style={{ padding: Spacing.three, gap: Spacing.one }}>
            <ThemedText type="small" themeColor="textSecondary">
              Nobody has posted anything close to that yet. Try a wider
              shot, or search the words instead.
            </ThemedText>
          </View>
        ) : (
          <FlatList
            data={rows}
            keyExtractor={(row) => row.key}
            numColumns={1}
            contentContainerStyle={{
              paddingHorizontal: Spacing.three,
              paddingBottom: insets.bottom + Spacing.five,
              gap: Spacing.two,
            }}
            showsVerticalScrollIndicator={false}
            renderItem={({ item }) =>
              item.kind === 'heading' ? (
                <View style={{ gap: Spacing.half, paddingTop: Spacing.one }}>
                  <ThemedText type="smallBold">{item.text}</ThemedText>
                  {item.note ? (
                    <ThemedText
                      type="small"
                      themeColor="textSecondary"
                      style={{ fontSize: FontSize.meta }}>
                      {item.note}
                    </ThemedText>
                  ) : null}
                </View>
              ) : (
                <FitCard
                  fit={item.pin}
                  onOpen={() => {
                    onClose();
                    router.push({
                      pathname: '/fit/[id]',
                      params: { id: item.pin.id },
                    });
                  }}
                />
              )
            }
          />
        )}
      </View>
    </Modal>
  );
}

type Row =
  | { kind: 'heading'; key: string; text: string; note?: string }
  | { kind: 'pin'; key: string; pin: FeedFit };
