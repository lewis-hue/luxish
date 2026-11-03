import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { View } from 'react-native';

import type { SocialLink } from '@/api/queries/profile-identity';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { ProfilePortrait } from '@/components/ui/profile-portrait';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { categoryById } from '@/features/discover/collections';
import { openSite } from '@/features/profile/website';
import { useScheme } from '@/hooks/use-theme';

/** The glyph for each platform a link may point at. */
const PLATFORM_ICON: Record<string, SymbolViewProps['name']> = {
  tiktok: { ios: 'music.note', android: 'music_note', web: 'music_note' },
  instagram: { ios: 'camera', android: 'photo_camera', web: 'photo_camera' },
  youtube: { ios: 'play.rectangle', android: 'smart_display', web: 'smart_display' },
  pinterest: { ios: 'pin', android: 'push_pin', web: 'push_pin' },
  x: { ios: 'text.bubble', android: 'chat', web: 'chat' },
};

/**
 * Who somebody is, at the top of their page.
 *
 * **Centred, and the name leads.** This is the one screen that is about
 * a person rather than about clothes, so it is laid out like an
 * introduction: picture, name, handle, a line about them, what they
 * wear, and then the single thing you came to do.
 *
 * **The handle is not the display name.** The name is whatever they
 * typed and can change; the handle is the stable thing other people
 * address them by. Showing both is what makes a rename harmless.
 *
 * **Links go out, and only where they say.** The server stores a
 * platform and a handle and builds the address itself, so a profile
 * cannot smuggle somebody to an arbitrary URL. They open in the system
 * browser rather than a webview, which is the honest way to leave an
 * app you are leaving.
 */
export function IdentityHeader({
  name,
  handle,
  bio,
  links,
  avatarUri,
  photoAssetId,
  email,
  aesthetics,
  action,
  counts,
  onOpenPeople,
}: {
  name: string | null;
  handle: string | null;
  bio: string | null;
  links: readonly SocialLink[];
  avatarUri?: string | null;
  photoAssetId?: string | null;
  email?: string | null;
  /** Style tags from their taste, rendered as chips. */
  aesthetics: readonly string[];
  /** The one action: Follow on somebody else's page, Edit on your own. */
  action?: { label: string; onPress: () => void; filled?: boolean };
  /**
   * Followers and following, shown as one line under the handle.
   *
   * Tappable when `onOpenPeople` is given, which it is on your own
   * profile: a count that cannot be opened is a number somebody has to
   * take on trust. Somebody else's page keeps the counts and does not
   * open, because a follower list is a list of real people and nobody
   * agreed to have theirs enumerated by a stranger.
   */
  counts?: { followers: number; following: number } | null;
  onOpenPeople?: (direction: 'followers' | 'following') => void;
}) {
  const colors = Colors[useScheme()];

  return (
    <View style={{ alignItems: 'center', gap: Spacing.two }}>
      <ProfilePortrait
        uri={avatarUri ?? null}
        photoAssetId={photoAssetId ?? null}
        name={name}
        email={email ?? undefined}
      />

      <View style={{ alignItems: 'center', gap: Spacing.half }}>
        <ThemedText
          accessibilityRole="header"
          numberOfLines={1}
          // The grotesque, not the display serif.
          //
          // The Bodoni is the product's own voice: a screen title, the
          // wordmark. A person's name sits above their handle and
          // their counts, all of which are interface, and setting it
          // in the display face made somebody's profile read as a
          // chapter opening rather than as a person.
          style={{ ...labelType(28, 800), lineHeight: 32, textAlign: 'center' }}>
          {name ?? 'Someone'}
        </ThemedText>
        {handle ? (
          <ThemedText type="small" themeColor="textSecondary">
            @{handle}
          </ThemedText>
        ) : null}

        {counts ? (
          <View
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: Spacing.one,
              paddingTop: Spacing.half,
            }}>
            <CountLink
              label={
                counts.followers === 1
                  ? '1 follower'
                  : `${counts.followers} followers`
              }
              onPress={
                onOpenPeople ? () => onOpenPeople('followers') : undefined
              }
            />
            <ThemedText type="small" themeColor="textSecondary">
              &middot;
            </ThemedText>
            <CountLink
              label={`${counts.following} following`}
              onPress={
                onOpenPeople ? () => onOpenPeople('following') : undefined
              }
            />
          </View>
        ) : null}
      </View>

      {bio ? (
        <ThemedText
          type="small"
          themeColor="textSecondary"
          style={{ textAlign: 'center', maxWidth: 320 }}>
          {bio}
        </ThemedText>
      ) : null}

      {links.length > 0 ? (
        <View style={{ flexDirection: 'row', gap: Spacing.two }}>
          {links.map((link) => (
            <MotionPressable
              key={link.platform}
              accessibilityRole="link"
              accessibilityLabel={`${link.platform}, ${link.handle}`}
              accessibilityHint="Opens in your browser"
              animateEntrance={false}
              scale={0.94}
              onPress={() => {
                void tapFeedback();
                // The system browser, not a webview: leaving the app
                // should look like leaving the app.
                openSite(link.url);
              }}
              style={{
                minHeight: 32,
                flexDirection: 'row',
                alignItems: 'center',
                gap: Spacing.one,
                paddingHorizontal: Spacing.two,
                borderRadius: Radius.full,
                borderWidth: 1,
                borderColor: colors.border,
              }}>
              <SymbolView
                name={
                  PLATFORM_ICON[link.platform] ?? {
                    ios: 'link',
                    android: 'link',
                    web: 'link',
                  }
                }
                size={13}
                tintColor={colors.textSecondary}
              />
              <ThemedText
                type="small"
                themeColor="textSecondary"
                style={{ fontSize: FontSize.meta }}>
                {link.handle}
              </ThemedText>
            </MotionPressable>
          ))}
        </View>
      ) : null}

      {aesthetics.length > 0 ? (
        <View
          style={{
            flexDirection: 'row',
            flexWrap: 'wrap',
            justifyContent: 'center',
            gap: Spacing.one,
          }}>
          {aesthetics.map((id) => (
            <View
              key={id}
              style={{
                paddingHorizontal: Spacing.three,
                paddingVertical: Spacing.one,
                borderRadius: Radius.full,
                backgroundColor: colors.backgroundElement,
              }}>
              <ThemedText
                type="small"
                style={{ fontSize: FontSize.footnote }}>
                {(categoryById(id)?.title ?? id).toUpperCase()}
              </ThemedText>
            </View>
          ))}
        </View>
      ) : null}

      {action ? (
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel={action.label}
          animateEntrance={false}
          onPress={() => {
            void tapFeedback();
            action.onPress();
          }}
          style={{
            minHeight: TapTarget,
            minWidth: 180,
            alignItems: 'center',
            justifyContent: 'center',
            paddingHorizontal: Spacing.five,
            borderRadius: Radius.full,
            backgroundColor: action.filled ? colors.accent : 'transparent',
            borderWidth: 1,
            borderColor: action.filled ? colors.accent : colors.border,
          }}>
          <ThemedText
            type="smallBold"
            style={{ color: action.filled ? colors.accentText : colors.text }}>
            {action.label}
          </ThemedText>
        </MotionPressable>
      ) : null}
    </View>
  );
}

/**
 * One count, a link when it leads somewhere.
 *
 * Rendered as plain text rather than a disabled button when it does
 * not: a control that looks pressable and is not is worse than a label.
 */
function CountLink({
  label,
  onPress,
}: {
  label: string;
  onPress?: () => void;
}) {
  if (!onPress) {
    return (
      <ThemedText type="small" themeColor="textSecondary">
        {label}
      </ThemedText>
    );
  }
  return (
    <MotionPressable
      accessibilityRole="link"
      accessibilityLabel={label}
      animateEntrance={false}
      scale={0.95}
      hitSlop={8}
      onPress={() => {
        void tapFeedback();
        onPress();
      }}>
      <ThemedText type="smallBold">{label}</ThemedText>
    </MotionPressable>
  );
}
