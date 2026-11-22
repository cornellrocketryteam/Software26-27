"""Network page acceptance with mocked API/sockets; block external requests and every write."""
import json
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'ground-station/network-devices'))
from service import DeviceRegistry
BASE='http://127.0.0.1:4173'
CONFIG={'schemaVersion':1,'fillStationWebSocketUrl':None,'grafanaUrl':'/grafana/','fieldMode':True,'map':{'tileUrl':'/tiles/{z}/{x}/{y}.png','tilesConfigured':False}}
DATA={**DeviceRegistry(json.loads((ROOT/'ground-station/network-devices/inventory.json').read_text())).snapshot(),
      'powerWritesConfigured':False,'operatorAuthorizationRequired':True}

with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,channel='chrome')
 try:
  context=browser.new_context(viewport={'width':1440,'height':1000})
  context.route_web_socket('**',lambda socket:socket.close())
  external=[];requests=[];mode={'value':'normal'}
  def route(r):
   req=r.request
   if not req.url.startswith(BASE+'/'):external.append(req.url);r.abort();return
   if req.url.endswith('/station-config.json'):
    r.fulfill(content_type='application/json',body=json.dumps(CONFIG));return
   if '/network-api/' in req.url:
    requests.append((req.method,req.url))
    assert req.method=='GET','Network page attempted a write'
    if mode['value']=='down':r.fulfill(status=503,body='unavailable');return
    if mode['value']=='invalid':r.fulfill(content_type='application/json',body='{}');return
    data=json.loads(json.dumps(DATA))
    if mode['value']=='live':
     plug=data['devices'][-1];plug.update(state='available',output=False,stale=False,metrics={'powerW':0,'voltageV':120},lastSuccessUnixMs=1)
    r.fulfill(content_type='application/json',body=json.dumps(data));return
   r.continue_()
  context.route('**/*',route)
  page=context.new_page();page.set_default_timeout(8000)
  errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(BASE+'/stations')
  page.get_by_role('button',name='Network devices',exact=False).click()
  expect(page.get_by_role('heading',name='Network devices',exact=True)).to_be_visible()
  expect(page.get_by_role('region',name='ground-poe',exact=True)).to_be_visible()
  assert page.get_by_role('region').count()==7
  expect(page.get_by_role('region',name='shelly-plug-1').get_by_text('Not configured',exact=True)).to_be_visible()
  expect(page.get_by_role('region',name='shelly-plug-1').get_by_text('Relay report: Unknown')).to_be_visible()
  assert page.get_by_role('table').count()==3
  expect(page.get_by_role('region',name='ground-poe').get_by_text('Non-PoE',exact=True)).to_be_visible()
  assert page.get_by_role('button',name='On',exact=True).count()==0
  page.screenshot(path='/private/tmp/crt-network-page-desktop.png',full_page=True)
  mode['value']='live'
  plug=page.get_by_role('region',name='shelly-plug-2')
  expect(plug.get_by_text('Relay report: Off')).to_be_visible()
  expect(plug.get_by_text('Power: 0 W',exact=True)).to_be_visible()
  mode['value']='down'
  expect(page.get_by_role('alert')).to_be_visible()
  expect(plug.get_by_text('Relay report: Unknown')).to_be_visible()
  expect(plug.get_by_text('Power: Unavailable',exact=True)).to_be_visible()
  mode['value']='invalid'
  page.reload();expect(page.get_by_role('alert')).to_be_visible()
  assert page.get_by_role('region').count()==0
  mode['value']='normal'
  page.reload();expect(page.get_by_role('region',name='ground-poe',exact=True)).to_be_visible()
  page.set_viewport_size({'width':390,'height':844})
  page.screenshot(path='/private/tmp/crt-network-page-mobile.png',full_page=True)
  assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),'Horizontal page overflow'
  page.get_by_role('button',name='Back to stations',exact=True).click()
  expect(page.get_by_role('heading',name='Select a Station')).to_be_visible()
  assert all(method=='GET' for method,_ in requests)
  assert not external,external
  assert not errors,errors
  print('Network page: inventory, off/zero versus unknown, outage/malformed response, navigation, mobile and GET-only checks passed.')
 finally:browser.close()
