import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';

import { call, InfoRow, RecordHeader } from '@/components/fleet';
import { RecordPage, Section, useRecordId } from '@/components/record';
import { Badge } from '@/components/ui';
import { api } from '@/lib/api';
import { localPhone } from '@/lib/format';
import { useCan } from '@/state/auth';

export default function EmployeeScreen() {
  const id = useRecordId()!;
  const canEdit = useCan('employees', 'change');
  const employee = useQuery({ queryKey: ['employees', 'detail', id], queryFn: () => api.employees.get(id) });

  return (
    <RecordPage
      query={employee}
      title={(e) => e.full_name}
      onEdit={canEdit ? () => router.push({ pathname: '/employees/edit', params: { id } }) : undefined}>
      {(e) => (
        <>
          <RecordHeader
            icon={e.role === 'driver' ? 'person' : e.role === 'turnboy' ? 'people' : 'briefcase'}
            title={e.full_name}
            subtitle={`${e.role_display} · ${e.employee_code}`}
            badges={
              <>
                <Badge label={e.role_display} tone={e.role === 'other' ? 'muted' : 'info'} />
                {!e.is_active && <Badge label="Inactive" tone="muted" />}
              </>
            }
          />
          <Section title="Employee">
            <InfoRow icon="id-card-outline" label="Employee code" value={e.employee_code} />
            <InfoRow icon="ribbon-outline" label="Role" value={e.role_display} />
            <InfoRow icon="business-outline" label="Company" value={`${e.company.name} (${e.company.code})`} />
            <InfoRow icon="call-outline" label="Phone" value={localPhone(e.phone_number)}
              onPress={e.phone_number ? () => call(e.phone_number) : undefined} actionIcon="call" />
          </Section>
          {e.role !== 'other' && (
            <Section title="Vehicle" note="Drivers and turnboys are put on a vehicle from the vehicle's page.">
              {e.vehicle ? (
                <InfoRow icon="bus-outline" label={`${e.role_display} of`} value={e.vehicle.registration_number}
                  onPress={() => router.push({ pathname: '/vehicles/[id]', params: { id: e.vehicle!.id } })} />
              ) : (
                <InfoRow icon="bus-outline" label="Vehicle" value="Not on a vehicle" />
              )}
            </Section>
          )}
        </>
      )}
    </RecordPage>
  );
}
