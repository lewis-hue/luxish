import { Image } from 'expo-image';
import { router } from 'expo-router';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { useState } from 'react';
import { Alert, Modal, Pressable, ScrollView, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import {
  AspectRatio,
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
} from '@/constants/theme';
import { SLOT_LABELS, categoryById } from '@/features/taxonomy/garments';
import type { Availability } from '@/features/wardrobe/sample';
import { StudioPanel } from '@/features/wardrobe/studio-panel';
import type { WardrobeEntry } from '@/features/wardrobe/store';
import { useScheme } from '@/hooks/use-theme';

/**
 * Availability, in the user's words and with the colour that reads at a
 * glance.
 *
 * Stored values are terse (`laundry`); the labels say what the state means
 * for the thing the user cares about — whether the stylist may reach for
 * it. Green is the only one that means yes, which is why it is the only
 * one that fills.
 */
const AVAILABILITY: readonly { id: Availability; label: string; dot: string }[] = [
  { id: 'available', label: 'Ready to wear', dot: '#4F7A3A' },
  { id: 'laundry', label: 'In the wash', dot: '#8A6D2F' },
  { id: 'unavailable', label: 'Unavailable', dot: '#9B2226' },
  { id: 'archived', label: 'Archived', dot: '#6B625C' },
];

/**
 * One garment, and everything you can do to it.
 *
 * A sheet rather than a screen: this is a decision taken *about the thing
 * you are looking at*, so navigating away loses the context that prompted
 * it and lands you somewhere you then have to come back from.
 */
export function GarmentSheet({
  entry,
  onClose,
  onRename,
  onSetAvailability,
  onDelete,
  onToggleFavourite,
  isFavourite,
}: {
  entry: WardrobeEntry | null;
  onClose: () => void;
  onRename: (id: string, name: string) => Promise<void>;
  onSetAvailability: (id: string, availability: Availability) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onToggleFavourite: (id: string) => Promise<void>;
  isFavourite: boolean;
}) {
  return (
    <Modal
      visible={entry !== null}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}>
      {entry ? (
        <Sheet
          // Keyed on the garment so the name field resets when a different
          // one is opened; without it the input keeps the previous value.
          key={entry.id}
          entry={entry}
          onClose={onClose}
          onRename={onRename}
          onSetAvailability={onSetAvailability}
          onDelete={onDelete}
          onToggleFavourite={onToggleFavourite}
          isFavourite={isFavourite}
        />
      ) : null}
    </Modal>
  );
}

function Sheet({
  entry,
  onClose,
  onRename,
  onSetAvailability,
  onDelete,
  onToggleFavourite,
  isFavourite,
}: {
  entry: WardrobeEntry;
  onClose: () => void;
  onRename: (id: string, name: string) => Promise<void>;
  onSetAvailability: (id: string, availability: Availability) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onToggleFavourite: (id: string) => Promise<void>;
  isFavourite: boolean;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const [name, setName] = useState(entry.name);

  // Saved on blur rather than on every keystroke: a rename is one edit, and
  // a write per character is a write per character.
  const commitName = () => {
    const cleaned = name.trim();
    if (cleaned && cleaned !== entry.name) void onRename(entry.id, cleaned);
    else if (!cleaned) setName(entry.name);
  };

  const confirmDelete = () => {
    Alert.alert(
      `Remove ${entry.name}?`,
      'It leaves your wardrobe and the stylist stops suggesting it.',
      [
        { text: 'Keep', style: 'cancel' },
        {
          text: 'Remove',
          style: 'destructive',
          onPress: () => {
            void onDelete(entry.id);
            onClose();
          },
        },
      ],
    );
  };

  const category = entry.categoryId ? categoryById(entry.categoryId) : undefined;
  const source = entry.image ?? (entry.uri ? { uri: entry.uri } : null);

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <ScrollView
        contentInsetAdjustmentBehavior="automatic"
        automaticallyAdjustKeyboardInsets
        keyboardDismissMode="interactive"
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{
          padding: Spacing.three,
          paddingBottom: insets.bottom + Spacing.five,
          gap: Spacing.four,
        }}
        showsVerticalScrollIndicator={false}>
        <View
          style={{
            borderRadius: Radius.lg,
            borderCurve: 'continuous',
            overflow: 'hidden',
            backgroundColor: colors.backgroundElement,
            aspectRatio: AspectRatio.garment,
          }}>
          {source ? (
            <Image
              source={source}
              placeholder={entry.thumbhash ? { thumbhash: entry.thumbhash } : undefined}
              contentFit="cover"
              transition={120}
              accessible
              accessibilityLabel={entry.name}
              style={{ width: '100%', height: '100%' }}
            />
          ) : null}
        </View>

        <View style={{ gap: Spacing.one }}>
          <Label>Name</Label>
          <TextInput
            value={name}
            onChangeText={setName}
            onBlur={commitName}
            onSubmitEditing={commitName}
            returnKeyType="done"
            accessibilityLabel="Garment name"
            placeholder="Name this garment"
            placeholderTextColor={colors.textSecondary}
            style={{
              minHeight: TapTarget,
              paddingHorizontal: Spacing.three,
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              backgroundColor: colors.backgroundElement,
              color: colors.text,
              fontSize: FontSize.body,
            }}
          />
        </View>

        <View style={{ gap: Spacing.one }}>
          <Label>Group</Label>
          <ThemedText type="small" themeColor="textSecondary">
            {SLOT_LABELS[entry.slot]}
            {category ? ` · ${category.label}` : ''}
          </ThemedText>
        </View>

        <View style={{ gap: Spacing.two }}>
          <Label>Availability</Label>
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ fontSize: FontSize.footnote }}>
            Anything not available is left out of suggestions.
          </ThemedText>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two }}>
            {AVAILABILITY.map((option) => {
              const active = entry.availability === option.id;
              return (
                <Pressable
                  key={option.id}
                  accessibilityRole="button"
                  accessibilityState={{ selected: active }}
                  accessibilityLabel={option.label}
                  onPress={() => void onSetAvailability(entry.id, option.id)}
                  style={({ pressed }) => ({
                    minHeight: TapTarget,
                    flexDirection: 'row',
                    alignItems: 'center',
                    gap: Spacing.two,
                    paddingHorizontal: Spacing.three,
                    borderRadius: Radius.full,
                    borderWidth: 1,
                    borderColor: active ? option.dot : colors.border,
                    backgroundColor: active ? option.dot : 'transparent',
                    opacity: pressed ? 0.7 : 1,
                  })}>
                  {/* The dot carries the state's colour on the unselected
                      chips, where the fill cannot. */}
                  {!active ? (
                    <View
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: Radius.full,
                        backgroundColor: option.dot,
                      }}
                    />
                  ) : null}
                  <ThemedText
                    type="small"
                    style={{ color: active ? '#FFFFFF' : colors.text }}>
                    {option.label}
                  </ThemedText>
                </Pressable>
              );
            })}
          </View>
        </View>

        {/* The studio, on the page it acts on.

            A treatment edits this garment's stored photograph, so the
            place to ask for one is the page showing that photograph.
            Reachable only through the stylist, it was invisible to
            anybody who did not think to ask for it in words.

            Needs the garment on the server: the studio edits the
            *stored* picture, and one still uploading has none. */}
        {entry.serverId ? <StudioPanel garmentId={entry.serverId} /> : null}

        {/* One row of verbs, not a column of explanations.

            This was three stacked bordered cards, each with a bold title
            and a line or two of prose, which put more reading at the
            bottom of the sheet than there was anywhere else on it — under
            a photograph of the very thing being described. A glyph and one
            word is what a board app shows here, and it is right: these are
            actions on something already in front of you, so the picture is
            the context and the label only has to name the verb.

            Remove sits in the row rather than hiding in a menu. It is in
            the danger colour and it confirms before it acts, which is the
            guard that actually matters. */}
        <View style={{ flexDirection: 'row', gap: Spacing.two }}>
          <SheetAction
            label="Favourite"
            hint="Favourites are weighted when the stylist builds an outfit."
            icon={{
              ios: isFavourite ? 'heart.fill' : 'heart',
              android: isFavourite ? 'favorite' : 'favorite_border',
              web: 'favorite',
            }}
            active={isFavourite}
            onPress={() => void onToggleFavourite(entry.id)}
          />
          {/* Hands the piece to the stylist with it already attached.

              For the things a sentence does better than a button:
              styling an outfit around it, or asking for a set of brand
              visuals. The four fixed treatments are above, where they
              act on the picture in view. */}
          {entry.serverId ? (
            <SheetAction
              label="Stylist"
              hint="Ask about this piece, or build an outfit around it."
              icon={{ ios: 'sparkles', android: 'auto_awesome', web: 'auto_awesome' }}
              onPress={() => {
                onClose();
                router.push({
                  // The assistant lives on the wardrobe tab now, and
                  // `(tabs)` is a route group that never appears in
                  // a path - so this resolved to nothing twice over
                  // and the row did nothing at all.
                  pathname: '/wardrobe',
                  params: { garment: entry.serverId as string },
                });
              }}
            />
          ) : null}
          {!entry.isSample ? (
            <SheetAction
              label="Remove"
              hint="Takes this garment out of your wardrobe."
              icon={{ ios: 'trash', android: 'delete', web: 'delete' }}
              destructive
              onPress={confirmDelete}
            />
          ) : null}
        </View>
      </ScrollView>
    </View>
  );
}

/** A field's name. Small, quiet, and the same on every row. */
function Label({ children }: { children: React.ReactNode }) {
  return (
    <ThemedText type="label" themeColor="textSecondary">
      {children}
    </ThemedText>
  );
}

/**
 * One action, as a glyph over a word.
 *
 * **No description.** These sit under a photograph of the garment they act
 * on, so the context is already on screen and a sentence explaining the
 * button is the heaviest thing in the sheet. What the explanations said is
 * now `accessibilityHint`, which a screen reader announces after the label
 * — available to anyone who needs it, occupying nothing.
 *
 * Favourite fills when it is on, which is the one piece of state in the
 * row; the others are plain verbs.
 */
function SheetAction({
  label,
  hint,
  icon,
  onPress,
  active,
  destructive,
}: {
  label: string;
  hint?: string;
  icon: SymbolViewProps['name'];
  onPress: () => void;
  active?: boolean;
  destructive?: boolean;
}) {
  const colors = Colors[useScheme()];
  const tint = destructive
    ? colors.danger
    : active
      ? colors.accentText
      : colors.text;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={hint}
      accessibilityState={{ selected: active }}
      onPress={onPress}
      style={({ pressed }) => ({
        flex: 1,
        minHeight: 72,
        alignItems: 'center',
        justifyContent: 'center',
        gap: Spacing.one,
        paddingHorizontal: Spacing.two,
        borderRadius: Radius.md,
        borderCurve: 'continuous',
        borderWidth: 1,
        borderColor: destructive
          ? colors.danger
          : active
            ? colors.accent
            : colors.border,
        backgroundColor: active && !destructive ? colors.accent : 'transparent',
        opacity: pressed ? 0.7 : 1,
      })}>
      <SymbolView name={icon} size={22} tintColor={tint} />
      <ThemedText type="small" numberOfLines={1} style={{ color: tint }}>
        {label}
      </ThemedText>
    </Pressable>
  );
}
