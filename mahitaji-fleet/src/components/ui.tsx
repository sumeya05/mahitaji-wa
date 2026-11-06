import Ionicons from '@expo/vector-icons/Ionicons';
import { type ComponentProps, type ReactNode, useState } from 'react';
import {
  ActivityIndicator, Pressable, type StyleProp, StyleSheet, Text, type TextInputProps, TextInput, type TextProps,
  View, type ViewStyle,
} from 'react-native';

import { colors, fonts, radius, shadow, space, type Tone, tones } from '@/lib/theme';

export type IconName = ComponentProps<typeof Ionicons>['name'];

// ---------------------------------------------------------------------------
// Text
// ---------------------------------------------------------------------------
type Variant = 'title' | 'heading' | 'subheading' | 'body' | 'label' | 'caption';

export function T({ variant = 'body', style, ...props }: TextProps & { variant?: Variant }) {
  return <Text {...props} style={[text[variant], style]} />;
}

const text = StyleSheet.create({
  title: { fontFamily: fonts.displayHeavy, fontSize: 26, color: colors.ink, letterSpacing: -0.4 },
  heading: { fontFamily: fonts.display, fontSize: 19, color: colors.ink },
  subheading: { fontFamily: fonts.semibold, fontSize: 16, color: colors.ink },
  body: { fontFamily: fonts.body, fontSize: 15, color: colors.text, lineHeight: 21 },
  label: { fontFamily: fonts.semibold, fontSize: 13, color: colors.text2 },
  caption: { fontFamily: fonts.body, fontSize: 12.5, color: colors.muted, lineHeight: 17 },
});

// ---------------------------------------------------------------------------
// Buttons
// ---------------------------------------------------------------------------
type ButtonKind = 'primary' | 'secondary' | 'ghost' | 'danger' | 'accent';

export function Button({
  title, onPress, kind = 'primary', icon, loading, disabled, style, small,
}: {
  title: string;
  onPress?: () => void;
  kind?: ButtonKind;
  icon?: IconName;
  loading?: boolean;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
  small?: boolean;
}) {
  const palette = buttonPalette[kind];
  const inactive = disabled || loading;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: !!inactive, busy: !!loading }}
      onPress={onPress}
      disabled={inactive}
      style={({ pressed }) => [
        styles.button,
        small && styles.buttonSmall,
        { backgroundColor: palette.bg, borderColor: palette.border },
        pressed && { opacity: 0.85 },
        inactive && { opacity: 0.55 },
        style,
      ]}>
      {loading ? (
        <ActivityIndicator color={palette.fg} />
      ) : (
        <>
          {icon && <Ionicons name={icon} size={small ? 16 : 18} color={palette.fg} />}
          <Text style={[styles.buttonText, small && { fontSize: 14 }, { color: palette.fg }]}>{title}</Text>
        </>
      )}
    </Pressable>
  );
}

const buttonPalette: Record<ButtonKind, { bg: string; fg: string; border: string }> = {
  primary: { bg: colors.brand800, fg: '#fff', border: colors.brand800 },
  accent: { bg: colors.amber500, fg: colors.brand950, border: colors.amber500 },
  secondary: { bg: colors.surface, fg: colors.brand800, border: colors.line2 },
  ghost: { bg: 'transparent', fg: colors.brand700, border: 'transparent' },
  danger: { bg: colors.surface, fg: colors.danger, border: colors.danger100 },
};

export function IconButton({
  icon, onPress, label, color = colors.ink, size = 22, style, badge,
}: {
  icon: IconName;
  onPress?: () => void;
  label: string;
  color?: string;
  size?: number;
  style?: StyleProp<ViewStyle>;
  badge?: number;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={8}
      onPress={onPress}
      style={({ pressed }) => [styles.iconButton, pressed && { opacity: 0.6 }, style]}>
      <Ionicons name={icon} size={size} color={color} />
      {!!badge && (
        <View style={styles.dotBadge}>
          <Text style={styles.dotBadgeText}>{badge > 99 ? '99+' : badge}</Text>
        </View>
      )}
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// Form fields
// ---------------------------------------------------------------------------
export function Field({
  label, error, hint, secure, style, ...props
}: TextInputProps & { label: string; error?: string; hint?: string; secure?: boolean }) {
  const [hidden, setHidden] = useState(true);
  const [focused, setFocused] = useState(false);
  return (
    <View style={[{ gap: 6 }, style as StyleProp<ViewStyle>]}>
      <T variant="label">{label}</T>
      <View
        style={[
          styles.input,
          focused && { borderColor: colors.brand500 },
          !!error && { borderColor: colors.danger },
        ]}>
        <TextInput
          accessibilityLabel={label}
          placeholderTextColor={colors.muted}
          secureTextEntry={secure && hidden}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          style={[styles.inputText, props.multiline && { minHeight: 84, textAlignVertical: 'top', paddingTop: 12 }]}
          {...props}
        />
        {secure && (
          <IconButton
            icon={hidden ? 'eye-outline' : 'eye-off-outline'}
            label={hidden ? 'Show password' : 'Hide password'}
            size={20}
            color={colors.muted}
            onPress={() => setHidden((h) => !h)}
          />
        )}
      </View>
      {error ? (
        <T variant="caption" style={{ color: colors.danger }}>{error}</T>
      ) : hint ? (
        <T variant="caption">{hint}</T>
      ) : null}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Containers & feedback
// ---------------------------------------------------------------------------
export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function Badge({ label, tone = 'info', icon }: { label: string; tone?: Tone; icon?: IconName }) {
  const palette = tones[tone];
  return (
    <View style={[styles.badge, { backgroundColor: palette.bg }]}>
      {icon && <Ionicons name={icon} size={12} color={palette.fg} />}
      <Text style={[styles.badgeText, { color: palette.fg }]}>{label}</Text>
    </View>
  );
}

export function Chip({ label, active, onPress, icon }: { label: string; active?: boolean; onPress?: () => void; icon?: IconName }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: !!active }}
      onPress={onPress}
      style={[styles.chip, active && styles.chipActive]}>
      {icon && <Ionicons name={icon} size={15} color={active ? '#fff' : colors.text2} />}
      <Text style={[styles.chipText, active && { color: '#fff' }]} numberOfLines={1}>{label}</Text>
    </Pressable>
  );
}

export function Notice({ tone = 'info', children, icon }: { tone?: Tone; children: ReactNode; icon?: IconName }) {
  const palette = tones[tone];
  return (
    <View style={[styles.notice, { backgroundColor: palette.bg }]}>
      <Ionicons
        name={icon ?? (tone === 'danger' ? 'alert-circle' : tone === 'success' ? 'checkmark-circle' : 'information-circle')}
        size={18}
        color={palette.fg}
      />
      <Text style={[styles.noticeText, { color: palette.fg }]}>{children}</Text>
    </View>
  );
}

export function Loading({ label }: { label?: string }) {
  return (
    <View style={styles.center}>
      <ActivityIndicator size="large" color={colors.brand600} />
      {label && <T variant="caption">{label}</T>}
    </View>
  );
}

export function EmptyState({
  icon, title, message, action,
}: {
  icon: IconName;
  title: string;
  message?: string;
  action?: ReactNode;
}) {
  return (
    <View style={styles.center}>
      <View style={styles.emptyIcon}>
        <Ionicons name={icon} size={34} color={colors.brand600} />
      </View>
      <T variant="heading" style={{ textAlign: 'center' }}>{title}</T>
      {message && <T style={{ textAlign: 'center', color: colors.muted }}>{message}</T>}
      {action}
    </View>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <EmptyState
      icon="cloud-offline-outline"
      title="Couldn't load this"
      message={error instanceof Error ? error.message : 'Please try again.'}
      action={onRetry && <Button title="Try again" kind="secondary" icon="refresh" onPress={onRetry} />}
    />
  );
}

export function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <View style={styles.row}>
      <T variant={strong ? 'subheading' : 'body'} style={!strong && { color: colors.text2 }}>{label}</T>
      <T variant={strong ? 'subheading' : 'body'} style={strong && { fontFamily: fonts.display, fontSize: 18 }}>{value}</T>
    </View>
  );
}

export function Divider() {
  return <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: colors.line2, marginVertical: space.sm }} />;
}

export function SectionHeader({ title, action, onAction }: { title: string; action?: string; onAction?: () => void }) {
  return (
    <View style={styles.sectionHeader}>
      <T variant="heading">{title}</T>
      {action && (
        <Pressable onPress={onAction} hitSlop={8} accessibilityRole="link">
          <Text style={styles.sectionAction}>{action}</Text>
        </Pressable>
      )}
    </View>
  );
}

export function ListItem({
  icon, title, subtitle, onPress, right, danger,
}: {
  icon: IconName;
  title: string;
  subtitle?: string;
  onPress?: () => void;
  right?: ReactNode;
  danger?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [styles.listItem, pressed && { backgroundColor: colors.bg }]}>
      <View style={[styles.listIcon, danger && { backgroundColor: colors.danger100 }]}>
        <Ionicons name={icon} size={19} color={danger ? colors.danger : colors.brand700} />
      </View>
      <View style={{ flex: 1 }}>
        <T variant="subheading" style={[{ fontSize: 15 }, danger && { color: colors.danger }]}>{title}</T>
        {subtitle && <T variant="caption">{subtitle}</T>}
      </View>
      {right ?? <Ionicons name="chevron-forward" size={18} color={colors.muted} />}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    minHeight: 50,
    borderRadius: radius.md,
    borderWidth: 1,
    paddingHorizontal: space.lg,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.sm,
  },
  buttonSmall: { minHeight: 40, paddingHorizontal: space.md, borderRadius: radius.sm },
  buttonText: { fontFamily: fonts.semibold, fontSize: 15.5 },
  iconButton: { padding: 6, alignItems: 'center', justifyContent: 'center' },
  dotBadge: {
    position: 'absolute',
    top: 0,
    right: -2,
    minWidth: 18,
    height: 18,
    borderRadius: 9,
    paddingHorizontal: 4,
    backgroundColor: colors.amber500,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dotBadgeText: { fontFamily: fonts.semibold, fontSize: 10.5, color: colors.brand950 },
  input: {
    minHeight: 50,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.line2,
    backgroundColor: colors.surface,
    flexDirection: 'row',
    alignItems: 'center',
    paddingLeft: space.md,
    paddingRight: space.xs,
  },
  inputText: { flex: 1, fontFamily: fonts.body, fontSize: 15.5, color: colors.ink, paddingVertical: 12 },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.line,
    padding: space.lg,
    ...shadow,
  },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    alignSelf: 'flex-start',
    borderRadius: radius.pill,
    paddingHorizontal: 9,
    paddingVertical: 3,
  },
  badgeText: { fontFamily: fonts.semibold, fontSize: 11.5 },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    height: 36,
    paddingHorizontal: 14,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.line2,
    backgroundColor: colors.surface,
  },
  chipActive: { backgroundColor: colors.brand800, borderColor: colors.brand800 },
  chipText: { fontFamily: fonts.medium, fontSize: 13.5, color: colors.text2, maxWidth: 180 },
  notice: { flexDirection: 'row', gap: space.sm, padding: space.md, borderRadius: radius.md, alignItems: 'flex-start' },
  noticeText: { flex: 1, fontFamily: fonts.medium, fontSize: 13.5, lineHeight: 19 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: space.xl, gap: space.md },
  emptyIcon: {
    width: 76,
    height: 76,
    borderRadius: 38,
    backgroundColor: colors.brand100,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.xs,
  },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 5 },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: space.lg,
    marginBottom: space.md,
  },
  sectionAction: { fontFamily: fonts.semibold, fontSize: 14, color: colors.brand600 },
  listItem: { flexDirection: 'row', alignItems: 'center', gap: space.md, paddingVertical: 14, paddingHorizontal: space.lg },
  listIcon: {
    width: 38,
    height: 38,
    borderRadius: radius.sm,
    backgroundColor: colors.brand100,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
