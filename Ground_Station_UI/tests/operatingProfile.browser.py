"""Profile-specific React controls against local-only fake sockets; no devices."""
import json
from playwright.sync_api import sync_playwright,expect
BASE='http://127.0.0.1:4173'
CONFIG={'schemaVersion':1,'fillStationWebSocketUrl':'ws://fixture.invalid:9000','grafanaUrl':'/grafana/',
        'fieldMode':True,'map':{'tileUrl':'/tiles/{z}/{x}/{y}.png','tilesConfigured':False}}
MOCK='''(() => {
 window.sent=[];window.profile=PROFILE;window.sockets=[];
 const states={SV1:false,SV2:false,SV5:false,MAV:false};
 class Socket extends EventTarget {
  static OPEN=1;static CLOSED=3;readyState=0;
  constructor(){super();window.sockets.push(this);setTimeout(()=>{this.readyState=1;this.onopen?.({});},10);}
  emit(m){setTimeout(()=>this.dispatchEvent(new MessageEvent('message',{data:JSON.stringify(m)})),0);}
  send(raw){const m=JSON.parse(raw);window.sent.push(m);
   if(m.command==='get_operating_profile' && window.profile!=='unknown') this.emit({type:'operating_profile',profile_version:1,profile:window.profile,fsw_enabled:window.profile!=='hybrid-test'});
   if(m.command==='get_hardware_availability') this.emit({type:'hardware_availability',availability_version:1,configured_devices_mask:1855});
   if(m.command==='start_adc_stream') this.emit({type:'adc_data',availability_version:1,valid_readings_mask:7,configured_devices_mask:1855,adc1_valid:true,adc2_valid:true,
    adc1:[1,2,3,4].map(n=>({raw:n,voltage:0.1,scaled:n*100})),adc2:[0,1,2,3].map(n=>({raw:n+200,voltage:0.25,scaled:9999}))});
   if(m.command==='get_valve_state') this.emit({type:'valve_state',valve:m.valve,open:states[m.valve],continuity:true});
   if(m.command==='actuate_valve') states[m.valve]=m.open;
   if(m.command==='mav_open'||m.command==='mav_close') states.MAV=m.command==='mav_open';
   if(m.command==='get_mav_state') this.emit({type:'mav_state',open:states.MAV,pulse_width_us:1000});
  }
  close(){this.readyState=3;this.onclose?.({});}
 }
 window.WebSocket=Socket;
})()'''
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,channel='chrome')
 try:
  for profile in ['hybrid-test','hybrid','unknown']:
   context=browser.new_context(viewport={'width':1600,'height':1100})
   context.route_web_socket('**',lambda s:s.close())
   context.add_init_script(MOCK.replace('PROFILE',json.dumps(profile)))
   external=[];errors=[]
   def route(r):
    if not r.request.url.startswith(BASE+'/'):external.append(r.request.url);r.abort()
    elif r.request.url.endswith('/station-config.json'):r.fulfill(content_type='application/json',body=json.dumps(CONFIG))
    else:r.continue_()
   context.route('**/*',route);page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(BASE+'/propulsion');expect(page.get_by_text('Fill station: connected',exact=True)).to_be_visible()
   page.wait_for_timeout(800)
   if profile=='hybrid-test':
    expect(page.get_by_text('Flight Software Key:',exact=True)).to_be_hidden()
    expect(page.get_by_text('General Purpose Commands:',exact=True)).to_be_hidden()
    expect(page.get_by_text('LC2: 202 raw · 0.25 V (uncalibrated)',exact=True)).to_be_visible()
    page.get_by_role('button',name='Button Interaction State: DISABLED').click()
    for label,action in [('Solenoid Valve 2','OPEN'),('Solenoid Valve 2','CLOSE'),('MAV','OPEN'),('MAV','CLOSE')]:
     card=page.locator('div').filter(has=page.get_by_text(label,exact=True)).filter(has=page.get_by_role('button',name=action,exact=True)).last
     card.get_by_role('button',name=action,exact=True).click();page.get_by_role('button',name='Yes',exact=True).click();page.wait_for_timeout(650)
    sent=page.evaluate('window.sent')
    assert {'command':'actuate_valve','valve':'SV2','open':True} in sent,sent
    assert {'command':'mav_open'} in sent,sent
    assert {'command':'mav_close'} in sent,sent
    assert {'command':'actuate_valve','valve':'SV2','open':False} in sent,sent
    assert not any(m['command'].startswith('fsw_') or m['command']=='start_fsw_stream' for m in sent),sent
    page.screenshot(path='/private/tmp/hybrid-test-commanding.png',full_page=True)
   elif profile=='hybrid':
    expect(page.get_by_text('Flight Software Key:',exact=True)).to_be_visible()
    assert any(m['command']=='start_fsw_stream' for m in page.evaluate('window.sent'))
   else:
    expect(page.get_by_role('button',name='Button Interaction State: DISABLED')).to_be_disabled()
    expect(page.get_by_role('button',name='Solenoid Valve 1 Unavailable',exact=True)).to_be_disabled()
    assert not any(m['command'] in ['actuate_valve','mav_open','bv_open'] for m in page.evaluate('window.sent'))
   assert not external,external
   assert not errors,errors
   context.close()
  print('Hybrid-test local routes/readings, Hybrid FSW controls and unknown-profile read-only behavior passed (mock only).')
 finally:browser.close()
