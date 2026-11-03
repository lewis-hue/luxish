import { useRef, type ComponentRef } from 'react';
import { Pressable, TextInput, View, type TextInputProps } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import {
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
} from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';
import { tapFeedback } from '@/components/ui/motion';

/**
 * One search field, shared by every screen that needs one.
 *
 * Filters as you type rather than on submit. The lists it searches are held in
 * memory and small enough that there is nothing to wait for, so making someone
 * press return would add a step that buys nothing — and a field that looks like
 * search but does nothing until submitted is the kind of thing people try once.
 *
 * The clear button only appears once there is something to clear. A permanent
 * dimmed ✕ is a control that is disabled most of the time, and reads as broken
 * rather than as inactive.
 */
export function SearchField({
  value,
  onChangeText,
  placeholder = 'Search',
  accessibilityLabel,
  ...rest
}: {
  value: string;
  onChangeText: (next: string) => void;
  placeholder?: string;
  accessibilityLabel: string;
} & Omit<TextInputProps, 'value' | 'onChangeText' | 'placeholder'>) {
  const colors = Colors[useScheme()];
  // `ComponentRef` rather than `TextInput`: SDK 58 types the instance
  // separately from the component, so naming the component here types the
  // ref as the element type and `focus` does not exist on it.
  const input = useRef<ComponentRef<typeof TextInput>>(null);

  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.two,
        minHeight: TapTarget,
        paddingHorizontal: Spacing.three,
        borderRadius: Radius.full,
        borderCurve: 'continuous',
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.backgroundElement,
      }}>
      <TextInput
        ref={input}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.textSecondary}
        accessibilityLabel={accessibilityLabel}
        autoCapitalize="none"
        autoCorrect={false}
        returnKeyType="search"
        clearButtonMode="never"
        style={{
          flex: 1,
          paddingVertical: Spacing.two,
          fontSize: FontSize.subhead,
          color: colors.text,
        }}
        {...rest}
      />
      {value.length > 0 ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Clear search"
          hitSlop={10}
          onPress={() => {
            void tapFeedback();
            onChangeText('');
            // Focus stays in the field: clearing is nearly always a prelude to
            // typing something else, and dismissing the keyboard would make
            // that two taps.
            input.current?.focus();
          }}
          style={({ pressed }) => ({ opacity: pressed ? 0.5 : 1 })}>
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ fontSize: FontSize.subhead }}>
            Clear
          </ThemedText>
        </Pressable>
      ) : null}
    </View>
  );
}

/**
 * Does `haystack` match everything in `query`?
 *
 * Every whitespace-separated term must appear somewhere, in any order, so
 * "linen shirt" finds a "shirt, linen" as readily as the other way round.
 * Substring rather than word-prefix because garment vocabulary is full of
 * compounds — someone typing "neck" should still find "crewneck".
 */
export function matchesQuery(query: string, ...haystack: (string | null | undefined)[]): boolean {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;
  const subject = haystack.filter(Boolean).join(' ').toLowerCase();
  return terms.every((term) => subject.includes(term));
}
