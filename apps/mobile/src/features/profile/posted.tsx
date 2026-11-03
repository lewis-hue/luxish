import { View } from 'react-native';

import { type FeedFit } from '@/api/queries/discover-feed';
import { type MinePost } from '@/api/queries/posts';
import { ThemedText } from '@/components/themed-text';
import { Colors, FontSize, Radius, Spacing, labelType } from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/**
 * The two small pieces the profile's own grid needs.
 *
 * **The author's actions are not here.** Taking a fit private or down
 * lives on the fit's own screen, under the `...` it already has - the
 * profile's tiles carry no menu glyph, so they look exactly like the
 * kept ones beside them. A sheet lived here briefly and was removed
 * rather than left exported: two routes to the same two actions is
 * one more than there should be.
 */

/**
 * A fit of the author's own, in the shape a tile reads.
 *
 * The author's list carries less than the board's does - no tags, no
 * reactions, no comment count - because none of it is shown here. The
 * fields a tile actually uses are the id, the cover and its shape, and
 * those are all real.
 */
export function asFit(post: MinePost): FeedFit {
  return {
    id: post.id,
    authorId: post.authorId,
    authorName: post.authorName,
    caption: post.caption,
    captionIsDescribed: false,
    mediaAssetIds: post.mediaAssetIds,
    coverRatio: post.coverRatio,
    tags: [],
    groups: [],
    reactions: 0,
    saves: post.saves,
    comments: 0,
    myReaction: null,
    savedByMe: post.savedByMe,
    publishedAt: post.publishedAt,
  };
}

/**
 * Said on the tile, because the setting is invisible otherwise.
 *
 * A private fit looks exactly like a public one on your own profile -
 * which is the point, it is still yours - so without this the only way
 * to know which way the switch is set is to open the menu on every
 * tile. Held and removed say so here too: a fit that a stranger cannot
 * see should never look to its author like one that can.
 */
export function PostedBadge({ post }: { post: MinePost }) {
  const colors = Colors[useScheme()];

  const label =
    post.visibility === 'private'
      ? 'Private'
      : post.state === 'held'
        ? 'Held'
        : post.state === 'removed'
          ? 'Removed'
          : null;
  if (label === null) return null;

  return (
    <View
      // Not announced separately: the tile's own label already names
      // the fit, and this is read out as part of it.
      style={{
        position: 'absolute',
        top: Spacing.two,
        left: Spacing.two,
        paddingHorizontal: Spacing.two,
        paddingVertical: Spacing.half,
        borderRadius: Radius.full,
        backgroundColor: colors.scrim,
      }}>
      <ThemedText style={{ ...labelType(FontSize.meta, 800), color: '#FFFFFF' }}>
        {label}
      </ThemedText>
    </View>
  );
}
