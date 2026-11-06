import { Inter_400Regular, Inter_500Medium, Inter_600SemiBold } from '@expo-google-fonts/inter';
import { PlusJakartaSans_700Bold, PlusJakartaSans_800ExtraBold } from '@expo-google-fonts/plus-jakarta-sans';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useFonts } from 'expo-font';
import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';

import { ApiError } from '@/lib/api';
import { colors, fonts } from '@/lib/theme';
import { AuthProvider, useAuth } from '@/state/auth';

SplashScreen.preventAutoHideAsync().catch(() => undefined);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60 * 1000,
      // Retry dropped connections, but not answers the server gave on purpose (404, 401, 403...).
      retry: (failures, error) => failures < 2 && (!(error instanceof ApiError) || error.status === 0 || error.status >= 500),
    },
  },
});

export default function RootLayout() {
  const [fontsLoaded] = useFonts({
    Inter_400Regular,
    Inter_500Medium,
    Inter_600SemiBold,
    PlusJakartaSans_700Bold,
    PlusJakartaSans_800ExtraBold,
  });

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <StatusBar style="dark" />
        {fontsLoaded && <Navigator />}
      </AuthProvider>
    </QueryClientProvider>
  );
}

function Navigator() {
  const { ready, token } = useAuth();

  useEffect(() => {
    if (ready) SplashScreen.hideAsync().catch(() => undefined);
  }, [ready]);

  if (!ready) return null;
  // Everything is for signed-in staff: without a token only the sign-in screen exists.
  return (
    <Stack
      screenOptions={{
        headerTintColor: colors.brand800,
        headerTitleStyle: { fontFamily: fonts.display, color: colors.ink },
        headerStyle: { backgroundColor: colors.surface },
        headerShadowVisible: false,
        headerBackButtonDisplayMode: 'minimal',
        contentStyle: { backgroundColor: colors.bg },
      }}>
      <Stack.Protected guard={!token}>
        <Stack.Screen name="sign-in" options={{ headerShown: false }} />
      </Stack.Protected>
      <Stack.Protected guard={!!token}>
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="vehicles/[id]" options={{ title: 'Vehicle' }} />
        <Stack.Screen name="vehicles/edit" options={{ title: 'Vehicle', presentation: 'modal' }} />
        <Stack.Screen name="employees/[id]" options={{ title: 'Employee' }} />
        <Stack.Screen name="employees/edit" options={{ title: 'Employee', presentation: 'modal' }} />
        <Stack.Screen name="customers/[id]" options={{ title: 'Customer' }} />
        <Stack.Screen name="customers/edit" options={{ title: 'Customer', presentation: 'modal' }} />
        <Stack.Screen name="areas/[id]" options={{ title: 'Area' }} />
        <Stack.Screen name="areas/edit" options={{ title: 'Area', presentation: 'modal' }} />
        <Stack.Screen name="routes/[id]" options={{ title: 'Route' }} />
        <Stack.Screen name="routes/edit" options={{ title: 'Route', presentation: 'modal' }} />
        <Stack.Screen name="account" options={{ title: 'Account' }} />
      </Stack.Protected>
    </Stack>
  );
}
