import { StyleSheet, Text, type TextProps } from 'react-native';

import {
  FontSize,
  Mono,
  ThemeColor,
  labelType,
} from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

/**
 * Every piece of text in the app, on one of two faces.
 *
 * Bodoni Moda for the two heading roles, Archivo for everything that is read
 * or tapped. No system face anywhere, which is a change of
 * position rather than an oversight: ADR-019 originally kept body copy on San
 * Francisco, and its 2026-10-29 amendment records why that was reversed.
 *
 * **The weights are the design.** The brief asks for radical contrast with
 * nothing in between, so the roles here step 200 -> 400 -> 800 and skip the
 * middle entirely. There is no semibold in this file, and `theme.ts` makes
 * one a compile error rather than leaving it to discipline. Archivo runs the
 * full 100 to 900, which is why this spread is finally the one the brief
 * asked for rather than the closest the files allowed.
 *
 * Weight travels through `fontVariationSettings`, never `fontWeight`: both
 * files are variable, and `fontWeight` on a variable face invites the
 * platform to synthesise a weight instead of interpolating one.
 */

export type ThemedTextProps = TextProps & {
  type?:
    | 'default'
    | 'title'
    | 'small'
    | 'smallBold'
    | 'subtitle'
    | 'label'
    | 'link'
    | 'code';
  themeColor?: ThemeColor;
};

export function ThemedText({ style, type = 'default', themeColor, ...rest }: ThemedTextProps) {
  const theme = useTheme();

  return <Text style={[{ color: theme[themeColor ?? 'text'] }, styles[type], style]} {...rest} />;
}

const styles = StyleSheet.create({
  /** Body copy. iOS Body at the ratio Bringhurst would set it. */
  default: {
    ...labelType(FontSize.body, 400),
    lineHeight: Math.round(FontSize.body * 1.45),
  },
  /** The workhorse: 71 of the app's uses. */
  small: {
    ...labelType(FontSize.subhead, 400),
    lineHeight: Math.round(FontSize.subhead * 1.4),
  },
  /**
   * Emphasis inside small copy, and the label on every button.
   *
   * 800, not 600. A semibold is the hedge the brief argues against, and
   * Archivo's heavy weights stay narrow enough to carry a button label
   * without shouting next to a didone heading.
   */
  smallBold: {
    ...labelType(FontSize.subhead, 800),
    lineHeight: Math.round(FontSize.subhead * 1.4),
    letterSpacing: 0.1,
  },
  /**
   * The heavy eyebrow, and the other half of the contrast pair.
   *
   * Sits directly above or below a light Bodoni heading with no medium
   * weight between them, which is the whole move the brief describes.
   *
   * **Not uppercase.** A tracked-out caps label over every heading is one of
   * the most reliable tells of a templated page, and on a narrow tile it is
   * also what makes the layout congested.
   */
  label: {
    ...labelType(FontSize.meta, 800),
    lineHeight: Math.round(FontSize.meta * 1.4),
    letterSpacing: 0.2,
  },
  /**
   * A heading, in the app's one sans.
   *
   * This was Bodoni, and so were a dozen screen titles. Two faces
   * meant two kinds of page: Insights and Studio opened with a
   * didone while Wardrobe and Profile opened with Archivo, and
   * nothing about a screen predicted which it would be. Archivo
   * everywhere, at the heavy end of its axis, is one voice.
   */
  title: {
    ...labelType(FontSize.largeTitle, 800),
    lineHeight: Math.round(FontSize.largeTitle * 1.12),
  },
  subtitle: {
    ...labelType(FontSize.title2, 800),
    lineHeight: Math.round(FontSize.title2 * 1.25),
  },
  /**
   * A link, underlined rather than coloured.
   *
   * The old `linkPrimary` hardcoded `#3c87f7`, a stock iOS blue left over
   * from the project template, in an app whose palette has no blue in it at
   * all: every blue computed against this warm paper was tonally foreign,
   * which is why there is no `info` token (ADR-019). An underline carries the
   * affordance without introducing the one cold colour on the page, and
   * satisfies WCAG 1.4.1 by not relying on colour alone.
   */
  link: {
    ...labelType(FontSize.subhead, 400),
    lineHeight: Math.round(FontSize.subhead * 1.4),
    textDecorationLine: 'underline',
  },
  /** Monospace, for anything that must not be re-wrapped or re-spaced. */
  code: {
    fontFamily: Mono,
    fontSize: FontSize.caption,
    lineHeight: Math.round(FontSize.caption * 1.5),
    fontWeight: '500',
  },
});
