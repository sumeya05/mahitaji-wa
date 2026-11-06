/** Shapes returned by the Mahitaji Fleet API (fleet/api.py on the server). */

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/** A related master as the API shows it inside another record. */
export interface Ref {
  id: number;
  code: string;
  name: string;
}

export interface Choice {
  value: string;
  label: string;
}

export type Resource = 'companies' | 'employees' | 'routes' | 'areas' | 'vehicles' | 'customers';
export type Action = 'view' | 'add' | 'change';

export interface Me {
  id: number;
  username: string;
  name: string;
  email: string;
  permissions: Record<Resource, Record<Action, boolean>>;
  choices: { roles: Choice[]; vehicle_types: Choice[] };
}

export type Company = Ref;

export type Role = 'driver' | 'turnboy' | 'other';

export interface Employee {
  id: number;
  employee_code: string;
  full_name: string;
  role: Role;
  role_display: string;
  company: Ref;
  phone_number: string;
  vehicle: { id: number; registration_number: string } | null;
  is_active: boolean;
}

export interface CrewMember {
  id: number;
  employee_code: string;
  full_name: string;
  phone_number: string;
}

export interface Vehicle {
  id: number;
  registration_number: string;
  vehicle_type: string;
  vehicle_type_display: string;
  capacity_kg: number;
  company: Ref;
  driver: CrewMember | null;
  turnboy: CrewMember | null;
  is_active: boolean;
}

export interface Route {
  id: number;
  code: string;
  name: string;
  company: Ref;
  is_active: boolean;
}

export interface Area {
  id: number;
  code: string;
  name: string;
  route: Ref;
  company: Ref;
  county: string;
  town: string;
  description: string;
  is_active: boolean;
}

export interface Customer {
  id: number;
  customer_code: string;
  name: string;
  business_name: string | null;
  contact_person: string | null;
  phone_number: string;
  email: string;
  has_login: boolean;
  address: { physical_address: string; city: string } | null;
  area: Ref | null;
  route: Ref | null;
  latitude: number | null;
  longitude: number | null;
}
