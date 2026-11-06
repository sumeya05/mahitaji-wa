import { type UseQueryResult } from '@tanstack/react-query';
import { Stack, useLocalSearchParams } from 'expo-router';
import type { ReactNode } from 'react';
import { ScrollView, View } from 'react-native';

import type { ApiError } from '@/lib/api';
import { space } from '@/lib/theme';

import { FormScreen } from './screen';
import { Button, Card, ErrorState, Loading, Notice, T } from './ui';

/** The `id` in the address (/vehicles/12), or null on an add form. */
export function useRecordId() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  return id ? Number(id) : null;
}

/** A record's page: waits for it, then shows `children` with an Edit button for those allowed to change it. */
export function RecordPage<R>({
  query, title, children, onEdit,
}: {
  query: UseQueryResult<R>;
  title: (record: R) => string;
  children: (record: R) => ReactNode;
  onEdit?: () => void;
}) {
  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const record = query.data;
  return (
    <>
      <Stack.Screen options={{ title: title(record) }} />
      <ScrollView contentContainerStyle={{ padding: space.lg, gap: space.lg, paddingBottom: space.xxl }}>
        {children(record)}
        {onEdit && <Button title="Edit" kind="secondary" icon="create-outline" onPress={onEdit} />}
      </ScrollView>
    </>
  );
}

export function Section({ title, children, note }: { title: string; children: ReactNode; note?: string }) {
  return (
    <View style={{ gap: space.sm }}>
      <T variant="label" style={{ textTransform: 'uppercase', letterSpacing: 0.6 }}>{title}</T>
      <Card style={{ paddingVertical: space.sm }}>{children}</Card>
      {!!note && <T variant="caption">{note}</T>}
    </View>
  );
}

/**
 * An add / edit form. On an edit form (`id` set) it waits for the record and hands it to
 * `children`; on an add form `children` gets null.
 */
export function FormPage<R>({
  id, query, noun, children,
}: {
  id: number | null;
  query: UseQueryResult<R>;
  noun: string;
  children: (record: R | null) => ReactNode;
}) {
  const title = `${id ? 'Edit' : 'Add'} ${noun}`;
  if (id && query.isPending) return <Loading />;
  if (id && query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  return (
    <>
      <Stack.Screen options={{ title }} />
      {children(id ? (query.data ?? null) : null)}
    </>
  );
}

/** The scrolling body of a form, with the server's message on top and the save button at the end. */
export function FormBody({ error, busy, onSave, children }: { error: ApiError | null; busy: boolean; onSave: () => void; children: ReactNode }) {
  return (
    <FormScreen>
      {error && <Notice tone="danger">{error.message}</Notice>}
      {children}
      <Button title="Save" icon="checkmark" onPress={onSave} loading={busy} />
    </FormScreen>
  );
}
