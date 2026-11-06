import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';

import { InfoRow, RecordHeader } from '@/components/fleet';
import { RecordPage, Section, useRecordId } from '@/components/record';
import { Badge, T } from '@/components/ui';
import { api } from '@/lib/api';
import { localPhone } from '@/lib/format';
import type { Area } from '@/lib/types';
import { useCan } from '@/state/auth';

const SHOWN = 50;

export default function AreaScreen() {
  const id = useRecordId()!;
  const canEdit = useCan('areas', 'change');
  const area = useQuery({ queryKey: ['areas', 'detail', id], queryFn: () => api.areas.get(id) });

  return (
    <RecordPage
      query={area}
      title={(a) => a.name}
      onEdit={canEdit ? () => router.push({ pathname: '/areas/edit', params: { id } }) : undefined}>
      {(a) => (
        <>
          <RecordHeader
            icon="location"
            title={a.name}
            subtitle={`${a.code} · ${a.route.name} route`}
            badges={
              <>
                <Badge label={a.company.name} icon="business-outline" />
                {!a.is_active && <Badge label="Inactive" tone="muted" />}
              </>
            }
          />
          <Section title="Area">
            <InfoRow icon="git-branch-outline" label="Route" value={`${a.route.name} (${a.route.code})`}
              onPress={() => router.push({ pathname: '/routes/[id]', params: { id: a.route.id } })} />
            <InfoRow icon="business-outline" label="Company" value={`${a.company.name} (${a.company.code})`} />
            <InfoRow icon="map-outline" label="County" value={a.county} />
            <InfoRow icon="business-outline" label="Town" value={a.town} />
            <InfoRow icon="information-circle-outline" label="Landmarks and boundaries" value={a.description} />
          </Section>
          <AreaCustomers area={a} />
        </>
      )}
    </RecordPage>
  );
}

function AreaCustomers({ area }: { area: Area }) {
  const canSee = useCan('customers');
  const customers = useQuery({
    queryKey: ['customers', 'in-area', area.code],
    queryFn: () => api.customers.list({ area: area.code, page_size: SHOWN }),
    enabled: canSee,
  });
  if (!canSee) return null;
  const count = customers.data?.count ?? 0;
  return (
    <Section title={customers.data ? `Customers (${count})` : 'Customers'}
      note={count > SHOWN ? `Showing the first ${SHOWN}. Search the Customers tab for the rest.` : undefined}>
      {customers.isPending ? (
        <T variant="caption">Loading…</T>
      ) : customers.isError ? (
        <T variant="caption">{customers.error.message}</T>
      ) : count === 0 ? (
        <T variant="caption" style={{ paddingVertical: 8 }}>No customers in this area yet.</T>
      ) : (
        customers.data.results.map((customer) => (
          <InfoRow key={customer.id} icon="storefront-outline" label={customer.customer_code}
            value={[customer.name, localPhone(customer.phone_number)].filter(Boolean).join(' · ')}
            onPress={() => router.push({ pathname: '/customers/[id]', params: { id: customer.id } })} />
        ))
      )}
    </Section>
  );
}
