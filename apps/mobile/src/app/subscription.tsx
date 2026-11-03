import { useState } from 'react';
import { ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  meterLine,
  shortDate,
  useEntitlements,
  useSetAutoRenew,
  useSimulatedSubscribe,
} from '@/api/queries/billing';
import { ThemedText } from '@/components/themed-text';
import { usePullToRefresh } from '@/components/ui/pull-to-refresh';
import { EmptyState } from '@/components/ui/empty-state';
import { MotionPressable, tapFeedback } from '@/components/ui/motion';
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
 * The subscription, in whichever state it is actually in.
 *
 * One screen for both halves: the pitch when there is nothing, the ledger
 * when there is. They share every fact (the plan, the meter, the dates),
 * and two screens over one record is how "renews on" and "ends on" drift
 * into disagreeing.
 *
 * **The store is simulated and the screen says so, twice.** Once beside
 * the button that starts it, once on the standing subscription. Real
 * billing is blocked on Apple and Google store accounts; building the
 * screen against an honest fixture now is what makes the store swap a
 * data change later instead of a redesign. Nothing here names a price,
 * because showing a price no store charges is the one lie worse than a
 * fake store.
 *
 * **The pitch is one sentence, not a checklist.** The plan changes exactly
 * one number this build can stand behind, so the screen says that number
 * and stops. A feature list where every row is invented is the thing the
 * house rules exist to prevent.
 *
 * **Cancelling never claws back.** Renewal off keeps the period that was
 * granted, states the date it ends, and offers the way back. The word
 * "cancel" appears nowhere: the switch is renewal, and the copy says what
 * actually happens.
 */
export default function SubscriptionScreen() {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const refresh = usePullToRefresh();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';
  const entitlements = useEntitlements(signedIn);
  const subscribe = useSimulatedSubscribe();
  const setRenew = useSetAutoRenew();
  const [busy, setBusy] = useState(false);

  const act = (run: () => Promise<unknown>) => {
    if (busy) return;
    void tapFeedback();
    setBusy(true);
    void run().finally(() => setBusy(false));
  };

  const data = entitlements.data;

  return (
    <ScrollView
      refreshControl={refresh.control}
      style={{ flex: 1, backgroundColor: colors.background }}
      contentInsetAdjustmentBehavior="automatic"
      contentContainerStyle={{
        paddingTop: Spacing.three,
        paddingBottom: insets.bottom + Spacing.five,
        gap: Spacing.five,
      }}
      showsVerticalScrollIndicator={false}>
      <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.one }}>
        <ThemedText accessibilityRole="header" style={{ ...labelType(40, 800), lineHeight: 44 }}>
          {data?.plan === 'plus' ? 'Your plan' : 'Plus'}
        </ThemedText>
        {data ? (
          <ThemedText type="small" themeColor="textSecondary">
            {meterLine(data)}
          </ThemedText>
        ) : null}
      </View>

      {!data ? null : data.plan === 'free' ? (
        <FreePitch
          busy={busy || subscribe.isPending}
          onStart={() => act(() => subscribe.mutateAsync())}
        />
      ) : (
        <Standing
          state={data.state}
          periodEnd={data.periodEnd}
          simulated={data.simulated}
          busy={busy || setRenew.isPending}
          onSetRenew={(next) => act(() => setRenew.mutateAsync(next))}
        />
      )}

      {entitlements.isError ? (
        <EmptyState
          status="error"
          title="Could not load your plan"
          body="The server did not answer. Pull to try again."
        />
      ) : null}
    </ScrollView>
  );
}

/** The pitch: one number, how renewal works, and an honestly labelled way in. */
function FreePitch({ busy, onStart }: { busy: boolean; onStart: () => void }) {
  const colors = Colors[useScheme()];
  return (
    <View style={{ gap: Spacing.five }}>
      <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.two }}>
        <ThemedText style={{ ...labelType(24, 800), lineHeight: 30 }}>
          Sixty stylist runs a month, instead of twelve.
        </ThemedText>
        <ThemedText type="small" themeColor="textSecondary">
          That is the whole difference today. More arrives when it is real, and this
          page will say so in plain words.
        </ThemedText>
      </View>

      <View style={{ gap: Spacing.one }}>
        <TimelineRow
          when="Today"
          what="Plus starts, and the meter above moves to sixty."
        />
        <TimelineRow when="Every 30 days" what="It renews. This build moves no money." />
        <TimelineRow
          when="Anytime"
          what="Turn renewal off. You keep what is left of the period."
        />
      </View>

      <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.two }}>
        <MotionPressable
          accessibilityRole="button"
          accessibilityState={{ disabled: busy }}
          disabled={busy}
          animateEntrance={false}
          onPress={onStart}
          style={{
            minHeight: TapTarget + 8,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            backgroundColor: colors.text,
            opacity: busy ? 0.5 : 1,
          }}>
          <ThemedText type="smallBold" style={{ color: colors.background }}>
            Start Plus
          </ThemedText>
        </MotionPressable>
        <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: FontSize.meta }}>
          Billing is simulated in this build. No money moves and no store is charged;
          app store billing arrives with the store accounts.
        </ThemedText>
      </View>
    </View>
  );
}

/** The standing subscription: facts as rows, one switch, no dark corners. */
function Standing({
  state,
  periodEnd,
  simulated,
  busy,
  onSetRenew,
}: {
  state: 'free' | 'active' | 'ending';
  periodEnd: string | null;
  simulated: boolean;
  busy: boolean;
  onSetRenew: (next: boolean) => void;
}) {
  const colors = Colors[useScheme()];
  const ending = state === 'ending';
  return (
    <View style={{ gap: Spacing.five }}>
      <View>
        <FactRow label="Plan" value="Plus" />
        <FactRow
          label={ending ? 'Ends' : 'Renews'}
          value={periodEnd ? shortDate(periodEnd) : ''}
        />
        <FactRow label="Store" value={simulated ? 'Simulated' : 'App store'} />
      </View>

      {ending ? (
        <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.half }}>
          <ThemedText type="small" themeColor="textSecondary">
            Renewal is off. Plus runs to the date above, then the meter returns to
            twelve. Nothing already granted is taken back.
          </ThemedText>
        </View>
      ) : null}

      <View style={{ paddingHorizontal: Spacing.three, gap: Spacing.two }}>
        <MotionPressable
          accessibilityRole="button"
          accessibilityState={{ disabled: busy }}
          disabled={busy}
          animateEntrance={false}
          onPress={() => onSetRenew(ending)}
          style={{
            minHeight: TapTarget,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: Radius.md,
            borderCurve: 'continuous',
            borderWidth: 1,
            borderColor: colors.borderStrong,
            opacity: busy ? 0.5 : 1,
          }}>
          <ThemedText type="smallBold">
            {ending ? 'Resume renewal' : 'Turn off renewal'}
          </ThemedText>
        </MotionPressable>
        {simulated ? (
          <ThemedText type="small" themeColor="textSecondary" style={{ fontSize: FontSize.meta }}>
            This subscription came from the simulated store. It exists so the screens
            above it could be built and tested; it is not revenue and never will be.
          </ThemedText>
        ) : null}
      </View>
    </View>
  );
}

function TimelineRow({ when, what }: { when: string; what: string }) {
  const colors = Colors[useScheme()];
  return (
    <View
      style={{
        flexDirection: 'row',
        gap: Spacing.three,
        paddingHorizontal: Spacing.three,
        paddingVertical: Spacing.two,
        borderBottomWidth: 1,
        borderBottomColor: colors.border,
      }}>
      <ThemedText type="smallBold" style={{ width: 104 }}>
        {when}
      </ThemedText>
      <ThemedText type="small" themeColor="textSecondary" style={{ flex: 1 }}>
        {what}
      </ThemedText>
    </View>
  );
}

function FactRow({ label, value }: { label: string; value: string }) {
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
      <ThemedText type="smallBold">{value}</ThemedText>
    </View>
  );
}
