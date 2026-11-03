import { Image } from 'expo-image';
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  DRESS_CODE_LABELS,
  GOAL_LABELS,
  useSetTaste,
  useTaste,
  useTasteOptions,
} from '@/api/queries/taste';
import { ThemedText } from '@/components/themed-text';
import { EmptyState } from '@/components/ui/empty-state';
import { MotionPressable, tapFeedback, successFeedback } from '@/components/ui/motion';
import {
  AspectRatio,
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { useAuth } from '@/features/auth/session';
import { categoryById } from '@/features/discover/collections';
import { coverFor } from '@/features/discover/imagery';
import { markTasteAsked } from '@/features/onboarding/taste';
import { useScheme } from '@/hooks/use-theme';

/**
 * Four questions, asked once.
 *
 * They exist so a brand-new account has something to personalise from on day
 * one — which is the only day it most needs to be good, and the one day there
 * is no interaction history and possibly no wardrobe either.
 *
 * **Asked, never inferred.** The answers are stored as preferences, whose own
 * rule is that a stated preference beats an inference. Nothing here reads
 * taste off somebody's clothes.
 *
 * **It is not a wall.** Skip is a real, equally weighted action, and
 * declining is recorded as an answer rather than leaving the question to be
 * asked again every launch. Browsing already works without an account; this
 * must not be the thing that stops it.
 *
 * **The aesthetics are pictures, not words.** Asking somebody to pick "quiet
 * luxury" from a list of phrases tests whether they read fashion blogs. The
 * covers already exist and a picture is the question a fashion app should
 * ask.
 */
export default function TasteScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';

  const options = useTasteOptions();
  const stored = useTaste(signedIn);
  const save = useSetTaste();

  // Seeded lazily from whatever is stored, so re-opening the screen from
  // Profile shows the existing answers rather than a blank form. An overlay
  // rather than a copy, for the reason the avatar screen uses one: copying
  // server state into state needs an effect to seed it, and that effect
  // overwrites an answer somebody just tapped when a refetch lands.
  const [problem, setProblem] = useState<string | null>(null);
  const [edits, setEdits] = useState<{
    aesthetics?: string[];
    occasions?: string[];
    dressCode?: string;
    goal?: string | null;
  }>({});

  const aesthetics = edits.aesthetics ?? [...(stored.data?.aesthetics ?? [])];
  const occasions = edits.occasions ?? [...(stored.data?.occasions ?? [])];
  const dressCode = edits.dressCode ?? stored.data?.dressCode ?? 'unspecified';
  const goal = edits.goal !== undefined ? edits.goal : (stored.data?.goal ?? null);
  const cap = options.data?.maxChoices ?? 6;

  const toggle = (list: string[], id: string): string[] =>
    list.includes(id) ? list.filter((item) => item !== id) : [...list, id];

  const finish = async (answers: boolean) => {
    void tapFeedback();
    // Recorded either way, and before the save. Declining is an answer, and
    // asking again every launch is how a one-time question becomes nagging —
    // including when the save is what failed.
    await markTasteAsked();
    if (!answers) {
      router.back();
      return;
    }
    try {
      await save.mutateAsync({ aesthetics, occasions, dressCode, goal });
      void successFeedback();
      router.back();
    } catch (caught) {
      // Stay on the screen with the answers intact. Dismissing here would
      // throw away everything somebody just tapped and leave them believing
      // it was recorded.
      setProblem(
        caught instanceof Error && caught.message.trim()
          ? caught.message.trim()
          : 'Your answers could not be saved. Try again in a moment.',
      );
    }
  };

  if (!signedIn) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, justifyContent: 'center' }}>
        <EmptyState
          status="blocked"
          title="Sign in to save your answers"
          body="These shape what Discover shows you, so they are kept with your account."
          action={{ label: 'Sign in', onPress: () => router.push('/sign-in') }}
        />
      </View>
    );
  }

  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={{
        paddingHorizontal: Spacing.three,
        paddingBottom: insets.bottom + Spacing.six,
        gap: Spacing.five,
      }}
      showsVerticalScrollIndicator={false}>
      <View style={{ gap: Spacing.one, marginTop: Spacing.two }}>
        <ThemedText type="label" themeColor="textSecondary">
          Four questions, once
        </ThemedText>
        <ThemedText style={{ ...labelType(40, 800), lineHeight: 44 }}>
          What are you into
        </ThemedText>

      </View>

      <Question
        label="Looks you are drawn to"
        hint={`Pick up to ${cap}`}
        count={aesthetics.length}>
        <View
          style={{
            flexDirection: 'row',
            flexWrap: 'wrap',
            gap: Spacing.two,
          }}>
          {(options.data?.aesthetics ?? []).map((id) => (
            <CoverChoice
              key={id}
              id={id}
              selected={aesthetics.includes(id)}
              // The cap is enforced on the way in rather than by disabling
              // every other tile: a grid that goes dead under your finger
              // with no explanation reads as broken.
              onPress={() => {
                const next = toggle(aesthetics, id);
                if (next.length > cap) return;
                setEdits({ ...edits, aesthetics: next });
              }}
            />
          ))}
        </View>
      </Question>

      <Question label="Where you actually need outfits" hint="Pick any">
        <Chips
          options={(options.data?.occasions ?? []).map((id) => [
            id,
            categoryById(id)?.title ?? id,
          ])}
          selected={occasions}
          onPress={(id) => setEdits({ ...edits, occasions: toggle(occasions, id) })}
        />
      </Question>

      <Question label="How you dress on a working day" hint="Pick one">
        <Chips
          options={(options.data?.dressCodes ?? []).map((id) => [
            id,
            DRESS_CODE_LABELS[id] ?? id,
          ])}
          selected={dressCode === 'unspecified' ? [] : [dressCode]}
          onPress={(id) =>
            setEdits({ ...edits, dressCode: dressCode === id ? 'unspecified' : id })
          }
        />
      </Question>

      <Question label="What you want from this" hint="Pick one">
        <Chips
          options={(options.data?.goals ?? []).map((id) => [id, GOAL_LABELS[id] ?? id])}
          selected={goal ? [goal] : []}
          onPress={(id) => setEdits({ ...edits, goal: goal === id ? null : id })}
        />
      </Question>

      <View style={{ gap: Spacing.two }}>
        {problem ? (
          <View
            style={{
              padding: Spacing.three,
              gap: Spacing.half,
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              borderWidth: 1,
              borderColor: colors.danger,
            }}>
            <ThemedText type="label" style={{ color: colors.danger }}>
              Not saved
            </ThemedText>
            <ThemedText type="small" themeColor="textSecondary">
              {problem}
            </ThemedText>
          </View>
        ) : null}

        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Save my answers"
          accessibilityState={{ busy: save.isPending, disabled: save.isPending }}
          disabled={save.isPending}
          animateEntrance={false}
          onPress={() => void finish(true)}
          style={{
            minHeight: TapTarget + 8,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            backgroundColor: colors.text,
            opacity: save.isPending ? 0.45 : 1,
          }}>
          <ThemedText type="smallBold" style={{ color: colors.background }}>
            {save.isPending ? 'Saving' : 'Save'}
          </ThemedText>
        </MotionPressable>

        {/* Equal weight, deliberately. A skip styled as a whisper under a
            loud primary is a wall with a door painted on it. */}
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Skip these questions"
          disabled={save.isPending}
          animateEntrance={false}
          onPress={() => void finish(false)}
          style={{
            minHeight: TapTarget + 8,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            borderWidth: 1,
            borderColor: colors.borderStrong,
          }}>
          <ThemedText type="smallBold" style={{ color: colors.text }}>
            Skip
          </ThemedText>
        </MotionPressable>

        <ThemedText
          type="small"
          themeColor="textSecondary"
          style={{ fontSize: FontSize.meta, textAlign: 'center' }}>
          Not shared.
        </ThemedText>
      </View>
    </ScrollView>
  );
}

function Question({
  label,
  hint,
  count,
  children,
}: {
  label: string;
  hint: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <View style={{ gap: Spacing.two }}>
      <View style={{ gap: Spacing.half }}>
        <ThemedText type="smallBold">{label}</ThemedText>
        <ThemedText
          type="small"
          themeColor="textSecondary"
          style={{ fontSize: FontSize.footnote }}>
          {/* The count lives in the label rather than in a coloured badge,
              which is the convention every measured retailer uses. */}
          {count ? `${hint} · ${count} chosen` : hint}
        </ThemedText>
      </View>
      {children}
    </View>
  );
}

/**
 * One aesthetic, as its own cover.
 *
 * Selection is carried by a border *and* a visible tick, never by colour
 * alone — WCAG 1.4.1, and on a photograph a tint is easy to miss anyway.
 */
function CoverChoice({
  id,
  selected,
  onPress,
}: {
  id: string;
  selected: boolean;
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  const category = categoryById(id);
  const cover = coverFor(id, category?.title ?? id);
  if (!cover) return null;

  return (
    <Pressable
      accessibilityRole="checkbox"
      accessibilityState={{ checked: selected }}
      accessibilityLabel={category?.title ?? id}
      onPress={() => {
        void tapFeedback();
        onPress();
      }}
      style={({ pressed }) => ({
        width: '31%',
        opacity: pressed ? 0.75 : 1,
        gap: Spacing.half,
      })}>
      <View
        style={{
          aspectRatio: AspectRatio.editorial,
          borderRadius: Radius.sm,
          borderCurve: 'continuous',
          overflow: 'hidden',
          borderWidth: selected ? 2 : 1,
          borderColor: selected ? colors.accent : colors.border,
        }}>
        <Image
          source={cover.thumbSource ?? cover.localSource}
          placeholder={cover.blurhash ? { blurhash: cover.blurhash } : undefined}
          contentFit="cover"
          style={{ width: '100%', height: '100%' }}
        />
        {selected ? (
          <View
            style={{
              position: 'absolute',
              right: Spacing.half,
              top: Spacing.half,
              width: 20,
              height: 20,
              borderRadius: Radius.full,
              backgroundColor: colors.accent,
              alignItems: 'center',
              justifyContent: 'center',
            }}>
            <ThemedText
              type="small"
              style={{ fontSize: FontSize.meta, color: colors.accentText }}>
              ✓
            </ThemedText>
          </View>
        ) : null}
      </View>
      <ThemedText
        type="small"
        themeColor={selected ? 'text' : 'textSecondary'}
        numberOfLines={1}
        style={{ fontSize: FontSize.meta }}>
        {category?.title ?? id}
      </ThemedText>
    </Pressable>
  );
}

/** A row of word answers, for the questions a picture cannot ask. */
function Chips({
  options,
  selected,
  onPress,
}: {
  options: readonly (readonly [string, string])[];
  selected: readonly string[];
  onPress: (id: string) => void;
}) {
  const colors = Colors[useScheme()];

  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.one }}>
      {options.map(([id, label]) => {
        const active = selected.includes(id);
        return (
          <Pressable
            key={id}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
            hitSlop={6}
            onPress={() => {
              void tapFeedback();
              onPress(id);
            }}
            style={({ pressed }) => ({
              minHeight: 34,
              justifyContent: 'center',
              paddingHorizontal: Spacing.three,
              borderRadius: Radius.full,
              backgroundColor: active ? colors.text : 'transparent',
              borderWidth: 1,
              borderColor: active ? colors.text : colors.border,
              opacity: pressed ? 0.6 : 1,
            })}>
            <ThemedText
              type="small"
              style={{
                fontSize: FontSize.footnote,
                color: active ? colors.background : colors.textSecondary,
              }}>
              {label}
            </ThemedText>
          </Pressable>
        );
      })}
    </View>
  );
}
