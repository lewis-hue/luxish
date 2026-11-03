import { Image } from 'expo-image';
import * as ImagePicker from 'expo-image-picker';
import { Stack, router } from 'expo-router';
import { useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Switch,
  TextInput,
  View,
  type TextStyle,
} from 'react-native';

import {
  useMyProfile,
  useUpdateProfile,
  type SocialLink,
} from '@/api/queries/profile-identity';

import { useMe, useUpdateMe } from '@/api/queries/me';
import { usePostImages } from '@/api/queries/post-media';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { ProfilePortrait } from '@/components/ui/profile-portrait';
import { Screen } from '@/components/ui/screen';
import { useAuth } from '@/features/auth/session';
import { uploadMedia } from '@/features/media/upload';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  type Palette,
} from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/** Matches `display_name` on the server, which is `String(120)`. */
const MAX_NAME = 120;

/**
 * Editing who you are: a name, and a photograph.
 *
 * **A sheet, not a settings row.** Both of these are things somebody changes
 * once and then forgets about, and a dedicated screen for two fields reads
 * as more ceremony than the task deserves. Presented over Profile so
 * dismissing it is as cheap as opening it.
 *
 * **The photograph is optional and stays optional.** Profile already shows
 * the drawn avatar, and the avatar is a better default than an empty circle
 * — it was made from answers somebody gave. This adds a photograph for the
 * people who want one and leaves everybody else exactly as they were.
 *
 * Nothing here can change the email. It arrives in the token on every
 * sign-in, so a local edit would be overwritten minutes later; the server
 * rejects the field outright rather than accepting a write it will lose.
 */
export default function ProfileEditScreen() {
  const colors = Colors[useScheme()];
  const auth = useAuth();
  const me = useMe(auth.status === 'signedIn');
  const update = useUpdateMe();

  // Seeded once from what the server holds. A lazy initialiser rather than
  // an effect: syncing a prop into state inside an effect is both a lint
  // error here and a second render, and this field is only ever edited by
  // the person looking at it.
  const [name, setName] = useState(() => me.data?.displayName ?? '');
  const profile = useMyProfile(true);
  const updateProfile = useUpdateProfile();
  const [handle, setHandle] = useState('');
  const [isPrivate, setIsPrivate] = useState(false);
  const [bio, setBio] = useState('');
  const [links, setLinks] = useState<Record<string, string>>({});
  const [bannering, setBannering] = useState(false);

  // Served behind a bearer token and cached to disk once, like every
  // other picture this app shows.
  const bannerImages = usePostImages(
    profile.data?.bannerAssetId ? [profile.data.bannerAssetId] : [],
  );
  const bannerUri = profile.data?.bannerAssetId
    ? (bannerImages.data?.[profile.data.bannerAssetId] ?? null)
    : null;
  const [loaded, setLoaded] = useState(false);

  // Filled once, when the profile first arrives. Re-filling on every
  // render would overwrite whatever is being typed.
  if (!loaded && profile.data) {
    setLoaded(true);
    setHandle(profile.data.handle ?? '');
    setIsPrivate(profile.data.private);
    setBio(profile.data.bio ?? '');
    setLinks(
      Object.fromEntries(profile.data.links.map((l: SocialLink) => [l.platform, l.handle])),
    );
  }
  const [uploading, setUploading] = useState(false);

  const busy = uploading || update.isPending;

  const save = async () => {
    void tapFeedback();
    try {
      await update.mutateAsync({ displayName: name.trim() || null });
      // The identity half is a separate row with its own rules, so it
      // is a separate call. Only what changed is sent: `bio` is
      // omitted when untouched, because sending it would put an
      // unchanged bio back into review.
      const identity: {
        handle?: string;
        bio?: string | null;
        links?: Record<string, string>;
        private?: boolean;
      } = {};
      const wantedHandle = handle.trim().toLowerCase();
      if (wantedHandle && wantedHandle !== (profile.data?.handle ?? '')) {
        identity.handle = wantedHandle;
      }
      if (bio.trim() !== (profile.data?.bio ?? '')) {
        identity.bio = bio.trim() || null;
      }
      const wantedLinks = Object.fromEntries(
        Object.entries(links).filter(([, value]) => value.trim()),
      );
      const currentLinks = Object.fromEntries(
        (profile.data?.links ?? []).map((l: SocialLink) => [l.platform, l.handle]),
      );
      if (JSON.stringify(wantedLinks) !== JSON.stringify(currentLinks)) {
        identity.links = wantedLinks;
      }
      if (isPrivate !== (profile.data?.private ?? false)) {
        identity.private = isPrivate;
      }
      if (Object.keys(identity).length > 0) {
        await updateProfile.mutateAsync(identity);
      }
      router.back();
    } catch {
      // The mutation's own error is surfaced below rather than thrown away;
      // staying on the sheet keeps what they typed.
      Alert.alert('Could not save', 'That change did not go through. Try again.');
    }
  };

  const chooseBanner = async () => {
    void tapFeedback();
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      Alert.alert(
        'Photo access needed',
        'Grant access in Settings to choose a banner. Everything else keeps working.',
      );
      return;
    }

    const picked = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      // Wide, because that is the shape it is shown in. Cropping here
      // beats cropping at display time, where the middle of a portrait
      // is a strip of somebody's torso.
      allowsEditing: true,
      aspect: [16, 9],
      quality: 0.9,
    });
    if (picked.canceled || !picked.assets[0]) return;

    setBannering(true);
    try {
      const assetId = await uploadMedia({
        uri: picked.assets[0].uri,
        // Its own kind: a banner is decoration shown to everybody who
        // opens the page, and nothing that reads clothes or faces
        // should pick it up.
        kind: 'profile_banner',
      });
      await updateProfile.mutateAsync({ bannerAssetId: assetId });
    } catch (caught) {
      Alert.alert(
        'Could not upload',
        caught instanceof Error ? caught.message : 'That picture did not upload.',
      );
    } finally {
      setBannering(false);
    }
  };

  const removeBanner = async () => {
    void tapFeedback();
    try {
      await updateProfile.mutateAsync({ bannerAssetId: null });
    } catch {
      Alert.alert('Could not remove', 'That did not go through. Try again.');
    }
  };

  const choosePhoto = async () => {
    void tapFeedback();
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      Alert.alert(
        'Photo access needed',
        'Grant access in Settings to choose a profile picture. Everything else keeps working.',
      );
      return;
    }

    const picked = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      // Square, because every place this is shown is a circle. Cropping here
      // beats cropping at display time, where the middle of a portrait is a
      // midsection rather than a face.
      allowsEditing: true,
      aspect: [1, 1],
      quality: 0.9,
    });
    if (picked.canceled || !picked.assets[0]) return;

    setUploading(true);
    try {
      const assetId = await uploadMedia({
        uri: picked.assets[0].uri,
        // Not `garment_photo`: that kind runs cut-out and categorisation
        // jobs, and a picture of a person is not a garment to be segmented.
        kind: 'outfit_photo',
      });
      await update.mutateAsync({ profilePhotoAssetId: assetId });
    } catch (caught) {
      Alert.alert(
        'Could not upload',
        caught instanceof Error ? caught.message : 'That picture did not upload.',
      );
    } finally {
      setUploading(false);
    }
  };

  const removePhoto = async () => {
    void tapFeedback();
    try {
      await update.mutateAsync({ profilePhotoAssetId: null });
    } catch {
      Alert.alert('Could not remove', 'That change did not go through. Try again.');
    }
  };

  return (
    <>
      <Stack.Screen options={{ title: 'Edit profile' }} />
      <Screen scroll>
        <View style={{ alignItems: 'center', gap: Spacing.three }}>
          <ProfilePortrait
            uri={null}
            photoAssetId={me.data?.profilePhotoAssetId ?? null}
            name={me.data?.displayName ?? null}
            email={me.data?.email}
            onPress={() => void choosePhoto()}
          />

          <View style={{ flexDirection: 'row', gap: Spacing.two }}>
            <SheetButton
              label={uploading ? 'Uploading' : 'Choose a photo'}
              onPress={() => void choosePhoto()}
              disabled={busy}
              busy={uploading}
            />
            {me.data?.profilePhotoAssetId ? (
              <SheetButton
                label="Remove"
                onPress={() => void removePhoto()}
                disabled={busy}
              />
            ) : null}
          </View>
        </View>

        {/* The banner, under the portrait because that is the order
            they appear in on the page. */}
        <View style={{ gap: Spacing.two, marginTop: Spacing.five }}>
          <ThemedText type="label" themeColor="textSecondary">
            Banner
          </ThemedText>

          {bannerUri ? (
            <Image
              source={{ uri: bannerUri }}
              contentFit="cover"
              transition={140}
              accessible
              accessibilityLabel="Your banner"
              style={{
                width: '100%',
                height: 120,
                borderRadius: Radius.md,
                borderCurve: 'continuous',
                backgroundColor: colors.backgroundElement,
              }}
            />
          ) : (
            <View
              accessible
              accessibilityLabel="No banner yet"
              style={{
                width: '100%',
                height: 120,
                borderRadius: Radius.md,
                borderCurve: 'continuous',
                borderWidth: 1,
                borderStyle: 'dashed',
                borderColor: colors.border,
              }}
            />
          )}

          {/* Said only to its owner: a banner in review or held is
              their business, and nobody else's page shows it. */}
          {profile.data?.bannerState === 'pending_review' ? (
            <ThemedText
              type="small"
              themeColor="textSecondary"
              style={{ fontSize: FontSize.meta }}>
              Being checked. It appears on your page once it has been.
            </ThemedText>
          ) : profile.data?.bannerState === 'held' ? (
            <ThemedText
              type="small"
              style={{ fontSize: FontSize.meta, color: colors.danger }}>
              {profile.data.bannerNote ?? 'This was held.'}
            </ThemedText>
          ) : null}

          <View style={{ flexDirection: 'row', gap: Spacing.two }}>
            <SheetButton
              label={bannering ? 'Uploading' : 'Choose a banner'}
              onPress={() => void chooseBanner()}
              disabled={busy}
              busy={bannering}
            />
            {profile.data?.bannerAssetId ? (
              <SheetButton
                label="Remove"
                onPress={() => void removeBanner()}
                disabled={busy}
              />
            ) : null}
          </View>
        </View>

        <View style={{ gap: Spacing.two, marginTop: Spacing.five }}>
          <ThemedText type="label" themeColor="textSecondary">
            Name
          </ThemedText>
          <TextInput
            value={name}
            onChangeText={setName}
            placeholder="What should we call you?"
            placeholderTextColor={colors.textSecondary}
            maxLength={MAX_NAME}
            autoCapitalize="words"
            autoCorrect={false}
            accessibilityLabel="Your name"
            style={{
              minHeight: TapTarget,
              paddingHorizontal: Spacing.three,
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              borderWidth: 1,
              borderColor: colors.border,
              backgroundColor: colors.backgroundElement,
              color: colors.text,
              fontSize: FontSize.body,
            }}
          />
          {/* What actually happens if they leave it empty, rather than a
              rule stated in the abstract. */}
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ fontSize: FontSize.caption }}>
            {name.trim()
              ? `The app will greet you as ${name.trim().split(/\s+/)[0]}.`
              : 'Empty, and the app uses your email instead.'}
          </ThemedText>
        </View>

        {/* Private, which is a switch rather than a consent.

            `community_sharing` is a grant about the shelf of other
            people's looks you kept; this is about your own fits and
            the two lists of who you are connected to. One control
            answering both questions would mean neither. */}
        <View style={{ gap: Spacing.two, marginTop: Spacing.five }}>
          <View
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: Spacing.three,
              minHeight: TapTarget,
            }}>
            <View style={{ flex: 1, gap: Spacing.half }}>
              <ThemedText type="smallBold">Private account</ThemedText>
              <ThemedText
                type="small"
                themeColor="textSecondary"
                style={{ fontSize: FontSize.caption }}>
                Nobody but you sees your fits, your followers or who you
                follow. The counts still show, because a count is not a list.
              </ThemedText>
            </View>
            <Switch
              value={isPrivate}
              onValueChange={(next) => {
                void tapFeedback();
                setIsPrivate(next);
              }}
              accessibilityLabel="Private account"
            />
          </View>
        </View>

        <View style={{ gap: Spacing.two, marginTop: Spacing.five }}>
          <ThemedText type="label" themeColor="textSecondary">
            Handle
          </ThemedText>
          <TextInput
            value={handle}
            onChangeText={setHandle}
            placeholder="whatpeoplecallyou"
            placeholderTextColor={colors.textSecondary}
            maxLength={30}
            autoCapitalize="none"
            autoCorrect={false}
            accessibilityLabel="Your handle"
            style={fieldStyle(colors)}
          />
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ fontSize: FontSize.caption }}>
            {handle.trim()
              ? `People find you as @${handle.trim().toLowerCase()}.`
              : 'Letters, digits, dots and underscores. This is how other people address you, and it does not change when your name does.'}
          </ThemedText>
        </View>

        <View style={{ gap: Spacing.two, marginTop: Spacing.five }}>
          <ThemedText type="label" themeColor="textSecondary">
            Bio
          </ThemedText>
          <TextInput
            value={bio}
            onChangeText={setBio}
            placeholder="A line about what you wear."
            placeholderTextColor={colors.textSecondary}
            maxLength={300}
            multiline
            accessibilityLabel="Your bio"
            style={{ ...fieldStyle(colors), minHeight: 88, paddingTop: Spacing.two, textAlignVertical: 'top' }}
          />
          {/* Said before they write it, not after it is held: a bio is
              read by strangers, so it is checked like a caption is. */}
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ fontSize: FontSize.caption }}>
            Checked before other people see it. Yours shows to you either way.
          </ThemedText>
          {profile.data?.bioState === 'held' ? (
            <ThemedText
              type="small"
              style={{ fontSize: FontSize.caption, color: colors.danger }}>
              {profile.data.bioNote ?? 'Held for review.'}
            </ThemedText>
          ) : null}
        </View>

        <View style={{ gap: Spacing.two, marginTop: Spacing.five }}>
          <ThemedText type="label" themeColor="textSecondary">
            Where else to find you
          </ThemedText>
          {/* A handle per platform, never a URL. The address is built on
              the server from a fixed table, so a profile cannot send
              anybody to an arbitrary link. */}
          {(profile.data?.platforms ?? []).map((platform: string) => (
            <View key={platform} style={{ gap: Spacing.one }}>
              <ThemedText type="small" themeColor="textSecondary">
                {platform}
              </ThemedText>
              <TextInput
                value={links[platform] ?? ''}
                onChangeText={(next) =>
                  setLinks((current) => ({ ...current, [platform]: next }))
                }
                placeholder="yourhandle"
                placeholderTextColor={colors.textSecondary}
                maxLength={64}
                autoCapitalize="none"
                autoCorrect={false}
                accessibilityLabel={`Your ${platform} handle`}
                style={fieldStyle(colors)}
              />
            </View>
          ))}
        </View>

        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Save"
          accessibilityState={{ disabled: busy, busy: update.isPending }}
          disabled={busy}
          animateEntrance={false}
          onPress={() => void save()}
          style={{
            marginTop: Spacing.five,
            minHeight: TapTarget + 8,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            backgroundColor: colors.text,
            opacity: busy ? 0.5 : 1,
          }}>
          {update.isPending ? (
            <ActivityIndicator color={colors.background} />
          ) : (
            <ThemedText type="smallBold" style={{ color: colors.background }}>
              Save
            </ThemedText>
          )}
        </MotionPressable>
      </Screen>
    </>
  );
}

/** A secondary action under the portrait. */
function SheetButton({
  label,
  onPress,
  disabled,
  busy,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  busy?: boolean;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: !!disabled, busy: !!busy }}
      disabled={disabled}
      animateEntrance={false}
      onPress={onPress}
      style={{
        minHeight: TapTarget,
        justifyContent: 'center',
        paddingHorizontal: Spacing.four,
        borderRadius: Radius.full,
        borderWidth: 1,
        borderColor: colors.borderStrong,
        opacity: disabled ? 0.5 : 1,
      }}>
      <ThemedText type="smallBold">{label}</ThemedText>
    </MotionPressable>
  );
}


/** The one input treatment this screen uses, so the fields match. */
function fieldStyle(colors: Palette): TextStyle {
  return {
    minHeight: TapTarget,
    paddingHorizontal: Spacing.three,
    borderRadius: Radius.md,
    borderCurve: 'continuous',
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.backgroundElement,
    color: colors.text,
    fontSize: FontSize.body,
  };
}
