import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery } from '@tanstack/react-query';
import { Tabs } from 'expo-router';
import { type ColorValue, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Button, ErrorState, type IconName, Loading } from '@/components/ui';
import { api } from '@/lib/api';
import { colors, fonts } from '@/lib/theme';
import { useAuth } from '@/state/auth';

function icon(name: IconName, active: IconName) {
  return function TabIcon({ color, focused }: { color: ColorValue; focused: boolean }) {
    return <Ionicons name={focused ? active : name} size={24} color={color as string} />;
  };
}

export default function TabsLayout() {
  const { user, token, signOut } = useAuth();
  const insets = useSafeAreaInsets();
  // The same query the auth state reads; used here for its loading / error state.
  const me = useQuery({ queryKey: ['me', token], queryFn: api.me, enabled: !!token });

  if (!user) {
    if (me.isError) {
      return (
        <View style={{ flex: 1, backgroundColor: colors.bg, paddingBottom: 32 }}>
          <ErrorState error={me.error} onRetry={() => me.refetch()} />
          <Button title="Sign out" kind="ghost" onPress={() => void signOut()} />
        </View>
      );
    }
    return <Loading label="Signing in…" />;
  }

  const can = user.permissions;
  // A tab is shown only to people allowed to see that master (permissions are set in the admin).
  const shown = (allowed: boolean) => (allowed ? {} : { href: null });

  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: colors.brand800,
        tabBarInactiveTintColor: colors.muted,
        tabBarLabelStyle: { fontFamily: fonts.medium, fontSize: 11.5, lineHeight: 14 },
        // Each tab takes 5 px padding top and bottom and a 28 px icon box; the default 49 px bar
        // leaves too little for the label at this size, so the bar is made taller instead.
        tabBarStyle: {
          borderTopColor: colors.line,
          backgroundColor: colors.surface,
          height: 60 + insets.bottom,
          paddingTop: 2,
          paddingBottom: insets.bottom,
        },
        headerTitleStyle: { fontFamily: fonts.display, color: colors.ink },
        headerShadowVisible: false,
        sceneStyle: { backgroundColor: colors.bg },
      }}>
      <Tabs.Screen name="index" options={{ title: 'Home', headerShown: false, tabBarIcon: icon('home-outline', 'home') }} />
      <Tabs.Screen
        name="vehicles"
        options={{ title: 'Vehicles', tabBarIcon: icon('bus-outline', 'bus'), ...shown(can.vehicles.view) }}
      />
      <Tabs.Screen
        name="employees"
        options={{ title: 'Crew', headerTitle: 'Employees', tabBarIcon: icon('people-outline', 'people'), ...shown(can.employees.view) }}
      />
      <Tabs.Screen
        name="customers"
        options={{ title: 'Customers', tabBarIcon: icon('storefront-outline', 'storefront'), ...shown(can.customers.view) }}
      />
      <Tabs.Screen
        name="areas"
        options={{
          title: 'Areas',
          headerTitle: 'Areas & routes',
          tabBarIcon: icon('map-outline', 'map'),
          ...shown(can.areas.view || can.routes.view),
        }}
      />
    </Tabs>
  );
}
