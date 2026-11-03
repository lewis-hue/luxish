import { Image } from 'expo-image';
import { MotiView } from 'moti';
import { View } from 'react-native';

import { useMotiTiming } from '@/components/ui/motion';
import { blurhashFor } from '@/features/discover/blurhashes';

/**
 * Three close crops of cloth, flush against each other, bleeding off both
 * edges of the screen.
 *
 * **Deliberately not another collage.** The welcome screen opens on six
 * photographs scattered at angles; doing that again one tap later is the same
 * screen twice, which is what made sign-in read as the brand name repeated.
 * Flush columns with no gaps and no rotation are the other editorial
 * register — a contact sheet rather than a pile of prints — so the two
 * screens look like they come from one art department without looking alike.
 *
 * **No faces.** A cuff, a shoulder seam and a shoe. Partly because detail
 * crops are the more interesting picture, and partly because the single face
 * on a sign-in screen becomes the face of the product, which is a decision
 * this app has already been corrected on once.
 *
 * Each column rises into place in sequence, once. Nothing loops here: a
 * repeating animation beside the sign-in buttons is what WCAG 2.2.2 asks for
 * a pause control for, and `useMotiTiming` collapses it to nothing under
 * Reduce Motion.
 */
const CROPS = [
  { id: 'cuff', alt: 'Hands fastening a shirt cuff' },
  { id: 'shoulder', alt: 'The shoulder seam of a wool coat' },
  { id: 'step', alt: 'Trainers and the hem of wide trousers, mid-stride' },
] as const;

export function DetailStrip({ height }: { height: number }) {
  const timing = useMotiTiming();

  return (
    <View
      // One unit to a screen reader: three crops of cloth are a single
      // decorative band, not three things to step through.
      accessible
      accessibilityRole="image"
      accessibilityLabel="Close details of a shirt cuff, a wool coat and trainers"
      style={{ flexDirection: 'row', height }}>
      {CROPS.map((crop, index) => (
        <MotiView
          key={crop.id}
          from={{ opacity: 0, translateY: 28 }}
          animate={{ opacity: 1, translateY: 0 }}
          transition={timing({ duration: 760, delay: index * 120 })}
          // Equal thirds, flush. A gap here would make it three cards, and
          // three cards is the look this is deliberately not.
          style={{ flex: 1, overflow: 'hidden' }}>
          <CropImage crop={crop} />
        </MotiView>
      ))}
    </View>
  );
}

/** Split out so the placeholder can be resolved before it is handed over:
 *  `blurhashFor` returns null for an unknown key, and `expo-image` wants the
 *  prop absent rather than carrying a null. */
function CropImage({ crop }: { crop: (typeof CROPS)[number] }) {
  const blurhash = blurhashFor(`signin/${crop.id}`);
  return (
    <Image
      source={
              crop.id === 'cuff'
          ? require('../../../assets/images/signin/cuff.webp')
          : crop.id === 'shoulder'
            ? require('../../../assets/images/signin/shoulder.webp')
            : require('../../../assets/images/signin/step.webp')
      }
      placeholder={blurhash ? { blurhash } : undefined}
      placeholderContentFit="cover"
      contentFit="cover"
      transition={0}
      accessible={false}
      style={{ width: '100%', height: '100%' }}
    />
  );
}
