import { Image } from 'expo-image';
import { SymbolView } from 'expo-symbols';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { ScrollView, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useCreatePost } from '@/api/queries/posts';
import { useTasteOptions } from '@/api/queries/taste';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { uploadMedia } from '@/features/media/upload';
import { useGarmentCapture } from '@/features/wardrobe/capture';
import { useWardrobe } from '@/features/wardrobe/store';
import { useScheme } from '@/hooks/use-theme';

/**
 * The composer: one screen, one honest ending.
 *
 * **A fit is structured, not freeform.** A look from the taxonomy as its
 * picture, a capped caption as its only free text, an occasion from the
 * taste vocabulary, and tags drawn from the poster's own wardrobe. The
 * narrow shape is the moderation surface staying small enough to screen.
 *
 * **A fit is live when you press post.** It used to wait for the
 * screen, which meant pressing publish and seeing nothing appear. The
 * screen still runs and can take a fit down afterwards; what changed
 * is which side of it the post sits on. The copy here says what
 * actually happens either way - a composer that promised a review it
 * does not wait for would be as wrong as one promising a post it
 * never made.
 */
/**
 * The groups Discover actually has, as one-tap suggestions.
 *
 * Mirrors `app.domain.feed.GROUP_TAGS` on the server. Typing anything
 * else still works — these are the ones that put a fit somewhere
 * people browse.
 */
const TAG_SUGGESTIONS: readonly string[] = [
  'streetwear',
  'casual',
  'office',
  'evening',
  'workout',
  'minimal',
  'vintage',
  'romantic',
  'outdoors',
  'occasion',
  'denim',
  'modest',
  'heritage',
];

export default function ComposeScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();

  const options = useTasteOptions();
  const wardrobe = useWardrobe(new Set());
  const create = useCreatePost();
  const capture = useGarmentCapture();

  /**
   * Take a picture off the phone and put it on the server.
   *
   * The library only. A fit is a photograph somebody already took and
   * chose; opening the camera here would be asking them to produce one
   * on the spot, which is not what the `+` on a board means.
   *
   * The upload starts immediately rather than at post time, so the
   * wait happens while they are writing a caption instead of after
   * they press the button.
   */
  const upload = async (uri: string) => {
    setUploading(true);
    try {
      setPhotoAssetId(await uploadMedia({ uri, kind: 'outfit_photo' }));
    } catch {
      // The preview stays, saying it could not upload. Clearing it
      // would lose the picture along with the error.
      setPhotoAssetId(null);
    } finally {
      setUploading(false);
    }
  };

  const choosePhoto = async () => {
    void tapFeedback();
    const picked = await capture.pickFromLibrary();
    if (typeof picked === 'string' || !picked.length) return;

    const chosen = picked[0];
    setPhotoUri(chosen.uri);
    setPhotoAssetId(null);
    await upload(chosen.uri);
  };


  //: The photograph being posted, and its id once it has gone up.
  //:
  //: Two fields because they arrive at different moments: the local URI
  //: is there the instant somebody picks a picture and is what the
  //: preview renders, and the asset id only exists after the upload.
  // Arriving with a picture already chosen: from the `+`, which opens
  // the camera roll first, or from the collage editor, which hands
  // over a flattened canvas. Read straight into the initial state
  // rather than synced by an effect - an effect would render the
  // empty chooser first and then replace it, which flashes.
  const { photo } = useLocalSearchParams<{ photo?: string }>();
  const [photoUri, setPhotoUri] = useState<string | null>(photo ?? null);
  const [photoAssetId, setPhotoAssetId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  // A handed-in picture still has to go up, and it starts going up on
  // first render rather than waiting for somebody to press post.
  const started = useRef(false);

  // A fit needs one picture, from either source. Checked once here
  // rather than in three style props that can disagree.
  const canPost =
    Boolean(photoAssetId) && !create.isPending && !uploading;

  // A picture handed in by the `+` or the collage editor starts going
  // up as soon as the screen mounts, so the wait happens while
  // somebody writes a caption rather than after they press post.
  //
  // In an effect rather than during render: a ref read while
  // rendering is a value React is allowed to not re-run for, and
  // starting an upload is a side effect either way.
  useEffect(() => {
    if (!photo || started.current) return;
    started.current = true;
    void upload(photo);
    // Once, for the picture this screen opened with: the ref guard
    // is what stops a second run uploading the same file twice.
  }, [photo]);
  const [caption, setCaption] = useState('');
  const [tags, setTags] = useState('');
  const [occasion, setOccasion] = useState<string | null>(null);
  const [garmentIds, setGarmentIds] = useState<string[]>([]);
  const [submitted, setSubmitted] = useState<string | null>(null);

  const occasions = options.data?.occasions ?? [];
  const synced = wardrobe.items.filter((item) => item.serverId);

  const toggleGarment = (serverId: string) => {
    setGarmentIds((current) =>
      current.includes(serverId)
        ? current.filter((id) => id !== serverId)
        : current.length >= 6
          ? current
          : [...current, serverId],
    );
  };

  const publish = () => {
    // A photograph. The server still accepts a curated look id and
    // nothing sends one any more, so the button waits on the picture.
    if (!photoAssetId || create.isPending || uploading) return;
    void tapFeedback();
    create.mutate(
      {
        mediaAssetIds: photoAssetId ? [photoAssetId] : undefined,
        caption: [caption.trim(), tags.trim()].filter(Boolean).join(' ') || undefined,
        occasion: occasion ?? undefined,
        garmentIds,
      },
      { onSuccess: (data) => setSubmitted(data.note) },
    );
  };

  if (submitted) {
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: colors.background,
          justifyContent: 'center',
          padding: Spacing.five,
          gap: Spacing.three,
        }}>
        <ThemedText style={{ ...labelType(28, 800), lineHeight: 34 }}>Posted</ThemedText>
        <ThemedText type="small" themeColor="textSecondary">
          {submitted}
        </ThemedText>
        <MotionPressable
          accessibilityRole="button"
          animateEntrance={false}
          onPress={() => router.back()}
          style={{
            minHeight: TapTarget,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            backgroundColor: colors.text,
          }}>
          <ThemedText type="smallBold" style={{ color: colors.background }}>
            Done
          </ThemedText>
        </MotionPressable>
      </View>
    );
  }

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.background }}
      contentInsetAdjustmentBehavior="automatic"
      automaticallyAdjustKeyboardInsets
      keyboardDismissMode="interactive"
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={{
        paddingTop: Spacing.three,
        paddingBottom: insets.bottom + Spacing.five,
        gap: Spacing.five,
      }}
      showsVerticalScrollIndicator={false}>
      <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.half }}>
        <ThemedText accessibilityRole="header" style={{ ...labelType(32, 800), lineHeight: 38 }}>
          Share a fit
        </ThemedText>
        <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: FontSize.footnote }}>
          Goes straight to Discover.
        </ThemedText>
      </View>

      {/* Your photograph. First, because it is what a fit usually is.

          This screen only ever offered a curated look as the picture,
          which made posting a way to republish the app's own artwork.
          Everything else here is built on photographs people took. */}
      <View style={{ gap: Spacing.two, paddingHorizontal: Spacing.three }}>
        <ThemedText type="smallBold">Your photo</ThemedText>

        {photoUri ? (
          <View style={{ flexDirection: 'row', gap: Spacing.three }}>
            <Image
              source={{ uri: photoUri }}
              contentFit="cover"
              transition={120}
              accessible
              accessibilityLabel="The photograph you are posting"
              style={{
                width: 96,
                height: 128,
                borderRadius: Radius.md,
                borderCurve: 'continuous',
                backgroundColor: colors.backgroundElement,
              }}
            />
            <View style={{ flex: 1, gap: Spacing.two }}>
              <ThemedText
                type="small"
                themeColor="textSecondary"
                style={{ fontSize: FontSize.meta }}>
                {uploading
                  ? 'Uploading'
                  : photoAssetId
                    ? 'Ready to post'
                    : 'Could not upload. Pick it again.'}
              </ThemedText>
              <MotionPressable
                accessibilityRole="button"
                accessibilityLabel="Remove this photograph"
                animateEntrance={false}
                scale={0.95}
                onPress={() => {
                  void tapFeedback();
                  setPhotoUri(null);
                  setPhotoAssetId(null);
                }}
                style={{
                  alignSelf: 'flex-start',
                  minHeight: 34,
                  justifyContent: 'center',
                  paddingHorizontal: Spacing.three,
                  borderRadius: Radius.full,
                  borderWidth: 1,
                  borderColor: colors.border,
                }}>
                <ThemedText type="small" style={{ fontSize: FontSize.footnote }}>
                  Remove
                </ThemedText>
              </MotionPressable>
            </View>
          </View>
        ) : (
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Choose a photo from your phone"
            accessibilityState={{ busy: uploading, disabled: uploading }}
            disabled={uploading}
            animateEntrance={false}
            scale={0.98}
            onPress={() => void choosePhoto()}
            style={{
              minHeight: TapTarget + Spacing.three,
              flexDirection: 'row',
              alignItems: 'center',
              justifyContent: 'center',
              gap: Spacing.two,
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              borderWidth: 1,
              borderStyle: 'dashed',
              borderColor: colors.borderStrong,
              opacity: uploading ? 0.6 : 1,
            }}>
            <SymbolView
              name={{ ios: 'photo.on.rectangle', android: 'image', web: 'image' }}
              size={20}
              tintColor={colors.text}
            />
            <ThemedText type="smallBold">
              {uploading ? 'Uploading' : 'Choose from your phone'}
            </ThemedText>
          </MotionPressable>
        )}
      </View>

      <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.one }}>
        <ThemedText type="smallBold">Say what makes it work</ThemedText>
        <TextInput
          value={caption}
          onChangeText={(next) => setCaption(next.slice(0, 300))}
          multiline
          placeholder="Optional, up to 300 characters."
          placeholderTextColor={colors.textSecondary as string}
          style={{
            minHeight: 72,
            padding: Spacing.two,
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            backgroundColor: colors.backgroundElement,
            color: colors.text as string,
            fontSize: FontSize.subhead,
            textAlignVertical: 'top',
          }}
        />
      </View>

      <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.two }}>
        <ThemedText type="smallBold">Tag it</ThemedText>
        {/* **The author's own words decide where this lands.** Discover
            groups by hashtags rather than by anything read off the
            picture, because somebody writing `#streetwear` is stating
            what they put together — which is better evidence than a
            guess from pixels.

            Suggestions rather than a fixed list: they fill the field so
            it can be edited, and anything else typed still counts. */}
        <TextInput
          value={tags}
          onChangeText={(next) => setTags(next.slice(0, 160))}
          placeholder="#streetwear #thrifted"
          placeholderTextColor={colors.textSecondary as string}
          autoCapitalize="none"
          autoCorrect={false}
          accessibilityLabel="Hashtags for this fit"
          style={{
            minHeight: TapTarget,
            paddingHorizontal: Spacing.two,
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            backgroundColor: colors.backgroundElement,
            color: colors.text as string,
            fontSize: FontSize.subhead,
          }}
        />
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          automaticallyAdjustKeyboardInsets
          keyboardDismissMode="interactive"
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{ flexDirection: 'row', gap: Spacing.one }}>
          {TAG_SUGGESTIONS.map((tag) => {
            const chosen = tags.toLowerCase().includes(`#${tag}`);
            return (
              <MotionPressable
                key={tag}
                accessibilityRole="button"
                accessibilityState={{ selected: chosen }}
                accessibilityLabel={`Tag ${tag}`}
                animateEntrance={false}
                onPress={() => {
                  void tapFeedback();
                  setTags((current) =>
                    chosen
                      ? current.replace(new RegExp(`#${tag}\\b`, 'gi'), '').replace(/\s+/g, ' ').trim()
                      : `${current} #${tag}`.trim(),
                  );
                }}
                style={{
                  minHeight: 32,
                  justifyContent: 'center',
                  paddingHorizontal: Spacing.three,
                  borderRadius: Radius.full,
                  backgroundColor: chosen ? colors.text : 'transparent',
                  borderWidth: 1,
                  borderColor: chosen ? colors.text : colors.border,
                }}>
                <ThemedText
                  type="small"
                  style={{
                    fontSize: FontSize.footnote,
                    color: chosen ? colors.background : colors.textSecondary,
                  }}>
                  #{tag}
                </ThemedText>
              </MotionPressable>
            );
          })}
        </ScrollView>
      </View>

      {occasions.length > 0 ? (
        <View style={{ gap: Spacing.one }}>
          <ThemedText type="smallBold" style={{ paddingHorizontal: Spacing.three }}>
            For
          </ThemedText>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ paddingHorizontal: Spacing.three, gap: Spacing.one }}>
            {occasions.map((option) => {
              const selected = option === occasion;
              return (
                <MotionPressable
                  key={option}
                  accessibilityRole="button"
                  accessibilityState={{ selected }}
                  animateEntrance={false}
                  onPress={() => setOccasion(selected ? null : option)}
                  style={{
                    minHeight: 36,
                    paddingHorizontal: Spacing.three,
                    justifyContent: 'center',
                    borderRadius: Radius.full,
                    backgroundColor: selected ? colors.backgroundSelected : 'transparent',
                    borderWidth: 1,
                    borderColor: selected ? colors.backgroundSelected : colors.border,
                  }}>
                  <ThemedText type="small" style={{ fontSize: FontSize.footnote }}>
                    {option.replace(/_/g, ' ')}
                  </ThemedText>
                </MotionPressable>
              );
            })}
          </ScrollView>
        </View>
      ) : null}

      {synced.length > 0 ? (
        <View style={{ gap: Spacing.one }}>
          {/* The heading and its explanation were removed on the
              product owner's instruction. The chips below still say
              what they are, and the row sits under the picture it
              belongs to, so a label above it was restating the
              obvious. What readers see is unchanged: the kind of
              piece, never somebody's own name for it. */}
          <View
            style={{
              flexDirection: 'row',
              flexWrap: 'wrap',
              gap: Spacing.one,
              paddingHorizontal: Spacing.three,
            }}>
            {synced.map((item) => {
              const selected = garmentIds.includes(item.serverId as string);
              return (
                <MotionPressable
                  key={item.id}
                  accessibilityRole="button"
                  accessibilityState={{ selected }}
                  animateEntrance={false}
                  onPress={() => {
                    void tapFeedback();
                    toggleGarment(item.serverId as string);
                  }}
                  style={{
                    minHeight: 36,
                    paddingHorizontal: Spacing.three,
                    justifyContent: 'center',
                    borderRadius: Radius.full,
                    backgroundColor: selected ? colors.backgroundSelected : 'transparent',
                    borderWidth: 1,
                    borderColor: selected ? colors.backgroundSelected : colors.border,
                  }}>
                  <ThemedText type="small" style={{ fontSize: FontSize.footnote }} numberOfLines={1}>
                    {item.name}
                  </ThemedText>
                </MotionPressable>
              );
            })}
          </View>
        </View>
      ) : null}

      <View style={{ paddingHorizontal: Spacing.three }}>
        <MotionPressable
          accessibilityRole="button"
          accessibilityState={{ disabled: !canPost }}
          disabled={!canPost}
          animateEntrance={false}
          onPress={publish}
          style={{
            minHeight: TapTarget + 8,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            backgroundColor: colors.text,
            opacity: !photoAssetId || create.isPending ? 0.5 : 1,
          }}>
          <ThemedText type="smallBold" style={{ color: colors.background }}>
            Post
          </ThemedText>
        </MotionPressable>
      </View>
    </ScrollView>
  );
}
