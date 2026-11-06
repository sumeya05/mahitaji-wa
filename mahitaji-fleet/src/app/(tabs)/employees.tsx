import { router } from 'expo-router';

import { FilterRow, MasterList, useListFilter } from '@/components/fleet';
import { Chip, ListItem } from '@/components/ui';
import { api } from '@/lib/api';
import type { Employee } from '@/lib/types';
import { useAuth, useCan } from '@/state/auth';

export default function EmployeesScreen() {
  const roles = useAuth().user?.choices.roles ?? [];
  const canAdd = useCan('employees', 'add');
  const { filter, choose, of } = useListFilter();
  const role = of('role');

  return (
    <MasterList<Employee>
      queryKey={['employees', filter]}
      fetchPage={(query) => api.employees.list({ ...query, role })}
      searchPlaceholder="Name, employee code or phone"
      filters={
        <FilterRow>
          <Chip label="All" active={!role} onPress={() => choose('')} />
          {roles.map((choice) => (
            <Chip key={choice.value} label={choice.label} active={role === choice.value} onPress={() => choose(`role:${choice.value}`)} />
          ))}
        </FilterRow>
      }
      empty={{ icon: 'people-outline', title: 'No employees yet', message: 'Drivers, turnboys and other staff appear here.' }}
      onAdd={canAdd ? () => router.push('/employees/edit') : undefined}
      addLabel="Add employee"
      renderItem={(employee) => (
        <ListItem
          icon={employee.role === 'driver' ? 'person-outline' : employee.role === 'turnboy' ? 'people-outline' : 'briefcase-outline'}
          title={employee.full_name}
          subtitle={[
            `${employee.role_display} · ${employee.employee_code}`,
            employee.role === 'other' ? employee.company.name : employee.vehicle ? `On ${employee.vehicle.registration_number}` : 'Not on a vehicle',
          ].join('\n')}
          onPress={() => router.push({ pathname: '/employees/[id]', params: { id: employee.id } })}
        />
      )}
    />
  );
}
