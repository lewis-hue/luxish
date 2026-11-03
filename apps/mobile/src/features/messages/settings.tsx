import { router } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { Alert, Modal, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useSetBlocked } from '@/api/queries/community';
import { greetingName, useMe } from '@/api/queries/me';
import {
  useClearThread,
  useThread,
  useThreadSettings,
} from '@/api/queries/messages';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { Monogram } from '@/components/ui/monogram';
import {
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
 * What a conversation can be done about.
 *
 * **Block is on the row of the person it applies to.** A list of two
 * names with one button is the clearest statement there is of who is
 * being blocked, and it is the control messages were always gated on.
 *
 * **The consequence is written down, not implied.** Blocking removes
 * every conversation they are part of, and somebody should read that
 * before they tap it rather than discover it afterwards.
 *
 * **Hiding is not deleting, and the copy says which it is.** Their
 * copy is theirs, and a new message brings this one back — a hidden
 * conversation that swallowed messages would be a delivery failure
 * wearing a preference.
 */
export function MessageSettings({
  userId,
  name,
  visible,
  onClose,
}: {
  userId: string;
  name: string;
  visible: boolean;
  onClose: () => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const auth = useAuth();
  const me = useMe(auth.status === 'signedIn' && visible);
  const thread = useThread(userId, visible);
  const settings = useThreadSettings(userId);
  const clear = useClearThread();
  const setBlocked = useSetBlocked();

  const notifies = thread.data?.notifies !== false;
  const hidden = Boolean(thread.data?.hidden);
  const mine = greetingName(me.data ?? undefined) ?? 'You';

  const confirmBlock = () =>
    Alert.alert(
      `Block ${name}?`,
      'Every conversation they are part of is removed, they stop appearing anywhere in your app, and any follows between you end. They are not told.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Block',
          style: 'destructive',
          onPress: () => {
            setBlocked.mutate({ userId, blocked: true });
            onClose();
            if (router.canGoBack()) router.back();
            else router.replace('/messages');
          },
        },
      ],
    );

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <View
        style={{
          flex: 1,
          backgroundColor: colors.background,
          paddingTop: insets.top,
        }}>
        <View
          style={{
            minHeight: TapTarget,
            justifyContent: 'center',
            paddingHorizontal: Spacing.three,
          }}>
          <ThemedText
            accessibilityRole="header"
            style={{ ...labelType(FontSize.body, 800), textAlign: 'center' }}>
            Message settings
          </ThemedText>
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Back"
            animateEntrance={false}
            scale={0.92}
            hitSlop={8}
            onPress={() => {
              void tapFeedback();
              onClose();
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

        <View style={{ paddingTop: Spacing.four, gap: Spacing.two }}>
          <Person name={mine} id={me.data?.userId} />
          <Person name={name} id={userId}>
            <MotionPressable
              accessibilityRole="button"
              accessibilityLabel={`Block ${name}`}
              animateEntrance={false}
              scale={0.96}
              onPress={() => {
                void tapFeedback();
                confirmBlock();
              }}
              style={{
                minHeight: 40,
                justifyContent: 'center',
                paddingHorizontal: Spacing.four,
                borderRadius: Radius.md,
                borderCurve: 'continuous',
                backgroundColor: colors.backgroundElement,
              }}>
              <ThemedText style={labelType(FontSize.subhead, 800)}>
                Block
              </ThemedText>
            </MotionPressable>
          </Person>

          <ThemedText
            themeColor="textSecondary"
            style={{
              paddingHorizontal: Spacing.three,
              paddingTop: Spacing.two,
              ...labelType(FontSize.subhead, 400),
            }}>
            If you block someone, every conversation they are part of is
            removed.
          </ThemedText>

          <ThemedText
            accessibilityRole="header"
            style={{
              paddingHorizontal: Spacing.three,
              paddingTop: Spacing.four,
              ...labelType(FontSize.title3, 800),
            }}>
            Notifications
          </ThemedText>
          <MotionPressable
            accessibilityRole="switch"
            accessibilityState={{ checked: notifies }}
            accessibilityLabel={`Notifications ${notifies ? 'on' : 'off'}`}
            accessibilityHint="Whether a new message here reaches you"
            animateEntrance={false}
            scale={0.99}
            onPress={() => {
              void tapFeedback();
              settings.mutate({ notifies: !notifies });
            }}
            style={{
              minHeight: TapTarget,
              justifyContent: 'center',
              paddingHorizontal: Spacing.three,
            }}>
            <ThemedText style={labelType(FontSize.title3, 400)}>
              {notifies ? 'On' : 'Off'}
            </ThemedText>
          </MotionPressable>

          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel={`Report ${name}`}
            animateEntrance={false}
            scale={0.99}
            onPress={() => {
              void tapFeedback();
              onClose();
              router.push({
                pathname: '/member/[id]',
                params: { id: userId, report: '1' },
              });
            }}
            style={{
              minHeight: TapTarget + Spacing.two,
              justifyContent: 'center',
              paddingHorizontal: Spacing.three,
            }}>
            <ThemedText style={labelType(FontSize.title3, 800)}>
              Report conversation
            </ThemedText>
          </MotionPressable>

          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel={
              hidden ? 'Unhide this conversation' : 'Hide this conversation'
            }
            accessibilityHint="Hiding takes it off your list. A new message brings it back."
            animateEntrance={false}
            scale={0.99}
            onPress={() => {
              void tapFeedback();
              settings.mutate({ hidden: !hidden });
              if (!hidden) {
                onClose();
                if (router.canGoBack()) router.back();
                else router.replace('/messages');
              }
            }}
            style={{
              minHeight: TapTarget + Spacing.two,
              justifyContent: 'center',
              paddingHorizontal: Spacing.three,
            }}>
            <ThemedText style={labelType(FontSize.title3, 800)}>
              {hidden ? 'Unhide conversation' : 'Hide conversation'}
            </ThemedText>
          </MotionPressable>

          {/* Deleting is not hiding, and the difference is worth the
              second row: hiding takes a conversation off your list
              until something new arrives, deleting draws a line under
              everything in it. Neither reaches into their copy. */}
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Delete this conversation"
            accessibilityHint="Clears it for you. Their copy is theirs."
            animateEntrance={false}
            scale={0.99}
            onPress={() => {
              void tapFeedback();
              Alert.alert(
                'Delete this conversation?',
                'It goes from your list and everything in it is cleared for you. Their copy is theirs, and anything they send after this still arrives.',
                [
                  { text: 'Cancel', style: 'cancel' },
                  {
                    text: 'Delete',
                    style: 'destructive',
                    onPress: () => {
                      clear.mutate(userId);
                      onClose();
                      if (router.canGoBack()) router.back();
                      else router.replace('/messages');
                    },
                  },
                ],
              );
            }}
            style={{
              minHeight: TapTarget + Spacing.two,
              justifyContent: 'center',
              paddingHorizontal: Spacing.three,
            }}>
            <ThemedText
              style={{
                ...labelType(FontSize.title3, 800),
                color: colors.danger,
              }}>
              Delete conversation
            </ThemedText>
          </MotionPressable>
        </View>
      </View>
    </Modal>
  );
}

function Person({
  name,
  id,
  children,
}: {
  name: string;
  /** Their account, so the monogram's ground matches it elsewhere. */
  id?: string;
  children?: React.ReactNode;
}) {
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.three,
        minHeight: TapTarget,
        paddingHorizontal: Spacing.three,
      }}>
      <Monogram name={name} id={id} size={40} />
      <ThemedText style={{ flex: 1, ...labelType(FontSize.body, 400) }}>
        {name}
      </ThemedText>
      {children}
    </View>
  );
}
