import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';

import { type Option, PickerField, SwitchField } from '@/components/fleet';
import { FormBody, FormPage, useRecordId } from '@/components/record';
import { Field } from '@/components/ui';
import { api } from '@/lib/api';
import { useForm } from '@/lib/form';
import { loadCompanies, refOption } from '@/lib/options';
import type { Route } from '@/lib/types';

export default function RouteFormScreen() {
  const id = useRecordId();
  const route = useQuery({ queryKey: ['routes', 'detail', id], queryFn: () => api.routes.get(id!), enabled: !!id });
  return (
    <FormPage id={id} query={route} noun="route">
      {(record) => <RouteForm route={record} />}
    </FormPage>
  );
}

function RouteForm({ route }: { route: Route | null }) {
  const form = useForm({
    code: route?.code ?? '',
    name: route?.name ?? '',
    company: (route ? refOption(route.company) : null) as Option | null,
    is_active: route?.is_active ?? true,
  });
  const v = form.values;

  const save = () => {
    const data = { code: v.code, name: v.name, company: v.company?.id ?? null, is_active: v.is_active };
    form.submit(
      () => (route ? api.routes.update(route.id, data) : api.routes.add(data)),
      (saved) => (route ? router.back() : router.replace({ pathname: '/routes/[id]', params: { id: saved.id } })),
    );
  };

  return (
    <FormBody error={form.error} busy={form.busy} onSave={save}>
      <Field label="Route code" placeholder="R01" autoCapitalize="characters" autoCorrect={false} {...form.bind('code')} />
      <Field label="Route name" placeholder="Thika Road" autoCapitalize="words" {...form.bind('name')} />
      <PickerField label="Company" value={v.company} onChange={(option) => form.set('company', option)}
        load={loadCompanies} queryKey={['companies']} error={form.errorFor('company')} />
      {route && (
        <SwitchField label="Active" hint="Inactive routes are hidden from lists." value={v.is_active}
          onChange={(on) => form.set('is_active', on)} />
      )}
    </FormBody>
  );
}
