import { router } from 'expo-router';

import { FilterRow, MasterList, useListFilter } from '@/components/fleet';
import { Chip, ListItem } from '@/components/ui';
import { api } from '@/lib/api';
import { capacity } from '@/lib/format';
import type { Vehicle } from '@/lib/types';
import { useAuth, useCan } from '@/state/auth';

export default function VehiclesScreen() {
  const types = useAuth().user?.choices.vehicle_types ?? [];
  const canAdd = useCan('vehicles', 'add');
  const { filter, choose, of } = useListFilter();
  const type = of('type');
  const missing = of('missing');

  return (
    <MasterList<Vehicle>
      queryKey={['vehicles', filter]}
      fetchPage={(query) => api.vehicles.list({ ...query, type, missing })}
      searchPlaceholder="Vehicle number or crew name"
      filters={
        <FilterRow>
          <Chip label="All" active={!filter} onPress={() => choose('')} />
          <Chip label="No driver" icon="alert-circle-outline" active={missing === 'driver'} onPress={() => choose('missing:driver')} />
          <Chip label="No turnboy" icon="alert-circle-outline" active={missing === 'turnboy'} onPress={() => choose('missing:turnboy')} />
          {types.map((choice) => (
            <Chip key={choice.value} label={choice.label} active={type === choice.value} onPress={() => choose(`type:${choice.value}`)} />
          ))}
        </FilterRow>
      }
      empty={
        missing
          ? { icon: 'checkmark-circle-outline', title: 'All crewed', message: `Every vehicle has a ${missing}.` }
          : { icon: 'bus-outline', title: 'No vehicles yet', message: 'Vehicles added here or in the admin show up in this list.' }
      }
      onAdd={canAdd ? () => router.push('/vehicles/edit') : undefined}
      addLabel="Add vehicle"
      renderItem={(vehicle) => (
        <ListItem
          icon="bus-outline"
          title={vehicle.registration_number}
          subtitle={[
            `${vehicle.vehicle_type_display} · ${capacity(vehicle.capacity_kg)}`,
            `Driver: ${vehicle.driver?.full_name ?? 'none'} · Turnboy: ${vehicle.turnboy?.full_name ?? 'none'}`,
          ].join('\n')}
          onPress={() => router.push({ pathname: '/vehicles/[id]', params: { id: vehicle.id } })}
        />
      )}
    />
  );
}
