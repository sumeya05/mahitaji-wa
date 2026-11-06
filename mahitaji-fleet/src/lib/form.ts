import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { ApiError } from './api';

type StringKeys<T> = { [K in keyof T]: T[K] extends string ? K : never }[keyof T] & string;

/** Field values plus the messages the server sent back for them. */
export function useForm<T extends Record<string, unknown>>(initial: T) {
  const [values, setValues] = useState<T>(initial);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const queryClient = useQueryClient();

  return {
    values,
    error,
    busy,
    set: <K extends keyof T>(name: K, value: T[K]) => setValues((v) => ({ ...v, [name]: value })),
    errorFor: (name: string) => error?.field(name),
    /** Props for a text <Field>: its value, change handler and server error. */
    bind: (name: StringKeys<T>) => ({
      value: values[name] as string,
      onChangeText: (text: string) => setValues((v) => ({ ...v, [name]: text })),
      error: error?.field(name),
    }),
    /**
     * Send the form. On success everything cached is refetched (a vehicle's crew shows on the
     * employee too) and `then` gets the saved record; on failure the messages go to the fields.
     */
    submit: async <R>(send: () => Promise<R>, then: (saved: R) => void) => {
      setError(null);
      setBusy(true);
      try {
        const saved = await send();
        void queryClient.invalidateQueries();
        then(saved);
      } catch (e) {
        setError(e instanceof ApiError ? e : new ApiError(e instanceof Error ? e.message : 'Something went wrong.', 0));
      } finally {
        setBusy(false);
      }
    },
  };
}

/** '' -> null, so a cleared optional field is stored as empty. */
export function blankToNull(value: string) {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}
