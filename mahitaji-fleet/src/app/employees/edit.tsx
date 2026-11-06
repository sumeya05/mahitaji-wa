import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';

import { ChoiceField, type Option, PickerField, SwitchField } from '@/components/fleet';
import { FormBody, FormPage, useRecordId } from '@/components/record';
import { Field } from '@/components/ui';
import { api } from '@/lib/api';
import { useForm } from '@/lib/form';
import { loadCompanies, refOption } from '@/lib/options';
import type { Employee } from '@/lib/types';
import { useAuth } from '@/state/auth';

export default function EmployeeFormScreen() {
  const id = useRecordId();
  const employee = useQuery({ queryKey: ['employees', 'detail', id], queryFn: () => api.employees.get(id!), enabled: !!id });
  return (
    <FormPage id={id} query={employee} noun="employee">
      {(record) => <EmployeeForm employee={record} />}
    </FormPage>
  );
}

function EmployeeForm({ employee }: { employee: Employee | null }) {
  const roles = useAuth().user?.choices.roles ?? [];
  const form = useForm({
    employee_code: employee?.employee_code ?? '',
    full_name: employee?.full_name ?? '',
    role: employee?.role ?? 'driver',
    company: (employee ? refOption(employee.company) : null) as Option | null,
    phone_number: employee?.phone_number ?? '',
    is_active: employee?.is_active ?? true,
  });
  const v = form.values;

  const save = () => {
    const data = {
      employee_code: v.employee_code,
      full_name: v.full_name,
      role: v.role,
      company: v.company?.id ?? null,
      phone_number: v.phone_number.trim(),
      is_active: v.is_active,
    };
    form.submit(
      () => (employee ? api.employees.update(employee.id, data) : api.employees.add(data)),
      (saved) => (employee ? router.back() : router.replace({ pathname: '/employees/[id]', params: { id: saved.id } })),
    );
  };

  return (
    <FormBody error={form.error} busy={form.busy} onSave={save}>
      <Field label="Employee code" placeholder="EMP014" autoCapitalize="characters" autoCorrect={false} {...form.bind('employee_code')} />
      <Field label="Full name" autoCapitalize="words" textContentType="name" {...form.bind('full_name')} />
      <ChoiceField label="Role" choices={roles} value={v.role} onChange={(value) => form.set('role', value as Employee['role'])}
        error={form.errorFor('role')} />
      <PickerField label="Company" value={v.company} onChange={(option) => form.set('company', option)}
        load={loadCompanies} queryKey={['companies']} error={form.errorFor('company')} />
      <Field label="Phone" placeholder="0712 345 678" keyboardType="phone-pad" textContentType="telephoneNumber" {...form.bind('phone_number')} />
      {employee && (
        <SwitchField label="Active" hint="Inactive employees are hidden from lists." value={v.is_active}
          onChange={(on) => form.set('is_active', on)} />
      )}
    </FormBody>
  );
}
