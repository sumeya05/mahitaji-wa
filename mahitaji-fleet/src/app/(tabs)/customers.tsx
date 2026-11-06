import { router } from 'expo-router';

import { FilterRow, MasterList, useListFilter } from '@/components/fleet';
import { Chip, ListItem } from '@/components/ui';
import { api } from '@/lib/api';
import { localPhone } from '@/lib/format';
import type { Customer } from '@/lib/types';
import { useCan } from '@/state/auth';

export default function CustomersScreen() {
  const canAdd = useCan('customers', 'add');
  const { filter, choose, of } = useListFilter();
  const missing = of('missing');

  return (
    <MasterList<Customer>
      queryKey={['customers', filter]}
      fetchPage={(query) => api.customers.list({ ...query, missing })}
      searchPlaceholder="Name, customer code or phone"
      filters={
        <FilterRow>
          <Chip label="All" active={!filter} onPress={() => choose('')} />
          <Chip label="No area" icon="alert-circle-outline" active={missing === 'area'} onPress={() => choose('missing:area')} />
          <Chip label="No GPS location" icon="alert-circle-outline" active={missing === 'location'} onPress={() => choose('missing:location')} />
        </FilterRow>
      }
      empty={
        missing
          ? { icon: 'checkmark-circle-outline', title: 'All done', message: `Every customer has ${missing === 'area' ? 'a delivery area' : 'a GPS location'}.` }
          : { icon: 'storefront-outline', title: 'No customers yet', message: 'Shop customers and delivery customers appear here.' }
      }
      onAdd={canAdd ? () => router.push('/customers/edit') : undefined}
      addLabel="Add customer"
      renderItem={(customer) => (
        <ListItem
          icon="storefront-outline"
          title={customer.name}
          subtitle={[
            [customer.customer_code, localPhone(customer.phone_number)].filter(Boolean).join(' · '),
            customer.area ? `${customer.area.name} · ${customer.route?.name} route` : 'No delivery area yet',
          ].join('\n')}
          onPress={() => router.push({ pathname: '/customers/[id]', params: { id: customer.id } })}
        />
      )}
    />
  );
}
