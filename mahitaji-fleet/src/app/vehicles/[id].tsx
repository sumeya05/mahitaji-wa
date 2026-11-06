import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';

import { call, InfoRow, RecordHeader } from '@/components/fleet';
import { RecordPage, Section, useRecordId } from '@/components/record';
import { Badge } from '@/components/ui';
import { api } from '@/lib/api';
import { capacity, localPhone } from '@/lib/format';
import type { CrewMember } from '@/lib/types';
import { useCan } from '@/state/auth';

export default function VehicleScreen() {
  const id = useRecordId()!;
  const canEdit = useCan('vehicles', 'change');
  const vehicle = useQuery({ queryKey: ['vehicles', 'detail', id], queryFn: () => api.vehicles.get(id) });

  return (
    <RecordPage
      query={vehicle}
      title={(v) => v.registration_number}
      onEdit={canEdit ? () => router.push({ pathname: '/vehicles/edit', params: { id } }) : undefined}>
      {(v) => (
        <>
          <RecordHeader
            icon="bus"
            title={v.registration_number}
            subtitle={`${v.vehicle_type_display} · ${capacity(v.capacity_kg)}`}
            badges={
              <>
                <Badge label={v.company.name} icon="business-outline" />
                {!v.is_active && <Badge label="Inactive" tone="muted" />}
              </>
            }
          />
          <Section title="Vehicle">
            <InfoRow icon="car-outline" label="Vehicle number" value={v.registration_number} />
            <InfoRow icon="pricetag-outline" label="Type" value={v.vehicle_type_display} />
            <InfoRow icon="barbell-outline" label="Capacity" value={capacity(v.capacity_kg)} />
            <InfoRow icon="business-outline" label="Company" value={`${v.company.name} (${v.company.code})`} />
          </Section>
          <Section title="Crew" note="Each driver and turnboy is on one vehicle at a time.">
            <CrewRows role="Driver" member={v.driver} />
            <CrewRows role="Turnboy" member={v.turnboy} />
          </Section>
        </>
      )}
    </RecordPage>
  );
}

function CrewRows({ role, member }: { role: string; member: CrewMember | null }) {
  if (!member) return <InfoRow icon="person-outline" label={role} value="" />;
  return (
    <>
      <InfoRow
        icon="person-outline"
        label={role}
        value={`${member.full_name} (${member.employee_code})`}
        onPress={() => router.push({ pathname: '/employees/[id]', params: { id: member.id } })}
      />
      {!!member.phone_number && (
        <InfoRow icon="call-outline" label={`Call the ${role.toLowerCase()}`} value={localPhone(member.phone_number)}
          onPress={() => call(member.phone_number)} actionIcon="call" />
      )}
    </>
  );
}
