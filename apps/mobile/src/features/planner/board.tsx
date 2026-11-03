import { Image } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { useMemo, useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  addDays,
  isoDay,
  startOfWeek,
  useMarkWorn,
  usePlanDay,
  usePlanner,
  useUnplanDay,
} from '@/api/queries/planner';
import { ThemedText } from '@/components/themed-text';
import { EmptyState } from '@/components/ui/empty-state';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
import {
  BottomTabInset,
  Colors,
  FontSize,
  ImageFade,
  Radius,
  Spacing,
  TapTarget,
  labelType,
} from '@/constants/theme';
import { usePostImage } from '@/api/queries/post-media';
import { useAuth } from '@/features/auth/session';
import { useFavouriteGarments } from '@/features/discover/saved';
import { useWardrobe, type WardrobeEntry } from '@/features/wardrobe/store';
import { useScheme } from '@/hooks/use-theme';

const WEEKDAYS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'] as const;

/** How many garments one day may hold. A plan, not a packing list. */
const MOST = 8;

/**
 * What you are wearing, by day.
 *
 * The app answers "what should I wear" on every other screen and had
 * nowhere to answer it *for Thursday*. This is that: a week, a day,
 * and the clothes you picked for it.
 *
 * **Planned from your own wardrobe.** A plan used to name a curated
 * look — a catalogue entry nobody owned, out of a generated set — so
 * planning a week produced a wardrobe of clothes the wearer did not
 * have, and "wore it?" was a question about somebody else's outfit.
 * The picker is now the clothes in the wardrobe, and every id is
 * re-validated against its owner before the server stores it.
 *
 * **Everything here is a day, never an instant.** Dates go to the
 * server as `YYYY-MM-DD` and come back the same way: a plan made for
 * Thursday has to still be Thursday after a flight, and
 * round-tripping an instant through a timezone is how it stops being.
 *
 * **No weather, deliberately.** The reference shows a temperature
 * beside the date and this service has no weather provider. A
 * hardcoded 23 degrees would be a fixture reading as a live
 * integration, on the one screen where being wrong about the weather
 * gets somebody rained on.
 */
export function PlannerBoard({ embedded = false }: { embedded?: boolean } = {}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';
  const favourites = useFavouriteGarments();
  const wardrobe = useWardrobe(favourites.values);

  const today = useMemo(() => new Date(), []);
  const [weekStart, setWeekStart] = useState(() => startOfWeek(today));
  const [selected, setSelected] = useState(() => isoDay(today));

  const days = useMemo(
    () => Array.from({ length: 7 }, (_, index) => addDays(weekStart, index)),
    [weekStart],
  );
  const rangeStart = isoDay(days[0]);
  const rangeEnd = isoDay(days[6]);

  const planner = usePlanner(rangeStart, rangeEnd, signedIn);
  const planDay = usePlanDay();
  // Carried in from a pin's menu, when that is where this was opened
  // from. Read here rather than passed as a prop because the board
  // is rendered both as its own screen and inline in the library.
  const { fit: fitParam } = useLocalSearchParams<{ fit?: string }>();
  const unplanDay = useUnplanDay();
  const markWorn = useMarkWorn();

  const byDay = useMemo(
    () => new Map((planner.data ?? []).map((plan) => [plan.plannedFor, plan])),
    [planner.data],
  );
  const plan = byDay.get(selected);

  /**
   * The wardrobe, by server id.
   *
   * A plan refers to the server's garments; the device knows them by
   * its own id until they have synced. Anything not yet uploaded
   * cannot be planned, because the server has nothing to validate
   * against — and that is the honest state rather than a tile that
   * fails when tapped.
   */
  const owned = useMemo(() => {
    const out = new Map<string, WardrobeEntry>();
    for (const item of wardrobe.entries) {
      if (item.serverId) out.set(item.serverId, item);
    }
    return out;
  }, [wardrobe.entries]);

  const wearing = (plan?.garmentIds ?? [])
    .map((id) => owned.get(id))
    .filter((item): item is WardrobeEntry => item !== undefined);
  const chosen = new Set(plan?.garmentIds ?? []);

  const toggle = (serverId: string) => {
    void tapFeedback();
    const next = chosen.has(serverId)
      ? (plan?.garmentIds ?? []).filter((id) => id !== serverId)
      : [...(plan?.garmentIds ?? []), serverId].slice(0, MOST);
    if (next.length === 0) {
      unplanDay.mutate(selected);
      return;
    }
    planDay.mutate({
      day: selected,
      garmentIds: next,
      // **The fit somebody came here from, kept with the day.**
      //
      // The pin menu no longer offers "plan a day for it" - a plan
      // is made of garments somebody owns and a pin is a photograph
      // of somebody else's outfit, so the option promised something
      // this screen could not do with it. The parameter is still
      // honoured because the planner can be reached with a `fit`
      // from elsewhere, and a day that remembers what inspired it
      // is worth keeping. Sent only on the first save after
      // arriving: omitting it leaves any existing reference alone.
      ...(fitParam && !plan?.referencePostId
        ? { referencePostId: fitParam }
        : {}),
    });
  };

  if (!signedIn) {
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: colors.background,
          justifyContent: 'center',
        }}>
        <EmptyState
          status="blocked"
          title="Sign in to plan"
          body="Your plans are kept with your account, so they are there on any phone."
          action={{ label: 'Sign in', onPress: () => router.push('/sign-in') }}
        />
      </View>
    );
  }

  // Embedded in the library tab the surrounding screen owns the scroll
  // and the heading, so this draws neither: two scroll views nested is
  // a gesture conflict, and two headings is a screen saying its own
  // name twice.
  const Frame = embedded ? EmbeddedFrame : ScrollingFrame;

  return (
    <Frame colors={colors} insets={insets}>
      <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.half }}>
        <ThemedText
          themeColor="textSecondary"
          style={labelType(FontSize.subhead, 400)}>
          {monthLabel(days[0], days[6])}
        </ThemedText>
        {embedded ? null : (
          <ThemedText
            accessibilityRole="header"
            style={{ ...labelType(28, 800), lineHeight: 34 }}>
            Planner
          </ThemedText>
        )}
      </View>

      {/* The week strip. Arrows rather than a swipe, because a
          horizontal swipe inside a vertical scroll is a gesture people
          discover by accident and then cannot repeat. */}
      <View style={{ gap: Spacing.two }}>
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
            paddingHorizontal: Spacing.three,
          }}>
          <WeekStep
            label="Previous week"
            icon={{ ios: 'chevron.left', android: 'chevron_left', web: 'chevron_left' }}
            onPress={() => setWeekStart(addDays(weekStart, -7))}
          />
          <ThemedText
            themeColor="textSecondary"
            style={labelType(FontSize.subhead, 400)}>
            {isoDay(startOfWeek(today)) === isoDay(weekStart) ? 'This week' : ''}
          </ThemedText>
          <WeekStep
            label="Next week"
            icon={{
              ios: 'chevron.right',
              android: 'chevron_right',
              web: 'chevron_right',
            }}
            onPress={() => setWeekStart(addDays(weekStart, 7))}
          />
        </View>

        <View style={{ flexDirection: 'row', paddingHorizontal: Spacing.three }}>
          {days.map((day, index) => {
            const iso = isoDay(day);
            const isSelected = iso === selected;
            const isToday = iso === isoDay(today);
            const planned = (byDay.get(iso)?.garmentIds ?? []).length > 0;
            return (
              <Pressable
                key={iso}
                accessibilityRole="button"
                accessibilityState={{ selected: isSelected }}
                accessibilityLabel={`${dayLabel(day)}${planned ? ', planned' : ''}`}
                onPress={() => {
                  void tapFeedback();
                  setSelected(iso);
                }}
                style={{ flex: 1, alignItems: 'center', gap: Spacing.one }}>
                <ThemedText
                  themeColor="textSecondary"
                  style={labelType(FontSize.meta, 400)}>
                  {WEEKDAYS[index]}
                </ThemedText>
                <View
                  style={{
                    width: 38,
                    height: 38,
                    borderRadius: Radius.md,
                    borderCurve: 'continuous',
                    alignItems: 'center',
                    justifyContent: 'center',
                    backgroundColor: isSelected ? colors.text : 'transparent',
                    // Today is an outline rather than a fill, so the
                    // selected day is never ambiguous when they differ.
                    borderWidth: isToday && !isSelected ? 1 : 0,
                    borderColor: colors.borderStrong,
                  }}>
                  <ThemedText
                    style={{
                      ...labelType(FontSize.subhead, isSelected ? 800 : 400),
                      color: isSelected ? colors.background : colors.text,
                      fontVariant: ['tabular-nums'],
                    }}>
                    {day.getDate()}
                  </ThemedText>
                </View>
                {/* A dot under a planned day, so the week reads at a
                    glance rather than needing seven taps to find out. */}
                <View
                  style={{
                    width: 4,
                    height: 4,
                    borderRadius: Radius.full,
                    backgroundColor: planned ? colors.accent : 'transparent',
                  }}
                />
              </Pressable>
            );
          })}
        </View>
      </View>

      <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.two }}>
        <ThemedText style={labelType(FontSize.body, 800)}>
          {dayLabel(new Date(`${selected}T00:00:00`))}
        </ThemedText>

        {wearing.length > 0 ? (
          <>
            {/* The outfit, as the clothes themselves. Cut-outs on a
                tinted ground, which is how the wardrobe shows them
                everywhere else. */}
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.two }}>
              {wearing.map((item) => (
                <Piece key={item.id} item={item} size={84} />
              ))}
            </View>

            {/* **The fit this day was planned from.**
                Storing the reference changes nothing anybody can see
                unless it is drawn, and the whole point of "plan a
                day for it" is that the day remembers what "it" was.
                Tappable, because the obvious next question is what
                the picture was. */}
            {plan?.referenceAssetId ? (
              <PlannedFrom
                assetId={plan.referenceAssetId}
                postId={plan.referencePostId}
              />
            ) : null}

            {plan?.note ? (
              <ThemedText
                themeColor="textSecondary"
                style={labelType(FontSize.subhead, 400)}>
                {plan.note}
              </ThemedText>
            ) : null}

            <View style={{ flexDirection: 'row', gap: Spacing.two }}>
              <Action
                label={plan?.worn === true ? 'Wore it' : 'Wore it?'}
                active={plan?.worn === true}
                onPress={() =>
                  markWorn.mutate({ day: selected, worn: plan?.worn !== true })
                }
              />
              <Action label="Clear" onPress={() => unplanDay.mutate(selected)} />
            </View>
          </>
        ) : (
          <ThemedText
            themeColor="textSecondary"
            style={labelType(FontSize.subhead, 400)}>
            Nothing planned. Tap what you are wearing.
          </ThemedText>
        )}
      </View>

      <View style={{ gap: Spacing.two }}>
        <ThemedText
          style={{
            ...labelType(FontSize.body, 800),
            paddingHorizontal: Spacing.three,
          }}>
          Your wardrobe
        </ThemedText>

        {owned.size === 0 ? (
          <View style={{ paddingHorizontal: Spacing.three }}>
            <EmptyState
              status="empty"
              title="Nothing to plan with yet"
              body="Photograph something into your wardrobe and it becomes a day you can plan."
              action={{
                label: 'Open the wardrobe',
                onPress: () => router.push('/wardrobe'),
              }}
            />
          </View>
        ) : (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{
              gap: Spacing.two,
              paddingHorizontal: Spacing.three,
            }}>
            {[...owned.entries()].map(([serverId, item]) => (
              <Piece
                key={item.id}
                item={item}
                size={96}
                chosen={chosen.has(serverId)}
                onPress={() => toggle(serverId)}
              />
            ))}
          </ScrollView>
        )}
      </View>

      <ThemedText
        themeColor="textSecondary"
        style={{
          paddingHorizontal: Spacing.three,
          ...labelType(FontSize.meta, 400),
        }}>
        No weather yet.
      </ThemedText>
    </Frame>
  );
}

/**
 * One garment, as a square.
 *
 * The cut-out where there is one, because a plan is read at a glance
 * and a cut-out on a plain ground is the one rendering of a garment
 * that reads at thumbnail size.
 */
function Piece({
  item,
  size,
  chosen,
  onPress,
}: {
  item: WardrobeEntry;
  size: number;
  chosen?: boolean;
  onPress?: () => void;
}) {
  const colors = Colors[useScheme()];
  const source = item.uri ? { uri: item.uri } : item.image;

  return (
    <MotionPressable
      accessibilityRole={onPress ? 'checkbox' : 'image'}
      accessibilityState={onPress ? { checked: Boolean(chosen) } : undefined}
      accessibilityLabel={item.name}
      animateEntrance={false}
      disabled={!onPress}
      animatePress={Boolean(onPress)}
      scale={0.95}
      onPress={onPress}
      style={{ width: size, gap: Spacing.half }}>
      <View
        style={{
          width: size,
          height: size,
          borderRadius: Radius.md,
          borderCurve: 'continuous',
          overflow: 'hidden',
          backgroundColor: colors.backgroundElement,
          borderWidth: chosen ? 2 : 0,
          borderColor: colors.text,
        }}>
        {source ? (
          <Image
            source={source}
            contentFit="contain"
            transition={120}
            accessible={false}
            style={{ width: '100%', height: '100%' }}
          />
        ) : null}
      </View>
      <ThemedText numberOfLines={1} style={labelType(FontSize.meta, 400)}>
        {item.name}
      </ThemedText>
    </MotionPressable>
  );
}

function WeekStep({
  label,
  icon,
  onPress,
}: {
  label: string;
  icon: Parameters<typeof SymbolView>[0]['name'];
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      animateEntrance={false}
      scale={0.92}
      hitSlop={8}
      onPress={() => {
        void tapFeedback();
        onPress();
      }}
      style={{
        width: TapTarget,
        height: TapTarget,
        alignItems: 'center',
        justifyContent: 'center',
      }}>
      <SymbolView name={icon} size={18} tintColor={colors.text} />
    </MotionPressable>
  );
}

function Action({
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
      accessibilityState={{ selected: Boolean(active) }}
      accessibilityLabel={label}
      animateEntrance={false}
      scale={0.96}
      onPress={() => {
        void tapFeedback();
        onPress();
      }}
      style={{
        minHeight: 40,
        justifyContent: 'center',
        paddingHorizontal: Spacing.four,
        borderRadius: Radius.md,
        borderCurve: 'continuous',
        backgroundColor: active ? colors.text : colors.backgroundElement,
      }}>
      <ThemedText
        style={{
          ...labelType(FontSize.subhead, 800),
          color: active ? colors.background : colors.text,
        }}>
        {label}
      </ThemedText>
    </MotionPressable>
  );
}

function EmbeddedFrame({ children }: { children: React.ReactNode }) {
  return <View style={{ gap: Spacing.four }}>{children}</View>;
}

function ScrollingFrame({
  colors,
  insets,
  children,
}: {
  colors: (typeof Colors)['light'] | (typeof Colors)['dark'];
  insets: { bottom: number };
  children: React.ReactNode;
}) {
  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.background }}
      contentInsetAdjustmentBehavior="automatic"
      contentContainerStyle={{
        paddingTop: Spacing.three,
        paddingBottom: BottomTabInset + insets.bottom + Spacing.five,
        gap: Spacing.four,
      }}
      showsVerticalScrollIndicator={false}>
      {children}
    </ScrollView>
  );
}

/** "November", or "October – November" when a week straddles two. */
function monthLabel(start: Date, end: Date): string {
  const first = start.toLocaleDateString(undefined, { month: 'long' });
  const last = end.toLocaleDateString(undefined, { month: 'long' });
  return first === last ? first : `${first} to ${last}`;
}

function dayLabel(day: Date): string {
  return day.toLocaleDateString(undefined, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  });
}


/**
 * The picture a day was planned from, under the clothes.
 *
 * Small and quiet: the plan is the garments, and this is the thing
 * that prompted them. Big enough to recognise, not so big it reads
 * as what is being worn.
 */
function PlannedFrom({
  assetId,
  postId,
}: {
  assetId: string;
  postId: string | null;
}) {
  const colors = Colors[useScheme()];
  const uri = usePostImage(assetId).data ?? null;
  if (!uri) return null;

  return (
    <MotionPressable
      accessibilityRole="link"
      accessibilityLabel="The fit this day was planned from"
      animateEntrance={false}
      disabled={!postId}
      onPress={() => {
        if (!postId) return;
        void tapFeedback();
        router.push({ pathname: '/fit/[id]', params: { id: postId } });
      }}
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: Spacing.two,
      }}>
      <Image
        source={{ uri }}
        contentFit="cover"
        transition={ImageFade}
        accessible={false}
        style={{
          width: 40,
          height: 54,
          borderRadius: Radius.sm,
          borderCurve: 'continuous',
          backgroundColor: colors.backgroundElement,
        }}
      />
      <ThemedText
        themeColor="textSecondary"
        style={labelType(FontSize.footnote, 400)}>
        Planned from this fit
      </ThemedText>
    </MotionPressable>
  );
}
