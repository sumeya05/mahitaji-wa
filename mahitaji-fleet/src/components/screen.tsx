import type { ReactNode } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, type StyleProp, type ViewStyle } from 'react-native';

import { space } from '@/lib/theme';

/** A scrolling page that keeps focused inputs above the keyboard. */
export function FormScreen({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={90}>
      <ScrollView
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={[{ padding: space.lg, gap: space.lg, paddingBottom: space.xxl }, style]}>
        {children}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
