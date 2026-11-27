import test from 'node:test';
import assert from 'node:assert/strict';
import {parseEcoflowStatus} from '../src/ecoflowStatus.ts';
const base={enabled:true,state:'cloud-snapshot',readOnly:true,deviceSampleTimeKnown:false,ageSeconds:0,batteryPercent:0,inputWatts:0,outputWatts:12};
test('EcoFlow preserves zero and unknown metrics',()=>{assert.equal(parseEcoflowStatus(base).batteryPercent,0);assert.equal(parseEcoflowStatus({...base,inputWatts:null}).inputWatts,null);});
test('EcoFlow rejects misleading freshness and invalid values',()=>{for(const value of [{...base,deviceSampleTimeKnown:true},{...base,batteryPercent:101},{...base,inputWatts:true},{...base,ageSeconds:-1},{...base,state:'online'},{...base,state:'stale'}])assert.throws(()=>parseEcoflowStatus(value));});
test('EcoFlow unavailable states have no metrics',()=>{for(const state of ['pending','stale','unavailable','cloud-reports-offline','disabled'])assert.equal(parseEcoflowStatus({...base,enabled:state!=='disabled',state,ageSeconds:null,batteryPercent:null,inputWatts:null,outputWatts:null}).state,state);});
