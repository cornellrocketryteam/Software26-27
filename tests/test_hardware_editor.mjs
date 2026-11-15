import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

class Element {
  constructor(tag='div') { this.tag=tag; this.children=[]; this.attrs={}; this.events={}; }
  setAttribute(name,value) { this.attrs[name]=value; }
  addEventListener(name,fn) { this.events[name]=fn; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children=children; }
}
const source=readFileSync(new URL('../fill-station/hardware/web/app.js',import.meta.url),'utf8');
function editor() {
  const elements=new Map();
  const context={Node:Element, document:{createElement:tag=>new Element(tag),createTextNode:text=>Object.assign(new Element('text'),{text}),getElementById:id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);}},setTimeout:()=>0,clearTimeout:()=>{}};
  vm.createContext(context);
  vm.runInContext(source.slice(0,source.indexOf("$('profile').addEventListener"))+'\nglobalThis.editor={state,portOptions,renderEditor};',context);
  context.editor.state.profile={profile:'liquid',devices:[],buses:[]};
  context.editor.state.bootstrap={headers:{PRU:54,EXPANSION:40,MCU:28},board:JSON.parse(readFileSync(new URL('../fill-station/hardware/board-pins.json',import.meta.url))),catalog:JSON.parse(readFileSync(new URL('../fill-station/hardware/catalog.json',import.meta.url)))};
  return {...context.editor,elements};
}
test('PWM selector exposes all direct outputs and blocks a GPIO-owned alias',()=>{
  const ui=editor();
  let options=ui.portOptions('pwm',null,'servo.pwm',null,'pwm');
  assert.equal(options.filter(o=>o.value.includes('|PRG0_PRU')).length,38);
  ui.state.profile.devices.push({id:'valve',enabled:true,connections:{control:{pin:'main:0x01b8',function:'GPIO1_22'}}});
  options=ui.portOptions('pwm',null,'servo.pwm',null,'pwm');
  assert.equal(options.find(o=>o.value==='main:0x01b8|PRG0_PRU1_GPO2').disabled,true);
});
test('PWM settings render numeric inputs and edits serialize as numbers',()=>{
  const ui=editor();
  const device={id:'servo',type:'ereg',role:null,enabled:true,connections:{},settings:{}};
  ui.state.profile.devices.push(device);ui.state.selected='device:0';
  ui.renderEditor();
  const descend=n=>[n,...n.children.flatMap(descend)];
  const inputs=descend(ui.elements.get('editor')).filter(n=>n.attrs.type==='number');
  assert.equal(inputs.length,4);
  const period=inputs.find(n=>n.attrs['aria-label']==='PWM period (ns)');
  assert.equal(period.attrs.value,'3030000');
  period.events.change({target:{value:'20000000'}});
  assert.equal(device.settings.period_ns,20000000);
});
