import { Image } from 'expo-image';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { View } from 'react-native';

import { greetingName, useMe, useProfilePhoto } from '@/api/queries/me';
import { ThemedText } from '@/components/themed-text';
import { Radius, labelType } from '@/constants/theme';
import { useAuth } from '@/features/auth/session';

/**
 * The Profile chip's glyph: whoever is signed in, not a generic person.
 *
 * **A tab that is about *you* should show you.** The chip drew
 * `person.crop.circle.fill` for everybody, which is the icon for the
 * idea of an account rather than for the account somebody is using -
 * and a bar whose last chip is anonymous reads as signed out even
 * when it is not. Every reference app puts the person's own picture
 * there, and this app already has one: the photograph they chose on
 * the profile screen.
 *
 * Three states, in the order a person would expect:
 *
 *   1. the photograph they chose;
 *   2. the first letter of their first name, when they have not
 *      chosen one - the same monogram `ProfilePortrait` draws, so
 *      the chip and the page agree;
 *   3. the symbol, when nobody is signed in or the account has no
 *      name to take a letter from. A letter invented for a person
 *      with no name is worse than the icon.
 *
 * The photograph is the same cached file the profile page shows -
 * `useProfilePhoto` keys on the asset id and writes it to disk once -
 * so putting it in the bar costs a lookup, not a download per screen.
 */
export function ProfileTabGlyph({
  focused,
  tint,
  icon,
}: {
  focused: boolean;
  /** The chip's current foreground colour, selected or not. */
  tint: string;
  /** What to draw when there is nobody to draw. */
  icon: SymbolViewProps['name'];
}) {
  const auth = useAuth();
  const me = useMe(auth.status === 'signedIn');
  const photo = useProfilePhoto(me.data?.profilePhotoAssetId ?? null);
  // The same first-name rule the greeting uses, so the letter in the
  // bar is the letter in "Hey, Lewis". It returns null for a local
  // part that is plainly not a name, which is what sends an account
  // like `user42@` to the symbol rather than to a "U".
  const initial = greetingName(me.data ?? undefined)?.charAt(0).toUpperCase();

  if (photo) {
    return (
      <Image
        testID="profile-tab-photo"
        source={{ uri: photo }}
        contentFit="cover"
        contentPosition="center"
        style={{
          width: PICTURE,
          height: PICTURE,
          borderRadius: Radius.full,
          // A hairline in the chip's own colour, so a photograph with
          // a pale edge still reads as a disc rather than bleeding
          // into the blurred pane behind it.
          borderWidth: focused ? 1.5 : 1,
          borderColor: tint,
        }}
        accessible={false}
      />
    );
  }

  if (initial) {
    return (
      <View
        testID="profile-tab-initial"
        style={{
          width: PICTURE,
          height: PICTURE,
          borderRadius: Radius.full,
          borderWidth: focused ? 1.5 : 1,
          borderColor: tint,
          alignItems: 'center',
          justifyContent: 'center',
        }}>
        <ThemedText
          // Decorative: the chip is already labelled "Profile", and a
          // screen reader announcing a lone letter is noise.
          accessible={false}
          style={[labelType(13, 800), { color: tint, lineHeight: 15 }]}>
          {initial}
        </ThemedText>
      </View>
    );
  }

  return (
    <SymbolView
      testID="profile-tab-symbol"
      name={icon}
      size={focused ? 24 : 22}
      tintColor={tint}
    />
  );
}

/**
 * Diameter of the picture, against the symbol's 22-24.
 *
 * Slightly larger than the glyph it replaces: a photograph needs more
 * room than a line drawing to be recognisable as a face, and the
 * circle has a border where the symbol has none.
 */
const PICTURE = 26;
