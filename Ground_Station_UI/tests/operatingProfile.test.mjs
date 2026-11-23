import test from 'node:test';
import assert from 'node:assert/strict';
import {profileFromMessage,profileCommand,profileAllowsCommand,testStandReadings} from '../src/operatingProfile.ts';
test('profile identity is explicit and incompatible reports fail closed',()=>{
 assert.equal(profileFromMessage({type:'operating_profile',profile_version:1,profile:'hybrid-test',fsw_enabled:false}),'hybrid-test');
 assert.equal(profileFromMessage({type:'operating_profile',profile_version:1,profile:'hybrid-test',fsw_enabled:true}),'unknown');
 assert.equal(profileFromMessage({type:'operating_profile',profile_version:2,profile:'hybrid'}),'unknown');
 assert.equal(profileFromMessage({type:'adc_data'}),undefined);
});
test('test mode uses local commands, Hybrid keeps FSW commands',()=>{
 assert.deepEqual(profileCommand('hybrid-test','sv2',true),{command:'actuate_valve',valve:'SV2',open:true});
 assert.deepEqual(profileCommand('hybrid-test','mav',false),{command:'mav_close'});
 assert.deepEqual(profileCommand('hybrid','sv2',false),{command:'fsw_close_sv'});
 assert.equal(profileCommand('unknown','mav',true),null);
 assert.equal(profileAllowsCommand('hybrid-test',{command:'fsw_key_arm'}),false);
 assert.equal(profileAllowsCommand('unknown',{command:'bv_open'}),false);
 assert.equal(profileAllowsCommand('unknown',{command:'get_operating_profile'}),true);
});
test('test sensors use local ADCs and LC2 voltage, never inherited calibration',()=>{
 const sample={adc1_valid:true,adc2_valid:true,adc1:[{scaled:1},{scaled:2},{scaled:3},{scaled:4}],adc2:[{}, {},{raw:123,voltage:0.25,scaled:9999}]};
 assert.deepEqual(testStandReadings('hybrid-test',sample),{pt3:3,pt4:4,lc2Raw:123,lc2Voltage:0.25});
 assert.deepEqual(testStandReadings('hybrid',sample),{pt3:null,pt4:null,lc2Raw:null,lc2Voltage:null});
 sample.adc2_valid=false;assert.equal(testStandReadings('hybrid-test',sample).lc2Raw,null);
});

test('UI ownership and test sensor channels agree with the operating definitions',async()=>{
 const {readFile}=await import('node:fs/promises');
 const {profiles}=JSON.parse(await readFile(new URL('../../fill-station/hardware/operating-profiles.json',import.meta.url),'utf8'));
 for(const name of ['hybrid','hybrid-test']) {
  const profile=profiles[name];
  for(const id of ['sv2','mav']) {
   const owner=profile.controls.find(c=>c.id===id).owner;
   assert.equal(profileCommand(name,id,true).command.startsWith('fsw_'),owner==='fsw');
  }
 }
 const sensors=profiles['hybrid-test'].sensors;
 for(const [id,adc,ch] of [['pt3','adc1',2],['pt4','adc1',3],['lc2','adc2',2]]) {
  const sensor=sensors.find(s=>s.id===id);
  assert.deepEqual([sensor.deviceId,sensor.channel],[adc,ch]);
 }
});
