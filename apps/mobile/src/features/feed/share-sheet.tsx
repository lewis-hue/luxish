import { Image } from 'expo-image';
import * as Sharing from 'expo-sharing';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { Modal, Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { FeedFit } from '@/api/queries/discover-feed';
import { usePostImages } from '@/api/queries/post-media';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, successFeedback, tapFeedback } from '@/components/ui/motion';
import { Colors, FontSize, Radius, Spacing, TapTarget } from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/**
 * Save or share a fit.
 *
 * **Offered on a screenshot, because a screenshot is a request.**
 * Somebody capturing the screen is trying to keep or send a picture,
 * and the OS screenshot is the worst version of both: it carries the
 * status bar, the tab chrome and none of the attribution. Catching the
 * gesture and offering the real thing gives them a better file and
 * gives the author their credit.
 *
 * **Sharing goes through the system sheet.** Rebuilding a row of
 * WhatsApp and Telegram buttons means maintaining a list of other
 * people's apps forever, and the OS already knows what is installed and
 * what the person actually uses.
 */
/**
 * The system sheet, with the picture and where it lives.
 *
 * The file is the thing somebody is trying to send; the link is how
 * whoever receives it gets to the fit, its author and everything
 * under it. The sheet sends one item, and a picture with a caption is
 * the shape every target understands.
 *
 * Exported because two things share a fit - the icon on the fit page,
 * which shares at once, and the prompt after a screenshot, which
 * offers to. One function, so they cannot drift apart.
 */
export async function shareFit({
  uri,
  authorName,
  link,
}: {
  uri: string | null;
  authorName: string;
  link?: string;
}): Promise<void> {
  void tapFeedback();
  if (!uri || !(await Sharing.isAvailableAsync())) return;
  await Sharing.shareAsync(uri, {
    mimeType: 'image/webp',
    dialogTitle: link ? `${authorName}'s fit - ${link}` : `${authorName}'s fit`,
  });
  void successFeedback();
}

export function ShareSheet({
  fit,
  visible,
  reason,
  link,
  onClose,
  onSave,
  onBoard,
  onTryOn,
}: {
  fit: FeedFit | null;
  visible: boolean;
  /** Why it opened, so a screenshot can say so rather than appearing. */
  reason?: 'screenshot' | 'tapped';
  /**
   * Where the fit lives, sent with the picture.
   *
   * A photograph shared on its own is a photograph nobody can trace
   * back to the person who posted it, and nobody can open. Empty when
   * the server has nowhere to point at, and then only the picture
   * goes - better than attaching a URL that resolves nowhere.
   */
  link?: string;
  onClose: () => void;
  onSave: () => void;
  onBoard: () => void;
  onTryOn: () => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const images = usePostImages(fit?.mediaAssetIds ?? []);

  if (!fit) return null;
  const uri = images.data?.[fit.mediaAssetIds[0] ?? ''] ?? null;

  const share = () => void shareFit({ uri, authorName: fit.authorName, link });

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Close"
        onPress={onClose}
        style={{ flex: 1, justifyContent: 'flex-end', backgroundColor: '#00000066' }}>
        <Pressable
          // Swallows taps so pressing the sheet does not close it.
          onPress={() => {}}
          style={{
            paddingTop: Spacing.three,
            paddingHorizontal: Spacing.three,
            paddingBottom: insets.bottom + Spacing.three,
            gap: Spacing.three,
            backgroundColor: colors.background,
            borderTopLeftRadius: Radius.lg,
            borderTopRightRadius: Radius.lg,
            borderCurve: 'continuous',
          }}>
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ textAlign: 'center', fontSize: FontSize.footnote }}>
            {reason === 'screenshot'
              ? 'Screenshot taken. Keep the real picture instead?'
              : `${fit.authorName}'s fit`}
          </ThemedText>

          {uri ? (
            <View style={{ alignItems: 'center' }}>
              <Image
                source={{ uri }}
                contentFit="cover"
                transition={120}
                accessible
                accessibilityLabel={fit.caption ?? 'This fit'}
                style={{
                  width: 132,
                  height: 176,
                  borderRadius: Radius.md,
                  borderCurve: 'continuous',
                }}
              />
            </View>
          ) : null}

          <View style={{ flexDirection: 'row', gap: Spacing.two }}>
            <Tile
              label={fit.savedByMe ? 'Kept' : 'Keep'}
              icon={{
                ios: fit.savedByMe ? 'bookmark.fill' : 'bookmark',
                android: fit.savedByMe ? 'bookmark' : 'bookmark_border',
                web: 'bookmark',
              }}
              active={fit.savedByMe}
              onPress={() => {
                onSave();
                onClose();
              }}
            />
            <Tile
              label="Board"
              icon={{ ios: 'pin', android: 'push_pin', web: 'push_pin' }}
              onPress={() => {
                onClose();
                onBoard();
              }}
            />
            <Tile
              label="Try it on"
              icon={{ ios: 'figure.stand', android: 'person', web: 'person' }}
              onPress={() => {
                onClose();
                onTryOn();
              }}
            />
            <Tile
              label="Share"
              icon={{
                ios: 'square.and.arrow.up',
                android: 'ios_share',
                web: 'ios_share',
              }}
              onPress={() => void share()}
            />
          </View>

          {/* The credit, because a picture that leaves this app without
              it is a picture somebody else made and nobody can trace. */}
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ textAlign: 'center', fontSize: FontSize.meta }}>
            {link
              ? `Shared pictures carry ${fit.authorName}'s name and a link back here.`
              : `Shared pictures keep ${fit.authorName}'s name on them.`}
          </ThemedText>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

function Tile({
  label,
  icon,
  active,
  onPress,
}: {
  label: string;
  icon: SymbolViewProps['name'];
  active?: boolean;
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ selected: active }}
      animateEntrance={false}
      scale={0.96}
      onPress={onPress}
      style={{
        flex: 1,
        minHeight: TapTarget + Spacing.four,
        alignItems: 'center',
        justifyContent: 'center',
        gap: Spacing.one,
        borderRadius: Radius.md,
        borderCurve: 'continuous',
        backgroundColor: active ? colors.accent : colors.backgroundElement,
      }}>
      <SymbolView
        name={icon}
        size={20}
        tintColor={active ? colors.accentText : colors.text}
      />
      <ThemedText
        type="small"
        numberOfLines={1}
        style={{
          fontSize: FontSize.meta,
          color: active ? colors.accentText : colors.text,
        }}>
        {label}
      </ThemedText>
    </MotionPressable>
  );
}
