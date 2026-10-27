import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { TextInput, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { EmptyState } from '@/components/ui/empty-state';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import { Screen } from '@/components/ui/screen';
import { SkeletonText, useDelayedVisible } from '@/components/ui/skeleton';
import {
  Colors,
  Display,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  Tracking,
  toneColor,
} from '@/constants/theme';
import { useFavouriteGarments } from '@/features/discover/saved';
import { lookById, ownedCount } from '@/features/discover/looks';
import { DRESS_CODES } from '@/features/taxonomy';
import { useWardrobe } from '@/features/wardrobe/store';
import { useScheme } from '@/hooks/use-theme';

/**
 * Ask for an outfit built from clothes the user already owns.
 *
 * The screen leads with the request rather than with a chat transcript. A
 * centred text box plus a row of suggestion chips is now the default shape of
 * every AI product, and it is the shape users have learned to ignore; what
 * makes this one different is that it opens already knowing the wardrobe it
 * will style from, and says so.
 *
 * It is also deliberately not called an assistant or a chatbot. NET-A-PORTER
 * and MR PORTER both frame the same capability as a Personal Shopper, which
 * is a service word rather than a technology word, and reads as something a
 * fashion house offers rather than a feature someone bolted on.
 */

/** Enough garments to combine into something worth showing. */
const MINIMUM_GARMENTS = 4;

const PROMPTS = [
  'Something for the office tomorrow',
  'Dinner, smart but not stiff',
  'Weekend, walking a lot',
  'Cold morning, warm evening',
] as const;

type RunState =
  | { status: 'idle' }
  | { status: 'running' }
  | { status: 'failed'; title: string; body: string };

export default function StylistScreen() {
  const colors = Colors[useScheme()];
  const favourites = useFavouriteGarments();
  const wardrobe = useWardrobe(favourites.values);

  // Arriving from a look carries it as the subject of the question. Read
  // straight into the initial state rather than synced from an effect: an
  // effect would render the empty field first and then replace it, which
  // flashes.
  const { look: lookId } = useLocalSearchParams<{ look?: string }>();
  const subject = lookId ? lookById(lookId) : undefined;

  const [request, setRequest] = useState(
    subject ? `Something like ${subject.title}` : '',
  );
  const [dressCode, setDressCode] = useState<string | null>(null);
  const [run, setRun] = useState<RunState>({ status: 'idle' });

  const wearable = wardrobe.entries.filter(
    (entry) => entry.availability === 'available' && !entry.isSample,
  );
  const ready = wearable.length >= MINIMUM_GARMENTS;
  const thinking = useDelayedVisible(run.status === 'running');

  const ask = async () => {
    void tapFeedback();
    setRun({ status: 'running' });
    // The run itself is a backend call, and the backend needs a signed-in
    // session. Until sign-in is reachable this reports the real reason rather
    // than spinning forever or inventing an outfit locally, which would be
    // the one genuinely dishonest option.
    setRun({
      status: 'failed',
      title: 'Sign in to use the stylist',
      body: 'Styling runs on the server so it can see your whole wardrobe.',
    });
  };

  return (
    <Screen scroll>
      <View style={{ gap: Spacing.one, marginBottom: Spacing.four }}>
        <ThemedText
          style={{ fontFamily: Display.regular, fontSize: 40, lineHeight: 44 }}>
          Stylist
        </ThemedText>
        <ThemedText type="small" themeColor="textSecondary">
          Outfits from the clothes you already own.
        </ThemedText>
      </View>

      {/* What it has to work with. Stated up front because an outfit built
          from four garments and one built from forty are different promises,
          and the user is the only one who can fix a thin wardrobe. */}
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: Spacing.two,
          padding: Spacing.three,
          borderRadius: Radius.md,
          borderCurve: 'continuous',
          backgroundColor: colors.backgroundElement,
          marginBottom: Spacing.four,
        }}>
        <View
          style={{
            width: 8,
            height: 8,
            borderRadius: Radius.full,
            backgroundColor: toneColor(colors, ready ? 'success' : 'warning'),
          }}
        />
        <ThemedText type="small" style={{ flex: 1, fontSize: FontSize.footnote }}>
          {ready
            ? `${wearable.length} garments ready to wear`
            : `Add ${MINIMUM_GARMENTS - wearable.length} more to start styling`}
          {favourites.count > 0 ? `, ${favourites.count} loved` : ''}
        </ThemedText>
      </View>

      {subject ? (
        <View
          style={{
            gap: Spacing.one,
            padding: Spacing.three,
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            borderWidth: 1,
            borderColor: colors.borderStrong,
            marginBottom: Spacing.four,
          }}>
          <Label>Asking about</Label>
          <ThemedText type="small" style={{ fontSize: FontSize.subhead }}>
            {subject.title}
          </ThemedText>
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ fontSize: FontSize.caption }}>
            {subject.pieces.length} pieces, {ownedCount(subject)} in your wardrobe
          </ThemedText>
        </View>
      ) : null}

      <View style={{ gap: Spacing.three }}>
        <Label>What is the occasion</Label>

        <TextInput
          value={request}
          onChangeText={setRequest}
          placeholder="Describe where you are going"
          placeholderTextColor={colors.textSecondary}
          multiline
          accessibilityLabel="Describe where you are going"
          style={{
            minHeight: 96,
            padding: Spacing.three,
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            borderWidth: 1,
            // An input is bounded by its border, so it needs 3:1 per WCAG
            // 1.4.11. The hairline `border` is 1.32:1 and fails it.
            borderColor: colors.borderStrong,
            backgroundColor: colors.backgroundElement,
            color: colors.text,
            fontSize: FontSize.body,
            textAlignVertical: 'top',
          }}
        />

        {/* Prompts, not "suggestions": they fill the field so the user can
            edit rather than committing them to a phrasing they did not write. */}
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two }}>
          {PROMPTS.map((prompt) => (
            <Chip
              key={prompt}
              label={prompt}
              onPress={() => {
                void tapFeedback();
                setRequest(prompt);
              }}
            />
          ))}
        </View>

        <Label>Dress code</Label>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two }}>
          {DRESS_CODES.slice(0, 6).map((code) => (
            <Chip
              key={code.id}
              label={code.label}
              active={dressCode === code.id}
              onPress={() => {
                void tapFeedback();
                setDressCode(dressCode === code.id ? null : code.id);
              }}
            />
          ))}
        </View>

        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Style me"
          accessibilityState={{
            disabled: !ready || run.status === 'running',
            busy: run.status === 'running',
          }}
          disabled={!ready || run.status === 'running'}
          animateEntrance={false}
          onPress={() => void ask()}
          style={{
            minHeight: TapTarget + 6,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            backgroundColor: colors.accent,
            opacity: ready && run.status !== 'running' ? 1 : 0.45,
          }}>
          <ThemedText type="smallBold" style={{ color: colors.accentText }}>
            {run.status === 'running' ? 'Styling' : 'Style me'}
          </ThemedText>
        </MotionPressable>
      </View>

      <View style={{ marginTop: Spacing.four }}>
        {/* Held back 400ms: under a second, a placeholder flashing in and out
            reads as a glitch rather than as progress. */}
        {thinking ? (
          <View
            style={{
              gap: Spacing.three,
              padding: Spacing.three,
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              backgroundColor: colors.backgroundElement,
            }}>
            <Label>Putting a look together</Label>
            <SkeletonText lines={3} />
          </View>
        ) : null}

        {run.status === 'failed' ? (
          <EmptyState status="blocked" title={run.title} body={run.body} />
        ) : null}

        {run.status === 'idle' && !ready ? (
          <EmptyState
            status="empty"
            title="Your wardrobe is nearly ready"
            body="Add a few more garments and the stylist can start."
          />
        ) : null}
      </View>
    </Screen>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <ThemedText
      type="small"
      themeColor="textSecondary"
      style={{
        fontSize: FontSize.meta,
        letterSpacing: Tracking.wide,
        textTransform: 'uppercase',
      }}>
      {children}
    </ThemedText>
  );
}

function Chip({
  label,
  active,
  onPress,
}: {
  label: string;
  active?: boolean;
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      animateEntrance={false}
      scale={0.97}
      onPress={onPress}
      style={{
        minHeight: 36,
        justifyContent: 'center',
        paddingHorizontal: Spacing.three,
        borderRadius: Radius.full,
        backgroundColor: active ? colors.text : 'transparent',
        borderWidth: 1,
        borderColor: active ? colors.text : colors.borderStrong,
      }}>
      <ThemedText
        type="small"
        style={{
          fontSize: FontSize.footnote,
          color: active ? colors.background : colors.textSecondary,
        }}>
        {label}
      </ThemedText>
    </MotionPressable>
  );
}
