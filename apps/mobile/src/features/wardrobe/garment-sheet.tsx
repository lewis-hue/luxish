import { Image } from 'expo-image';
import { useState } from 'react';
import { Alert, Modal, Pressable, ScrollView, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import {
  AspectRatio,
  Colors,
  Display,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  Tracking,
  toneColor,
} from '@/constants/theme';
import {
  AVAILABILITY_LABEL,
  AVAILABILITY_TONE,
  type Availability,
} from '@/features/wardrobe/sample';
import type { WardrobeEntry } from '@/features/wardrobe/store';
import { SLOT_LABELS, categoryById } from '@/features/taxonomy';
import { useScheme } from '@/hooks/use-theme';

/**
 * One garment: rename it, mark it loved, say it is in the wash, or remove it.
 *
 * A bottom sheet rather than a pushed screen, because every action here is quick and
 * the user's place in the grid is worth preserving.
 *
 * Renaming is the important one. Auto-categorisation will be wrong sometimes, and a
 * wardrobe you cannot correct becomes a wardrobe you stop trusting — so the name
 * field is the first thing in the sheet, not buried behind an edit mode. The
 * correction is stored as a *confirmed* value, which outranks anything a model
 * later infers (ADR-010).
 */

const AVAILABILITY_OPTIONS: readonly Availability[] = [
  'available',
  'laundry',
  'unavailable',
  'archived',
];

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
  if (!entry) return null;

  // Keyed by id so opening a different garment remounts the body with fresh state.
  // Resetting the name field from an effect instead would work, but costs a second
  // render on every open and shows the previous garment's name for a frame.
  return (
    <GarmentSheetBody
      key={entry.id}
      entry={entry}
      onClose={onClose}
      onRename={onRename}
      onSetAvailability={onSetAvailability}
      onDelete={onDelete}
      onToggleFavourite={onToggleFavourite}
      isFavourite={isFavourite}
    />
  );
}

function GarmentSheetBody({
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

  const category = entry.categoryId ? categoryById(entry.categoryId) : undefined;
  const commitName = () => {
    if (name.trim() && name.trim() !== entry.name) void onRename(entry.id, name);
  };

  const confirmDelete = () => {
    Alert.alert(
      `Remove ${entry.name}?`,
      'This takes it out of your wardrobe. The stylist will stop suggesting it.',
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

  return (
    <Modal
      visible
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <ScrollView
          contentContainerStyle={{
            padding: Spacing.three,
            paddingBottom: insets.bottom + Spacing.five,
            gap: Spacing.four,
          }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
            <ThemedText style={{ fontFamily: Display.regular, fontSize: 26, lineHeight: 30 }}>
              {entry.isSample ? 'Sample item' : 'Your item'}
            </ThemedText>
            <Pressable accessibilityRole="button" onPress={onClose} hitSlop={10}>
              <ThemedText type="smallBold" style={{ color: colors.accent }}>
                Done
              </ThemedText>
            </Pressable>
          </View>

          <View
            style={{
              borderRadius: Radius.lg,
              borderCurve: 'continuous',
              overflow: 'hidden',
              backgroundColor: colors.backgroundElement,
            }}>
            <Image
              source={entry.image ?? (entry.uri ? { uri: entry.uri } : undefined)}
              placeholder={entry.blurhash ? { blurhash: entry.blurhash } : undefined}
              contentFit="cover"
              cachePolicy="memory-disk"
              accessibilityLabel={entry.name}
              style={{ width: '100%', aspectRatio: AspectRatio.garment }}
            />
          </View>

          {/* Name first: this is the correction path, and it has to be obvious. */}
          <View style={{ gap: Spacing.two }}>
            <Label>Name</Label>
            <TextInput
              value={name}
              onChangeText={setName}
              onBlur={commitName}
              onSubmitEditing={commitName}
              editable={!entry.isSample}
              returnKeyType="done"
              accessibilityLabel="Garment name"
              style={{
                minHeight: 48,
                paddingHorizontal: Spacing.three,
                borderRadius: Radius.md,
                borderCurve: 'continuous',
                borderWidth: 1,
                borderColor: colors.border,
                backgroundColor: colors.backgroundElement,
                color: entry.isSample ? colors.textSecondary : colors.text,
                fontSize: 16,
              }}
            />
            {entry.isSample ? (
              <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: FontSize.caption }}>
                Sample items cannot be edited. Add your own photo to make it yours.
              </ThemedText>
            ) : null}
          </View>

          <View style={{ gap: Spacing.two }}>
            <Label>Group</Label>
            <ThemedText type="small" themeColor="textSecondary">
              {SLOT_LABELS[entry.slot]}
              {category ? ` · ${category.label}` : ''}
              {entry.status === 'pending' ? ' · sorting…' : ''}
            </ThemedText>
          </View>

          <View style={{ gap: Spacing.two }}>
            <Label>Availability</Label>
            <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: FontSize.caption }}>
              Anything not available is left out of suggestions.
            </ThemedText>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two }}>
              {AVAILABILITY_OPTIONS.map((option) => {
                const active = entry.availability === option;
                const tone = toneColor(colors, AVAILABILITY_TONE[option]);
                return (
                  <Pressable
                    key={option}
                    accessibilityRole="button"
                    accessibilityState={{ selected: active, disabled: entry.isSample }}
                    disabled={entry.isSample}
                    onPress={() => void onSetAvailability(entry.id, option)}
                    style={({ pressed }) => ({
                      minHeight: TapTarget,
                      flexDirection: 'row',
                      alignItems: 'center',
                      gap: Spacing.two,
                      paddingHorizontal: Spacing.three,
                      borderRadius: Radius.full,
                      // Selected fills with the state's own colour, so the
                      // chip says what it means rather than only that it is
                      // chosen. Unselected uses `borderStrong`, because an
                      // outlined control is bounded by its border and the
                      // faint hairline is 1.32:1, under WCAG 1.4.11's 3:1.
                      backgroundColor: active ? tone : 'transparent',
                      borderWidth: 1,
                      borderColor: active ? tone : colors.borderStrong,
                      opacity: entry.isSample ? 0.4 : pressed ? 0.6 : 1,
                    })}>
                    {!active ? (
                      // The dot keeps the meaning visible when the chip is not
                      // filled, so colour is never the only signal.
                      <View
                        style={{
                          width: 6,
                          height: 6,
                          borderRadius: Radius.full,
                          backgroundColor: tone,
                        }}
                      />
                    ) : null}
                    <ThemedText
                      type="small"
                      style={{
                        fontSize: FontSize.footnote,
                        color: active ? '#FFFFFF' : colors.textSecondary,
                      }}>
                      {AVAILABILITY_LABEL[option] ?? 'Ready to wear'}
                    </ThemedText>
                  </Pressable>
                );
              })}
            </View>
          </View>

          <View style={{ gap: Spacing.two }}>
            <SheetAction
              label={isFavourite ? 'One of your favourites' : 'Add to favourites'}
              detail="Favourites are weighted when the stylist builds an outfit."
              active={isFavourite}
              onPress={() => void onToggleFavourite(entry.id)}
            />
            {!entry.isSample ? (
              <SheetAction label="Remove from wardrobe" destructive onPress={confirmDelete} />
            ) : null}
          </View>
        </ScrollView>
      </View>
    </Modal>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <ThemedText
      type="small"
      themeColor="textSecondary"
      style={{
        fontSize: FontSize.meta,
        letterSpacing: Tracking.wide,
        textTransform: 'uppercase',
      }}>
      {children}
    </ThemedText>
  );
}

function SheetAction({
  label,
  detail,
  onPress,
  active,
  destructive,
}: {
  label: string;
  detail?: string;
  onPress: () => void;
  active?: boolean;
  destructive?: boolean;
}) {
  const colors = Colors[useScheme()];
  const tint = destructive ? colors.danger : active ? colors.accent : colors.text;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      onPress={onPress}
      style={({ pressed }) => ({
        minHeight: 50,
        justifyContent: 'center',
        paddingHorizontal: Spacing.three,
        borderRadius: Radius.md,
        borderCurve: 'continuous',
        borderWidth: 1,
        borderColor: destructive ? colors.danger : active ? colors.accent : colors.border,
        backgroundColor: active && !destructive ? colors.accent : 'transparent',
        opacity: pressed ? 0.7 : 1,
        gap: 2,
      })}>
      <ThemedText
        type="smallBold"
        style={{ color: active && !destructive ? colors.accentText : tint }}>
        {label}
      </ThemedText>
      {detail ? (
        <ThemedText
          type="small"
          style={{
            fontSize: 11,
            color: active && !destructive ? colors.accentText : colors.textSecondary,
          }}>
          {detail}
        </ThemedText>
      ) : null}
    </Pressable>
  );
}
