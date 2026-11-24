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

test('power eligibility requires explicit fresh configured authorized Shelly state',async()=>{
 const {canControlPower}=await import('../src/networkDevices.ts');
 const d={...device,address:'192.168.1.120',connectedLoad:'Fixture lamp',canSetOutput:true,state:'available',output:false,stale:false};
 const s={...snapshot([d]),powerWritesConfigured:true};const token='fixture-token-at-least-24-chars';
 assert.equal(canControlPower(s,d,token,true,false),true);
 for(const changed of [{...d,connectedLoad:null},{...d,canSetOutput:false},{...d,stale:true},{...d,state:'unknown'},{...d,kind:'omada-switch'},{...d,address:null}]) assert.equal(canControlPower(s,changed,token,true,false),false);
 assert.equal(canControlPower(s,d,token,false,false),false);
 assert.equal(canControlPower(s,d,token,true,true),false);
 assert.equal(canControlPower(s,d,'',true,false),false);
 assert.equal(canControlPower({...s,powerWritesConfigured:false},d,token,true,false),false);
});
test('power reply validates requested state and never invents confirmation',async()=>{
 const {parsePowerReply}=await import('../src/networkDevices.ts');
 const raw={requestedOutput:true,confirmed:true,observed:{state:'available',output:true,metrics:{powerW:0}}};
 assert.equal(parsePowerReply(raw,true).confirmed,true);
 assert.equal(parsePowerReply({...raw,observed:{...raw.observed,output:false}},true).confirmed,false);
 assert.throws(()=>parsePowerReply({...raw,requestedOutput:false},true));
 assert.throws(()=>parsePowerReply({...raw,observed:{...raw.observed,output:null}},true));
});
