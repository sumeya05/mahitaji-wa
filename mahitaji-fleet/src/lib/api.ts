import Constants from 'expo-constants';

import type {
  Area,
  Company,
  Customer,
  Employee,
  Me,
  Page,
  Route,
  Vehicle,
} from './types';

function resolveBaseUrl() {
  const configured = process.env.EXPO_PUBLIC_API_URL;

  if (configured) {
    return configured.replace(/\/+$/, '');
  }

  const host = Constants.expoConfig?.hostUri?.split(':')[0];

  return `http://${host || 'localhost'}:8000`;
}

export const BASE_URL = resolveBaseUrl();

const API = `${BASE_URL}/api/v1/fleet`;

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public fields: Record<string, string[]> = {},
  ) {
    super(message);
  }

  field(name: string) {
    return this.fields[name]?.[0];
  }
}

let authToken: string | null = null;

let onUnauthorized: (() => void) | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

export function setUnauthorizedHandler(
  handler: (() => void) | null,
) {
  onUnauthorized = handler;
}

type Method = 'GET' | 'POST' | 'PATCH';

type Query = Record<string, string | number | undefined>;

async function request<T>(
  method: Method,
  path: string,
  body?: unknown,
  query?: Query,
): Promise<T> {
  let url = `${API}${path}`;

  if (query) {
    const params = Object.entries(query)
      .filter(
        ([, value]) =>
          value !== undefined && value !== '',
      )
      .map(
        ([key, value]) =>
          `${encodeURIComponent(key)}=${encodeURIComponent(
            String(value),
          )}`,
      );

    if (params.length) {
      url += `?${params.join('&')}`;
    }
  }

  const headers: Record<string, string> = {
    Accept: 'application/json',
  };

  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  if (authToken) {
    headers.Authorization = `Token ${authToken}`;
  }

  let response: Response;

  try {
    response = await fetch(url, {
      method,
      headers,
      body:
        body === undefined
          ? undefined
          : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(
      "Can't reach Mahitaji right now. Check your internet connection and try again.",
      0,
    );
  }

  const data = await response.json().catch(() => null);

  if (response.ok) {
    return data as T;
  }

  if (response.status === 401 && authToken) {
    onUnauthorized?.();
  }

  const message =
    data?.error ||
    (response.status === 403
      ? "Your account isn't allowed to do this. Ask the office for access."
      : response.status === 429
        ? 'Too many requests. Please wait a moment and try again.'
        : response.status >= 500
          ? 'Something went wrong on our side. Please try again shortly.'
          : 'That did not work. Please try again.');

  throw new ApiError(
    message,
    response.status,
    data?.errors ?? {},
  );
}

export interface ListQuery extends Query {
  q?: string;
  page?: number;
  page_size?: number;
}

export type Payload = Record<
  string,
  string | number | boolean | null
>;

function master<T>(path: string) {
  return {
    list: (query: ListQuery = {}) =>
      request<Page<T>>(
        'GET',
        `/${path}/`,
        undefined,
        query,
      ),

    get: (id: number) =>
      request<T>(
        'GET',
        `/${path}/${id}/`,
      ),

    add: (data: Payload) =>
      request<T>(
        'POST',
        `/${path}/`,
        data,
      ),

    update: (id: number, data: Payload) =>
      request<T>(
        'PATCH',
        `/${path}/${id}/`,
        data,
      ),
  };
}

export const api = {
  login: (
    username: string,
    password: string,
  ) =>
    request<{
      token: string;
      user: Me;
    }>(
      'POST',
      '/auth/login/',
      {
        username,
        password,
      },
    ),

  register: (
    username: string,
    email: string,
    first_name: string,
    last_name: string,
    phone: string,
    password: string,
    password_confirm: string,
  ) =>
    request<{
      message: string;
      username: string;
    }>(
      'POST',
      '/auth/register/',
      {
        username,
        email,
        first_name,
        last_name,
        phone,
        password,
        password_confirm,
      },
    ),

  logout: () =>
    request<{
      ok: boolean;
    }>(
      'POST',
      '/auth/logout/',
    ),

  me: () =>
    request<Me>(
      'GET',
      '/me/',
    ),

  companies: (query: ListQuery = {}) =>
    request<Page<Company>>(
      'GET',
      '/companies/',
      undefined,
      query,
    ),

  employees: master<Employee>('employees'),

  routes: master<Route>('routes'),

  areas: master<Area>('areas'),

  vehicles: master<Vehicle>('vehicles'),

  customers: master<Customer>('customers'),
};
