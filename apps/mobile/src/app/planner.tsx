import { PlannerBoard } from '@/features/planner/board';

/**
 * What you are wearing, by day.
 *
 * The screen is a wrapper: the calendar itself is `PlannerBoard`, because
 * the library's Calendar tab renders the same thing inline. Two copies of
 * a week strip is two places for the dates to disagree.
 */
export default function PlannerScreen() {
  return <PlannerBoard />;
}
