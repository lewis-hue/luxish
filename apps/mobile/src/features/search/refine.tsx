import { Image } from 'expo-image';
import { SymbolView } from 'expo-symbols';
import { View } from 'react-native';

import { usePostImages } from '@/api/queries/post-media';
import type { Door } from '@/api/queries/explore';
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
import { useScheme } from '@/hooks/use-theme';

/** The most rows offered. Past this it is a browse, not a nudge. */
export const MOST_REFINEMENTS = 6;

/**
 * Pick the refinements to offer for a search that found little.
 *
 * **Order matters more than the list.** Tags related to what was
 * actually typed come first, because they are the only ones that
 * answer *this* search. Only once those run out does it fall back to
 * what is busy, which is what to offer somebody whose query matched
 * nothing at all. A search for gibberish gets the busy list, which is
 * the right answer to "I have no idea what you meant" and is what
 * the reference does.
 *
 * Deduplicated on the key, because a related tag is very often also
 * a popular one and the same row twice reads as a bug.
 */
export function refinements(input: {
  related?: readonly string[];
  popular?: readonly Door[];
  /** Never offered back: it is the thing that just failed. */
  exclude?: string;
}): Door[] {
  const seen = new Set<string>();
  const no = input.exclude?.trim().toLowerCase().replace(/^#/, '');
  const out: Door[] = [];

  const take = (door: Door) => {
    const key = door.key.trim().toLowerCase();
    if (!key || key === no || seen.has(key)) return;
    seen.add(key);
    out.push(door);
  };

  for (const tag of input.related ?? []) {
    take({ kind: 'tag', key: tag, label: tag, posts: 0, coverAssetId: null });
  }
  for (const door of input.popular ?? []) take(door);

  return out.slice(0, MOST_REFINEMENTS);
}

/**
 * What to try instead, when a search did not land.
 *
 * **A dead end is the thing a search must never be.** The screen used
 * to answer a query it could not match with one sentence about
 * hashtags and a button that emptied the box, which tells somebody
 * their search was wrong and leaves them to guess again. The
 * reference answers even nonsense with somewhere to go, and that is
 * what this is: rows that are real searches with real results behind
 * them, so tapping one cannot land back here.
 */
export function Refine({
  doors,
  onPick,
}: {
  doors: readonly Door[];
  onPick: (query: string) => void;
}) {
  const colors = Colors[useScheme()];
  const covers = usePostImages(
    doors.map((door) => door.coverAssetId).filter((id): id is string => !!id),
  );

  if (doors.length === 0) return null;

  return (
    <View style={{ gap: Spacing.two, paddingHorizontal: Spacing.three }}>
      <ThemedText style={labelType(FontSize.title3, 800)}>
        Refine your search
      </ThemedText>
      {doors.map((door) => {
        const uri = door.coverAssetId
          ? (covers.data?.[door.coverAssetId] ?? null)
          : null;
        return (
          <MotionPressable
            key={`${door.kind}:${door.key}`}
            accessibilityRole="link"
            accessibilityLabel={`Search ${door.label}`}
            animateEntrance={false}
            onPress={() => {
              void tapFeedback();
              onPick(door.key);
            }}
            style={{
              minHeight: TapTarget,
              flexDirection: 'row',
              alignItems: 'center',
              gap: Spacing.three,
              paddingRight: Spacing.three,
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              overflow: 'hidden',
              backgroundColor: colors.backgroundElement,
            }}>
            {/* A photograph from behind the tag when there is one. It
                is what makes a row a place rather than a word, and it
                is already loaded for the board this tag opens. */}
            {uri ? (
              <Image
                source={{ uri }}
                contentFit="cover"
                transition={ImageFade}
                cachePolicy="memory-disk"
                style={{ width: TapTarget, height: TapTarget }}
              />
            ) : (
              <View style={{ width: TapTarget, height: TapTarget }} />
            )}
            <SymbolView
              name={{
                ios: 'magnifyingglass',
                android: 'search',
                web: 'search',
              }}
              size={18}
              weight="regular"
              tintColor={colors.text}
            />
            <ThemedText
              numberOfLines={1}
              style={{ ...labelType(FontSize.body, 400), flex: 1 }}>
              {door.label}
            </ThemedText>
          </MotionPressable>
        );
      })}
    </View>
  );
}
