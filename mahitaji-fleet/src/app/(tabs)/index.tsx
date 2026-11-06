import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { type Href, router, useFocusEffect } from 'expo-router';
import { setStatusBarStyle } from 'expo-status-bar';
import { type ReactNode, useCallback } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Card, type IconName, T } from '@/components/ui';
import { api, type ListQuery } from '@/lib/api';
import type { Me, Page } from '@/lib/types';
import { colors, fonts, radius, shadow, space } from '@/lib/theme';
import { useAuth } from '@/state/auth';

type Counter = (query: ListQuery) => Promise<Page<unknown>>;

/** How many records a list holds, from a one-row page. */
function useCount(key: string, count: Counter, query: ListQuery, enabled: boolean) {
  const result = useQuery({
    queryKey: [key, 'count', query],
    queryFn: () => count({ ...query, page_size: 1 }),
    enabled,
  });
  return result.data?.count;
}

export default function HomeScreen() {
  const { user } = useAuth();
  const insets = useSafeAreaInsets();

  // White status bar text over the navy header, dark again on the other screens.
  useFocusEffect(
    useCallback(() => {
      setStatusBarStyle('light');
      return () => setStatusBarStyle('dark');
    }, []),
  );

  if (!user) return null;
  const can = user.permissions;

  return (
    <ScrollView style={{ flex: 1, backgroundColor: colors.bg }} contentContainerStyle={{ paddingBottom: space.xxl }}>
      <View style={[styles.hero, { paddingTop: insets.top + space.lg }, !can.vehicles.view && { paddingBottom: space.xl }]}>
        <View style={styles.heroTop}>
          <View style={styles.brand}>
            <View style={styles.logo}>
              <Image source={require('../../../assets/logo.png')} style={{ width: 22, height: 22 }} />
            </View>
            <Text style={styles.brandText}>Mahitaji Fleet</Text>
          </View>
          <Pressable accessibilityRole="button" accessibilityLabel="Account" onPress={() => router.push('/account')}
            style={({ pressed }) => [styles.avatar, pressed && { opacity: 0.8 }]}>
            <Text style={styles.avatarText}>{initials(user.name)}</Text>
          </Pressable>
        </View>
        <Text style={styles.greeting}>{greeting()},</Text>
        <Text style={styles.name}>{user.name.split(' ')[0]}</Text>
        <Text style={styles.date}>{today()}</Text>
      </View>

      <View style={styles.body}>
        {can.vehicles.view && <FleetCard />}
        <QuickAdd user={user} />
        <NeedsAttention user={user} />
        <Masters user={user} />
      </View>
    </ScrollView>
  );
}

// ---------------------------------------------------------------------------
// Vehicle crews
// ---------------------------------------------------------------------------
function FleetCard() {
  const total = useCount('vehicles', api.vehicles.list, {}, true);
  const noDriver = useCount('vehicles', api.vehicles.list, { missing: 'driver' }, true);
  const noTurnboy = useCount('vehicles', api.vehicles.list, { missing: 'turnboy' }, true);
  const ready = total !== undefined && noDriver !== undefined && noTurnboy !== undefined;

  return (
    <Pressable accessibilityRole="button" accessibilityLabel="Vehicles" onPress={() => router.navigate('/vehicles')}
      style={({ pressed }) => [styles.fleetCard, pressed && { opacity: 0.9 }]}>
      <View style={styles.fleetHeader}>
        <View style={[styles.iconCircle, { backgroundColor: colors.brand100 }]}>
          <Ionicons name="bus" size={20} color={colors.brand700} />
        </View>
        <View style={{ flex: 1 }}>
          <T variant="caption">Active vehicles</T>
          <Text style={styles.fleetCount}>{ready ? total.toLocaleString() : '…'}</Text>
        </View>
        <View style={styles.viewAll}>
          <Text style={styles.viewAllText}>View all</Text>
          <Ionicons name="chevron-forward" size={16} color={colors.brand600} />
        </View>
      </View>
      <Coverage label="With a driver" have={ready ? total - noDriver : 0} of={ready ? total : 0} />
      <Coverage label="With a turnboy" have={ready ? total - noTurnboy : 0} of={ready ? total : 0} />
    </Pressable>
  );
}

function Coverage({ label, have, of }: { label: string; have: number; of: number }) {
  const share = of ? have / of : 0;
  const complete = of > 0 && have === of;
  return (
    <View style={{ gap: 6 }}>
      <View style={styles.coverageRow}>
        <T variant="label" style={{ flex: 1 }}>{label}</T>
        <Text style={styles.coverageValue}>{of ? `${have} of ${of}` : '–'}</Text>
      </View>
      <View style={styles.track}>
        <View style={[styles.fill, { width: `${Math.round(share * 100)}%`, backgroundColor: complete ? colors.success : colors.amber500 }]} />
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Quick add
// ---------------------------------------------------------------------------
function QuickAdd({ user }: { user: Me }) {
  const can = user.permissions;
  const actions: { label: string; icon: IconName; href: Href; allowed: boolean }[] = [
    { label: 'Customer', icon: 'storefront-outline', href: '/customers/edit', allowed: can.customers.add },
    { label: 'Vehicle', icon: 'bus-outline', href: '/vehicles/edit', allowed: can.vehicles.add },
    { label: 'Employee', icon: 'person-add-outline', href: '/employees/edit', allowed: can.employees.add },
    { label: 'Area', icon: 'location-outline', href: '/areas/edit', allowed: can.areas.add },
  ];
  const allowed = actions.filter((action) => action.allowed);
  if (!allowed.length) return null;
  return (
    <Block title="Add new">
      <View style={styles.quickRow}>
        {allowed.map((action) => (
          <Pressable key={action.label} accessibilityRole="button" accessibilityLabel={`Add ${action.label.toLowerCase()}`}
            onPress={() => router.push(action.href)} style={({ pressed }) => [styles.quick, pressed && { opacity: 0.7 }]}>
            <View style={styles.quickIcon}>
              <Ionicons name={action.icon} size={22} color={colors.brand800} />
              <View style={styles.quickPlus}>
                <Ionicons name="add" size={12} color={colors.brand950} />
              </View>
            </View>
            <Text style={styles.quickLabel} numberOfLines={1}>{action.label}</Text>
          </Pressable>
        ))}
      </View>
    </Block>
  );
}

// ---------------------------------------------------------------------------
// Needs attention: what still has to be filled in
// ---------------------------------------------------------------------------
function NeedsAttention({ user }: { user: Me }) {
  const can = user.permissions;
  const items = [
    {
      key: 'no-driver', icon: 'person-outline' as IconName, enabled: can.vehicles.view,
      count: useCount('vehicles', api.vehicles.list, { missing: 'driver' }, can.vehicles.view),
      text: (n: number) => `${plural(n, 'vehicle has', 'vehicles have')} no driver`,
      href: { pathname: '/vehicles', params: { missing: 'driver' } } as Href,
    },
    {
      key: 'no-turnboy', icon: 'people-outline' as IconName, enabled: can.vehicles.view,
      count: useCount('vehicles', api.vehicles.list, { missing: 'turnboy' }, can.vehicles.view),
      text: (n: number) => `${plural(n, 'vehicle has', 'vehicles have')} no turnboy`,
      href: { pathname: '/vehicles', params: { missing: 'turnboy' } } as Href,
    },
    {
      key: 'no-area', icon: 'map-outline' as IconName, enabled: can.customers.view,
      count: useCount('customers', api.customers.list, { missing: 'area' }, can.customers.view),
      text: (n: number) => `${plural(n, 'customer has', 'customers have')} no delivery area`,
      href: { pathname: '/customers', params: { missing: 'area' } } as Href,
    },
    {
      key: 'no-location', icon: 'navigate-outline' as IconName, enabled: can.customers.view,
      count: useCount('customers', api.customers.list, { missing: 'location' }, can.customers.view),
      text: (n: number) => `${plural(n, 'customer has', 'customers have')} no GPS location`,
      href: { pathname: '/customers', params: { missing: 'location' } } as Href,
    },
  ].filter((item) => item.enabled);

  if (!items.length) return null;
  const loaded = items.every((item) => item.count !== undefined);
  const open = items.filter((item) => item.count);

  return (
    <Block title="Needs attention">
      <Card style={{ padding: 0, overflow: 'hidden' }}>
        {!loaded ? (
          <T variant="caption" style={{ padding: space.lg }}>Checking…</T>
        ) : open.length === 0 ? (
          <View style={styles.allSet}>
            <View style={[styles.iconCircle, { backgroundColor: colors.success100 }]}>
              <Ionicons name="checkmark" size={20} color={colors.success} />
            </View>
            <View style={{ flex: 1 }}>
              <T variant="subheading" style={{ fontSize: 15 }}>All set</T>
              <T variant="caption">Every vehicle has its crew and every customer an area and location.</T>
            </View>
          </View>
        ) : (
          open.map((item, index) => (
            <Pressable key={item.key} accessibilityRole="button" onPress={() => router.navigate(item.href)}
              style={({ pressed }) => [styles.attention, index > 0 && styles.attentionDivider, pressed && { backgroundColor: colors.bg }]}>
              <View style={[styles.iconCircle, { backgroundColor: colors.amber100 }]}>
                <Ionicons name={item.icon} size={18} color={colors.amber600} />
              </View>
              <T style={{ flex: 1, color: colors.ink }}>{item.text(item.count!)}</T>
              <Ionicons name="chevron-forward" size={18} color={colors.muted} />
            </Pressable>
          ))
        )}
      </Card>
    </Block>
  );
}

// ---------------------------------------------------------------------------
// Masters
// ---------------------------------------------------------------------------
function Masters({ user }: { user: Me }) {
  const can = user.permissions;
  const tiles = [
    { key: 'vehicles', label: 'Vehicles', icon: 'bus-outline' as IconName, tint: colors.brand100, ink: colors.brand700,
      enabled: can.vehicles.view, count: useCount('vehicles', api.vehicles.list, {}, can.vehicles.view), href: '/vehicles' as Href },
    { key: 'drivers', label: 'Drivers', icon: 'person-outline' as IconName, tint: colors.info100, ink: colors.brand700,
      enabled: can.employees.view, count: useCount('employees', api.employees.list, { role: 'driver' }, can.employees.view),
      href: { pathname: '/employees', params: { role: 'driver' } } as Href },
    { key: 'turnboys', label: 'Turnboys', icon: 'people-outline' as IconName, tint: colors.info100, ink: colors.brand700,
      enabled: can.employees.view, count: useCount('employees', api.employees.list, { role: 'turnboy' }, can.employees.view),
      href: { pathname: '/employees', params: { role: 'turnboy' } } as Href },
    { key: 'customers', label: 'Customers', icon: 'storefront-outline' as IconName, tint: colors.amber100, ink: colors.amber600,
      enabled: can.customers.view, count: useCount('customers', api.customers.list, {}, can.customers.view), href: '/customers' as Href },
    { key: 'areas', label: 'Areas', icon: 'location-outline' as IconName, tint: colors.success100, ink: colors.success,
      enabled: can.areas.view, count: useCount('areas', api.areas.list, {}, can.areas.view), href: '/areas' as Href },
    { key: 'routes', label: 'Routes', icon: 'git-branch-outline' as IconName, tint: colors.success100, ink: colors.success,
      enabled: can.routes.view, count: useCount('routes', api.routes.list, {}, can.routes.view), href: '/areas' as Href },
  ].filter((tile) => tile.enabled);
  if (!tiles.length) return null;

  return (
    <Block title="Masters">
      <View style={styles.grid}>
        {tiles.map((tile) => (
          <Pressable key={tile.key} accessibilityRole="button" accessibilityLabel={`${tile.label}: ${tile.count ?? ''}`}
            onPress={() => router.navigate(tile.href)} style={({ pressed }) => [styles.tile, pressed && { opacity: 0.8 }]}>
            <View style={[styles.tileIcon, { backgroundColor: tile.tint }]}>
              <Ionicons name={tile.icon} size={17} color={tile.ink} />
            </View>
            <Text style={styles.tileCount}>{tile.count === undefined ? '…' : tile.count.toLocaleString()}</Text>
            <Text style={styles.tileLabel} numberOfLines={1}>{tile.label}</Text>
          </Pressable>
        ))}
      </View>
    </Block>
  );
}

// ---------------------------------------------------------------------------
function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <View style={{ gap: space.md }}>
      <T variant="heading" style={{ fontSize: 17 }}>{title}</T>
      {children}
    </View>
  );
}

function greeting() {
  const hour = new Date().getHours();
  return hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
}

function today() {
  return new Date().toLocaleDateString('en-KE', { weekday: 'long', day: 'numeric', month: 'long' });
}

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]!.toUpperCase()).join('') || '?';
}

function plural(n: number, one: string, many: string) {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

const styles = StyleSheet.create({
  hero: {
    backgroundColor: colors.brand900,
    paddingHorizontal: space.xl,
    paddingBottom: 76,
    borderBottomLeftRadius: 28,
    borderBottomRightRadius: 28,
  },
  heroTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: space.xl },
  brand: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  logo: { width: 34, height: 34, borderRadius: 10, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  brandText: { fontFamily: fonts.semibold, fontSize: 15, color: '#fff', letterSpacing: 0.2 },
  avatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.amber500,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: { fontFamily: fonts.display, fontSize: 15, color: colors.brand950 },
  greeting: { fontFamily: fonts.medium, fontSize: 16, color: colors.brand200 },
  name: { fontFamily: fonts.displayHeavy, fontSize: 30, color: '#fff', letterSpacing: -0.4, marginTop: 2 },
  date: { fontFamily: fonts.body, fontSize: 13.5, color: colors.brand400, marginTop: space.xs },

  body: { paddingHorizontal: space.lg, gap: space.xl },
  fleetCard: {
    marginTop: -56,
    backgroundColor: colors.surface,
    borderRadius: radius.xl,
    padding: space.lg,
    gap: space.lg,
    boxShadow: '0 10px 30px rgba(10, 25, 49, 0.14)',
  },
  fleetHeader: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  fleetCount: { fontFamily: fonts.displayHeavy, fontSize: 26, color: colors.ink, lineHeight: 30 },
  viewAll: { flexDirection: 'row', alignItems: 'center', gap: 2 },
  viewAllText: { fontFamily: fonts.semibold, fontSize: 13.5, color: colors.brand600 },
  iconCircle: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  coverageRow: { flexDirection: 'row', alignItems: 'center' },
  coverageValue: { fontFamily: fonts.semibold, fontSize: 13.5, color: colors.ink },
  track: { height: 8, borderRadius: 4, backgroundColor: colors.bg2, overflow: 'hidden' },
  fill: { height: '100%', borderRadius: 4 },

  quickRow: { flexDirection: 'row', gap: space.md },
  quick: { flex: 1, alignItems: 'center', gap: space.sm },
  quickIcon: {
    width: 58,
    height: 58,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
    alignItems: 'center',
    justifyContent: 'center',
    ...shadow,
  },
  quickPlus: {
    position: 'absolute',
    right: -4,
    bottom: -4,
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: colors.amber500,
    borderWidth: 2,
    borderColor: colors.bg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  quickLabel: { fontFamily: fonts.medium, fontSize: 12.5, color: colors.text2 },

  attention: { flexDirection: 'row', alignItems: 'center', gap: space.md, paddingVertical: 12, paddingHorizontal: space.lg },
  attentionDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.line },
  allSet: { flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.lg },

  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  tile: {
    width: '31.5%',
    flexGrow: 1,
    padding: space.md,
    gap: 2,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
  },
  tileIcon: { width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center', marginBottom: space.xs },
  tileCount: { fontFamily: fonts.displayHeavy, fontSize: 22, color: colors.ink },
  tileLabel: { fontFamily: fonts.medium, fontSize: 12.5, color: colors.muted },
});
