export type OperatingProfile = 'unknown' | 'legacy' | 'hybrid' | 'hybrid-test';
type Command = {command:string; valve?:string; open?:boolean};
export function profileFromMessage(message: Record<string,unknown>): OperatingProfile | undefined {
  if(message.type !== 'operating_profile') return undefined;
  const profile=message.profile;
  return message.profile_version===1 && typeof profile==='string' && ['legacy','hybrid','hybrid-test'].includes(profile)
    && message.fsw_enabled===(profile!=='hybrid-test') ? profile as OperatingProfile : 'unknown';
}
export function profileCommand(profile:OperatingProfile, device:'sv2'|'mav', open:boolean):Command|null {
  if(profile==='unknown') return null;
  if(profile==='hybrid-test') return device==='sv2' ? {command:'actuate_valve',valve:'SV2',open}
    : {command:open?'mav_open':'mav_close'};
  return {command:`fsw_${open?'open':'close'}_${device==='sv2'?'sv':'mav'}`};
}
export function profileAllowsCommand(profile:OperatingProfile, value:Command):boolean {
  if(profile==='unknown') return ['heartbeat','get_operating_profile','get_hardware_availability',
    'get_valve_state','get_mav_state','get_ball_valve_state','start_adc_stream','stop_adc_stream'].includes(value.command);
  return profile!=='hybrid-test' || !(value.command.startsWith('fsw_') || ['start_fsw_stream','stop_fsw_stream'].includes(value.command));
}
type Reading = {raw?:number; voltage?:number; scaled?:number|null};
type ADC = {adc1_valid?:boolean;adc2_valid?:boolean;adc1?:Reading[];adc2?:Reading[]};
export const finiteReading=(value:unknown):number|null => typeof value==='number' && Number.isFinite(value) ? value : null;
export function testStandReadings(profile:OperatingProfile, data:ADC) {
  const local=profile==='hybrid-test';
  const lc2=local && data.adc2_valid===true && finiteReading(data.adc2?.[2]?.voltage)!==null;
  return {pt3:local && data.adc1_valid===true?finiteReading(data.adc1?.[2]?.scaled):null,
    pt4:local && data.adc1_valid===true?finiteReading(data.adc1?.[3]?.scaled):null,
    lc2Raw:lc2 && Number.isInteger(data.adc2?.[2]?.raw)?data.adc2![2].raw!:null,
    lc2Voltage:lc2?finiteReading(data.adc2?.[2]?.voltage):null};
}
