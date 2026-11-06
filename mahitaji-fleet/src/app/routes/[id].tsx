import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';

import { InfoRow, RecordHeader } from '@/components/fleet';
import { RecordPage, Section, useRecordId } from '@/components/record';
import { Badge, T } from '@/components/ui';
import { api } from '@/lib/api';
import type { Route } from '@/lib/types';
import { useCan } from '@/state/auth';

export default function RouteScreen() {
  const id = useRecordId()!;
  const canEdit = useCan('routes', 'change');
  const route = useQuery({ queryKey: ['routes', 'detail', id], queryFn: () => api.routes.get(id) });

  return (
    <RecordPage
      query={route}
      title={(r) => r.name}
      onEdit={canEdit ? () => router.push({ pathname: '/routes/edit', params: { id } }) : undefined}>
      {(r) => (
        <>
          <RecordHeader
            icon="git-branch"
            title={r.name}
            subtitle={r.code}
            badges={
              <>
                <Badge label={r.company.name} icon="business-outline" />
                {!r.is_active && <Badge label="Inactive" tone="muted" />}
              </>
            }
          />
          <Section title="Route">
            <InfoRow icon="pricetag-outline" label="Route code" value={r.code} />
            <InfoRow icon="business-outline" label="Company" value={`${r.company.name} (${r.company.code})`} />
          </Section>
          <RouteAreas route={r} />
        </>
      )}
    </RecordPage>
  );
}

function RouteAreas({ route }: { route: Route }) {
  const canSee = useCan('areas');
  const areas = useQuery({
    queryKey: ['areas', 'on-route', route.code],
    queryFn: () => api.areas.list({ route: route.code, page_size: 200 }),
    enabled: canSee,
  });
  if (!canSee) return null;
  return (
    <Section title={areas.data ? `Areas (${areas.data.count})` : 'Areas'}>
      {areas.isPending ? (
        <T variant="caption">Loading…</T>
      ) : areas.isError ? (
        <T variant="caption">{areas.error.message}</T>
      ) : areas.data.count === 0 ? (
        <T variant="caption" style={{ paddingVertical: 8 }}>No areas on this route yet.</T>
      ) : (
        areas.data.results.map((area) => (
          <InfoRow key={area.id} icon="location-outline" label={area.code} value={[area.name, area.town].filter(Boolean).join(' · ')}
            onPress={() => router.push({ pathname: '/areas/[id]', params: { id: area.id } })} />
        ))
      )}
    </Section>
  );
}
