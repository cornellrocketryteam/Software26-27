import test from 'node:test';
import assert from 'node:assert/strict';
import { roleAvailable, commandAvailable, readingAvailable } from '../src/hardwareAvailability.ts';
test('legacy data retains previous interpretation',()=>{
 assert.equal(roleAvailable(null,'sv1'),true);
 assert.equal(commandAvailable(null,{command:'launch'}),true);
 assert.equal(readingAvailable({valid:true},0),true);
});
test('disabled role rejects compound launch and local valve, leaving FSW controls alone',()=>{
 const availability={availability_version:1,configured_devices_mask:4095 & ~1 & ~(1<<4)};
 assert.equal(commandAvailable(availability,{command:'launch'}),false);
 assert.equal(commandAvailable(availability,{command:'actuate_valve',valve:'SV1'}),false);
 assert.equal(commandAvailable(availability,{command:'fsw_open_sv'}),true);
 assert.equal(commandAvailable(availability,{command:'bv_open'}),true);
});
test('independent ADC validity masks do not erase valid readings',()=>{
 const message={availability_version:1,valid:false,valid_readings_mask:3};
 assert.equal(readingAvailable(message,0),true);
 assert.equal(readingAvailable(message,1),true);
 assert.equal(readingAvailable(message,2),false);
});
test('unknown availability versions do not claim local hardware exists',()=>{
 assert.equal(roleAvailable({availability_version:2,configured_devices_mask:4095},'sv1'),false);
});
test('legacy ADC data clears availability from a previous modern connection', async()=>{
 const { availabilityFromMessage } = await import('../src/hardwareAvailability.ts');
 assert.equal(availabilityFromMessage({type:'adc_data',valid:true}),null);
 assert.deepEqual(availabilityFromMessage({type:'hardware_availability',availability_version:1,configured_devices_mask:3}),{availability_version:1,configured_devices_mask:3});
 assert.equal(availabilityFromMessage({type:'fsw_telemetry'}),undefined);
});
test('cancelling a timed vent closes it now or remembers to close on reconnect', async()=>{
 const { reconcileVentClose } = await import('../src/hardwareAvailability.ts');
 assert.deepEqual(reconcileVentClose(false,true,false,true),{pending:false,close:true});
 const offline=reconcileVentClose(false,true,false,false);
 assert.deepEqual(offline,{pending:true,close:false});
 assert.deepEqual(reconcileVentClose(offline.pending,false,true,true),{pending:false,close:true});
 assert.deepEqual(reconcileVentClose(false,false,true,true),{pending:false,close:false});
});
