import { router } from 'expo-router';
import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { useState } from 'react';
import { View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import {
  MotionPressable,
  successFeedback,
  tapFeedback,
} from '@/components/ui/motion';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { keepToPhotos, sharePicture } from '@/features/avatar/keep';
import { useScheme } from '@/hooks/use-theme';

/**
 * Save it, send it, or post it here.
 *
 * **One row under any picture this app made.** A render of an outfit
 * and a shot out of the studio are the same thing to somebody holding
 * a phone - a picture they asked for and now want to keep - so they
 * get the same three controls rather than each screen inventing its
 * own.
 *
 * **Saving writes the file the app already has.** Renders and shots
 * are downloaded through the authenticated fetch and cached before
 * they are shown, so this is a local copy at whatever resolution the
 * model returned. Nothing is re-encoded or resized on the way out: a
 * picture saved is the picture generated.
 *
 * **Posting is a separate act.** Sharing hands the file to the system
 * sheet and the app stops being involved; posting it *here* means a
 * fit with an author and a caption, so it goes through compose like
 * anything else somebody publishes.
 */
export function PictureActions({
  uri,
  /** Shown instead of the row while the picture is still arriving. */
  pending = false,
  /** Posting is offered only where a picture is the author's own. */
  canPost = true,
  /**
   * Which ground this sits on.
   *
   * **`dark` is not optional decoration.** A picture viewer is a
   * black screen, and `ThemedText` on it is the page's own near-black
   * on near-black: the labels were invisible, which is how this was
   * found. There is no theme token for "on a scrim" because a scrim
   * is dark in both schemes, so the light values are written here.
   */
  on = 'page',
  onLeave,
}: {
  uri: string | null;
  pending?: boolean;
  canPost?: boolean;
  on?: 'page' | 'dark';
  /**
   * Close whatever this is sitting in, before going somewhere.
   *
   * **A sheet left open over the destination is a trap.** Posting
   * pushed to compose without telling the viewer it was inside, so
   * the modal stayed mounted underneath: coming back, its invisible
   * backdrop was still over the page swallowing every tap, and the
   * pictures read as dead. `PinActions` and `FitMenu` have always
   * closed first for exactly this reason; this did not.
   */
  onLeave?: () => void;
}) {
  const [said, setSaid] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  if (!uri || pending) return null;

  const run = async (what: 'save' | 'share') => {
    void tapFeedback();
    setSaid(null);
    setWorking(true);
    try {
      if (what === 'save') {
        await keepToPhotos(uri);
        void successFeedback();
        setSaid('Saved to your photos.');
      } else {
        await sharePicture(uri);
      }
    } catch (caught) {
      setSaid(
        caught instanceof Error ? caught.message : 'That did not work. Try again.',
      );
    } finally {
      setWorking(false);
    }
  };

  return (
    <View style={{ gap: Spacing.two }}>
      <View style={{ flexDirection: 'row', gap: Spacing.two }}>
        <Action
          label="Save"
          hint="Puts it in your photos"
          icon={{
            ios: 'arrow.down.to.line',
            android: 'download',
            web: 'download',
          }}
          busy={working}
          on={on}
          onPress={() => void run('save')}
        />
        <Action
          label="Share"
          hint="Send it anywhere"
          icon={{
            ios: 'square.and.arrow.up',
            android: 'share',
            web: 'share',
          }}
          busy={working}
          on={on}
          onPress={() => void run('share')}
        />
        {canPost ? (
          <Action
            label="Post"
            hint="Put it on the board"
            icon={{ ios: 'plus.square', android: 'add_box', web: 'add_box' }}
            busy={working}
            on={on}
            onPress={() => {
              void tapFeedback();
              // Out of the way first, then go.
              onLeave?.();
              // Compose owns captions, tags and the screen that reads
              // them. Publishing from here would be a second way to
              // post with none of that.
              //
              // `photo`, which compose already reads: the `+` on
              // Discover opens it the same way. A second parameter
              // meaning the same thing is a second thing to keep in
              // step.
              router.push({ pathname: '/compose', params: { photo: uri } });
            }}
          />
        ) : null}
      </View>

      {said ? (
        <ThemedText
          selectable
          type="small"
          themeColor={on === 'dark' ? undefined : 'textSecondary'}
          style={{
            ...labelType(FontSize.footnote, 400),
            ...(on === 'dark' ? { color: ON_DARK } : null),
          }}>
          {said}
        </ThemedText>
      ) : null}
    </View>
  );
}

/** Text and glyphs on a scrim. Fixed: a scrim is dark in both schemes. */
const ON_DARK = '#FFFFFF';

function Action({
  label,
  hint,
  icon,
  busy,
  on,
  onPress,
}: {
  label: string;
  hint: string;
  icon: SymbolViewProps['name'];
  busy: boolean;
  on: 'page' | 'dark';
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  const ink = on === 'dark' ? ON_DARK : colors.text;
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={hint}
      accessibilityState={{ disabled: busy, busy }}
      animateEntrance={false}
      disabled={busy}
      onPress={onPress}
      style={{
        flex: 1,
        minHeight: TapTarget,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: Spacing.one,
        borderRadius: Radius.full,
        borderWidth: 1,
        borderColor: on === 'dark' ? 'rgba(255, 255, 255, 0.45)' : colors.border,
        opacity: busy ? 0.5 : 1,
      }}>
      <SymbolView name={icon} size={18} tintColor={ink} />
      <ThemedText type="smallBold" style={{ color: ink }}>
        {label}
      </ThemedText>
    </MotionPressable>
  );
}
