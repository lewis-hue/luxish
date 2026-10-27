import { Image } from 'expo-image';
import * as Haptics from 'expo-haptics';
import { LinearGradient } from 'expo-linear-gradient';
import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useEffect } from 'react';
import { Platform, Pressable, ScrollView, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ThemedText } from '@/components/themed-text';
import { EmptyState } from '@/components/ui/empty-state';
import { Colors, Display, Motion, Radius, Spacing } from '@/constants/theme';
import { recordInteraction } from '@/features/discover/interactions';
import { lookById, ownedCount, type Look } from '@/features/discover/looks';
import { useSavedLooks } from '@/features/discover/saved';
import { webSearchUrlForDescription } from '@/features/discover/visual-search';
import {
  SLOT_LABELS,
  aestheticById,
  dressCodeById,
  explainAesthetic,
  piecesBySlot,
  type OutfitPiece,
} from '@/features/taxonomy';
import { useScheme } from '@/hooks/use-theme';
import * as Linking from 'expo-linking';

/**
 * One look, broken into the pieces that make it.
 *
 * The pieces are the point. "Streetwear" is not actionable; "boxy graphic tee, wide
 * cargos, chunky trainers, bomber" is something you can look for in your own
 * wardrobe or search for. So the screen leads with the photograph and then spends
 * the rest of its space on what the outfit is actually made of.
 *
 * Every piece says plainly whether the user owns it, because that is the difference
 * between "wear this tonight" and "this costs money" — and a styling app that blurs
 * the two is not trustworthy.
 */
export default function LookDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const saved = useSavedLooks();

  const look = id ? lookById(id) : undefined;

  // Fire-and-forget: a tap must never wait on analytics.
  useEffect(() => {
    if (look) void recordInteraction(look.id, 'view', look.aesthetics);
  }, [look]);

  if (!look) {
    return (
      <>
        <Stack.Screen options={{ title: 'Look' }} />
        <EmptyState
          status="empty"
          title="That look is not here"
          body="It may have been removed from the collection."
          action={{ label: 'Back to Discover', onPress: () => router.back() }}
        />
      </>
    );
  }

  const owned = ownedCount(look);
  const dressCode = dressCodeById(look.dressCode);
  const groups = piecesBySlot(look.pieces);
  const isSaved = saved.has(look.id);

  return (
    <>
      <Stack.Screen options={{ title: look.title, headerTransparent: true }} />
      <ScrollView
        style={{ backgroundColor: colors.background }}
        contentContainerStyle={{ paddingBottom: insets.bottom + Spacing.six }}
        showsVerticalScrollIndicator={false}>
        {/* Full-bleed cover: this is a fashion app, the photograph leads. */}
        <View style={{ width, aspectRatio: 4 / 5 }}>
          {look.cover ? (
            <Image
              source={look.cover.localSource ?? { uri: look.cover.uri }}
              placeholder={
                look.cover.blurhash ? { blurhash: look.cover.blurhash } : undefined
              }
              cachePolicy="memory-disk"
              contentFit="cover"
              transition={Motion.base}
              accessibilityLabel={look.cover.alt}
              style={{ width: '100%', height: '100%' }}
            />
          ) : (
            <View style={{ flex: 1, backgroundColor: colors.backgroundSelected }} />
          )}
          <LinearGradient
            colors={['transparent', 'rgba(16,12,11,0.85)']}
            locations={[0.5, 1]}
            pointerEvents="none"
            style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: '55%' }}
          />
          <View style={{ position: 'absolute', left: 0, right: 0, bottom: 0, padding: Spacing.four }}>
            <ThemedText
              style={{
                fontFamily: Display.regular,
                fontSize: 38,
                lineHeight: 42,
                color: '#FFFFFF',
              }}>
              {look.title}
            </ThemedText>
          </View>
        </View>

        <View style={{ padding: Spacing.three, gap: Spacing.four }}>
          {/* Aesthetics, each explained by the evidence that produced it. An
              unexplained tag is not useful and cannot be argued with. */}
          <View style={{ gap: Spacing.two }}>
            <SectionLabel>Why this reads the way it does</SectionLabel>
            <View style={{ gap: Spacing.two }}>
              {look.aesthetics.map((aestheticId) => {
                const aesthetic = aestheticById(aestheticId);
                if (!aesthetic) return null;
                return (
                  <View
                    key={aestheticId}
                    style={{
                      padding: Spacing.three,
                      borderRadius: Radius.md,
                      borderCurve: 'continuous',
                      backgroundColor: colors.backgroundElement,
                      gap: Spacing.one,
                    }}>
                    <ThemedText type="smallBold" style={{ color: colors.accent }}>
                      {aesthetic.label}
                    </ThemedText>
                    <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: 13 }}>
                      {explainAesthetic(aesthetic, look.styleEvidence).replace(
                        `${aesthetic.label} — `,
                        '',
                      )}
                    </ThemedText>
                  </View>
                );
              })}
            </View>
          </View>

          {/* Dress code and occasion are separate axes from aesthetic. */}
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two }}>
            {dressCode ? <Chip label={dressCode.label} /> : null}
            {look.occasions.map((occasion) => (
              <Chip key={occasion} label={occasion} muted />
            ))}
          </View>

          {/* The pieces. */}
          <View style={{ gap: Spacing.three }}>
            <View style={{ gap: Spacing.half }}>
              <SectionLabel>The pieces</SectionLabel>
              <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: 13 }}>
                {owned > 0
                  ? `You already own ${owned} of ${look.pieces.length}.`
                  : `${look.pieces.length} pieces. None are in your wardrobe yet.`}
              </ThemedText>
            </View>

            {groups.map((group) => (
              <View key={group.slot} style={{ gap: Spacing.two }}>
                <ThemedText
                  type="small"
                  themeColor="textSecondary"
                  style={{ fontSize: 11, letterSpacing: 1.2, textTransform: 'uppercase' }}>
                  {SLOT_LABELS[group.slot]}
                </ThemedText>
                {group.pieces.map((piece) => (
                  <PieceRow key={piece.id} piece={piece} look={look} />
                ))}
              </View>
            ))}
          </View>

          {/* Actions. */}
          <View style={{ gap: Spacing.two }}>
            <ActionButton
              label={isSaved ? 'Saved to your inspiration' : 'Save for inspiration'}
              active={isSaved}
              onPress={() => {
                if (Platform.OS !== 'web') void Haptics.selectionAsync();
                void saved.toggle(look.id);
                if (!isSaved) void recordInteraction(look.id, 'save', look.aesthetics);
              }}
            />
            <ActionButton
              label="Ask the stylist about this look"
              onPress={() => {
                void recordInteraction(look.id, 'ask_stylist', look.aesthetics);
                router.push('/(tabs)/stylist');
              }}
            />
          </View>

          {/* Disclosure, moved here from the grid where it repeated on every card. */}
          {look.isGenerated ? (
            <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: 11 }}>
              This image was generated, not photographed. The pieces are real garment
              types you can look for.
            </ThemedText>
          ) : null}
        </View>
      </ScrollView>
    </>
  );
}

function PieceRow({ piece, look }: { piece: OutfitPiece; look: Look }) {
  const colors = Colors[useScheme()];

  const search = () => {
    if (Platform.OS !== 'web') void Haptics.selectionAsync();
    // Searching for a piece is a much stronger signal than opening the look.
    void recordInteraction(look.id, 'search_piece', look.aesthetics);
    void Linking.openURL(
      webSearchUrlForDescription({
        name: piece.name,
        colour: piece.colour,
        category: piece.categoryId,
      }),
    );
  };

  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.three,
        padding: Spacing.two,
        borderRadius: Radius.md,
        borderCurve: 'continuous',
        backgroundColor: colors.backgroundElement,
      }}>
      <View
        style={{
          width: 52,
          height: 52,
          borderRadius: Radius.sm,
          borderCurve: 'continuous',
          overflow: 'hidden',
          backgroundColor: colors.backgroundSelected,
        }}>
        {piece.image ? (
          <Image
            source={piece.image}
            placeholder={piece.blurhash ? { blurhash: piece.blurhash } : undefined}
            contentFit="cover"
            cachePolicy="memory-disk"
            accessible={false}
            style={{ width: '100%', height: '100%' }}
          />
        ) : null}
      </View>

      <View style={{ flex: 1, gap: 2 }}>
        <ThemedText type="small" numberOfLines={1}>
          {piece.name}
        </ThemedText>
        <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: 12 }}>
          {piece.owned ? 'In your wardrobe' : 'Not in your wardrobe'}
        </ThemedText>
      </View>

      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`Search the web for ${piece.name}`}
        onPress={search}
        hitSlop={8}
        style={({ pressed }) => ({
          paddingHorizontal: Spacing.three,
          paddingVertical: Spacing.two,
          borderRadius: Radius.full,
          borderWidth: 1,
          borderColor: colors.border,
          opacity: pressed ? 0.6 : 1,
        })}>
        <ThemedText type="small" style={{ fontSize: 12, color: colors.accent }}>
          Find
        </ThemedText>
      </Pressable>
    </View>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <ThemedText
      type="small"
      themeColor="textSecondary"
      style={{ fontSize: 11, letterSpacing: 1.4, textTransform: 'uppercase' }}>
      {children}
    </ThemedText>
  );
}

function Chip({ label, muted }: { label: string; muted?: boolean }) {
  const colors = Colors[useScheme()];
  return (
    <View
      style={{
        paddingHorizontal: Spacing.three,
        paddingVertical: Spacing.one,
        borderRadius: Radius.full,
        borderWidth: 1,
        borderColor: muted ? colors.border : colors.accent,
      }}>
      <ThemedText
        type="small"
        style={{ fontSize: 12, color: muted ? colors.textSecondary : colors.accent }}>
        {label}
      </ThemedText>
    </View>
  );
}

function ActionButton({
  label,
  onPress,
  active,
}: {
  label: string;
  onPress: () => void;
  active?: boolean;
}) {
  const colors = Colors[useScheme()];
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      onPress={onPress}
      style={({ pressed }) => ({
        minHeight: 50,
        justifyContent: 'center',
        alignItems: 'center',
        borderRadius: Radius.md,
        borderCurve: 'continuous',
        backgroundColor: active ? colors.accent : 'transparent',
        borderWidth: 1,
        borderColor: active ? colors.accent : colors.border,
        opacity: pressed ? 0.7 : 1,
      })}>
      <ThemedText
        type="smallBold"
        style={{ color: active ? colors.accentText : colors.text }}>
        {label}
      </ThemedText>
    </Pressable>
  );
}
