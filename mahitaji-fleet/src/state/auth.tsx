import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { api, setAuthToken, setUnauthorizedHandler } from '@/lib/api';
import { secure } from '@/lib/secure';
import type { Action, Me, Resource } from '@/lib/types';

const TOKEN_KEY = 'mahitaji-fleet.token';

interface AuthState {
  /** False until the saved token has been read from secure storage. */
  ready: boolean;
  token: string | null;
  user: Me | null;
  signIn: (token: string, user: Me) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [ready, setReady] = useState(false);
  const [token, setToken] = useState<string | null>(null);

  const applyToken = useCallback(
    async (next: string | null) => {
      setAuthToken(next);
      setToken(next);
      if (next) await secure.set(TOKEN_KEY, next);
      else await secure.remove(TOKEN_KEY);
      // What a person may see depends on their permissions, so nothing is kept across accounts.
      queryClient.clear();
    },
    [queryClient],
  );

  useEffect(() => {
    secure.get(TOKEN_KEY)
      .then((saved) => {
        setAuthToken(saved);
        setToken(saved);
      })
      .finally(() => setReady(true));
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => void applyToken(null));
    return () => setUnauthorizedHandler(null);
  }, [applyToken]);

  // Permissions are fetched again on every launch, so changes made in the admin reach the phone.
  const me = useQuery({ queryKey: ['me', token], queryFn: api.me, enabled: ready && !!token, staleTime: 5 * 60 * 1000 });

  const signIn = useCallback(
    async (next: string, user: Me) => {
      await applyToken(next);
      queryClient.setQueryData(['me', next], user);
    },
    [applyToken, queryClient],
  );

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // Signed out on the phone even if the server could not be reached.
    }
    await applyToken(null);
  }, [applyToken]);

  const value = useMemo(
    () => ({ ready, token, user: token ? (me.data ?? null) : null, signIn, signOut }),
    [ready, token, me.data, signIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside AuthProvider');
  return context;
}

/** Whether the signed-in person may view / add / change a kind of record (set in the admin). */
export function useCan(resource: Resource, action: Action = 'view') {
  return !!useAuth().user?.permissions[resource][action];
}
