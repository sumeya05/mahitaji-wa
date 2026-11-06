import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useRef } from 'react';

import { type Option, PickerField, SwitchField } from '@/components/fleet';
import { FormBody, FormPage, useRecordId } from '@/components/record';
import { Field } from '@/components/ui';
import { api } from '@/lib/api';
import { useForm } from '@/lib/form';
import { routeOption } from '@/lib/options';
import type { Area, Ref } from '@/lib/types';

export default function AreaFormScreen() {
  const id = useRecordId();
  const area = useQuery({ queryKey: ['areas', 'detail', id], queryFn: () => api.areas.get(id!), enabled: !!id });
  return (
    <FormPage id={id} query={area} noun="area">
      {(record) => <AreaForm area={record} />}
    </FormPage>
  );
}

function AreaForm({ area }: { area: Area | null }) {
  const form = useForm({
    code: area?.code ?? '',
    name: area?.name ?? '',
    route: (area ? { id: area.route.id, label: area.route.name, detail: `${area.route.code} · ${area.company.name}` } : null) as Option | null,
    company: (area?.company ?? null) as Ref | null,
    county: area?.county ?? '',
    town: area?.town ?? '',
    description: area?.description ?? '',
    is_active: area?.is_active ?? true,
  });
  const v = form.values;
  // An area belongs to its route's company, so the company is taken from the route picked.
  const routeCompanies = useRef(new Map<number, Ref>());
  const loadRoutes = (q: string) =>
    api.routes.list({ q, page_size: 100 }).then((page) => {
      page.results.forEach((route) => routeCompanies.current.set(route.id, route.company));
      return page.results.map(routeOption);
    });

  const save = () => {
    const data = {
      code: v.code,
      name: v.name,
      route: v.route?.id ?? null,
      company: v.company?.id ?? null,
      county: v.county.trim(),
      town: v.town.trim(),
      description: v.description.trim(),
      is_active: v.is_active,
    };
    form.submit(
      () => (area ? api.areas.update(area.id, data) : api.areas.add(data)),
      (saved) => (area ? router.back() : router.replace({ pathname: '/areas/[id]', params: { id: saved.id } })),
    );
  };

  return (
    <FormBody error={form.error} busy={form.busy} onSave={save}>
      <Field label="Area code" placeholder="KSR" autoCapitalize="characters" autoCorrect={false} {...form.bind('code')} />
      <Field label="Area name" placeholder="Kasarani" autoCapitalize="words" {...form.bind('name')} />
      <PickerField
        label="Route"
        value={v.route}
        onChange={(option) => {
          form.set('route', option);
          form.set('company', option ? (routeCompanies.current.get(option.id) ?? null) : null);
        }}
        load={loadRoutes}
        queryKey={['routes']}
        error={form.errorFor('route') ?? form.errorFor('company')}
        hint={v.company ? `Company: ${v.company.name} (from the route)` : 'The area takes the route’s company.'}
      />
      <Field label="County" placeholder="Nairobi" autoCapitalize="words" {...form.bind('county')} />
      <Field label="Town" autoCapitalize="words" {...form.bind('town')} />
      <Field label="Landmarks and boundaries" placeholder="What helps a driver find the area" multiline {...form.bind('description')} />
      {area && (
        <SwitchField label="Active" hint="Inactive areas are hidden from lists." value={v.is_active}
          onChange={(on) => form.set('is_active', on)} />
      )}
    </FormBody>
  );
}
