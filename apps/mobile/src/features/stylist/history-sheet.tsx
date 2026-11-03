import { SymbolView } from 'expo-symbols';
import { Alert, Modal, Pressable, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

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
import type { Session } from '@/features/stylist/history';
import { useScheme } from '@/hooks/use-theme';

/**
 * Earlier conversations, as a list you can get back into.
 *
 * **Grouped by when, because that is how anybody looks for one.**
 * Nobody remembers the title of a conversation about a coat; they
 * remember that it was yesterday. Today / Yesterday / This week /
 * Earlier is the whole of the organisation, and it is the real
 * structure of the data rather than decoration - a heading only
 * appears when something falls under it.
 *
 * **Reopening restores the context, not just the text.** The turns go
 * back into the thread, so the next question is sent with the same
 * history it would have had if the app had never been closed. That is
 * the point of keeping them; the list is only how you reach it.
 */

/** Midnight today, as a timestamp. */
function startOfToday(now: number): number {
  const date = new Date(now);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

const DAY = 24 * 60 * 60 * 1000;

interface Band {
  title: string;
  items: Session[];
}

export function bands(sessions: readonly Session[], now = Date.now()): Band[] {
  const today = startOfToday(now);
  const buckets: Band[] = [
    { title: 'Today', items: [] },
    { title: 'Yesterday', items: [] },
    { title: 'This week', items: [] },
    { title: 'Earlier', items: [] },
  ];
  for (const session of sessions) {
    const when = session.updatedAt;
    if (when >= today) buckets[0].items.push(session);
    else if (when >= today - DAY) buckets[1].items.push(session);
    else if (when >= today - 7 * DAY) buckets[2].items.push(session);
    else buckets[3].items.push(session);
  }
  // A heading with nothing under it is furniture.
  return buckets.filter((band) => band.items.length > 0);
}

export function HistorySheet({
  open,
  sessions,
  currentId,
  onClose,
  onResume,
  onForget,
  onForgetAll,
  onStartNew,
}: {
  open: boolean;
  sessions: readonly Session[];
  currentId: string;
  onClose: () => void;
  onResume: (id: string) => void;
  onForget: (id: string) => void;
  onForgetAll: () => void;
  onStartNew: () => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const grouped = bands(sessions);

  return (
    <Modal
      visible={open}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
            paddingTop: Spacing.three,
            paddingHorizontal: Spacing.three,
            paddingBottom: Spacing.two,
            gap: Spacing.three,
          }}>
          <ThemedText
            accessibilityRole="header"
            style={{ ...labelType(22, 800), lineHeight: 28 }}>
            Conversations
          </ThemedText>
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Close"
            animateEntrance={false}
            onPress={() => {
              void tapFeedback();
              onClose();
            }}
            style={{
              width: TapTarget,
              height: TapTarget,
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: Radius.full,
            }}>
            <SymbolView
              name={{ ios: 'xmark', android: 'close', web: 'close' }}
              size={18}
              tintColor={colors.text}
            />
          </MotionPressable>
        </View>

        <ScrollView
          contentInsetAdjustmentBehavior="automatic"
          contentContainerStyle={{
            paddingHorizontal: Spacing.three,
            paddingBottom: insets.bottom + Spacing.five,
            gap: Spacing.four,
          }}>
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Start a new conversation"
            animateEntrance={false}
            onPress={() => {
              void tapFeedback();
              onStartNew();
              onClose();
            }}
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              gap: Spacing.two,
              minHeight: TapTarget,
              paddingHorizontal: Spacing.three,
              borderRadius: Radius.lg,
              borderCurve: 'continuous',
              borderWidth: 1,
              borderColor: colors.borderStrong,
            }}>
            <SymbolView
              name={{ ios: 'plus', android: 'add', web: 'add' }}
              size={16}
              tintColor={colors.text}
            />
            <ThemedText type="smallBold">New conversation</ThemedText>
          </MotionPressable>

          {grouped.length === 0 ? (
            <ThemedText
              type="small"
              themeColor="textSecondary"
              style={labelType(FontSize.footnote, 400)}>
              Nothing yet. What you ask the stylist is kept on this phone so
              you can pick a conversation back up.
            </ThemedText>
          ) : null}

          {grouped.map((band) => (
            <View key={band.title} style={{ gap: Spacing.one }}>
              <ThemedText
                type="smallBold"
                themeColor="textSecondary"
                style={{ fontSize: FontSize.footnote }}>
                {band.title}
              </ThemedText>
              {band.items.map((session) => (
                <Row
                  key={session.id}
                  session={session}
                  current={session.id === currentId}
                  onResume={() => {
                    void tapFeedback();
                    onResume(session.id);
                    onClose();
                  }}
                  onForget={() => onForget(session.id)}
                />
              ))}
            </View>
          ))}

          {sessions.length > 0 ? (
            <MotionPressable
              accessibilityRole="button"
              accessibilityLabel="Forget every conversation"
              animateEntrance={false}
              onPress={() => {
                // Irreversible and local, so it is confirmed. An
                // Alert rather than a custom dialog: this is exactly
                // the consequential-action case the platform one is
                // for.
                Alert.alert(
                  'Forget every conversation?',
                  'They are only on this phone, so this cannot be undone.',
                  [
                    { text: 'Keep them', style: 'cancel' },
                    {
                      text: 'Forget all',
                      style: 'destructive',
                      onPress: () => onForgetAll(),
                    },
                  ],
                );
              }}
              style={{ minHeight: TapTarget, justifyContent: 'center' }}>
              <ThemedText type="small" style={{ color: colors.danger }}>
                Forget every conversation
              </ThemedText>
            </MotionPressable>
          ) : null}
        </ScrollView>
      </View>
    </Modal>
  );
}

function Row({
  session,
  current,
  onResume,
  onForget,
}: {
  session: Session;
  current: boolean;
  onResume: () => void;
  onForget: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center' }}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={session.title}
        accessibilityState={{ selected: current }}
        onPress={onResume}
        style={({ pressed }) => ({
          flex: 1,
          minHeight: TapTarget,
          justifyContent: 'center',
          paddingVertical: Spacing.two,
          opacity: pressed ? 0.6 : 1,
        })}>
        <ThemedText
          numberOfLines={1}
          type={current ? 'smallBold' : 'small'}
          style={{ color: current ? colors.accent : colors.text }}>
          {session.title}
        </ThemedText>
      </Pressable>
      <MotionPressable
        accessibilityRole="button"
        accessibilityLabel={`Forget ${session.title}`}
        animateEntrance={false}
        onPress={() => {
          void tapFeedback();
          onForget();
        }}
        style={{
          width: TapTarget,
          height: TapTarget,
          alignItems: 'center',
          justifyContent: 'center',
        }}>
        <SymbolView
          name={{ ios: 'trash', android: 'delete', web: 'delete' }}
          size={15}
          tintColor={colors.textSecondary}
        />
      </MotionPressable>
    </View>
  );
}
