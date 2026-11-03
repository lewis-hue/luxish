import { router } from 'expo-router';
import { useState } from 'react';
import { ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  bestDayLine,
  useStudio,
  type StudioWindow,
  type TopFit,
} from '@/api/queries/studio';
import { ThemedText } from '@/components/themed-text';
import { usePullToRefresh } from '@/components/ui/pull-to-refresh';
import { EmptyState } from '@/components/ui/empty-state';
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
 * Insights: what other people do with the fits you publish.
 *
 * **Renamed off `/studio` on 2026-11-01.** The word now belongs to the
 * tab where pictures are made, which is what a reader of this app
 * means by a studio. This screen never made anything - it reports
 * reach, best day and top fits - so it took the name it should have
 * had, and the route collision that the rename resolved was two
 * different features answering to one path.
 *
 * **One hero number, set as type.** The screens this is measured against
 * all converge on the same move: a single figure in the display face, a
 * chart subordinate to it, and a sentence where an analytics product
 * would put an axis. Saves is the hero because a save is somebody
 * planning to wear the thing; reach is the supporting fact.
 *
 * **The chart is twenty-eight plain views.** No library, no gridlines,
 * no tooltip: a bar at this width is an eleven point target, which is
 * under the floor a tap needs, so the interaction is a caption naming
 * the best day instead. The peak bar carries the accent, which is the
 * entire legend.
 *
 * **Every number excludes you.** The server counts other people only,
 * so this screen cannot be inflated by looking at your own shelf.
 */
export default function InsightsScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const refresh = usePullToRefresh();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';
  const [window, setWindow] = useState<StudioWindow>('28d');
  const studio = useStudio(window, signedIn);

  const data = studio.data;

  return (
    <ScrollView
      refreshControl={refresh.control}
      style={{ flex: 1, backgroundColor: colors.background }}
      contentInsetAdjustmentBehavior="automatic"
      contentContainerStyle={{
        paddingTop: Spacing.three,
        paddingBottom: BottomTabInset + insets.bottom + Spacing.five,
        gap: Spacing.five,
      }}
      showsVerticalScrollIndicator={false}>
      <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.two }}>
        <ThemedText accessibilityRole="header" style={{ ...labelType(40, 800), lineHeight: 44 }}>
          Insights
        </ThemedText>
        <WindowChips value={window} onChange={setWindow} />
      </View>

      {!data ? null : data.fits === 0 ? (
        <EmptyState
          status="empty"
          title="Nothing to measure yet"
          body="Post a fit and this fills in. The studio counts what other people do with the fits you publish."
          action={{ label: 'Post a fit', onPress: () => router.push('/compose') }}
        />
      ) : (
        <>
          {/* The hero: one number, its label, and the fact beside it. */}
          <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.half }}>
            <ThemedText style={{ ...labelType(56, 800), lineHeight: 60 }}>
              {data.saves}
            </ThemedText>
            <ThemedText type="smallBold">
              {data.saves === 1 ? 'save' : 'saves'} by other people
            </ThemedText>
            <ThemedText type="small" themeColor="textSecondary">
              {windowLine(window)}, across the {data.fits}{' '}
              {data.fits === 1 ? 'fit' : 'fits'} you have posted.
            </ThemedText>
          </View>

          <Bars series={data.series} />

          <View>
            <FactRow label="Reach" value={`${data.reach}`} detail="distinct people" />
            <FactRow
              label="Followers"
              value={`${data.followers}`}
              detail={data.followersGained > 0 ? `+${data.followersGained} ${windowLine(window).toLowerCase()}` : undefined}
            />
            <FactRow label="You posted" value={`${data.fits}`} detail="fits" />
          </View>

          {/* Which fits earned the number above.

              This panel had no table for a while: the old one listed the
              curated catalogue, and every row opened a page the app no
              longer shows. A row names a fit now, so it opens the fit. */}
          {data.topFits.length > 0 ? (
            <View style={{ gap: Spacing.one }}>
              <ThemedText
                type="smallBold"
                style={{ paddingHorizontal: Spacing.three }}>
                {data.topFits.length === 1 ? 'Your top fit' : 'Your top fits'}
              </ThemedText>
              {data.topFits.map((fit, place) => (
                <TopFitRow key={fit.postId} fit={fit} place={place + 1} />
              ))}
            </View>
          ) : null}

          <ThemedText
            themeColor="textSecondary"
            style={{
              paddingHorizontal: Spacing.three,
              ...labelType(FontSize.footnote, 400),
            }}>
            Counted over what people actually did {windowLine(window).toLowerCase()}.
          </ThemedText>
        </>
      )}
    </ScrollView>
  );
}

function windowLine(window: StudioWindow): string {
  if (window === '7d') return 'In the last 7 days';
  if (window === '28d') return 'In the last 28 days';
  return 'All time';
}

const WINDOWS: { id: StudioWindow; label: string }[] = [
  { id: '7d', label: '7 days' },
  { id: '28d', label: '28 days' },
  { id: 'all', label: 'All time' },
];

/** One global range. Per-card ranges are how two numbers end up answering
 *  different questions on the same screen. */
function WindowChips({
  value,
  onChange,
}: {
  value: StudioWindow;
  onChange: (next: StudioWindow) => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <View style={{ flexDirection: 'row', gap: Spacing.one }}>
      {WINDOWS.map((option) => {
        const selected = option.id === value;
        return (
          <MotionPressable
            key={option.id}
            accessibilityRole="button"
            accessibilityState={{ selected }}
            animateEntrance={false}
            onPress={() => {
              void tapFeedback();
              onChange(option.id);
            }}
            style={{
              minHeight: 36,
              paddingHorizontal: Spacing.three,
              justifyContent: 'center',
              borderRadius: Radius.full,
              backgroundColor: selected ? colors.backgroundSelected : 'transparent',
              borderWidth: 1,
              borderColor: selected ? colors.backgroundSelected : colors.border,
            }}>
            <ThemedText type="small" style={{ fontSize: FontSize.footnote }}>
              {option.label}
            </ThemedText>
          </MotionPressable>
        );
      })}
    </View>
  );
}

/** The month as plain views: a bar per day, the peak in the accent, and a
 *  sentence where an axis would be. */
function Bars({ series }: { series: readonly number[] }) {
  const colors = Colors[useScheme()];
  const peak = Math.max(...series, 0);
  const caption = bestDayLine(series);
  return (
    <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.one }}>
      <View
        accessible
        accessibilityLabel={caption ?? 'No activity in this window yet'}
        style={{
          height: 56,
          flexDirection: 'row',
          alignItems: 'flex-end',
          gap: Spacing.half,
        }}>
        {series.map((count, index) => (
          <View
            key={index}
            style={{
              flex: 1,
              // A zero day keeps a hairline, so the shape of the month
              // stays legible instead of gapping.
              height: peak > 0 ? Math.max(2, (count / peak) * 56) : 2,
              borderTopLeftRadius: 1,
              borderTopRightRadius: 1,
              backgroundColor:
                peak > 0 && count === peak ? colors.accent : colors.border,
            }}
          />
        ))}
      </View>
      {caption ? (
        <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: FontSize.meta }}>
          {caption}
        </ThemedText>
      ) : null}
    </View>
  );
}

/** One of the fits the numbers above are about, and a way into it. */
function TopFitRow({ fit, place }: { fit: TopFit; place: number }) {
  const colors = Colors[useScheme()];
  const people =
    fit.people === fit.saves
      ? null
      : `${fit.people} ${fit.people === 1 ? 'person' : 'people'} reached`;

  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={
        `Fit ranked ${place}: ${fit.saves} ${fit.saves === 1 ? 'save' : 'saves'}` +
        (people ? `, ${people}` : '')
      }
      animateEntrance={false}
      onPress={() => {
        void tapFeedback();
        router.push({ pathname: '/fit/[id]', params: { id: fit.postId } });
      }}
      style={{
        minHeight: TapTarget,
        marginHorizontal: Spacing.three,
        paddingHorizontal: Spacing.two,
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.two,
        borderRadius: Radius.md,
        borderCurve: 'continuous',
        backgroundColor: colors.backgroundElement,
      }}>
      {/* The place is the only numbering here, and it earns it: these are
          ranked, so the order is the information. */}
      <ThemedText
        type="small"
        themeColor="textSecondary"
        style={{ fontVariant: ['tabular-nums'] }}>
        {place}
      </ThemedText>
      <View style={{ flex: 1 }}>
        <ThemedText type="smallBold">
          {fit.saves} {fit.saves === 1 ? 'save' : 'saves'}
        </ThemedText>
        {people ? (
          <ThemedText
            type="small"
            themeColor="textSecondary"
            style={{ fontSize: FontSize.meta }}>
            {people}
          </ThemedText>
        ) : null}
      </View>
    </MotionPressable>
  );
}

function FactRow({ label, value, detail }: { label: string; value: string; detail?: string }) {
  const colors = Colors[useScheme()];
  return (
    <View
      style={{
        minHeight: TapTarget,
        paddingHorizontal: Spacing.three,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottomWidth: 1,
        borderBottomColor: colors.border,
      }}>
      <ThemedText type="small" themeColor="textSecondary">
        {label}
      </ThemedText>
      <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: Spacing.one }}>
        <ThemedText style={{ ...labelType(20, 800), lineHeight: 24 }}>{value}</ThemedText>
        {detail ? (
          <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: FontSize.meta }}>
            {detail}
          </ThemedText>
        ) : null}
      </View>
    </View>
  );
}
