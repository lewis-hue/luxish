import { router } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import * as WebBrowser from 'expo-web-browser';
import { Alert, ScrollView, Share, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  hasAiConsent,
  hasCommunityConsent,
  useConsents,
  useSetConsent,
} from '@/api/queries/consents';
import {
  exportLine,
  useAskForDataExport,
  useDataExport,
  useSaveDataExport,
} from '@/api/queries/account-export';
import {
  greetingName,
  useDeleteAccount,
  useMe,
  useProfilePhoto,
} from '@/api/queries/me';
import { useMyProfile } from '@/api/queries/profile-identity';
import { BRAND } from '@/branding';
import { ThemedText } from '@/components/themed-text';
import { Monogram } from '@/components/ui/monogram';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import {
  BottomTabInset,
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { useAuth } from '@/features/auth/session';
import { useScheme } from '@/hooks/use-theme';

/**
 * The account, and everything done to it rather than with it.
 *
 * **It opens on who you are.** The card at the top is the thing every
 * row below is about, and the two controls on it — look at your page,
 * hand somebody your page — are the two most-wanted things on the
 * screen. Finding them inside a list of consent toggles was the old
 * arrangement.
 *
 * **Rows are destinations, and they say so.** A chevron means another
 * screen in this app; an arrow means it leaves for the browser; a word
 * on the right means the row is a switch and that word is its state.
 * One glyph per kind, so nothing has to be tapped to find out which it
 * is.
 *
 * **Grouped by what breaks if you get it wrong.** Settings are things
 * you change; the account group is leaving, exporting and deleting,
 * which are the three that are hard to undo.
 */
export default function SettingsScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const auth = useAuth();
  const closeAccount = useDeleteAccount();
  const signedIn = auth.status === 'signedIn';
  // The export, which is three steps: ask, wait, save. Polling only
  // runs while one is gathering, so this costs nothing on a screen
  // somebody opened to do something else.
  const myExport = useDataExport(signedIn);
  const askForExport = useAskForDataExport();
  const saveExport = useSaveDataExport();

  const me = useMe(signedIn);
  const profile = useMyProfile(signedIn);
  const photo = useProfilePhoto(me.data?.profilePhotoAssetId ?? null);
  const consents = useConsents(signedIn);
  const setConsent = useSetConsent();
  const aiGranted = hasAiConsent(consents.data);
  const sharing = hasCommunityConsent(consents.data);

  const name = greetingName(me.data ?? undefined) ?? 'You';
  const handle = profile.data?.handle ?? null;
  const open = (url: string) => WebBrowser.openBrowserAsync(url);

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
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
          Your account
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
            else router.replace('/profile');
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
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{
          paddingTop: Spacing.three,
          paddingBottom: BottomTabInset + insets.bottom + Spacing.five,
        }}>
        {/* Who this is all about, and the two things most often wanted
            from it. On a tinted card rather than loose at the top: it
            is the subject of the page, not its first row. */}
        <View
          style={{
            marginHorizontal: Spacing.three,
            padding: Spacing.three,
            gap: Spacing.three,
            borderRadius: Radius.lg,
            borderCurve: 'continuous',
            backgroundColor: colors.backgroundElement,
          }}>
          <View
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: Spacing.three,
            }}>
            <Monogram
              name={name}
              id={me.data?.userId}
              uri={photo}
              size={64}
            />
            <View style={{ flex: 1, gap: Spacing.half }}>
              <ThemedText style={labelType(22, 800)} numberOfLines={1}>
                {name}
              </ThemedText>
              <ThemedText
                themeColor="textSecondary"
                numberOfLines={1}
                style={labelType(FontSize.body, 400)}>
                {handle ? `@${handle}` : 'No handle yet'}
              </ThemedText>
            </View>
          </View>

          <View style={{ flexDirection: 'row', gap: Spacing.two }}>
            <CardButton
              label="View profile"
              onPress={() => router.replace('/profile')}
            />
            <CardButton
              label="Share profile"
              onPress={() =>
                void Share.share({
                  message: handle
                    ? `Find me on ${BRAND.name}: @${handle}`
                    : `Find me on ${BRAND.name}.`,
                })
              }
            />
          </View>
        </View>

        <Heading>Settings</Heading>
        <Row
          label="Edit your profile"
          onPress={() => router.push('/profile-edit')}
        />
        <Row
          label="Profile visibility"
          hint={
            profile.data?.private
              ? 'Private. Only you see your fits and your lists.'
              : 'Public. Anybody can see what you post.'
          }
          onPress={() => router.push('/profile-edit')}
        />
        <Row
          label="Notifications"
          onPress={() => router.push('/notification-settings')}
        />
        {/* Withdrawable in the tap that granted it, which is the only
            arrangement a consent can honestly have. */}
        <Row
          label="Styling uses your wardrobe"
          state={aiGranted ? 'On' : 'Off'}
          onPress={() =>
            setConsent.mutate({
              kind: 'ai_processing',
              granted: !aiGranted,
              source: 'profile',
            })
          }
        />
        {/* Worded for everything the grant covers, not just the feed:
            it also releases the count of saved looks you have in common
            on a suggestion card, which reaches people who do not follow
            you. */}
        <Row
          label="Others can see what you keep"
          state={sharing ? 'On' : 'Off'}
          onPress={() =>
            setConsent.mutate({
              kind: 'community_sharing',
              granted: !sharing,
              source: 'profile',
            })
          }
        />
        <Row
          label="Plan and billing"
          onPress={() => router.push('/subscription')}
        />
        <Row label="Privacy policy" away onPress={() => open(BRAND.urls.privacy)} />
        <Row label="Terms" away onPress={() => open(BRAND.urls.terms)} />
        <Row
          label="Content policy"
          away
          onPress={() => open(BRAND.urls.contentPolicy)}
        />
        <Row label="Support" away onPress={() => open(BRAND.support.url)} />

        <Heading>Account</Heading>
        {/* **It was a disabled row saying "Phase D".**
            A control somebody looking for their data finds, taps, and
            nothing happens - which is worse than not offering it,
            because they have been told it exists.

            One row with three behaviours rather than three rows,
            because to the person tapping it there is one thing here:
            get my data. What the row says and what the tap does both
            follow the state. */}
        <Row
          label={
            myExport.data?.state === 'ready' ? 'Save my copy' : 'Export my data'
          }
          hint={exportLine(myExport.data)}
          plain
          onPress={
            myExport.data?.state === 'gathering' || askForExport.isPending
              ? // Deliberately inert while it gathers. The row says
                // so, and a second tap cannot start a second gather
                // anyway - the server hands back the one running.
                undefined
              : () => {
                  void tapFeedback();
                  const ready = myExport.data?.state === 'ready';
                  if (ready && myExport.data) {
                    saveExport.mutate(myExport.data.id, {
                      onError: (caught) =>
                        Alert.alert(
                          'That did not work',
                          caught instanceof Error
                            ? caught.message
                            : 'Try again in a moment.',
                        ),
                    });
                    return;
                  }
                  // Said before it starts, because the wait is long
                  // enough that an unexplained one reads as a hang,
                  // and because what the file contains is worth
                  // knowing before it is on somebody's phone.
                  Alert.alert(
                    'Get a copy of your data?',
                    'Your fits, wardrobe, boards, plans, messages and ' +
                      'pictures, as one file. It takes a few minutes and ' +
                      'the download works for two days.',
                    [
                      { text: 'Not now', style: 'cancel' },
                      {
                        text: 'Get my copy',
                        onPress: () =>
                          askForExport.mutate(undefined, {
                            onError: () =>
                              Alert.alert(
                                'That did not work',
                                'Try again in a moment.',
                              ),
                          }),
                      },
                    ],
                  );
                }
          }
        />
        <Row
          label="Delete account"
          plain
          onPress={() => {
            void tapFeedback();
            // **Asked properly, because it cannot be undone.** The
            // server soft-deletes, releases the email address for a
            // future signup, and revokes every session - there is no
            // screen afterwards on which somebody could change their
            // mind.
            Alert.alert(
              'Delete your account?',
              'Your fits, your wardrobe and your messages go, and this cannot be undone.',
              [
                { text: 'Keep my account', style: 'cancel' },
                {
                  text: 'Delete',
                  style: 'destructive',
                  onPress: () => {
                    closeAccount.mutate(undefined, {
                      onSuccess: () => {
                        void (async () => {
                          // The token is already dead - the server
                          // revoked it - so this is clearing what is
                          // left on the phone, not ending a session.
                          await auth.signOut();
                          router.replace('/welcome');
                        })();
                      },
                      onError: (caught) =>
                        Alert.alert(
                          'That did not work',
                          caught instanceof Error
                            ? caught.message
                            : 'Try again in a moment.',
                        ),
                    });
                  },
                },
              ],
            );
          }}
        />
        <Row
          label="Log out"
          plain
          onPress={() => {
            void (async () => {
              await auth.signOut();
              // Back to the introduction. `replace` so the tabs are not
              // behind it: a signed-out person pressing back into a
              // wardrobe they can no longer load is a worse ending than
              // the screen they just came from.
              router.replace('/welcome');
            })();
          }}
        />

        {BRAND.isWorkingName ? (
          <ThemedText
            themeColor="textSecondary"
            style={{
              paddingHorizontal: Spacing.three,
              paddingTop: Spacing.four,
              ...labelType(FontSize.footnote, 400),
            }}>
            {BRAND.name} is a working name. Branding is centralised, so the
            final name replaces it in one place.
          </ThemedText>
        ) : null}
      </ScrollView>
    </View>
  );
}

/** One of the two controls on the identity card. */
function CardButton({ label, onPress }: { label: string; onPress: () => void }) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      animateEntrance={false}
      scale={0.97}
      onPress={() => {
        void tapFeedback();
        onPress();
      }}
      style={{
        flex: 1,
        minHeight: TapTarget,
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: Radius.md,
        borderCurve: 'continuous',
        backgroundColor: colors.background,
      }}>
      <ThemedText style={labelType(FontSize.body, 800)}>{label}</ThemedText>
    </MotionPressable>
  );
}

/** A group name. Quiet, because the rows under it are the screen. */
function Heading({ children }: { children: string }) {
  return (
    <ThemedText
      accessibilityRole="header"
      themeColor="textSecondary"
      style={{
        paddingHorizontal: Spacing.three,
        paddingTop: Spacing.five,
        paddingBottom: Spacing.one,
        ...labelType(FontSize.body, 400),
      }}>
      {children}
    </ThemedText>
  );
}

/**
 * One row.
 *
 * The thing on the right says what kind of row it is: a chevron for a
 * screen in this app, an arrow for one that leaves, a word for a
 * switch and its state, nothing for an action taken in place.
 */
function Row({
  label,
  hint,
  state,
  away,
  plain,
  onPress,
}: {
  label: string;
  hint?: string;
  /** A switch, and the word is its current position. */
  state?: string;
  /** Leaves the app for a browser. */
  away?: boolean;
  /** Happens here and now, so there is nowhere to point. */
  plain?: boolean;
  onPress?: () => void;
}) {
  const colors = Colors[useScheme()];
  const disabled = !onPress;

  return (
    <MotionPressable
      accessibilityRole={disabled ? 'text' : away ? 'link' : 'button'}
      accessibilityState={{ disabled }}
      accessibilityHint={hint}
      disabled={disabled}
      // A row is wide, so a visible scale reads as the whole screen
      // moving rather than as the row being pressed.
      scale={0.99}
      animatePress={!disabled}
      haptic={!disabled}
      animateEntrance={false}
      onPress={onPress}
      style={{
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
        {hint ? (
          <ThemedText
            themeColor="textSecondary"
            style={labelType(FontSize.subhead, 400)}>
            {hint}
          </ThemedText>
        ) : null}
      </View>

      {state ? (
        <ThemedText
          themeColor="textSecondary"
          style={labelType(FontSize.body, 400)}>
          {state}
        </ThemedText>
      ) : plain ? null : (
        <SymbolView
          name={
            away
              ? {
                  ios: 'arrow.up.right',
                  android: 'arrow_outward',
                  web: 'arrow_outward',
                }
              : {
                  ios: 'chevron.right',
                  android: 'chevron_right',
                  web: 'chevron_right',
                }
          }
          size={18}
          tintColor={colors.text}
        />
      )}
    </MotionPressable>
  );
}
