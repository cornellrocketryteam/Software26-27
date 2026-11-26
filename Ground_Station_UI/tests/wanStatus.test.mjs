import test from 'node:test';
import assert from 'node:assert/strict';
import {parseWanStatus} from '../src/wanStatus.ts';
const base={enabled:true,state:'reachable',method:'tcp-connect',checkedUnixMs:1,ageSeconds:0,observedFailureSpanSeconds:null,targets:[{label:'External fixture',address:'1.1.1.1',port:443,reachable:true,connectMs:0,attempts:1,failures:0,failureFraction:0,meanSuccessfulConnectMs:0}]};
test('WAN parser preserves zero timing and zero failures',()=>{const v=parseWanStatus(base);assert.equal(v.targets[0].connectMs,0);assert.equal(v.targets[0].failureFraction,0);});
test('disabled and stale WAN are distinct from responding targets',()=>{assert.equal(parseWanStatus({...base,enabled:false,state:'disabled',targets:[]}).state,'disabled');assert.equal(parseWanStatus({...base,state:'stale',targets:[{...base.targets[0],reachable:null,connectMs:null}]}).state,'stale');});
test('invalid probe figures never become healthy metrics',()=>{for(const value of [{...base,method:'packet-loss'},{...base,state:'online'},{...base,state:'unreachable'},{...base,ageSeconds:-1},{...base,targets:[{...base.targets[0],failureFraction:2}]},{...base,targets:[{...base.targets[0],connectMs:Infinity}]}])assert.throws(()=>parseWanStatus(value));});
