import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';

import { call, InfoRow, openMap, RecordHeader } from '@/components/fleet';
import { RecordPage, Section, useRecordId } from '@/components/record';
import { Badge } from '@/components/ui';
import { api } from '@/lib/api';
import { coordinates, localPhone } from '@/lib/format';
import { useCan } from '@/state/auth';

export default function CustomerScreen() {
  const id = useRecordId()!;
  const canEdit = useCan('customers', 'change');
  const customer = useQuery({ queryKey: ['customers', 'detail', id], queryFn: () => api.customers.get(id) });

  return (
    <RecordPage
      query={customer}
      title={(c) => c.name}
      onEdit={canEdit ? () => router.push({ pathname: '/customers/edit', params: { id } }) : undefined}>
      {(c) => (
        <>
          <RecordHeader
            icon="storefront"
            title={c.name}
            subtitle={c.customer_code}
            badges={c.has_login ? <Badge label="Shop account" icon="globe-outline" /> : undefined}
          />
          <Section title="Contact">
            <InfoRow icon="person-outline" label="Contact person" value={c.contact_person ?? ''} />
            <InfoRow icon="call-outline" label="Phone" value={localPhone(c.phone_number)}
              onPress={c.phone_number ? () => call(c.phone_number) : undefined} actionIcon="call" />
            {!!c.email && <InfoRow icon="mail-outline" label="Email" value={c.email} />}
          </Section>
          <Section title="Delivery">
            <InfoRow icon="home-outline" label="Address"
              value={c.address ? `${c.address.physical_address}${c.address.city ? `, ${c.address.city}` : ''}` : ''} />
            <InfoRow icon="location-outline" label="Area" value={c.area ? `${c.area.name} (${c.area.code})` : ''}
              onPress={c.area ? () => router.push({ pathname: '/areas/[id]', params: { id: c.area!.id } }) : undefined} />
            <InfoRow icon="git-branch-outline" label="Route" value={c.route ? `${c.route.name} (${c.route.code})` : ''}
              onPress={c.route ? () => router.push({ pathname: '/routes/[id]', params: { id: c.route!.id } }) : undefined} />
            <InfoRow
              icon="navigate-outline"
              label="GPS location"
              value={c.latitude !== null && c.longitude !== null ? coordinates(c.latitude, c.longitude) : ''}
              onPress={c.latitude !== null && c.longitude !== null ? () => openMap(c.latitude!, c.longitude!) : undefined}
              actionIcon="map-outline"
            />
          </Section>
        </>
      )}
    </RecordPage>
  );
}
