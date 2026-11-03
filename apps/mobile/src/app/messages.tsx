import { router } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { Share, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useMessages, type Contact, type ThreadSummary } from '@/api/queries/messages';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { Monogram } from '@/components/ui/monogram';
import { usePullToRefresh } from '@/components/ui/pull-to-refresh';
import { SkeletonRows } from '@/components/ui/skeleton';
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
 * Messages: who you are talking to, and who you could be.
 *
 * **Conversations first, contacts under them.** A list of people you
 * have never written to is the right thing to show on an empty
 * screen and the wrong thing to show above a conversation waiting for
 * a reply.
 *
 * **Contacts are the people already connected to this account.** A
 * phone's address book is somebody else's data and asking for it to
 * fill a list is the kind of permission prompt that gets an app
 * deleted. Following somebody is reason enough to write to them.
 *
 * **Inviting is a share sheet, not a form.** The app has nothing to
 * send an invitation with — no address book, no email — so this hands
 * the link to whatever the phone already uses for that.
 */
export default function MessagesScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';
  const messages = useMessages(signedIn);
  const refresh = usePullToRefresh();

  const threads = messages.data?.threads ?? [];
  const contacts = messages.data?.contacts ?? [];

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
          Messages
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
            else router.replace('/');
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
          accessibilityLabel="Start a conversation"
          animateEntrance={false}
          scale={0.92}
          hitSlop={8}
          onPress={() => {
            void tapFeedback();
            // Writing to somebody starts by finding them, and the app
            // already has one screen for that.
            router.push('/search');
          }}
          style={{
            position: 'absolute',
            right: Spacing.three,
            height: TapTarget,
            justifyContent: 'center',
          }}>
          <SymbolView
            name={{ ios: 'square.and.pencil', android: 'edit', web: 'edit' }}
            size={20}
            tintColor={colors.text}
          />
        </MotionPressable>
      </View>

      <ScrollView
        refreshControl={refresh.control}
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{
          paddingTop: Spacing.four,
          paddingBottom: insets.bottom + Spacing.five,
          gap: Spacing.two,
        }}>
        {messages.isPending ? (
          <View style={{ paddingHorizontal: Spacing.three }}>
            <SkeletonRows count={4} label="Loading your messages" />
          </View>
        ) : null}

        {threads.length > 0 ? (
          <>
            <Heading>Conversations</Heading>
            {threads.map((thread) => (
              <ThreadRow key={thread.userId} thread={thread} />
            ))}
            <View style={{ height: Spacing.three }} />
          </>
        ) : null}

        <Heading>Contacts</Heading>

        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Invite your friends"
          animateEntrance={false}
          onPress={() => {
            void tapFeedback();
            void Share.share({
              message:
                'I am keeping my outfits on LUXish. Come and see what I am wearing.',
            });
          }}
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            gap: Spacing.three,
            minHeight: TapTarget + Spacing.two,
            paddingHorizontal: Spacing.three,
          }}>
          <View
            style={{
              width: 48,
              height: 48,
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: colors.backgroundElement,
            }}>
            <SymbolView
              name={{
                ios: 'person.badge.plus',
                android: 'person_add',
                web: 'person_add',
              }}
              size={22}
              tintColor={colors.text}
            />
          </View>
          <ThemedText style={labelType(FontSize.body, 800)}>
            Invite your friends
          </ThemedText>
        </MotionPressable>

        {contacts.map((contact) => (
          <ContactRow key={contact.userId} contact={contact} />
        ))}

        {!messages.isPending && contacts.length === 0 && threads.length === 0 ? (
          <ThemedText
            themeColor="textSecondary"
            style={{
              paddingHorizontal: Spacing.three,
              ...labelType(FontSize.subhead, 400),
            }}>
            Follow somebody and they show up here. You can write to anybody you
            are connected to.
          </ThemedText>
        ) : null}
      </ScrollView>
    </View>
  );
}

function Heading({ children }: { children: string }) {
  return (
    <ThemedText
      accessibilityRole="header"
      style={{
        ...labelType(FontSize.body, 800),
        paddingHorizontal: Spacing.three,
        paddingBottom: Spacing.one,
      }}>
      {children}
    </ThemedText>
  );
}

function ThreadRow({ thread }: { thread: ThreadSummary }) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="link"
      accessibilityLabel={`${thread.name}${
        thread.unread > 0 ? `, ${thread.unread} unread` : ''
      }. ${thread.last ?? 'No messages yet'}`}
      animateEntrance={false}
      onPress={() => {
        void tapFeedback();
        router.push({
          pathname: '/messages/[id]',
          params: { id: thread.userId, name: thread.name },
        });
      }}
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.three,
        minHeight: TapTarget + Spacing.two,
        paddingHorizontal: Spacing.three,
      }}>
      <Monogram name={thread.name} id={thread.userId} />
      <View style={{ flex: 1, gap: Spacing.half }}>
        <ThemedText style={labelType(FontSize.body, 800)} numberOfLines={1}>
          {thread.name}
        </ThemedText>
        <ThemedText
          numberOfLines={1}
          themeColor={thread.unread > 0 ? 'text' : 'textSecondary'}
          style={labelType(FontSize.subhead, thread.unread > 0 ? 800 : 400)}>
          {thread.last ?? ' '}
        </ThemedText>
      </View>
      {thread.unread > 0 ? (
        <View
          style={{
            minWidth: 22,
            height: 22,
            paddingHorizontal: Spacing.half,
            borderRadius: Radius.full,
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: colors.accent,
          }}>
          <ThemedText
            style={{
              ...labelType(FontSize.meta, 800),
              color: colors.accentText,
              fontVariant: ['tabular-nums'],
            }}>
            {thread.unread}
          </ThemedText>
        </View>
      ) : null}
    </MotionPressable>
  );
}

function ContactRow({ contact }: { contact: Contact }) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="link"
      accessibilityLabel={`Write to ${contact.name}`}
      animateEntrance={false}
      onPress={() => {
        void tapFeedback();
        router.push({
          pathname: '/messages/[id]',
          params: { id: contact.userId, name: contact.name },
        });
      }}
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.three,
        minHeight: TapTarget + Spacing.two,
        paddingHorizontal: Spacing.three,
      }}>
      <Monogram name={contact.name} id={contact.userId} />
      <View style={{ flex: 1, gap: Spacing.half }}>
        <ThemedText style={labelType(FontSize.body, 800)} numberOfLines={1}>
          {contact.name}
        </ThemedText>
        {contact.handle ? (
          <ThemedText
            themeColor="textSecondary"
            numberOfLines={1}
            style={labelType(FontSize.subhead, 400)}>
            @{contact.handle}
          </ThemedText>
        ) : null}
      </View>
      <SymbolView
        name={{
          ios: 'chevron.right',
          android: 'chevron_right',
          web: 'chevron_right',
        }}
        size={16}
        tintColor={colors.textSecondary}
      />
    </MotionPressable>
  );
}
