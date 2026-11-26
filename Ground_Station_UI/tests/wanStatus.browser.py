"""WAN UI and local-control independence; only mocked local HTTP."""
import json
from playwright.sync_api import sync_playwright,expect
expect.set_options(timeout=12000)
BASE='http://127.0.0.1:4173'
CONFIG={'schemaVersion':1,'fillStationWebSocketUrl':None,'grafanaUrl':'/grafana/','fieldMode':True,'map':{'tileUrl':'/tiles/{z}/{x}/{y}.png','tilesConfigured':False}}
DEVICE={'id':'plug','kind':'shelly','model':'Fixture plug','address':'192.168.1.120','connectedLoad':'Fixture lamp','state':'available','output':False,'metrics':{},'stale':False,'lastSuccessUnixMs':1,'canSetOutput':True}
DATA={'schemaVersion':1,'devices':[DEVICE],'powerWritesConfigured':True,'operatorAuthorizationRequired':True}
TARGET={'label':'External fixture','address':'1.1.1.1','port':443,'reachable':True,'connectMs':0,'attempts':1,'failures':0,'failureFraction':0,'meanSuccessfulConnectMs':0}
WAN={'enabled':True,'state':'reachable','method':'tcp-connect','checkedUnixMs':1,'ageSeconds':0,'observedFailureSpanSeconds':None,'targets':[TARGET]}
mode={'value':'normal'}
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,channel='chrome')
 try:
  context=browser.new_context(viewport={'width':1440,'height':1000})
  def route(r):
   request=r.request
   assert request.url.startswith(BASE),'External network request'
   assert request.method=='GET','Unexpected write'
   if request.url.endswith('/station-config.json'):r.fulfill(content_type='application/json',body=json.dumps(CONFIG));return
   if request.url.endswith('/network-api/v1/devices'):r.fulfill(content_type='application/json',body=json.dumps(DATA));return
   if request.url.endswith('/network-api/v1/wan'):
    if mode['value']=='api-down':r.fulfill(status=503,body='unavailable');return
    value=json.loads(json.dumps(WAN))
    if mode['value']=='failed':
     value.update(state='unreachable',observedFailureSpanSeconds=10)
     value['targets'][0].update(reachable=False,connectMs=None,attempts=2,failures=1,failureFraction=0.5)
    if mode['value']=='stale':
     value.update(state='stale',ageSeconds=100);value['targets'][0].update(reachable=None,connectMs=None)
    r.fulfill(content_type='application/json',body=json.dumps(value));return
   r.continue_()
  context.route('**/*',route)
  page=context.new_page();page.set_default_timeout(12000);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(BASE+'/network');expect(page.get_by_text('At least one TCP connection succeeded',exact=True)).to_be_visible()
  expect(page.get_by_text('Last TCP connect: 0.0 ms',exact=True)).to_be_visible()
  page.get_by_label('Operator token (this page only)').fill('fixture-operator-token-at-least-24')
  on=page.get_by_role('button',name='Turn on',exact=True);expect(on).to_be_enabled()
  mode['value']='failed';expect(page.get_by_text('No TCP connections succeeded',exact=True)).to_be_visible()
  expect(page.get_by_text('Recent probe failures: 1/2',exact=True)).to_be_visible();expect(on).to_be_enabled()
  mode['value']='stale';expect(page.get_by_text('Probe observations are stale',exact=True)).to_be_visible()
  expect(page.get_by_text('Last TCP connect: Unavailable',exact=True)).to_be_visible();expect(on).to_be_enabled()
  mode['value']='api-down';expect(page.get_by_text('Monitoring unavailable',exact=True)).to_be_visible();expect(on).to_be_enabled()
  mode['value']='normal';expect(page.get_by_text('At least one TCP connection succeeded',exact=True)).to_be_visible()
  page.get_by_role('button',name='Lock controls').click()
  page.screenshot(path='/private/tmp/crt-wan-desktop.png',full_page=True)
  page.set_viewport_size({'width':390,'height':844});page.wait_for_load_state('networkidle')
  assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
  page.screenshot(path='/private/tmp/crt-wan-mobile.png',full_page=True)
  assert not errors,errors
  print('WAN UI: zero timing, failed/stale/unavailable/recovery, independent Shelly eligibility and mobile passed')
 finally:browser.close()
