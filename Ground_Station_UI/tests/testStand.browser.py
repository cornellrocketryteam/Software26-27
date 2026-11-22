"""Local-only operator checks. All sockets are replaced before application startup."""
import json
from playwright.sync_api import sync_playwright, expect

BASE='http://127.0.0.1:4173'
CONFIG={'schemaVersion':1,'fillStationWebSocketUrl':'ws://fixture.invalid:9000','grafanaUrl':'/grafana/',
        'fieldMode':True,'map':{'tileUrl':'/tiles/{z}/{x}/{y}.png','tilesConfigured':False}}
MOCK='''(() => {
 window.sent=[]; window.sockets=[];window.reports=true;
 const states={SV1:false,BV:false,SV5:false};let stamp=1;
 class Socket extends EventTarget {
  static OPEN=1;static CLOSED=3;readyState=0;
  constructor(){super();window.sockets.push(this);setTimeout(()=>{this.readyState=1;this.onopen?.({});},10);}
  emit(m){setTimeout(()=>{if(window.reports)this.dispatchEvent(new MessageEvent('message',{data:JSON.stringify(m)}));},0);}
  send(raw){const m=JSON.parse(raw);window.sent.push(m);
   if(m.command==='get_hardware_availability'||m.command==='start_adc_stream') {
    this.emit({type:'hardware_availability',availability_version:1,configured_devices_mask:4095});
    this.emit({type:'adc_data',timestamp_ms:stamp++,availability_version:1,configured_devices_mask:4095,
     valid_readings_mask:3,adc1_valid:true,adc2_valid:false,
     adc1:[{raw:100,voltage:0.2,scaled:123.45},{raw:200,voltage:0.4,scaled:512.25},
      {raw:0,voltage:0,scaled:null},{raw:0,voltage:0,scaled:null}],
     adc2:Array(4).fill({raw:0,voltage:0,scaled:null})});
   }
   if(m.command==='get_valve_state') this.emit({type:'valve_state',valve:m.valve,open:states[m.valve],continuity:true});
   if(m.command==='get_ball_valve_state') this.emit({type:'ball_valve_state',open:states.BV});
   if(m.command==='actuate_valve') states[m.valve]=m.open;
   if(m.command==='bv_open'||m.command==='bv_close') states.BV=m.command==='bv_open';
  }
  close(){this.readyState=3;this.onclose?.({});}
 }
 window.WebSocket=Socket;
})()'''
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,channel='chrome')
 try:
  context=browser.new_context(viewport={'width':1600,'height':1100})
  context.route_web_socket('**',lambda s:s.close())
  context.add_init_script(MOCK)
  external=[]
  def route(r):
   if not r.request.url.startswith(BASE+'/'):external.append(r.request.url);r.abort()
   elif r.request.url.endswith('/station-config.json'):r.fulfill(content_type='application/json',body=json.dumps(CONFIG))
   else:r.continue_()
  context.route('**/*',route)
  page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(BASE+'/propulsion')
  expect(page.get_by_role('heading',name='Propulsion Page',exact=True)).to_be_visible()
  expect(page.get_by_text('Fill station: connected',exact=True)).to_be_visible()
  expect(page.get_by_role('button',name='Button Interaction State: DISABLED')).to_be_visible()
  expect(page.get_by_text('PT1: 123.45 PSI · PT2: 512.25 PSI',exact=False)).to_be_visible()
  for label in ['Solenoid Valve 1','Solenoid Valve 2','Ball Valve','MAV','Quick Disconnect','Launch Button','Reset FRAM','Wipe Flash','Reboot FSW']:
   expect(page.get_by_text(label,exact=True).first).to_be_visible()
  assert not page.get_by_role('button',name='Fill',exact=False).count()
  assert not page.get_by_role('button',name='Vent',exact=False).count()
  page.get_by_role('button',name='Button Interaction State: DISABLED').click()
  def card(label): return page.get_by_text(label,exact=True).locator('..')
  card('Solenoid Valve 1').get_by_role('button',name='OPEN',exact=True).click()
  page.get_by_role('button',name='No',exact=True).click()
  assert not any(m['command']=='actuate_valve' for m in page.evaluate('window.sent'))
  for label,action in [('Solenoid Valve 1','OPEN'),('Ball Valve','OPEN'),('Ball Valve','CLOSE'),('Quick Disconnect','RELEASE'),('Quick Disconnect','OFF')]:
   card(label).get_by_role('button',name=action,exact=True).click()
   page.get_by_role('button',name='Yes',exact=True).click()
   page.wait_for_timeout(500)
  acts=[m for m in page.evaluate('window.sent') if m['command'] in ['actuate_valve','bv_open','bv_close']]
  assert acts==[{'command':'actuate_valve','valve':'SV1','open':True},{'command':'bv_open'},{'command':'bv_close'},{'command':'actuate_valve','valve':'SV5','open':True},{'command':'actuate_valve','valve':'SV5','open':False}],acts
  assert not any(m['command'].startswith('qd_') for m in page.evaluate('window.sent'))
  page.screenshot(path='/private/tmp/restored-propulsion-ui.png',full_page=True)
  page.evaluate('window.sockets.at(-1).close()')
  expect(page.get_by_role('button',name='Button Interaction State: DISABLED')).to_be_visible()
  expect(page.get_by_text('Fill station: connected',exact=True)).to_be_visible(timeout=6000)
  expect(page.get_by_role('button',name='Button Interaction State: DISABLED')).to_be_visible()
  assert len([m for m in page.evaluate('window.sent') if m['command'] in ['actuate_valve','bv_open','bv_close']])==5
  assert not external,external
  assert not errors,errors
  print('Restored layout, on-rocket controls, SV1/BV/QD commands, cancellation and reconnect passed (mock sockets only).')
 finally: browser.close()
