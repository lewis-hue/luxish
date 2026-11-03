import { SymbolView } from 'expo-symbols';
import { useState } from 'react';
import { Modal, View } from 'react-native';
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
import { useScheme } from '@/hooks/use-theme';

/** What a search is looking through. */
export type SearchKind = 'fits' | 'boards' | 'people';

export interface SearchFilter {
  kind: SearchKind;
  /**
   * Drop fits a machine drew.
   *
   * Honest because it is checkable: nothing on a post records how it
   * was made, so this reads the kind of the pictures on it — a render,
   * a studio shot or an avatar is clothes nobody wore.
   */
  photographsOnly: boolean;
}

export const NO_FILTER: SearchFilter = { kind: 'fits', photographsOnly: false };

export function filtered(filter: SearchFilter): boolean {
  return filter.kind !== NO_FILTER.kind || filter.photographsOnly;
}

const KINDS: { id: SearchKind; label: string }[] = [
  { id: 'fits', label: 'All fits' },
  { id: 'boards', label: 'Boards' },
  { id: 'people', label: 'People' },
];

/**
 * What to narrow a search to.
 *
 * **Nothing applies until Apply.** A filter screen that acts on each
 * tap re-runs the search three times on the way to the combination
 * somebody wanted, and takes the page out from under them while they
 * are still deciding. Changes are held here and handed back at once.
 *
 * **Reset is a separate control from Apply**, because undoing a
 * narrowing is the other half of making one and hunting for the
 * original state tap by tap is how people end up closing the app.
 *
 * **One radio group and one switch**, which is the shape of the
 * question: a search looks through exactly one kind of thing, and
 * whether pictures were photographed is true or false about any of
 * them.
 */
export function SearchFilterSheet({
  visible,
  filter,
  onClose,
  onApply,
}: {
  visible: boolean;
  filter: SearchFilter;
  onClose: () => void;
  onApply: (next: SearchFilter) => void;
}) {
  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      {/* Mounted only while open, so the draft below starts from what
          is actually in force. Holding it across closes would reopen
          the screen on a combination somebody abandoned. */}
      {visible ? (
        <Body filter={filter} onClose={onClose} onApply={onApply} />
      ) : null}
    </Modal>
  );
}

function Body({
  filter,
  onClose,
  onApply,
}: {
  filter: SearchFilter;
  onClose: () => void;
  onApply: (next: SearchFilter) => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const [draft, setDraft] = useState<SearchFilter>(filter);

  return (
    <View
      style={{
        flex: 1,
        backgroundColor: colors.background,
        paddingTop: insets.top,
      }}>
      <View
        style={{
          minHeight: TapTarget + Spacing.two,
          justifyContent: 'center',
          paddingHorizontal: Spacing.three,
        }}>
        <ThemedText
          accessibilityRole="header"
          style={{ ...labelType(FontSize.body, 800), textAlign: 'center' }}>
          Filter by
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
            left: Spacing.two,
            width: TapTarget,
            height: TapTarget,
            alignItems: 'center',
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

      <View style={{ flex: 1, paddingHorizontal: Spacing.three }}>
        {KINDS.map((kind) => (
          <Row
            key={kind.id}
            label={kind.label}
            role="radio"
            on={draft.kind === kind.id}
            onPress={() => setDraft({ ...draft, kind: kind.id })}
          />
        ))}

        <View
          style={{
            height: 1,
            marginVertical: Spacing.three,
            backgroundColor: colors.border,
          }}
        />

        <Row
          label="Photographs only"
          hint="Leaves out fits drawn by the studio or worn by an avatar."
          role="checkbox"
          on={draft.photographsOnly}
          onPress={() =>
            setDraft({ ...draft, photographsOnly: !draft.photographsOnly })
          }
        />
      </View>

      <View
        style={{
          flexDirection: 'row',
          justifyContent: 'center',
          gap: Spacing.two,
          paddingHorizontal: Spacing.three,
          paddingBottom: insets.bottom + Spacing.three,
        }}>
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Reset the filters"
          animateEntrance={false}
          onPress={() => {
            void tapFeedback();
            setDraft(NO_FILTER);
          }}
          style={{
            minHeight: TapTarget + Spacing.one,
            justifyContent: 'center',
            paddingHorizontal: Spacing.five,
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            backgroundColor: colors.backgroundElement,
          }}>
          <ThemedText style={labelType(FontSize.body, 800)}>Reset</ThemedText>
        </MotionPressable>
        <MotionPressable
          accessibilityRole="button"
          accessibilityLabel="Apply these filters"
          animateEntrance={false}
          onPress={() => {
            void tapFeedback();
            onApply(draft);
          }}
          style={{
            minHeight: TapTarget + Spacing.one,
            justifyContent: 'center',
            paddingHorizontal: Spacing.five,
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            backgroundColor: colors.accent,
          }}>
          <ThemedText
            style={{
              ...labelType(FontSize.body, 800),
              color: colors.accentText,
            }}>
            Apply
          </ThemedText>
        </MotionPressable>
      </View>
    </View>
  );
}

/** One choice: its name on the left, its state on the right. */
function Row({
  label,
  hint,
  role,
  on,
  onPress,
}: {
  label: string;
  hint?: string;
  role: 'radio' | 'checkbox';
  on: boolean;
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole={role}
      accessibilityState={{ checked: on }}
      accessibilityLabel={label}
      accessibilityHint={hint}
      animateEntrance={false}
      scale={0.99}
      onPress={() => {
        void tapFeedback();
        onPress();
      }}
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.three,
        minHeight: TapTarget + Spacing.two,
      }}>
      <View style={{ flex: 1, gap: Spacing.half }}>
        <ThemedText style={labelType(20, 400)}>{label}</ThemedText>
        {hint ? (
          <ThemedText
            themeColor="textSecondary"
            style={labelType(FontSize.footnote, 400)}>
            {hint}
          </ThemedText>
        ) : null}
      </View>
      <View
        style={{
          width: 26,
          height: 26,
          alignItems: 'center',
          justifyContent: 'center',
          borderRadius: role === 'radio' ? Radius.full : Radius.sm,
          borderCurve: 'continuous',
          borderWidth: on ? 0 : 1.5,
          borderColor: colors.borderStrong,
          backgroundColor: on ? colors.accent : 'transparent',
        }}>
        {on ? (
          <SymbolView
            name={
              role === 'radio'
                ? { ios: 'circle.fill', android: 'circle', web: 'circle' }
                : { ios: 'checkmark', android: 'check', web: 'check' }
            }
            size={role === 'radio' ? 10 : 14}
            tintColor={colors.accentText}
          />
        ) : null}
      </View>
    </MotionPressable>
  );
}
