import { useQuery } from '@tanstack/react-query';
import * as Location from 'expo-location';
import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { type Option, PickerField } from '@/components/fleet';
import { FormBody, FormPage, useRecordId } from '@/components/record';
import { Button, Field, Notice, T } from '@/components/ui';
import { api } from '@/lib/api';
import { blankToNull, useForm } from '@/lib/form';
import { coordinates } from '@/lib/format';
import { loadAreas } from '@/lib/options';
import { space } from '@/lib/theme';
import type { Customer } from '@/lib/types';

export default function CustomerFormScreen() {
  const id = useRecordId();
  const customer = useQuery({ queryKey: ['customers', 'detail', id], queryFn: () => api.customers.get(id!), enabled: !!id });
  return (
    <FormPage id={id} query={customer} noun="customer">
      {(record) => <CustomerForm customer={record} />}
    </FormPage>
  );
}

function CustomerForm({ customer }: { customer: Customer | null }) {
  const form = useForm({
    business_name: customer?.business_name ?? '',
    customer_code: customer?.customer_code ?? '',
    contact_person: customer?.contact_person ?? '',
    phone_number: customer?.phone_number ?? '',
    address: customer?.address?.physical_address ?? '',
    city: customer?.address?.city ?? 'Nairobi',
    area: (customer?.area ? { id: customer.area.id, label: customer.area.name, detail: customer.area.code } : null) as Option | null,
    latitude: customer?.latitude ?? null,
    longitude: customer?.longitude ?? null,
  });
  const v = form.values;
  const [locating, setLocating] = useState(false);
  const [locationError, setLocationError] = useState('');

  /** Record where the phone is now: used when standing at the customer's shop. */
  const recordCurrentLocation = async () => {
    setLocationError('');
    setLocating(true);
    try {
      const permission = await Location.requestForegroundPermissionsAsync();
      if (!permission.granted) {
        setLocationError('Location permission was refused. Allow it in the phone settings to record the shop’s position.');
        return;
      }
      const position = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
      form.set('latitude', Number(position.coords.latitude.toFixed(6)));
      form.set('longitude', Number(position.coords.longitude.toFixed(6)));
    } catch {
      setLocationError("Couldn't get your location. Check that location is switched on and try again.");
    } finally {
      setLocating(false);
    }
  };

  const save = () => {
    const data = {
      business_name: v.business_name,
      customer_code: v.customer_code.trim(),
      contact_person: blankToNull(v.contact_person),
      phone_number: v.phone_number.trim(),
      address: v.address,
      city: v.city,
      area: v.area?.id ?? null,
      latitude: v.latitude,
      longitude: v.longitude,
    };
    form.submit(
      () => (customer ? api.customers.update(customer.id, data) : api.customers.add(data)),
      (saved) => (customer ? router.back() : router.replace({ pathname: '/customers/[id]', params: { id: saved.id } })),
    );
  };

  const hasLocation = v.latitude !== null && v.longitude !== null;

  return (
    <FormBody error={form.error} busy={form.busy} onSave={save}>
      <Field label="Customer name" placeholder="Business or shop name" autoCapitalize="words" {...form.bind('business_name')} />
      <Field label="Customer code" placeholder="Assigned automatically" autoCapitalize="characters" autoCorrect={false}
        hint={customer ? undefined : 'Leave empty to get the next code (like MC00042).'} {...form.bind('customer_code')} />
      <Field label="Contact person" autoCapitalize="words" {...form.bind('contact_person')} />
      <Field label="Phone" placeholder="0712 345 678" keyboardType="phone-pad" textContentType="telephoneNumber" {...form.bind('phone_number')} />
      <Field label="Address" placeholder="Street, building, landmark" multiline {...form.bind('address')} />
      <Field label="Town / city" autoCapitalize="words" {...form.bind('city')} />
      <PickerField label="Delivery area" value={v.area} onChange={(option) => form.set('area', option)} allowClear
        placeholder="No area yet" load={loadAreas} queryKey={['areas']} error={form.errorFor('area')}
        hint="The route comes from the area." />

      <View style={{ gap: space.sm }}>
        <T variant="label">GPS location</T>
        <T>{hasLocation ? coordinates(v.latitude!, v.longitude!) : 'Not recorded'}</T>
        {!!(form.errorFor('latitude') || form.errorFor('longitude')) && (
          <Notice tone="danger">{form.errorFor('latitude') ?? form.errorFor('longitude')}</Notice>
        )}
        {!!locationError && <Notice tone="warning">{locationError}</Notice>}
        <Button title={hasLocation ? 'Update to my current location' : 'Use my current location'} kind="secondary"
          icon="navigate-outline" onPress={recordCurrentLocation} loading={locating} />
        {hasLocation && (
          <Button title="Clear location" kind="ghost" small onPress={() => {
            form.set('latitude', null);
            form.set('longitude', null);
          }} />
        )}
        <T variant="caption">Stand at the customer’s shop when you record it, so drivers can find it.</T>
      </View>
    </FormBody>
  );
}
