import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,access} from 'node:fs/promises';
const source=path=>readFile(new URL('../src/'+path,import.meta.url),'utf8');
test('original propulsion layout and on-rocket controls remain without fill automation',async()=>{
 const s=await source('PropulsionPage.tsx');
 for(const label of ['Fill Station Commands:','General Purpose Commands:','Solenoid Valve 1','Solenoid Valve 2','Ball Valve','MAV','Quick Disconnect','Launch Button','Reset FRAM','Wipe Flash','Reboot FSW']) assert.ok(s.includes(label),label);
 assert.doesNotMatch(s,/FillButtonComponent|VentButtonComponent|FillState|isFillingRef|ventTimeoutRef/);
 for(const path of ['components/FillComponent.tsx','components/VentButtonComponent.tsx','components/subcomponents/FillButtonComponent.tsx']) await assert.rejects(access(new URL('../src/'+path,import.meta.url)),{code:'ENOENT'});
});
test('QD uses SV5 release output rather than retired motor protocol',async()=>{
 const s=await source('PropulsionPage.tsx');
 assert.match(s,/"valve": "SV5"/); assert.doesNotMatch(s,/qd_retract|qd_extend|get_qd_state|qd_stepper/);
 assert.match(await source('components/ButtonComponent.tsx'),/RELEASE/);
});
