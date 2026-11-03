import { router, useFocusEffect } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { useCallback, useState } from 'react';
import { AppState, Pressable, ScrollView, Switch, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  useNotificationPrefs,
  useSetNotificationPref,
  type NotificationPrefs,
} from '@/api/queries/notification-prefs';
import { announceDevice } from '@/api/queries/devices';
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
import { useAuth } from '@/features/auth/session';
import {
  ensureChannel,
  openSystemSettings,
  permissionState,
  requestPermission,
  type PermissionState,
} from '@/features/notifications/permission';
import { useScheme } from '@/hooks/use-theme';

/**
 * Notification settings: one permission, four switches, no dark corners.
 *
 * **The permission ask lives here, beside the words that say what it is
 * for.** iOS answers the system prompt once and records it forever, so the
 * prompt is only ever spent on a tap on the button below, never fired from
 * an effect on some other screen. When the answer was no and the system
 * will not ask again, the button honestly becomes "Open settings", because
 * that is the only door left.
 *
 * **Four switches, not forty.** One per inbox kind, plus plan reminders.
 * The toggles stay enabled while permission is off: a choice made here is
 * stored on the account and simply waits for the permission, rather than
 * being wiped and re-asked after the user comes back from Settings.
 *
 * **What is real is labelled.** Plan reminders are scheduled on this phone
 * and work today. Nothing on this screen implies a server push that is not
 * built; the footer says exactly where that stands.
 */
export default function NotificationSettingsScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';
  const prefs = useNotificationPrefs(signedIn);
  const setPref = useSetNotificationPref();

  const [permission, setPermission] = useState<PermissionState | null>(null);
  /**
   * Set when permission was given but this phone still cannot be
   * reached.
   *
   * **Because the alternative is a switch that lies.** Granting
   * permission and registering a device are two different things, and
   * the second can fail on its own: an Expo push token needs a build
   * that can mint one, and `announceDevice` is quiet by design so that
   * background work never interrupts anybody. The result was a screen
   * showing notifications as on, a server with nowhere to send, and
   * nothing anywhere saying so. Somebody is owed the difference
   * between "you said no" and "this build cannot receive these".
   */
  const [unreachable, setUnreachable] = useState(false);

  // Re-checked whenever the screen is focused or the app returns from the
  // background, because the common path through the `blocked` state is:
  // leave for Settings, flip the switch there, come straight back.
  useFocusEffect(
    useCallback(() => {
      let live = true;
      const check = () => {
        void permissionState().then((state) => {
          if (live) setPermission(state);
          // Tell the server where to reach this phone, once there is
          // permission to reach it at all. Idempotent, so running on
          // every focus costs nothing.
          if (state === 'granted') {
            void announceDevice().then((registered) => {
              if (live) setUnreachable(!registered);
            });
          }
        });
      };
      check();
      const sub = AppState.addEventListener('change', (next) => {
        if (next === 'active') check();
      });
      return () => {
        live = false;
        sub.remove();
      };
    }, []),
  );

  const ask = async () => {
    void tapFeedback();
    await ensureChannel();
    const state = await requestPermission();
    setPermission(state);
    if (state === 'granted') setUnreachable(!(await announceDevice()));
  };

  const toggle = (key: keyof NotificationPrefs) => (value: boolean) => {
    setPref.mutate({ [key]: value });
  };

  const data = prefs.data;

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      {/* Its own bar, the same one `settings` draws: the title between
          the way back and nothing else. The native header was showing
          an empty title, which left a floating chevron over a page
          that then had to introduce itself all over again. */}
      <View
        style={{
          minHeight: TapTarget,
          marginTop: insets.top + Spacing.one,
          justifyContent: 'center',
          paddingHorizontal: Spacing.three,
        }}>
        <ThemedText
          accessibilityRole="header"
          style={{ ...labelType(FontSize.body, 800), textAlign: 'center' }}>
          Notifications
        </ThemedText>
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Back"
          animateEntrance={false}
          scale={0.92}
          hitSlop={8}
          onPress={() => {
            void tapFeedback();
            if (router.canGoBack()) router.back();
            else router.replace('/settings');
          }}
          style={{
            position: 'absolute',
            left: Spacing.three,
            height: TapTarget,
            justifyContent: 'center',
          }}>
          <SymbolView
            name={{
              ios: 'chevron.left',
              android: 'arrow_back',
              web: 'arrow_back',
            }}
            size={20}
            tintColor={colors.text}
          />
        </MotionPressable>
      </View>

      <ScrollView
        contentContainerStyle={{
          paddingTop: Spacing.three,
          paddingBottom: insets.bottom + Spacing.five,
        }}
        showsVerticalScrollIndicator={false}>

      {/* Permission given, and still nowhere to send.
          Worth its own line because every switch below it will look
          on and none of them will do anything, and that is not a
          state anybody should have to work out for themselves. */}
      {permission === 'granted' && unreachable ? (
        <View
          style={{
            marginHorizontal: Spacing.three,
            padding: Spacing.three,
            gap: Spacing.one,
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            backgroundColor: colors.backgroundElement,
          }}>
          <ThemedText style={labelType(FontSize.body, 800)}>
            This build cannot receive notifications
          </ThemedText>
          <ThemedText themeColor="textSecondary" style={labelType(FontSize.subhead, 400)}>
            You have allowed them, but Expo Go cannot register this phone. A
            development build can.
          </ThemedText>
        </View>
      ) : null}

      {/* The permission, in whichever state it is actually in. */}
      {permission === 'granted' ? null : (
        <View
          style={{
            marginHorizontal: Spacing.three,
            padding: Spacing.three,
            gap: Spacing.two,
            borderRadius: Radius.lg,
            borderCurve: 'continuous',
            backgroundColor: colors.backgroundElement,
          }}>
          <ThemedText style={labelType(20, 800)}>
            {permission === 'blocked'
              ? 'Notifications are off in your phone settings'
              : 'This phone has not been asked yet'}
          </ThemedText>
          <ThemedText
            themeColor="textSecondary"
            style={labelType(FontSize.subhead, 400)}>
            {permission === 'blocked'
              ? 'The switch lives in your system settings now. Your choices below are kept either way.'
              : 'One ask, used for plan reminders. Nothing here sends marketing.'}
          </ThemedText>
          <MotionPressable
            accessibilityRole="button"
            animateEntrance={false}
            onPress={permission === 'blocked' ? openSystemSettings : () => void ask()}
            style={{
              minHeight: TapTarget,
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              backgroundColor: colors.text,
            }}>
            <ThemedText
              style={{ ...labelType(FontSize.body, 800), color: colors.background }}>
              {permission === 'blocked' ? 'Open settings' : 'Turn on notifications'}
            </ThemedText>
          </MotionPressable>
        </View>
      )}

      <Section title="On this phone">
        <ToggleRow
          label="Plan reminders"
          detail="At 7:30 on the morning of a planned outfit."
          value={data?.planReminders ?? true}
          disabled={!data}
          onChange={toggle('planReminders')}
        />
      </Section>

      <Section title="In your inbox">
        <ToggleRow
          label="Wardrobe sorted"
          detail="When photographs finish being cut out and filed."
          value={data?.wardrobeSorted ?? true}
          disabled={!data}
          onChange={toggle('wardrobeSorted')}
        />
        <ToggleRow
          label="Outfit ready"
          detail="When a stylist request finishes."
          value={data?.stylistReady ?? true}
          disabled={!data}
          onChange={toggle('stylistReady')}
        />
        <ToggleRow
          label="Fits you kept"
          detail="When several people keep one of them too."
          value={data?.fitReactions ?? true}
          disabled={!data}
          onChange={toggle('fitReactions')}
        />
      </Section>

        <View
          style={{
            paddingHorizontal: Spacing.three,
            paddingTop: Spacing.five,
          }}>
          <ThemedText
            themeColor="textSecondary"
            style={labelType(FontSize.footnote, 400)}>
            Plan reminders are scheduled on this phone and work now. The
            switches above shape both what the inbox shows and what the
            server sends. Sending to a phone needs this build to be a
            development build with an EAS project linked; until then the
            server queues notifications and the inbox still shows them.
          </ThemedText>
        </View>
      </ScrollView>
    </View>
  );
}

/** A group name. Quiet, because the rows under it are the screen. */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View>
      <ThemedText
        accessibilityRole="header"
        themeColor="textSecondary"
        style={{
          paddingHorizontal: Spacing.three,
          paddingTop: Spacing.five,
          paddingBottom: Spacing.one,
          ...labelType(FontSize.body, 400),
        }}>
        {title}
      </ThemedText>
      {children}
    </View>
  );
}

/**
 * One switch and the words it answers to, as a single accessible element.
 *
 * The whole row toggles: a switch alone is a 51 point target at the far
 * edge of the screen, and the label is most of the row's width.
 */
function ToggleRow({
  label,
  detail,
  value,
  disabled,
  onChange,
}: {
  label: string;
  detail: string;
  value: boolean;
  disabled: boolean;
  onChange: (value: boolean) => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <Pressable
      accessible
      accessibilityRole="switch"
      accessibilityLabel={`${label}. ${detail}`}
      accessibilityState={{ checked: value, disabled }}
      disabled={disabled}
      onPress={() => onChange(!value)}
      style={{
        // A row is as tall as `settings` makes one: a list of switches
        // that is denser than the list beside it reads as a different
        // screen.
        minHeight: TapTarget + Spacing.two,
        paddingHorizontal: Spacing.three,
        paddingVertical: Spacing.two,
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.three,
        opacity: disabled ? 0.5 : 1,
      }}>
      <View style={{ flex: 1, gap: Spacing.half }}>
        {/* Body weight, not a heading.
            These were 20pt bold, which is the size this app uses for
            a section title. On a settings list every row then read as
            a heading with nothing under it, and a screenful of them
            crowded out the hints that explain what each one does. */}
        <ThemedText style={labelType(FontSize.body, 800)}>{label}</ThemedText>
        <ThemedText
          themeColor="textSecondary"
          style={labelType(FontSize.subhead, 400)}>
          {detail}
        </ThemedText>
      </View>
      <Switch
        value={value}
        disabled={disabled}
        onValueChange={onChange}
        trackColor={{ true: colors.accent as string, false: undefined }}
      />
    </Pressable>
  );
}
