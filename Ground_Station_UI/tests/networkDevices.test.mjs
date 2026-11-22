import test from 'node:test';
import assert from 'node:assert/strict';
import {parseNetworkSnapshot} from '../src/networkDevices.ts';
const device={id:'plug',kind:'shelly',model:'Shelly Plug US Gen4',address:null,state:'not_configured',output:null,metrics:{},stale:true,lastSuccessUnixMs:null,canSetOutput:false};
const snapshot=devices=>({schemaVersion:1,devices,powerWritesConfigured:false,operatorAuthorizationRequired:true});
test('unconfigured inventory preserves unknown output and absent address',()=>{
 const d=parseNetworkSnapshot(snapshot([device])).devices[0];assert.equal(d.output,null);assert.equal(d.address,null);
});
test('actual off and zero-power readings remain distinct from unknown',()=>{
 const d=parseNetworkSnapshot(snapshot([{...device,state:'available',output:false,stale:false,metrics:{powerW:0}}])).devices[0];
 assert.equal(d.output,false);assert.equal(d.metrics.powerW,0);
});
test('invalid protocol, duplicates and malformed device state are rejected',()=>{
 for(const value of [null,{}, {...snapshot([]),schemaVersion:2},snapshot([device,device]),snapshot([{...device,output:0}]),snapshot([{...device,state:'online'}])]) assert.throws(()=>parseNetworkSnapshot(value));
});
test('invalid metric numbers and port data are rejected',()=>{
 for(const d of [{...device,metrics:{powerW:Infinity}},{...device,ports:[{port:0}]},{...device,lastSuccessUnixMs:-1}]) assert.throws(()=>parseNetworkSnapshot(snapshot([d])));
});
