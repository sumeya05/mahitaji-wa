import type { Option } from '@/components/fleet';

import { api } from './api';
import type { Area, Employee, Ref, Role, Route } from './types';

/** Choices for the pickers on the add / edit forms. */
const PICKER_SIZE = 100;

export const refOption = (ref: Ref): Option => ({ id: ref.id, label: ref.name, detail: ref.code });

export const routeOption = (route: Route): Option => ({ id: route.id, label: route.name, detail: `${route.code} · ${route.company.name}` });

export const areaOption = (area: Area): Option => ({ id: area.id, label: area.name, detail: `${area.code} · ${area.route.name} route` });

export const employeeOption = (employee: { id: number; full_name: string; employee_code: string }, detail?: string): Option => ({
  id: employee.id,
  label: employee.full_name,
  detail: detail ?? employee.employee_code,
});

export const loadCompanies = (q: string) =>
  api.companies({ q, page_size: PICKER_SIZE }).then((page) => page.results.map(refOption));

export const loadRoutes = (q: string) =>
  api.routes.list({ q, page_size: PICKER_SIZE }).then((page) => page.results.map(routeOption));

export const loadAreas = (q: string) =>
  api.areas.list({ q, page_size: PICKER_SIZE }).then((page) => page.results.map(areaOption));

/** Drivers or turnboys, with the vehicle each is already on (one vehicle per person). */
export const loadCrew = (role: Role) => (q: string) =>
  api.employees.list({ q, role, page_size: PICKER_SIZE }).then((page) =>
    page.results.map((e: Employee) =>
      employeeOption(e, `${e.employee_code} · ${e.vehicle ? `on ${e.vehicle.registration_number}` : 'not on a vehicle'}`),
    ),
  );
