import Constants from 'expo-constants';
import { ScrollView, View } from 'react-native';

import { InfoRow, RecordHeader } from '@/components/fleet';
import { Section } from '@/components/record';
import { Badge, Button, T } from '@/components/ui';
import { BASE_URL } from '@/lib/api';
import { space } from '@/lib/theme';
import type { Resource } from '@/lib/types';
import { useAuth } from '@/state/auth';

const MASTERS: { resource: Resource; label: string }[] = [
  { resource: 'vehicles', label: 'Vehicles' },
  { resource: 'employees', label: 'Employees' },
  { resource: 'customers', label: 'Customers' },
  { resource: 'areas', label: 'Areas' },
  { resource: 'routes', label: 'Routes' },
  { resource: 'companies', label: 'Companies' },
];

export default function AccountScreen() {
  const { user, signOut } = useAuth();
  if (!user) return null;

  return (
    <ScrollView contentContainerStyle={{ padding: space.lg, gap: space.lg, paddingBottom: space.xxl }}>
      <RecordHeader icon="person" title={user.name} subtitle={user.email || user.username} />
      <Section title="What you can do" note="Access is set by the office in the Mahitaji admin.">
        {MASTERS.map(({ resource, label }) => {
          const can = user.permissions[resource];
          return (
            <View key={resource} style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 8, gap: space.sm }}>
              <T style={{ flex: 1 }}>{label}</T>
              {can.view ? <Badge label="View" tone="info" /> : <Badge label="No access" tone="muted" />}
              {can.add && <Badge label="Add" tone="success" />}
              {can.change && <Badge label="Edit" tone="success" />}
            </View>
          );
        })}
      </Section>
      <Section title="App">
        <InfoRow icon="server-outline" label="Server" value={BASE_URL} />
        <InfoRow icon="information-circle-outline" label="Version" value={Constants.expoConfig?.version ?? ''} />
      </Section>
      <Button title="Sign out" kind="danger" icon="log-out-outline" onPress={() => void signOut()} />
    </ScrollView>
  );
}
