import { SymbolView, type SymbolViewProps } from 'expo-symbols';
import { useState } from 'react';
import { Alert, Modal, Pressable, ScrollView, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  useCreateFolder,
  useDeleteFolder,
  useRenameFolder,
  useSetFolderMembers,
  type WardrobeFolder,
} from '@/api/queries/collections';
import { ThemedText } from '@/components/themed-text';
import { MotionPressable, successFeedback, tapFeedback } from '@/components/ui/motion';
import {
  BottomTabInset,
  Colors,
  FontSize,
  Radius,
  Spacing,
  TapTarget,
} from '@/constants/theme';
import { useScheme } from '@/hooks/use-theme';

/**
 * The bar that appears when garments are selected.
 *
 * **It floats over the grid rather than replacing the header.** Selecting
 * is a mode you are in *while looking at the wardrobe*, so the wardrobe
 * has to stay visible — a mode that hides what it acts on makes people
 * leave it to check what they picked.
 *
 * **Filing is a set operation, not a move.** Putting three things in
 * "Work" does not take them out of "Travel", because the same blazer
 * genuinely belongs to both. The sheet says so rather than leaving
 * somebody to discover it.
 */
export function SelectionBar({
  count,
  folders,
  selectedIds,
  onDelete,
  onClear,
}: {
  count: number;
  folders: readonly WardrobeFolder[];
  selectedIds: readonly string[];
  onDelete: () => void;
  onClear: () => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const [filing, setFiling] = useState(false);

  if (count === 0) return null;

  const confirmDelete = () => {
    Alert.alert(
      `Remove ${count} ${count === 1 ? 'item' : 'items'}?`,
      'They leave your wardrobe and the stylist stops suggesting them.',
      [
        { text: 'Keep', style: 'cancel' },
        { text: 'Remove', style: 'destructive', onPress: onDelete },
      ],
    );
  };

  return (
    <>
      <View
        pointerEvents="box-none"
        style={{
          position: 'absolute',
          left: Spacing.three,
          right: Spacing.three,
          bottom: BottomTabInset + insets.bottom + Spacing.two,
        }}>
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            gap: Spacing.two,
            paddingHorizontal: Spacing.two,
            paddingVertical: Spacing.two,
            borderRadius: Radius.lg,
            borderCurve: 'continuous',
            backgroundColor: colors.background,
            borderWidth: 1,
            borderColor: colors.border,
            boxShadow: '0 6px 16px rgba(0, 0, 0, 0.18)',
          }}>
          <ThemedText type="smallBold" style={{ flex: 1, paddingLeft: Spacing.two }}>
            {count} selected
          </ThemedText>
          <BarAction
            label="File"
            icon={{ ios: 'folder', android: 'folder', web: 'folder' }}
            onPress={() => {
              void tapFeedback();
              setFiling(true);
            }}
          />
          <BarAction
            label="Remove"
            icon={{ ios: 'trash', android: 'delete', web: 'delete' }}
            destructive
            onPress={() => {
              void tapFeedback();
              confirmDelete();
            }}
          />
          <BarAction
            label="Done"
            icon={{ ios: 'xmark', android: 'close', web: 'close' }}
            onPress={() => {
              void tapFeedback();
              onClear();
            }}
          />
        </View>
      </View>

      <Modal
        visible={filing}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setFiling(false)}>
        <FolderSheet
          folders={folders}
          selectedIds={selectedIds}
          onClose={() => setFiling(false)}
          onFiled={() => {
            setFiling(false);
            onClear();
          }}
        />
      </Modal>
    </>
  );
}

function BarAction({
  label,
  icon,
  onPress,
  destructive,
}: {
  label: string;
  icon: SymbolViewProps['name'];
  onPress: () => void;
  destructive?: boolean;
}) {
  const colors = Colors[useScheme()];
  const tint = destructive ? colors.danger : colors.text;
  return (
    <MotionPressable
      accessibilityRole="button"
      accessibilityLabel={label}
      animateEntrance={false}
      scale={0.92}
      onPress={onPress}
      style={{
        width: TapTarget + Spacing.two,
        height: TapTarget,
        alignItems: 'center',
        justifyContent: 'center',
        gap: Spacing.half,
      }}>
      <SymbolView name={icon} size={19} tintColor={tint} />
      <ThemedText type="small" style={{ fontSize: FontSize.meta, color: tint }}>
        {label}
      </ThemedText>
    </MotionPressable>
  );
}

/**
 * Which folders the selection belongs to.
 *
 * A toggle per folder rather than a one-way "move", because that is also
 * how something gets un-filed — and because a garment is in as many
 * folders as it is actually in.
 *
 * Naming a new folder is in the same sheet: the most common moment for
 * wanting one is the moment you have picked things that do not fit any of
 * the existing ones.
 */
function FolderSheet({
  folders,
  selectedIds,
  onClose,
  onFiled,
}: {
  folders: readonly WardrobeFolder[];
  selectedIds: readonly string[];
  onClose: () => void;
  onFiled: () => void;
}) {
  const colors = Colors[useScheme()];
  const insets = useSafeAreaInsets();
  const [name, setName] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draft, setDraft] = useState('');

  const create = useCreateFolder();
  const renameFolder = useRenameFolder();
  const deleteFolder = useDeleteFolder();
  const setMembers = useSetFolderMembers();

  const ids = [...selectedIds];
  const holdsAll = (folder: WardrobeFolder) =>
    ids.length > 0 && ids.every((id) => folder.garmentIds.includes(id));

  const toggle = (folder: WardrobeFolder) => {
    void tapFeedback();
    setMembers.mutate(
      { id: folder.id, garmentIds: ids, present: !holdsAll(folder) },
      { onError: (error) => setProblem((error as Error).message) },
    );
  };

  const makeAndFile = () => {
    const cleaned = name.trim();
    if (!cleaned) return;
    setProblem(null);
    create.mutate(cleaned, {
      onSuccess: (folder) => {
        setName('');
        setMembers.mutate(
          { id: folder.id, garmentIds: ids, present: true },
          {
            onSuccess: () => {
              void successFeedback();
              onFiled();
            },
          },
        );
      },
      onError: (error) => setProblem((error as Error).message),
    });
  };

  const commitRename = (folder: WardrobeFolder) => {
    const cleaned = draft.trim();
    setRenaming(null);
    if (!cleaned || cleaned === folder.name) return;
    setProblem(null);
    renameFolder.mutate(
      { id: folder.id, name: cleaned },
      { onError: (error) => setProblem((error as Error).message) },
    );
  };

  const confirmDeleteFolder = (folder: WardrobeFolder) => {
    Alert.alert(
      `Delete "${folder.name}"?`,
      'The folder goes. The clothes in it stay in your wardrobe.',
      [
        { text: 'Keep', style: 'cancel' },
        {
          text: 'Delete folder',
          style: 'destructive',
          onPress: () => deleteFolder.mutate(folder.id),
        },
      ],
    );
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <ScrollView
        contentInsetAdjustmentBehavior="automatic"
        automaticallyAdjustKeyboardInsets
        keyboardDismissMode="interactive"
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{
          padding: Spacing.three,
          paddingBottom: insets.bottom + Spacing.four,
          gap: Spacing.three,
        }}>
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}>
          <ThemedText type="smallBold">
            File {ids.length} {ids.length === 1 ? 'item' : 'items'}
          </ThemedText>
          <Pressable accessibilityRole="button" onPress={onClose} hitSlop={10}>
            <ThemedText type="small" themeColor="textSecondary">
              Close
            </ThemedText>
          </Pressable>
        </View>

        <ThemedText
          type="small"
          themeColor="textSecondary"
          style={{ fontSize: FontSize.footnote }}>
          A piece can be in several folders. Filing it here does not take it
          out of anywhere else.
        </ThemedText>

        {problem ? (
          <ThemedText type="small" style={{ color: colors.danger }}>
            {problem}
          </ThemedText>
        ) : null}

        <View style={{ gap: Spacing.one }}>
          {folders.map((folder) => {
            const on = holdsAll(folder);
            if (renaming === folder.id) {
              return (
                <TextInput
                  key={folder.id}
                  value={draft}
                  onChangeText={setDraft}
                  onBlur={() => commitRename(folder)}
                  onSubmitEditing={() => commitRename(folder)}
                  autoFocus
                  returnKeyType="done"
                  accessibilityLabel={`Rename ${folder.name}`}
                  style={{
                    minHeight: TapTarget,
                    paddingHorizontal: Spacing.three,
                    borderRadius: Radius.md,
                    borderCurve: 'continuous',
                    borderWidth: 1,
                    borderColor: colors.borderStrong,
                    backgroundColor: colors.backgroundElement,
                    color: colors.text,
                    fontSize: FontSize.body,
                  }}
                />
              );
            }
            return (
              <View
                key={folder.id}
                style={{ flexDirection: 'row', alignItems: 'center', gap: Spacing.one }}>
                <MotionPressable
                  accessibilityRole="button"
                  accessibilityState={{ selected: on }}
                  accessibilityLabel={`${folder.name}, ${folder.garmentIds.length} items`}
                  accessibilityHint={on ? 'Takes them out' : 'Puts them in'}
                  animateEntrance={false}
                  onPress={() => toggle(folder)}
                  style={{
                    flex: 1,
                    minHeight: TapTarget,
                    flexDirection: 'row',
                    alignItems: 'center',
                    gap: Spacing.three,
                    paddingHorizontal: Spacing.three,
                    borderRadius: Radius.md,
                    borderCurve: 'continuous',
                    borderWidth: 1,
                    borderColor: on ? colors.accent : colors.border,
                    backgroundColor: on ? colors.accent : 'transparent',
                  }}>
                  <SymbolView
                    name={{
                      ios: on ? 'checkmark.circle.fill' : 'circle',
                      android: on ? 'check_circle' : 'radio_button_unchecked',
                      web: 'check_circle',
                    }}
                    size={20}
                    tintColor={on ? colors.accentText : colors.textSecondary}
                  />
                  <ThemedText
                    type="small"
                    numberOfLines={1}
                    style={{ flex: 1, color: on ? colors.accentText : colors.text }}>
                    {folder.name}
                  </ThemedText>
                  <ThemedText
                    type="small"
                    style={{
                      fontSize: FontSize.meta,
                      color: on ? colors.accentText : colors.textSecondary,
                    }}>
                    {folder.garmentIds.length}
                  </ThemedText>
                </MotionPressable>

                <MotionPressable
                  accessibilityRole="button"
                  accessibilityLabel={`Rename ${folder.name}`}
                  animateEntrance={false}
                  hitSlop={6}
                  onPress={() => {
                    void tapFeedback();
                    setDraft(folder.name);
                    setRenaming(folder.id);
                  }}
                  style={{
                    width: TapTarget - Spacing.two,
                    height: TapTarget,
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}>
                  <SymbolView
                    name={{ ios: 'pencil', android: 'edit', web: 'edit' }}
                    size={16}
                    tintColor={colors.textSecondary}
                  />
                </MotionPressable>

                <MotionPressable
                  accessibilityRole="button"
                  accessibilityLabel={`Delete the folder ${folder.name}`}
                  animateEntrance={false}
                  hitSlop={6}
                  onPress={() => {
                    void tapFeedback();
                    confirmDeleteFolder(folder);
                  }}
                  style={{
                    width: TapTarget - Spacing.two,
                    height: TapTarget,
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}>
                  <SymbolView
                    name={{ ios: 'trash', android: 'delete', web: 'delete' }}
                    size={16}
                    tintColor={colors.textSecondary}
                  />
                </MotionPressable>
              </View>
            );
          })}
        </View>

        <View style={{ gap: Spacing.two }}>
          <ThemedText type="label" themeColor="textSecondary">
            New folder
          </ThemedText>
          <TextInput
            value={name}
            onChangeText={setName}
            onSubmitEditing={makeAndFile}
            returnKeyType="done"
            placeholder="Work, Gym, Weekend away"
            placeholderTextColor={colors.textSecondary}
            accessibilityLabel="Name a new folder"
            style={{
              minHeight: TapTarget,
              paddingHorizontal: Spacing.three,
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              borderWidth: 1,
              borderColor: colors.borderStrong,
              backgroundColor: colors.backgroundElement,
              color: colors.text,
              fontSize: FontSize.body,
            }}
          />
          <MotionPressable
            accessibilityRole="button"
            accessibilityLabel="Make the folder and file these"
            accessibilityState={{ disabled: name.trim().length === 0 }}
            disabled={name.trim().length === 0}
            animateEntrance={false}
            onPress={makeAndFile}
            style={{
              minHeight: TapTarget,
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: Radius.md,
              borderCurve: 'continuous',
              backgroundColor: colors.accent,
              opacity: name.trim().length === 0 ? 0.45 : 1,
            }}>
            <ThemedText type="smallBold" style={{ color: colors.accentText }}>
              Make folder and file
            </ThemedText>
          </MotionPressable>
        </View>
      </ScrollView>
    </View>
  );
}
