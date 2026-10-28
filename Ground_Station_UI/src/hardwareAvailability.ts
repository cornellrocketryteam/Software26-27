export type HardwareAvailability = { availability_version: number; configured_devices_mask: number } | null;
export const hardwareRoles = ['ig1', 'ig2', 'adc1', 'adc2', 'sv1', 'sv2', 'sv3', 'sv4', 'sv5', 'mav', 'ball_valve', 'qd_stepper'] as const;
export function roleAvailable(availability: HardwareAvailability, role: string): boolean {
  if (!availability || availability.availability_version === 0) return true;
  const bit = hardwareRoles.indexOf(role as typeof hardwareRoles[number]);
  return availability.availability_version === 1 && bit >= 0 && (availability.configured_devices_mask & (1 << bit)) !== 0;
}
export function commandAvailable(availability: HardwareAvailability, command: {command: string; valve?: string; id?: number}): boolean {
  let roles: string[] = [];
  const name = command.command;
  if (name === 'launch' || name === 'ignite') roles = ['ig1', 'ig2'];
  else if (name === 'actuate_valve' || name === 'get_valve_state') roles = [command.valve?.toLowerCase() ?? ''];
  else if (name === 'get_igniter_continuity') roles = [`ig${command.id}`];
  else if (name.startsWith('bv_') || name === 'get_ball_valve_state') roles = ['ball_valve'];
  else if (name.startsWith('qd_') || name === 'get_qd_state') roles = ['qd_stepper'];
  else if (name.startsWith('mav_') || name === 'get_mav_state') roles = ['mav'];
  return roles.every(role => roleAvailable(availability, role));
}
export function readingAvailable(message: {availability_version?:number;valid_readings_mask?:number;valid:boolean}, bit: number): boolean {
  return message.availability_version ? message.availability_version === 1 && ((message.valid_readings_mask ?? 0) & (1 << bit)) !== 0 : message.valid;
}

export function availabilityFromMessage(message: {type?:string; availability_version?:number; configured_devices_mask?:number}): HardwareAvailability | undefined {
  if (message.type !== 'hardware_availability' && message.type !== 'adc_data') return undefined;
  if (!Number.isInteger(message.availability_version) || !Number.isInteger(message.configured_devices_mask)) return null;
  return {availability_version:message.availability_version!,configured_devices_mask:message.configured_devices_mask!};
}

export function reconcileVentClose(pending: boolean, wasVenting: boolean, hardwareAvailable: boolean, connected: boolean): {pending:boolean; close:boolean} {
  const required = pending || (!hardwareAvailable && wasVenting);
  return {pending:required && !connected, close:required && connected};
}
