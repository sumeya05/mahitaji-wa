import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';

import { MasterList } from '@/components/fleet';
import { Chip, ListItem } from '@/components/ui';
import { api } from '@/lib/api';
import { colors, space } from '@/lib/theme';
import type { Area, Route } from '@/lib/types';
import { useCan } from '@/state/auth';

/** Areas and the routes they belong to, switched with the chips at the top. */
export default function AreasScreen() {
  const canSeeAreas = useCan('areas');
  const canSeeRoutes = useCan('routes');
  const canAddArea = useCan('areas', 'add');
  const canAddRoute = useCan('routes', 'add');
  const [tab, setTab] = useState<'areas' | 'routes'>(canSeeAreas ? 'areas' : 'routes');

  return (
    <View style={{ flex: 1 }}>
      {canSeeAreas && canSeeRoutes && (
        <View style={{ flexDirection: 'row', gap: space.sm, paddingHorizontal: space.lg, paddingTop: space.md, backgroundColor: colors.surface }}>
          <Chip label="Areas" icon="location-outline" active={tab === 'areas'} onPress={() => setTab('areas')} />
          <Chip label="Routes" icon="git-branch-outline" active={tab === 'routes'} onPress={() => setTab('routes')} />
        </View>
      )}
      {tab === 'areas' ? (
        <MasterList<Area>
          key="areas"
          queryKey={['areas']}
          fetchPage={api.areas.list}
          searchPlaceholder="Area, code, town or county"
          empty={{ icon: 'location-outline', title: 'No areas yet', message: 'Delivery areas group customers on a route.' }}
          onAdd={canAddArea ? () => router.push('/areas/edit') : undefined}
          addLabel="Add area"
          renderItem={(area) => (
            <ListItem
              icon="location-outline"
              title={area.name}
              subtitle={`${area.code} · ${area.route.name} route${area.town ? ` · ${area.town}` : ''}`}
              onPress={() => router.push({ pathname: '/areas/[id]', params: { id: area.id } })}
            />
          )}
        />
      ) : (
        <MasterList<Route>
          key="routes"
          queryKey={['routes']}
          fetchPage={api.routes.list}
          searchPlaceholder="Route name or code"
          empty={{ icon: 'git-branch-outline', title: 'No routes yet', message: 'Routes group the areas a vehicle covers.' }}
          onAdd={canAddRoute ? () => router.push('/routes/edit') : undefined}
          addLabel="Add route"
          renderItem={(route) => (
            <ListItem
              icon="git-branch-outline"
              title={route.name}
              subtitle={`${route.code} · ${route.company.name}`}
              onPress={() => router.push({ pathname: '/routes/[id]', params: { id: route.id } })}
            />
          )}
        />
      )}
    </View>
  );
}
