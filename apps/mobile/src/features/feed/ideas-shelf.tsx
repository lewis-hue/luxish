import { Image } from 'expo-image';
import { router } from 'expo-router';
import { View } from 'react-native';

import { type Door } from '@/api/queries/explore';
import { usePostImage } from '@/api/queries/post-media';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import {
  Colors,
  FontSize,
  ImageFade,
  Radius,
  Spacing,
  labelType,
} from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/**
 * Ideas you might love: a few ways back into what you keep saving.
 *
 * **It sits in a column of the board, not across it.** A full-width
 * band cuts the board in half and reads as an advertisement; one
 * column of cards reads as part of the same wall of photographs, which
 * is what the reference does and why it does not interrupt a scroll.
 *
 * **Each card wears a real photograph from the tag it opens.** A
 * generated cover describing user content is a catalogue pretending to
 * be a community. The picture is dimmed because the label has to be
 * legible over whatever it happens to be - a white word on a pale
 * photograph is a word nobody can read.
 */

/** How tall one card is against its width. Wide and short, as drawn. */
const CARD = 2.1;

export function IdeasShelf({ doors }: { doors: readonly Door[] }) {
  if (doors.length === 0) return null;

  return (
    <View style={{ gap: Spacing.two, paddingBottom: Spacing.three }}>
      <ThemedText
        accessibilityRole="header"
        style={{
          textAlign: 'center',
          paddingVertical: Spacing.two,
          ...labelType(20, 800),
          lineHeight: 24,
        }}>
        Ideas you might love
      </ThemedText>
      {doors.map((door) => (
        <IdeaCard key={`${door.kind}:${door.key}`} door={door} />
      ))}
    </View>
  );
}

function IdeaCard({ door }: { door: Door }) {
  const colors = Colors[useScheme()];
  const uri = usePostImage(door.coverAssetId).data ?? null;

  return (
    <MotionPressable
      accessibilityRole="link"
      accessibilityLabel={`${door.label}. ${
        door.posts === 1 ? '1 fit' : `${door.posts} fits`
      }.`}
      animateEntrance={false}
      scale={0.97}
      onPress={() => {
        void tapFeedback();
        router.push({ pathname: '/tag/[tag]', params: { tag: door.key } });
      }}
      style={{
        aspectRatio: CARD,
        borderRadius: Radius.lg,
        borderCurve: 'continuous',
        overflow: 'hidden',
        justifyContent: 'center',
        backgroundColor: colors.backgroundElement,
      }}>
      {uri ? (
        <Image
          source={{ uri }}
          recyclingKey={door.key}
          contentFit="cover"
          transition={ImageFade}
          accessible={false}
          style={{ position: 'absolute', width: '100%', height: '100%' }}
        />
      ) : null}

      {/* Dimmed, so the label is readable over a photograph nobody
          chose for its contrast. Fixed rather than themed: it darkens
          a picture, and a picture is the same in both schemes. */}
      <View
        pointerEvents="none"
        style={{
          position: 'absolute',
          width: '100%',
          height: '100%',
          backgroundColor: '#00000059',
        }}
      />

      <ThemedText
        numberOfLines={2}
        style={{
          paddingHorizontal: Spacing.three,
          textAlign: 'center',
          color: '#FFFFFF',
          ...labelType(FontSize.body, 800),
        }}>
        {door.label}
      </ThemedText>
    </MotionPressable>
  );
}
