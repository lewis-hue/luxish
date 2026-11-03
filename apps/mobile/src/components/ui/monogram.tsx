import { Image } from 'expo-image';
import { View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { Radius, labelType, tintFor } from '@/constants/theme';

/**
 * Somebody's face, or the letter that stands in for it.
 *
 * **One component, everywhere a person appears.** Nine screens drew
 * their own circle with their own tinted grey, which is how a list of
 * people ends up looking like a list of placeholders — and how one
 * account comes out a different shade depending on which screen you
 * found it on.
 *
 * **A colour per person, taken from their id.** Deterministic, so it
 * is the same on every screen and survives a rename, and from a set
 * of eight so a column of monograms is scannable rather than uniform.
 * A random colour per render would make one account look like
 * several.
 *
 * **A photograph wins when there is one.** The letter is the fallback,
 * not the design: carrying a face between accounts needs a consent
 * this app collects only for an avatar somebody made on purpose.
 */
export function Monogram({
  name,
  id,
  size = 48,
  uri,
}: {
  name: string;
  /**
   * What the colour is taken from. Their user id where there is one,
   * so the ground is stable even when the name changes; the name is
   * the fallback and is better than nothing.
   */
  id?: string;
  size?: number;
  /** A picture of them, where this app has one it may show. */
  uri?: string | null;
}) {
  const letter = (name ?? '').trim().charAt(0).toUpperCase() || '?';
  const ground = tintFor(id?.trim() || name || letter);

  if (uri) {
    return (
      <Image
        source={{ uri }}
        contentFit="cover"
        contentPosition="top"
        accessible={false}
        style={{ width: size, height: size, borderRadius: Radius.full }}
      />
    );
  }

  return (
    <View
      accessible={false}
      style={{
        width: size,
        height: size,
        borderRadius: Radius.full,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: ground,
      }}>
      <ThemedText
        // Fixed rather than themed: the ground is the same in both
        // schemes, so a letter that followed the scheme would be
        // white on a pale tint half the time.
        style={{ ...labelType(size / 2.4, 800), color: '#161210' }}>
        {letter}
      </ThemedText>
    </View>
  );
}
