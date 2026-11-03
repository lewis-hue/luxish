import { Image } from 'expo-image';
import { router } from 'expo-router';

import { useProfilePhoto } from '@/api/queries/me';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable } from '@/components/ui/motion';
import {
  Colors,
  Radius,
  labelType,
} from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/** Diameter. Large enough to be the anchor of the screen, small enough that
 *  the name still sits above the fold on a short phone. */
const PORTRAIT = 96;

/**
 * The picture at the top of Profile.
 *
 * **It is the drawn avatar, not an upload.** Every reference profile opens
 * with a round picture of the person, and this app already makes one: the
 * figure from `/avatar`, drawn from appearance somebody *answered*. Reusing
 * it means the identity block has a real image without adding a camera
 * permission, an upload endpoint, or a photo of a face on a server.
 *
 * **Cropped to the top, not the centre.** The render is a full-length
 * figure at 1:2. A circular centre crop of that is a midsection — which is
 * what a naive `cover` gives you, and it looks like a mistake because it is
 * one. `contentPosition="top"` takes the head and shoulders instead.
 *
 * With no figure yet it is a monogram and an invitation, because an empty
 * circle explains nothing and this one has somewhere to go.
 */
export function ProfilePortrait({
  uri,
  photoAssetId,
  name,
  email,
  onPress,
}: {
  /** The drawn avatar, as a local file URI. */
  /**
   * A picture to show when there is no profile photo.
   *
   * **Not the drawn avatar.** The profile tab used to pass the
   * generated figure here, so everybody's profile picture was a
   * full-length render of a stranger in grey clothes - a picture the
   * app made, standing in for one the person chose. A profile
   * picture is either a photograph somebody picked or their initial;
   * a generated body is neither.
   *
   * Left on the component because a caller may one day have a real
   * picture that is not the stored profile photo, but nothing passes
   * it today.
   */
  uri: string | null;
  /**
   * A photograph they chose, which wins over the drawn figure.
   *
   * Ordered that way deliberately: the avatar is a good *default* because it
   * was made from answers somebody gave, and a photograph is a choice they
   * made on purpose. A choice outranks a default.
   */
  photoAssetId?: string | null;
  name: string | null;
  email?: string | null;
  /** Overrides the default destination, for the edit sheet. */
  onPress?: () => void;
}) {
  const colors = Colors[useScheme()];
  const photo = useProfilePhoto(photoAssetId ?? null);
  // The letter somebody would recognise as theirs: their name if we have it,
  // otherwise the account the email names. Never a hardcoded placeholder.
  const initial = (name ?? email ?? '').trim().charAt(0).toUpperCase();

  return (
    <MotionPressable
      accessibilityRole="link"
      accessibilityLabel={
        photo || uri ? 'Edit your profile' : 'Add a profile picture'
      }
      animateEntrance={false}
      scale={0.96}
      onPress={onPress ?? (() => router.push('/profile-edit'))}
      style={{
        width: PORTRAIT,
        height: PORTRAIT,
        borderRadius: Radius.full,
        overflow: 'hidden',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: colors.backgroundElement,
      }}>
      {photo ? (
        <Image
          source={{ uri: photo }}
          contentFit="cover"
          // Centred, unlike the drawn figure: a photograph somebody cropped
          // to a square for this purpose already has the subject in the
          // middle, and anchoring it to the top would cut their chin off.
          contentPosition="center"
          style={{ width: '100%', height: '100%' }}
          accessible={false}
        />
      ) : uri ? (
        <Image
          source={{ uri }}
          contentFit="cover"
          // See the note above: the top of a full-length figure is the face.
          contentPosition="top"
          style={{ width: '100%', height: '100%' }}
          accessible={false}
        />
        /* Nothing passes `uri` any more; see the note on the prop. */
      ) : (
        <ThemedText
          themeColor="textSecondary"
          style={labelType(36, 800)}
          // Decorative: the pressable above already says what this is, and a
          // screen reader announcing a lone letter is noise.
          accessible={false}>
          {initial || '+'}
        </ThemedText>
      )}
    </MotionPressable>
  );
}
