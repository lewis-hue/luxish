import { Image } from 'expo-image';
import { SymbolView } from 'expo-symbols';
import { router } from 'expo-router';
import { useState } from 'react';
import {
  Modal,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
  useWindowDimensions,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  boardsHoldingPost,
  useCreateBoard,
  useMoodboards,
  usePinPost,
  useUnpinPost,
  type Moodboard,
} from '@/api/queries/moodboards';
import { usePostImages } from '@/api/queries/post-media';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, successFeedback, tapFeedback } from '@/components/ui/motion';
import { SkeletonMasonry } from '@/components/ui/skeleton';
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

/** Faces on one board tile. Three is the reference's composition. */
const FACES = 3;

/**
 * Where a save goes.
 *
 * **Boards are shown as what is on them.** A list of names with a
 * thumbnail beside each is a file manager; two columns of the boards'
 * own photographs is the thing being chosen between, and it keeps a
 * board honest — it cannot look fuller than it is.
 *
 * **Profile is a board here, and it is the default.** Everything saved
 * without a decision lives there, so it belongs in the grid rather
 * than being an absence from it.
 *
 * **A tap is a toggle.** The sheet shows every board with its current
 * state, so it is also how something comes off one. A "Save" that
 * cannot unsave sends people hunting through boards to undo a mistap.
 *
 * **Naming a new board happens here.** The commonest moment for
 * wanting one is the moment you find something that belongs on no
 * board you have.
 */
export function PinToBoard({
  postId,
  title,
  visible,
  onClose,
}: {
  /** The fit being saved. A board holds published fits and nothing else. */
  postId: string;
  title: string;
  visible: boolean;
  onClose: () => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const auth = useAuth();
  const signedIn = auth.status === 'signedIn';

  const boards = useMoodboards(signedIn && visible);
  const create = useCreateBoard();
  const pinPost = usePinPost();
  const unpinPost = useUnpinPost();

  const put = async (boardId: string) =>
    pinPost.mutateAsync({ id: boardId, postId });
  const take = async (boardId: string) =>
    unpinPost.mutateAsync({ id: boardId, postId });

  const [naming, setNaming] = useState(false);
  const [name, setName] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const holding = boardsHoldingPost(boards.data, postId);

  const all = boards.data ?? [];
  // Every picture on every board, asked for once. A request per tile
  // is a dozen subscriptions that each re-render the sheet.
  const faces = usePostImages(
    all.flatMap((board) => board.postIds.slice(0, FACES)),
  );
  const column = (width - Spacing.three * 2 - Spacing.two) / 2;

  const makeAndPin = async () => {
    const cleaned = name.trim();
    if (!cleaned) return;
    void tapFeedback();
    setProblem(null);
    try {
      const made = await create.mutateAsync({ name: cleaned });
      if (made?.id) await put(made.id);
      setName('');
      setNaming(false);
      void successFeedback();
    } catch (caught) {
      setProblem(
        caught instanceof Error && caught.message.trim()
          ? caught.message.trim()
          : 'That board could not be made.',
      );
    }
  };

  const toggle = async (boardId: string) => {
    void tapFeedback();
    setProblem(null);
    try {
      if (holding.has(boardId)) {
        await take(boardId);
      } else {
        await put(boardId);
        void successFeedback();
      }
    } catch (caught) {
      setProblem(
        caught instanceof Error && caught.message.trim()
          ? caught.message.trim()
          : 'That did not save.',
      );
    }
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: colors.background }}>
        {/* Close on the left, the title in the middle: this is a sheet
            about one decision, and a heading that shares the row with
            its own dismissal reads as the page it is. */}
        <View
          style={{
            minHeight: TapTarget + Spacing.two,
            justifyContent: 'center',
            paddingHorizontal: Spacing.three,
          }}>
          <ThemedText
            accessibilityRole="header"
            style={{
              ...labelType(FontSize.body, 800),
              textAlign: 'center',
            }}>
            Save to
          </ThemedText>
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Close"
            animateEntrance={false}
            scale={0.92}
            hitSlop={8}
            onPress={onClose}
            style={{
              position: 'absolute',
              left: Spacing.two,
              width: TapTarget,
              height: TapTarget,
              alignItems: 'center',
              justifyContent: 'center',
            }}>
            <SymbolView
              name={{ ios: 'xmark', android: 'close', web: 'close' }}
              size={18}
              tintColor={colors.text}
            />
          </MotionPressable>
        </View>

        <ScrollView
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{
            paddingHorizontal: Spacing.three,
            paddingBottom: Spacing.five,
            gap: Spacing.three,
          }}
          showsVerticalScrollIndicator={false}>
          <ThemedText
            numberOfLines={1}
            themeColor="textSecondary"
            style={labelType(FontSize.subhead, 400)}>
            {title}
          </ThemedText>

          {!signedIn ? (
            <ThemedText type="small" themeColor="textSecondary">
              Sign in to make boards.
            </ThemedText>
          ) : (
            <>
              {naming ? (
                <View style={{ flexDirection: 'row', gap: Spacing.two }}>
                  <TextInput
                    value={name}
                    onChangeText={setName}
                    placeholder="Name it"
                    placeholderTextColor={colors.textSecondary}
                    returnKeyType="done"
                    autoFocus
                    onSubmitEditing={() => void makeAndPin()}
                    accessibilityLabel="Name a new board"
                    maxLength={80}
                    style={{
                      flex: 1,
                      minHeight: TapTarget,
                      paddingHorizontal: Spacing.three,
                      borderRadius: Radius.md,
                      borderCurve: 'continuous',
                      borderWidth: 1,
                      borderColor: colors.borderStrong,
                      color: colors.text,
                      ...labelType(FontSize.subhead, 400),
                    }}
                  />
                  <MotionPressable
                    accessibilityRole="button"
                    accessibilityLabel="Make this board and save here"
                    disabled={!name.trim() || create.isPending}
                    animateEntrance={false}
                    onPress={() => void makeAndPin()}
                    style={{
                      minHeight: TapTarget,
                      paddingHorizontal: Spacing.four,
                      alignItems: 'center',
                      justifyContent: 'center',
                      borderRadius: Radius.md,
                      borderCurve: 'continuous',
                      backgroundColor: colors.text,
                      opacity: !name.trim() || create.isPending ? 0.4 : 1,
                    }}>
                    <ThemedText
                      style={{
                        ...labelType(FontSize.subhead, 800),
                        color: colors.background,
                      }}>
                      Make
                    </ThemedText>
                  </MotionPressable>
                </View>
              ) : null}

              {problem ? (
                <ThemedText type="small" style={{ color: colors.danger }}>
                  {problem}
                </ThemedText>
              ) : null}

              <View
                style={{
                  flexDirection: 'row',
                  flexWrap: 'wrap',
                  gap: Spacing.two,
                }}>
                {all.length === 0 && boards.isPending ? (
                  <SkeletonMasonry
                    count={4}
                    columns={2}
                    gutter={Spacing.two}
                    label="Loading your boards"
                  />
                ) : null}
                {all.map((board) => (
                  <BoardTile
                    key={board.id}
                    board={board}
                    width={column}
                    pictures={faces.data ?? {}}
                    saved={holding.has(board.id)}
                    onPress={() => void toggle(board.id)}
                  />
                ))}

                {/* Where an unsorted save already is. Shown as a tile
                    rather than implied by its absence, so the grid
                    answers "where did the last one go". */}
                <MotionPressable
                  accessibilityRole="link"
                  accessibilityLabel="Profile, where unsorted saves live"
                  animateEntrance={false}
                  onPress={() => {
                    void tapFeedback();
                    onClose();
                    router.push('/saved');
                  }}
                  style={{ width: column, gap: Spacing.one }}>
                  <View
                    style={{
                      width: column,
                      aspectRatio: 1,
                      borderRadius: Radius.md,
                      borderCurve: 'continuous',
                      alignItems: 'center',
                      justifyContent: 'center',
                      backgroundColor: colors.backgroundElement,
                    }}>
                    <SymbolView
                      name={{ ios: 'person', android: 'person', web: 'person' }}
                      size={28}
                      tintColor={colors.textSecondary}
                    />
                  </View>
                  <ThemedText style={labelType(FontSize.subhead, 800)}>
                    Profile
                  </ThemedText>
                </MotionPressable>
              </View>
            </>
          )}
        </ScrollView>

        <View
          style={{
            paddingHorizontal: Spacing.three,
            paddingTop: Spacing.two,
            paddingBottom: insets.bottom + Spacing.three,
          }}>
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Create a new board"
            animateEntrance={false}
            onPress={() => {
              void tapFeedback();
              setNaming(true);
            }}
            style={{
              minHeight: TapTarget + Spacing.one,
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              backgroundColor: colors.accent,
            }}>
            <ThemedText
              style={{
                ...labelType(FontSize.body, 800),
                color: colors.accentText,
              }}>
              Create new board
            </ThemedText>
          </MotionPressable>
        </View>
      </View>
    </Modal>
  );
}

/**
 * One board, wearing the first few things on it.
 *
 * One pin fills the frame, two split it, three make a grid with the
 * first given the larger half. The asymmetry is deliberate: four equal
 * squares is a component library's idea of a collage.
 */
function BoardTile({
  board,
  width,
  pictures,
  saved,
  onPress,
}: {
  board: Moodboard;
  width: number;
  pictures: Record<string, string>;
  saved: boolean;
  onPress: () => void;
}) {
  const colors = Colors[useScheme()];
  const shown = board.postIds
    .slice(0, FACES)
    .map((id) => pictures[id])
    .filter(Boolean);
  const pins = board.postIds.length;

  return (
    <MotionPressable
      accessibilityRole="checkbox"
      accessibilityState={{ checked: saved }}
      accessibilityLabel={`${board.name}, ${pins === 1 ? '1 pin' : `${pins} pins`}`}
      animateEntrance={false}
      onPress={onPress}
      style={{ width, gap: Spacing.one }}>
      <View
        style={{
          width,
          aspectRatio: 1,
          borderRadius: Radius.md,
          borderCurve: 'continuous',
          overflow: 'hidden',
          backgroundColor: colors.backgroundElement,
          flexDirection: 'row',
          // A hairline between faces, so two photographs sharing a tone
          // still read as two.
          gap: StyleSheet.hairlineWidth,
        }}>
        {shown.length > 0 ? (
          <>
            <Image
              source={{ uri: shown[0] }}
              contentFit="cover"
              accessible={false}
              style={{ flex: shown.length === 1 ? 1 : 1.2 }}
            />
            {shown.length > 1 ? (
              <View style={{ flex: 1, gap: StyleSheet.hairlineWidth }}>
                {shown.slice(1).map((uri) => (
                  <Image
                    key={uri}
                    source={{ uri }}
                    contentFit="cover"
                    accessible={false}
                    style={{ flex: 1 }}
                  />
                ))}
              </View>
            ) : null}
          </>
        ) : null}

        {/* On a board already, said with a mark as well as a tint:
            colour alone cannot carry a state. */}
        {saved ? (
          <View
            style={{
              position: 'absolute',
              right: Spacing.one,
              bottom: Spacing.one,
              width: 28,
              height: 28,
              borderRadius: Radius.full,
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: colors.text,
            }}>
            <SymbolView
              name={{ ios: 'checkmark', android: 'check', web: 'check' }}
              size={14}
              tintColor={colors.background}
            />
          </View>
        ) : null}
      </View>

      <ThemedText numberOfLines={1} style={labelType(FontSize.subhead, 800)}>
        {board.name}
      </ThemedText>
      <ThemedText
        themeColor="textSecondary"
        style={labelType(FontSize.footnote, 400)}>
        {pins === 1 ? '1 pin' : `${pins} pins`}
      </ThemedText>
    </MotionPressable>
  );
}
