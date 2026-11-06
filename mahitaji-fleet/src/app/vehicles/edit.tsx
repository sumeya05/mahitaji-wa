import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';

import { ChoiceField, type Option, PickerField, SwitchField } from '@/components/fleet';
import { FormBody, FormPage, useRecordId } from '@/components/record';
import { Field } from '@/components/ui';
import { api } from '@/lib/api';
import { useForm } from '@/lib/form';
import { employeeOption, loadCompanies, loadCrew, refOption } from '@/lib/options';
import type { Vehicle } from '@/lib/types';
import { useAuth } from '@/state/auth';

export default function VehicleFormScreen() {
  const id = useRecordId();
  const vehicle = useQuery({ queryKey: ['vehicles', 'detail', id], queryFn: () => api.vehicles.get(id!), enabled: !!id });
  return (
    <FormPage id={id} query={vehicle} noun="vehicle">
      {(record) => <VehicleForm vehicle={record} />}
    </FormPage>
  );
}

function VehicleForm({ vehicle }: { vehicle: Vehicle | null }) {
  const types = useAuth().user?.choices.vehicle_types ?? [];
  const form = useForm({
    registration_number: vehicle?.registration_number ?? '',
    vehicle_type: vehicle?.vehicle_type ?? '',
    capacity_kg: vehicle ? String(vehicle.capacity_kg) : '',
    company: (vehicle ? refOption(vehicle.company) : null) as Option | null,
    driver: (vehicle?.driver ? employeeOption(vehicle.driver) : null) as Option | null,
    turnboy: (vehicle?.turnboy ? employeeOption(vehicle.turnboy) : null) as Option | null,
    is_active: vehicle?.is_active ?? true,
  });
  const v = form.values;

  const save = () => {
    const data = {
      registration_number: v.registration_number,
      vehicle_type: v.vehicle_type,
      capacity_kg: v.capacity_kg.replace(/[,\s]/g, ''),
      company: v.company?.id ?? null,
      driver: v.driver?.id ?? null,
      turnboy: v.turnboy?.id ?? null,
      is_active: v.is_active,
    };
    form.submit(
      () => (vehicle ? api.vehicles.update(vehicle.id, data) : api.vehicles.add(data)),
      (saved) => (vehicle ? router.back() : router.replace({ pathname: '/vehicles/[id]', params: { id: saved.id } })),
    );
  };

  return (
    <FormBody error={form.error} busy={form.busy} onSave={save}>
      <Field label="Vehicle number" placeholder="KDA 123A" autoCapitalize="characters" autoCorrect={false}
        {...form.bind('registration_number')} />
      <ChoiceField label="Vehicle type" choices={types} value={v.vehicle_type} onChange={(value) => form.set('vehicle_type', value)}
        error={form.errorFor('vehicle_type')} />
      <Field label="Capacity (kg)" placeholder="3000" keyboardType="number-pad" hint="Maximum load in kilograms"
        {...form.bind('capacity_kg')} />
      <PickerField label="Company" value={v.company} onChange={(option) => form.set('company', option)}
        load={loadCompanies} queryKey={['companies']} error={form.errorFor('company')} />
      <PickerField label="Driver" value={v.driver} onChange={(option) => form.set('driver', option)} allowClear
        placeholder="No driver" load={loadCrew('driver')} queryKey={['employees', 'driver']} error={form.errorFor('driver')}
        hint="Only employees with the Driver role are listed." />
      <PickerField label="Turnboy" value={v.turnboy} onChange={(option) => form.set('turnboy', option)} allowClear
        placeholder="No turnboy" load={loadCrew('turnboy')} queryKey={['employees', 'turnboy']} error={form.errorFor('turnboy')}
        hint="Only employees with the Turnboy role are listed." />
      {vehicle && (
        <SwitchField label="Active" hint="Inactive vehicles are hidden from lists." value={v.is_active}
          onChange={(on) => form.set('is_active', on)} />
      )}
    </FormBody>
  );
}
