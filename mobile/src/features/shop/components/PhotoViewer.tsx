import { Ionicons } from '@expo/vector-icons';
import { Image } from 'expo-image';
import React, { useState } from 'react';
import {
  FlatList,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { colors, spacing, typography } from '../../../theme';

/**
 * A product's photos, full screen. Swipe sideways to move between them.
 *
 * Mount it only while it is open (`index !== null` at the caller), so it always
 * starts on the photo that was tapped.
 */
export function PhotoViewer({
  uris,
  initialIndex,
  onClose,
}: {
  uris: string[];
  initialIndex: number;
  onClose: () => void;
}) {
  const { width, height } = useWindowDimensions();
  const [index, setIndex] = useState(initialIndex);

  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <FlatList
          data={uris}
          keyExtractor={(uri, i) => `${i}-${uri}`}
          horizontal
          pagingEnabled
          showsHorizontalScrollIndicator={false}
          initialScrollIndex={initialIndex}
          getItemLayout={(_, i) => ({ length: width, offset: width * i, index: i })}
          onMomentumScrollEnd={(event) =>
            setIndex(Math.round(event.nativeEvent.contentOffset.x / width))
          }
          renderItem={({ item }) => (
            <Image source={{ uri: item }} style={{ width, height }} contentFit="contain" />
          )}
        />

        <SafeAreaView style={styles.bar} edges={['top']} pointerEvents="box-none">
          <Text style={styles.count}>
            {index + 1} / {uris.length}
          </Text>
          <Pressable
            onPress={onClose}
            hitSlop={14}
            style={styles.close}
            accessibilityRole="button"
            accessibilityLabel="Close photos"
          >
            <Ionicons name="close" size={24} color={colors.white} />
          </Pressable>
        </SafeAreaView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: '#000' },
  bar: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.lg,
  },
  count: { ...typography.caption, color: colors.white, fontWeight: '600' },
  close: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.overlay,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
