const $ = (id) => document.getElementById(id);
const state = {profile:null, baseline:'', revision:'', selected:null, bootstrap:null, report:null, epoch:0, selectedPin:null};
const names = {main_i2c0:'Main I²C0 · shared board bus',main_i2c2:'Main I²C2',main_i2c3:'Main I²C3',mcu_i2c0:'MCU I²C0',mcu_i2c1:'MCU I²C1'};
const noPull = new Set(['main:0x0260','main:0x0264','mcu:0x0048','mcu:0x004c']);
const fixed = new Set(['main:0x0164','main:0x02a8']);
const key = (pin) => `${pin.domain}:0x${Number(pin.offset).toString(16).padStart(4,'0')}`;
const sharedBus = bus => state.profile?.profile==='liquid' && bus.controller==='main_i2c0';
const controllerChoices = () => Object.entries(names).filter(([name])=>name!=='main_i2c0'||state.profile?.profile==='liquid');
const protectedPinForProfile = pin => !pin || fixed.has(key(pin)) || (key(pin)==='main:0x0264' && state.profile?.profile!=='liquid');
const dirty = () => state.profile && JSON.stringify(state.profile) !== state.baseline;
function el(tag, attrs={}, ...children) {
  const node = document.createElement(tag);
  for (const [name,value] of Object.entries(attrs)) {
    if (name.startsWith('on')) node.addEventListener(name.slice(2), value);
    else if (name === 'class') node.className=value;
    else if (name === 'checked') node.checked=Boolean(value);
    else if (value !== null && value !== undefined) node.setAttribute(name,String(value));
  }
  for (const child of children.flat(Infinity)) if(child !== null && child !== undefined) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return node;
}
function status(text) { $('status').textContent=text; }
async function api(path, method='GET', body=null) {
  const response=await fetch(path,{method,headers:body?{'Content-Type':'application/json','X-Session-Token':state.bootstrap.token}:{},body:body?JSON.stringify(body):null});
  const result=await response.json();
  if (!response.ok) throw Object.assign(new Error((result.errors||['Request failed']).join('\n')),{status:response.status,result});
  return result;
}
function chooseSelect(options, value, onchange, label) {
  const node=el('select',{'aria-label':label,onchange:(event)=>onchange(event.target.value)});
  for(const option of options) node.append(el('option',{value:option.value,disabled:option.disabled?'disabled':null},option.label));
  node.value=value ?? '';
  return node;
}
function field(label,node) { return el('label',{class:'field'},el('span',{},label),node); }
function markChanged() { state.epoch++; status(`${state.profile.profile === 'liquid'?'Liquid':'Hybrid'} · Unsaved changes`); $('save').disabled=true; renderNav(); renderHeaders(); clearTimeout(state.timer); state.timer=setTimeout(validate,220); }
function owners() {
  const map=new Map();
  const add=(connection,owner)=>{if(!connection?.pin)return; const list=map.get(connection.pin)||[]; list.push(owner);map.set(connection.pin,list);};
  for(const device of state.profile.devices||[]) if(device.enabled) for(const [port,connection] of Object.entries(device.connections||{}))add(connection,`${device.id}.${port}`);
  for(const bus of state.profile.buses||[]) if(sharedBus(bus)||state.profile.devices.some(d=>d.enabled&&d.bus===bus.id))for(const [port,connection]of Object.entries(bus.connections||{}))add(connection,`${bus.id}.${port}`);
  for(const pin of fixed)map.set(pin,['Board policy']);
  return map;
}
function pinLabel(pin,signal) { return `${(pin.headers||[]).join(' / ') || 'Board pad'} · ${signal} · ${pin.ball}`; }
function portOptions(kind,current,owner,controller,port) {
  const options=[{value:'',label:'Choose a connection…'}];const allocated=owners();
  const prefix={main_i2c0:'I2C0_',main_i2c2:'I2C2_',main_i2c3:'I2C3_',mcu_i2c0:'MCU_I2C0_',mcu_i2c1:'MCU_I2C1_'}[controller];
  for(const pin of state.bootstrap.board.pins) {
    if(protectedPinForProfile(pin))continue;
    for(const signal of Object.keys(pin.functions||{})) {
      if(kind==='gpio'&&!signal.includes('GPIO'))continue;
      if(kind==='pwm'&&!signal.startsWith('EHRPWM'))continue;
      if(kind==='i2c'&&signal!==prefix+port.toUpperCase())continue;
      const value=`${key(pin)}|${signal}`;
      const occupied=(allocated.get(key(pin))||[]).filter(x=>x!==owner);
      const isCurrent=current?.pin===key(pin)&&current?.function===signal;
      options.push({value,label:pinLabel(pin,signal)+(occupied.length?` — used by ${occupied.join(', ')}`:''),disabled:occupied.length>0&&!isCurrent});
    }
  }
  return options;
}
function connectionEditor(target,port,meta,owner,controller=null) {
  target.connections ||= {};
  const current=target.connections[port];
  const pick=chooseSelect(portOptions(meta.kind,current,owner,controller,port), current?`${current.pin}|${current.function}`:'', value=>{
    if(!value)delete target.connections[port];
    else {const [pin,signal]=value.split('|'); target.connections[port]={pin,function:signal,bias:noPull.has(pin)?'none':current?.bias??meta.bias??'pull-down',schmitt:current?.schmitt??true};}
    markChanged();renderEditor();
  },`${port} connection`);
  const result=el('div',{class:'port'},el('div',{class:'port-header'},el('span',{class:'port-title'},port.replaceAll('_',' ')),el('span',{class:'badge'},meta.kind==='i2c'?'I²C':`${meta.kind.toUpperCase()} ${meta.direction||''}`)),pick);
  if(current){
    const biasChoices=noPull.has(current.pin)?[{value:'none',label:'No pull (dedicated pad)'}]:[{value:'pull-down',label:'Pull-down'},{value:'pull-up',label:'Pull-up'},{value:'none',label:'No pull'}];
    const bias=chooseSelect(biasChoices,current.bias,v=>{current.bias=v;markChanged();},`${port} bias`);
    const schmitt=el('input',{type:'checkbox',checked:current.schmitt,onchange:e=>{current.schmitt=e.target.checked;markChanged();}});
    result.append(el('div',{class:'electrical'},el('label',{},'Bias',bias),el('label',{},schmitt,'Schmitt input')));
  }
  return result;
}
function renderNav() {
  const devices=$('devices');devices.replaceChildren();
  state.profile.devices.forEach((device,index)=>{
    const meta=state.bootstrap.catalog[device.type];
    devices.append(el('button',{class:`device ${state.selected===`device:${index}`?'selected':''} ${device.enabled?'':'disabled'}`,onclick:()=>{state.selected=`device:${index}`;renderNav();renderEditor();}},el('i',{class:`dot ${device.enabled?'active':'idle'}`}),el('span',{},el('span',{class:'name'},device.id),el('span',{class:'subtitle'},`${meta?.label||device.type}${device.enabled?'':' · disabled'}`))));
  });
  const buses=$('buses');buses.replaceChildren();
  state.profile.buses.forEach((bus,index)=>buses.append(el('button',{class:`device ${state.selected===`bus:${index}`?'selected':''}`,onclick:()=>{state.selected=`bus:${index}`;renderNav();renderEditor();}},el('i',{class:'dot active'}),el('span',{},el('span',{class:'name'},bus.id),el('span',{class:'subtitle'},names[bus.controller]||bus.controller)))));
  if(!state.profile.devices.length)devices.append(el('p',{class:'muted'},'Add a supported device to begin.'));
}
function renderEditor() {
  const pane=$('editor');pane.replaceChildren();
  if(!state.selected){pane.append(el('h3',{},'Choose a device'),el('p',{class:'muted'},'Select a device or I²C bus to edit its connections.'));return;}
  const [kind,number]=state.selected.split(':');const index=Number(number);const item=state.profile[kind==='device'?'devices':'buses'][index];
  if(!item){state.selected=null;renderEditor();return;}
  const device=kind==='device';const meta=device?state.bootstrap.catalog[item.type]:null;
  pane.append(el('div',{class:'editor-intro'},el('div',{},el('span',{class:'eyebrow'},device?meta?.label||item.type:'SHARED I²C BUS'),el('h3',{},item.id)),el('span',{class:'badge'},device?(item.role?'Application bound':'Initialized only'):'Shared connection')));
  const idInput=el('input',{value:item.id,'aria-label':'Instance ID',pattern:'[a-z][a-z0-9_]*',onchange:e=>{const previous=item.id;item.id=e.target.value;if(!device)for(const d of state.profile.devices)if(d.bus===previous)d.bus=item.id;markChanged();renderEditor();}});
  pane.append(field(device?'Instance ID':'Bus ID',idInput));
  if(device) {
    pane.append(el('label',{class:'toggle'},el('input',{type:'checkbox',checked:item.enabled,onchange:e=>{item.enabled=e.target.checked;markChanged();renderEditor();}}),'Enable device'));
    pane.append(el('p',{class:'muted'},item.role?`Application role: ${item.role}. Commands depend on this role, not the instance ID.`:'This device initializes at startup. Add a Rust application binding before controlling or publishing it.'));
    if(!item.enabled)pane.append(el('div',{class:'notice'},'Disabled devices do not initialize. Their connections are available for reassignment; otherwise available header pins return to their idle input state.'));
    if(item.type==='ads1015') {
      pane.append(field('I²C bus',chooseSelect([{value:'',label:'Choose an I²C bus…'},...state.profile.buses.map(b=>({value:b.id,label:`${b.id} · ${names[b.controller]||b.controller}`}))],item.bus,v=>{item.bus=v;markChanged();},'I2C bus')));
      pane.append(field('I²C address',chooseSelect([72,73,74,75].map(n=>({value:n,label:`0x${n.toString(16)}`})),item.address,v=>{item.address=Number(v);markChanged();},'I2C address')));
    }
    for(const [setting,definition]of Object.entries(meta?.settings||{})){
      item.settings ||= {};
      const choices=(definition.choices||[]).map(v=>({value:v,label:v.replaceAll('_',' ')}));
      pane.append(field(definition.label||setting,chooseSelect(choices,item.settings[setting]??definition.default,v=>{item.settings[setting]=v;markChanged();},definition.label||setting)));
      if(setting==='valve_type')pane.append(el('p',{class:'muted'},'Valve type describes its mechanical unpowered state; it is separate from pin bias.'));
    }
    const ports=el('div',{class:'ports'});for(const [port,definition]of Object.entries(meta?.ports||{}))ports.append(connectionEditor(item,port,definition,`${item.id}.${port}`));pane.append(ports);
  } else {
    if(sharedBus(item))pane.append(el('div',{class:'notice'},'Always enabled in Liquid, including with no external devices. PRU 6 = SCL; PRU 8 = SDA. Shared with onboard devices: addresses 0x30, 0x50 and 0x51 are reserved. Disconnect the old QD enable wire from PRU 6. New ADC types require separate driver integration.'));
    else pane.append(field('Controller',chooseSelect(controllerChoices().filter(([value])=>value!=='main_i2c0').map(([value,label])=>({value,label})),item.controller,v=>{item.controller=v;item.connections={};markChanged();renderEditor();},'I2C controller')));
    const users=state.profile.devices.filter(d=>d.bus===item.id).map(d=>d.id);
    pane.append(el('p',{class:'muted'},users.length?`Devices on this bus: ${users.join(', ')}`:sharedBus(item)?'No external device instances currently use this bus. Onboard devices still share it.':'No devices currently use this bus.'));
    for(const port of ['scl','sda'])pane.append(connectionEditor(item,port,{kind:'i2c',direction:'input',bias:'pull-up'},`${item.id}.${port}`,item.controller));
  }
  if(device||!sharedBus(item))pane.append(el('div',{class:'remove-row'},el('button',{class:'danger',onclick:()=>{if(!confirm(`Remove ${item.id}? ${item.role?'Its application role will become unavailable.':''}`))return;state.profile[device?'devices':'buses'].splice(index,1);state.selected=null;markChanged();renderNav();renderEditor();}},device?'Remove device':'Remove bus')));
}
function renderHeaders() {
  if(!state.bootstrap||!state.profile)return;
  const container=$('headers');container.replaceChildren();const allocated=owners();
  const byHeader=new Map();for(const pin of state.bootstrap.board.pins)for(const header of pin.headers||[])byHeader.set(header,pin);
  for(const [header,count]of Object.entries(state.bootstrap.headers)) {
    const grid=el('div',{class:'pin-grid'});
    for(let position=1;position<=count;position++){
      const pin=byHeader.get(`${header}:${position}`);const owner=pin?allocated.get(key(pin)):null;
      const protectedPin=protectedPinForProfile(pin);const active=Boolean(owner);
      const label=protectedPin?'Locked':owner?owner.join(', '):pin.gpio||'Idle';
      grid.append(el('button',{class:`pin ${protectedPin?'protected':active?'assigned':''} ${pin&&state.selectedPin===key(pin)?'highlight':''}`,'aria-label':`${header} pin ${position}: ${label}`,title:pin?`${pin.pad} (${pin.ball}) · ${(pin.headers||[]).join(' / ')} · ${label}`:'Protected, power or unlisted board position',onclick:()=>{
        state.selectedPin=pin?key(pin):null;
        $('pin-detail').textContent=pin?`${pin.pad} · ball ${pin.ball}\n${pin.headers.join(' ↔ ')}\n${owner?owner.join(', '):protectedPin?'Protected board resource':`Idle input · ${pin.idle_bias||'no pull'}`}`:`${header}:${position} · Protected or unlisted. Check the board schematic for its electrical purpose.`;
        renderHeaders();
      }},el('strong',{},position),el('span',{},label)));
    }
    container.append(el('section',{class:'connector'},el('div',{class:'connector-title'},el('h2',{},header==='EXPANSION'?'40-pin expansion':header==='PRU'?'PRU header':'MCU header'),el('span',{},`${count/2} × 2`)),grid));
  }
}
async function validate() {
  if(!state.profile)return false;
  const epoch=state.epoch;$('validation-state').textContent='Checking';
  try {
    const result=await api('/api/validate','POST',{profile:state.profile});if(epoch!==state.epoch)return false;
    state.report=result.report;$('validation-state').textContent='Valid';$('validation-state').className='badge good';
    const assignments=result.report.assignments||[];const idle=result.report.idle||[];
    $('errors').replaceChildren(el('p',{class:'success'},`No connection conflicts. ${assignments.length} assigned pads · ${idle.length} idle inputs.`));
    $('save').disabled=!dirty();return true;
  } catch(error) {
    if(epoch!==state.epoch)return false;
    $('validation-state').textContent='Needs attention';$('validation-state').className='badge bad';
    $('errors').replaceChildren(el('p',{class:'error'},error.message));$('save').disabled=true;return false;
  }
}
async function load(name) {
  const data=await api(`/api/profiles/${name}`);state.profile=data.profile;state.revision=data.revision;state.baseline=JSON.stringify(data.profile);state.selected=state.profile.devices.length?'device:0':null;state.epoch++;$('profile').value=name;renderNav();renderEditor();renderHeaders();status(`${name==='liquid'?'Liquid':'Hybrid'} · Saved profile`);await validate();
}
$('profile').addEventListener('change',async e=>{const name=e.target.value;if(dirty()&&!confirm('Discard unsaved changes and switch application?')){e.target.value=state.profile.profile;return;}try{await load(name);}catch(error){status(error.message);}});
$('validate').addEventListener('click',async()=>{if(await validate())status(`${dirty()?'Unsaved changes':'Saved profile'} · Configuration is valid`);});
$('save').addEventListener('click',async()=>{if(!await validate())return;const epoch=state.epoch;const profile=JSON.parse(JSON.stringify(state.profile));try{const saved=await api(`/api/profiles/${state.profile.profile}`,'PUT',{profile,revision:state.revision});state.revision=saved.revision;state.baseline=JSON.stringify(saved.profile);status(epoch===state.epoch?'Profile saved. Build the application separately.':'Profile saved; newer edits are still unsaved.');$('save').disabled=!dirty();}catch(error){$('errors').replaceChildren(el('p',{class:'error'},error.message));status(error.status===409?'Save blocked · profile changed on disk':'Profile was not saved');}});
$('discard').addEventListener('click',async()=>{if(dirty()&&!confirm('Discard unsaved changes and reload this profile from disk?'))return;try{await load(state.profile.profile);}catch(error){status(error.message);}});
function addDialog(bus) {
  state.addBus=bus;$('dialog-title').textContent=bus?'Add I²C bus':'Add device';$('confirm-add').textContent=bus?'Add bus':'Add device';
  const options=bus?controllerChoices().filter(([value])=>!state.profile.buses.some(b=>b.controller===value)).map(([value,label])=>({value,label})):Object.entries(state.bootstrap.catalog).map(([value,meta])=>({value,label:meta.label||value}));
  $('new-type').replaceChildren(...options.map(o=>el('option',{value:o.value},o.label)));$('new-id').value='';$('new-type').labels[0].firstChild.textContent=bus?'Controller':'Supported type';$('add-dialog').showModal();
}
$('add-device').addEventListener('click',()=>addDialog(false));$('add-bus').addEventListener('click',()=>addDialog(true));
$('add-form').addEventListener('submit',event=>{
  if(event.submitter?.value!=='add')return;event.preventDefault();const id=$('new-id').value;const type=$('new-type').value;
  if([...state.profile.devices,...state.profile.buses].some(item=>item.id===id)){$('new-id').setCustomValidity('Choose a unique instance ID');$('new-id').reportValidity();return;}
  if(state.addBus){state.profile.buses.push({id,controller:type,connections:{}});state.selected=`bus:${state.profile.buses.length-1}`;}
  else {const meta=state.bootstrap.catalog[type];const settings=Object.fromEntries(Object.entries(meta.settings||{}).map(([name,s])=>[name,s.default]));const item={id,type,role:null,enabled:true,connections:{},settings};if(type==='ads1015'){item.bus=state.profile.buses[0]?.id||'';item.address=72;}state.profile.devices.push(item);state.selected=`device:${state.profile.devices.length-1}`;}
  $('add-dialog').close();markChanged();renderNav();renderEditor();
});
$('new-id').addEventListener('input',()=> $('new-id').setCustomValidity(''));
window.addEventListener('beforeunload',event=>{if(dirty()){event.preventDefault();event.returnValue='';}});
try {state.bootstrap=await api('/api/bootstrap');await load('liquid');} catch(error){status(`Cannot load editor: ${error.message}`);$('errors').textContent=error.message;}
