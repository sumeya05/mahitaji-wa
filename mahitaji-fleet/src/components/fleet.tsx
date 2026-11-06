import Ionicons from '@expo/vector-icons/Ionicons';
import { type QueryKey, useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useLocalSearchParams } from 'expo-router';
import { type ReactElement, type ReactNode, useEffect, useState } from 'react';
import {
  ActivityIndicator, FlatList, Linking, Modal, Pressable, RefreshControl, ScrollView, StyleSheet, Switch, Text, TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { ListQuery } from '@/lib/api';
import { colors, fonts, radius, shadow, space } from '@/lib/theme';
import type { Choice, Page } from '@/lib/types';

import { Button, Chip, EmptyState, ErrorState, type IconName, Loading, T } from './ui';

/** The value after it has stopped changing for `delay` ms (search boxes). */
export function useDebounced<V>(value: V, delay = 300) {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return settled;
}

// ---------------------------------------------------------------------------
// Lists
// ---------------------------------------------------------------------------
export function SearchBar({ value, onChange, placeholder }: { value: string; onChange: (text: string) => void; placeholder: string }) {
  return (
    <View style={styles.search}>
      <Ionicons name="search" size={18} color={colors.muted} />
      <TextInput
        value={value}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={colors.muted}
        autoCapitalize="none"
        autoCorrect={false}
        returnKeyType="search"
        accessibilityLabel={placeholder}
        style={styles.searchInput}
      />
      {!!value && (
        <Pressable onPress={() => onChange('')} hitSlop={8} accessibilityLabel="Clear search">
          <Ionicons name="close-circle" size={18} color={colors.muted} />
        </Pressable>
      )}
    </View>
  );
}

/**
 * A searchable, paged list of one master, with pull to refresh and an Add button for those
 * allowed to add. `filters` (chips under the search box) are passed in already applied to `fetchPage`.
 */
export function MasterList<R extends { id: number }>({
  queryKey, fetchPage, renderItem, searchPlaceholder, filters, empty, onAdd, addLabel,
}: {
  queryKey: QueryKey;
  fetchPage: (query: ListQuery) => Promise<Page<R>>;
  renderItem: (item: R) => ReactElement;
  searchPlaceholder: string;
  filters?: ReactNode;
  empty: { icon: IconName; title: string; message: string };
  onAdd?: () => void;
  addLabel?: string;
}) {
  const [search, setSearch] = useState('');
  const q = useDebounced(search.trim());
  const list = useInfiniteQuery({
    queryKey: [...queryKey, 'list', q],
    queryFn: ({ pageParam }) => fetchPage({ q, page: pageParam }),
    initialPageParam: 1,
    getNextPageParam: (last, pages) => (last.next ? pages.length + 1 : undefined),
  });
  const items = list.data?.pages.flatMap((page) => page.results) ?? [];
  const count = list.data?.pages[0]?.count;

  return (
    <View style={{ flex: 1 }}>
      <FlatList
        data={items}
        keyExtractor={(item) => String(item.id)}
        renderItem={({ item }) => renderItem(item)}
        ItemSeparatorComponent={Separator}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ paddingBottom: onAdd ? 96 : space.xl, flexGrow: 1 }}
        ListHeaderComponent={
          <View style={styles.listHeader}>
            <SearchBar value={search} onChange={setSearch} placeholder={searchPlaceholder} />
            {filters}
            {count !== undefined && <T variant="caption">{count === 1 ? '1 record' : `${count.toLocaleString()} records`}</T>}
          </View>
        }
        ListEmptyComponent={
          list.isPending ? (
            <Loading />
          ) : list.isError ? (
            <ErrorState error={list.error} onRetry={() => list.refetch()} />
          ) : (
            <EmptyState
              icon={q ? 'search' : empty.icon}
              title={q ? 'Nothing matches' : empty.title}
              message={q ? `No results for “${q}”.` : empty.message}
            />
          )
        }
        ListFooterComponent={list.isFetchingNextPage ? <ActivityIndicator style={{ margin: space.lg }} color={colors.brand600} /> : null}
        onEndReached={() => list.hasNextPage && !list.isFetchingNextPage && list.fetchNextPage()}
        onEndReachedThreshold={0.4}
        refreshControl={<RefreshControl refreshing={list.isRefetching && !list.isFetchingNextPage} onRefresh={() => list.refetch()} />}
        style={{ backgroundColor: colors.surface }}
      />
      {onAdd && <Fab label={addLabel ?? 'Add'} onPress={onAdd} />}
    </View>
  );
}

function Separator() {
  return <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: colors.line, marginLeft: 70 }} />;
}

export function Fab({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      style={({ pressed }) => [styles.fab, pressed && { opacity: 0.85 }]}>
      <Ionicons name="add" size={22} color="#fff" />
      <Text style={styles.fabText}>{label}</Text>
    </Pressable>
  );
}

/**
 * The chosen filter chip of a list, as "kind:value" ('' = all). A link can open the list already
 * filtered (/vehicles?missing=driver, /employees?role=turnboy from Home); a newer link wins over an
 * earlier choice.
 */
export function useListFilter() {
  const { missing, role } = useLocalSearchParams<{ missing?: string; role?: string }>();
  const fromLink = missing ? `missing:${missing}` : role ? `role:${role}` : '';
  const [choice, setChoice] = useState({ link: fromLink, value: fromLink });
  const filter = choice.link === fromLink ? choice.value : fromLink;
  const [kind, value] = filter ? filter.split(':') : ['', ''];
  return {
    filter,
    choose: (next: string) => setChoice({ link: fromLink, value: next }),
    /** The value when the chosen chip is of this kind, e.g. of('missing') -> 'driver'. */
    of: (name: string) => (kind === name ? value : undefined),
  };
}

/** Filter chips in one line that scrolls sideways, edge to edge. */
export function FilterRow({ children }: { children: ReactNode }) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} keyboardShouldPersistTaps="handled"
      style={{ marginHorizontal: -space.lg }} contentContainerStyle={styles.filterRow}>
      {children}
    </ScrollView>
  );
}

// ---------------------------------------------------------------------------
// Form inputs beyond plain text
// ---------------------------------------------------------------------------
export interface Option {
  id: number;
  label: string;
  detail?: string;
}

/**
 * Choose a related record (company, route, driver...) from a searchable sheet. `load` fetches
 * the options for a search term; `allowClear` offers "None" for optional links.
 */
export function PickerField({
  label, value, onChange, load, queryKey, error, hint, allowClear, placeholder = 'Choose…', disabled,
}: {
  label: string;
  value: Option | null;
  onChange: (option: Option | null) => void;
  load: (q: string) => Promise<Option[]>;
  queryKey: QueryKey;
  error?: string;
  hint?: string;
  allowClear?: boolean;
  placeholder?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <View style={{ gap: 6 }}>
      <T variant="label">{label}</T>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${label}: ${value?.label ?? 'none chosen'}`}
        disabled={disabled}
        onPress={() => setOpen(true)}
        style={[styles.select, !!error && { borderColor: colors.danger }, disabled && { opacity: 0.6 }]}>
        <View style={{ flex: 1 }}>
          <Text style={[styles.selectText, !value && { color: colors.muted }]} numberOfLines={1}>
            {value?.label ?? placeholder}
          </Text>
          {!!value?.detail && <T variant="caption" numberOfLines={1}>{value.detail}</T>}
        </View>
        <Ionicons name="chevron-down" size={18} color={colors.muted} />
      </Pressable>
      {error ? <T variant="caption" style={{ color: colors.danger }}>{error}</T> : hint ? <T variant="caption">{hint}</T> : null}
      {open && (
        <PickerSheet
          title={label}
          selectedId={value?.id ?? null}
          load={load}
          queryKey={queryKey}
          allowClear={allowClear}
          onClose={() => setOpen(false)}
          onPick={(option) => {
            onChange(option);
            setOpen(false);
          }}
        />
      )}
    </View>
  );
}

function PickerSheet({
  title, selectedId, load, queryKey, allowClear, onClose, onPick,
}: {
  title: string;
  selectedId: number | null;
  load: (q: string) => Promise<Option[]>;
  queryKey: QueryKey;
  allowClear?: boolean;
  onClose: () => void;
  onPick: (option: Option | null) => void;
}) {
  const insets = useSafeAreaInsets();
  const [search, setSearch] = useState('');
  const q = useDebounced(search.trim());
  const options = useQuery({ queryKey: [...queryKey, 'options', q], queryFn: () => load(q) });

  return (
    <Modal visible animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={[styles.sheet, { paddingBottom: insets.bottom }]}>
        <View style={styles.sheetHeader}>
          <T variant="heading" style={{ flex: 1 }}>{title}</T>
          <Button title="Close" kind="ghost" small onPress={onClose} />
        </View>
        <View style={{ paddingHorizontal: space.lg, paddingBottom: space.sm }}>
          <SearchBar value={search} onChange={setSearch} placeholder="Search" />
        </View>
        {options.isPending ? (
          <Loading />
        ) : options.isError ? (
          <ErrorState error={options.error} onRetry={() => options.refetch()} />
        ) : (
          <FlatList
            data={options.data}
            keyExtractor={(option) => String(option.id)}
            keyboardShouldPersistTaps="handled"
            ItemSeparatorComponent={OptionSeparator}
            ListHeaderComponent={
              allowClear ? <OptionRow label="None" detail="Leave this empty" selected={selectedId === null} onPress={() => onPick(null)} /> : null
            }
            ListEmptyComponent={<EmptyState icon="search" title="Nothing found" message={q ? `No results for “${q}”.` : undefined} />}
            renderItem={({ item }) => (
              <OptionRow label={item.label} detail={item.detail} selected={item.id === selectedId} onPress={() => onPick(item)} />
            )}
          />
        )}
      </View>
    </Modal>
  );
}

function OptionSeparator() {
  return <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: colors.line }} />;
}

function OptionRow({ label, detail, selected, onPress }: { label: string; detail?: string; selected: boolean; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected }}
      onPress={onPress}
      style={({ pressed }) => [styles.option, pressed && { backgroundColor: colors.bg }]}>
      <View style={{ flex: 1 }}>
        <T variant="subheading" style={{ fontSize: 15 }}>{label}</T>
        {!!detail && <T variant="caption">{detail}</T>}
      </View>
      {selected && <Ionicons name="checkmark" size={20} color={colors.brand700} />}
    </Pressable>
  );
}

/** One of a few fixed values (role, vehicle type) as chips. */
export function ChoiceField({
  label, choices, value, onChange, error,
}: {
  label: string;
  choices: Choice[];
  value: string;
  onChange: (value: string) => void;
  error?: string;
}) {
  return (
    <View style={{ gap: 8 }}>
      <T variant="label">{label}</T>
      <View style={styles.choices}>
        {choices.map((choice) => (
          <Chip key={choice.value} label={choice.label} active={choice.value === value} onPress={() => onChange(choice.value)} />
        ))}
      </View>
      {!!error && <T variant="caption" style={{ color: colors.danger }}>{error}</T>}
    </View>
  );
}

export function SwitchField({ label, hint, value, onChange }: { label: string; hint?: string; value: boolean; onChange: (on: boolean) => void }) {
  return (
    <View style={styles.switchRow}>
      <View style={{ flex: 1 }}>
        <T variant="subheading" style={{ fontSize: 15 }}>{label}</T>
        {!!hint && <T variant="caption">{hint}</T>}
      </View>
      <Switch
        accessibilityLabel={label}
        value={value}
        onValueChange={onChange}
        trackColor={{ true: colors.brand600, false: colors.line2 }}
        thumbColor="#fff"
      />
    </View>
  );
}

// ---------------------------------------------------------------------------
// Detail pages
// ---------------------------------------------------------------------------
/** The big title block at the top of a record's page. */
export function RecordHeader({ icon, title, subtitle, badges }: { icon: IconName; title: string; subtitle?: string; badges?: ReactNode }) {
  return (
    <View style={styles.recordHeader}>
      <View style={styles.recordIcon}>
        <Ionicons name={icon} size={28} color={colors.brand700} />
      </View>
      <View style={{ flex: 1, gap: 4 }}>
        <T variant="title" style={{ fontSize: 22 }}>{title}</T>
        {!!subtitle && <T style={{ color: colors.muted }}>{subtitle}</T>}
        {badges && <View style={styles.choices}>{badges}</View>}
      </View>
    </View>
  );
}

/** A label / value line on a detail page; `onPress` makes it a link (call, open map, open record). */
export function InfoRow({ icon, label, value, onPress, actionIcon }: {
  icon: IconName;
  label: string;
  value: string;
  onPress?: () => void;
  actionIcon?: IconName;
}) {
  const body = (
    <>
      <Ionicons name={icon} size={19} color={colors.brand600} style={{ marginTop: 2 }} />
      <View style={{ flex: 1 }}>
        <T variant="caption">{label}</T>
        <T style={[{ color: colors.ink }, !value && { color: colors.muted }]}>{value || 'Not set'}</T>
      </View>
      {onPress && <Ionicons name={actionIcon ?? 'chevron-forward'} size={19} color={colors.brand600} />}
    </>
  );
  if (!onPress) return <View style={styles.info}>{body}</View>;
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={`${label}: ${value}`} onPress={onPress}
      style={({ pressed }) => [styles.info, pressed && { opacity: 0.6 }]}>
      {body}
    </Pressable>
  );
}

export function call(phone: string) {
  void Linking.openURL(`tel:${phone.replace(/\s/g, '')}`);
}

export function openMap(latitude: number, longitude: number) {
  void Linking.openURL(`https://www.google.com/maps/search/?api=1&query=${latitude},${longitude}`);
}

const styles = StyleSheet.create({
  search: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    height: 44,
    paddingHorizontal: space.md,
    borderRadius: radius.md,
    backgroundColor: colors.bg2,
  },
  searchInput: { flex: 1, fontFamily: fonts.body, fontSize: 15, color: colors.ink, paddingVertical: 8 },
  listHeader: { padding: space.lg, gap: space.md, backgroundColor: colors.surface },
  filterRow: { flexDirection: 'row', gap: space.sm, paddingHorizontal: space.lg },
  fab: {
    position: 'absolute',
    right: space.lg,
    bottom: space.lg,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    height: 52,
    paddingHorizontal: 20,
    borderRadius: radius.pill,
    backgroundColor: colors.brand800,
    ...shadow,
  },
  fabText: { fontFamily: fonts.semibold, fontSize: 15, color: '#fff' },
  select: {
    minHeight: 50,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.line2,
    backgroundColor: colors.surface,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    paddingHorizontal: space.md,
    paddingVertical: 8,
  },
  selectText: { fontFamily: fonts.body, fontSize: 15.5, color: colors.ink },
  sheet: { flex: 1, backgroundColor: colors.surface },
  sheetHeader: { flexDirection: 'row', alignItems: 'center', padding: space.lg, paddingBottom: space.md },
  option: { flexDirection: 'row', alignItems: 'center', gap: space.md, paddingVertical: 14, paddingHorizontal: space.lg },
  choices: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  switchRow: { flexDirection: 'row', alignItems: 'center', gap: space.md, paddingVertical: space.xs },
  recordHeader: { flexDirection: 'row', gap: space.lg, alignItems: 'center' },
  recordIcon: {
    width: 60,
    height: 60,
    borderRadius: radius.lg,
    backgroundColor: colors.brand100,
    alignItems: 'center',
    justifyContent: 'center',
  },
  info: { flexDirection: 'row', gap: space.md, alignItems: 'flex-start', paddingVertical: 10 },
});
