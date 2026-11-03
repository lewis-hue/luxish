import { router } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { useState } from 'react';
import { ScrollView, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { MIN_PEOPLE_QUERY, usePeopleSearch } from '@/api/queries/community';
import { useMessages } from '@/api/queries/messages';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { Monogram } from '@/components/ui/monogram';
import { SkeletonText } from '@/components/ui/skeleton';
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

interface Pick {
  userId: string;
  name: string;
  handle: string | null;
}

/**
 * Who to write to.
 *
 * **Contacts first, search when they are not among them.** The people
 * already connected to this account cover nearly every message
 * anybody sends, and making somebody type a name they can see on the
 * screen is a step for nothing.
 *
 * **Next is disabled until somebody is chosen**, rather than absent:
 * a control that appears when a condition is met is one nobody knew
 * was coming, and the greyed one says what the screen is waiting for.
 *
 * **Choosing does not start a conversation.** Nothing is created until
 * a message is actually sent, so backing out of the thread leaves no
 * row on anybody's list.
 */
export default function NewMessageScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';

  const [query, setQuery] = useState('');
  const [chosen, setChosen] = useState<Pick | null>(null);

  const messages = useMessages(signedIn);
  const searching = query.trim().length >= MIN_PEOPLE_QUERY;
  const found = usePeopleSearch(query, signedIn && searching);

  const needle = query.trim().toLowerCase();
  const contacts = (messages.data?.contacts ?? []).filter(
    (person) => !needle || person.name.toLowerCase().includes(needle),
  );
  const people: Pick[] = searching
    ? (found.data ?? []).map((person) => ({
        userId: person.userId,
        name: person.name,
        handle: null,
      }))
    : contacts.map((person) => ({
        userId: person.userId,
        name: person.name,
        handle: person.handle,
      }));

  const open = () => {
    if (!chosen) return;
    void tapFeedback();
    router.replace({
      pathname: '/messages/[id]',
      params: { id: chosen.userId, name: chosen.name },
    });
  };

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
          New message
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
            else router.replace('/messages');
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
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Next"
          accessibilityState={{ disabled: chosen === null }}
          disabled={chosen === null}
          animateEntrance={false}
          scale={0.96}
          onPress={open}
          style={{
            position: 'absolute',
            right: Spacing.three,
            minHeight: 40,
            justifyContent: 'center',
            paddingHorizontal: Spacing.three,
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            backgroundColor: chosen ? colors.accent : colors.backgroundElement,
          }}>
          <ThemedText
            style={{
              ...labelType(FontSize.subhead, 800),
              color: chosen ? colors.accentText : colors.textSecondary,
            }}>
            Next
          </ThemedText>
        </MotionPressable>
      </View>

      <View style={{ padding: Spacing.three }}>
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            gap: Spacing.two,
            minHeight: TapTarget + Spacing.one,
            paddingHorizontal: Spacing.three,
            borderRadius: Radius.full,
            borderWidth: 1,
            borderColor: colors.borderStrong,
          }}>
          <SymbolView
            name={{ ios: 'magnifyingglass', android: 'search', web: 'search' }}
            size={18}
            tintColor={colors.textSecondary}
          />
          <TextInput
            value={query}
            onChangeText={setQuery}
            placeholder="Search people"
            placeholderTextColor={colors.textSecondary}
            accessibilityLabel="Search people"
            autoCapitalize="none"
            autoCorrect={false}
            style={{
              flex: 1,
              paddingVertical: Spacing.two,
              color: colors.text,
              ...labelType(FontSize.body, 400),
            }}
          />
        </View>
      </View>

      <ScrollView
        automaticallyAdjustKeyboardInsets
        keyboardDismissMode="interactive"
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{ paddingBottom: insets.bottom + Spacing.five }}>
        {messages.isPending || (searching && found.isPending) ? (
          <View style={{ paddingHorizontal: Spacing.three }}>
            <SkeletonText lines={4} />
          </View>
        ) : people.length === 0 ? (
          <ThemedText
            themeColor="textSecondary"
            style={{
              paddingHorizontal: Spacing.three,
              ...labelType(FontSize.subhead, 400),
            }}>
            {searching
              ? `Nobody called "${query.trim()}" has published a fit. People become findable by posting one.`
              : 'Follow somebody and they show up here.'}
          </ThemedText>
        ) : (
          people.map((person) => {
            const picked = chosen?.userId === person.userId;
            return (
              <MotionPressable
                key={person.userId}
                accessibilityRole="radio"
                accessibilityState={{ checked: picked }}
                accessibilityLabel={person.name}
                animateEntrance={false}
                scale={0.99}
                onPress={() => {
                  void tapFeedback();
                  setChosen(picked ? null : person);
                }}
                style={{
                  flexDirection: 'row',
                  alignItems: 'center',
                  gap: Spacing.three,
                  minHeight: TapTarget + Spacing.two,
                  paddingHorizontal: Spacing.three,
                  backgroundColor: picked
                    ? colors.backgroundSelected
                    : 'transparent',
                }}>
                <Monogram name={person.name} id={person.userId} />
                <View style={{ flex: 1, gap: Spacing.half }}>
                  <ThemedText
                    style={labelType(FontSize.body, 800)}
                    numberOfLines={1}>
                    {person.name}
                  </ThemedText>
                  {person.handle ? (
                    <ThemedText
                      themeColor="textSecondary"
                      numberOfLines={1}
                      style={labelType(FontSize.subhead, 400)}>
                      @{person.handle}
                    </ThemedText>
                  ) : null}
                </View>
                {picked ? (
                  <SymbolView
                    name={{
                      ios: 'checkmark.circle.fill',
                      android: 'check_circle',
                      web: 'check_circle',
                    }}
                    size={22}
                    tintColor={colors.accent}
                  />
                ) : null}
              </MotionPressable>
            );
          })
        )}
      </ScrollView>
    </View>
  );
}
