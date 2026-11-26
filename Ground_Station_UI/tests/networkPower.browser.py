"""Explicit relay UI requests against mocked API only; no device traffic."""
import json
from playwright.sync_api import sync_playwright,expect
BASE='http://127.0.0.1:4173'
TOKEN='fixture-operator-token-at-least-24'
config={'schemaVersion':1,'fillStationWebSocketUrl':None,'grafanaUrl':'/grafana/','fieldMode':True,'map':{'tileUrl':'/tiles/{z}/{x}/{y}.png','tilesConfigured':False}}
device={'id':'plug','kind':'shelly','model':'Fixture plug','address':'192.168.1.120','connectedLoad':'Fixture lamp','state':'available','output':False,'metrics':{'powerW':0},'stale':False,'lastSuccessUnixMs':1,'canSetOutput':True}
snapshot={'schemaVersion':1,'devices':[device],'powerWritesConfigured':True,'operatorAuthorizationRequired':True}
mode={'value':'normal'};writes=[];held=[];hold={'value':False}
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,channel='chrome')
 try:
  context=browser.new_context(viewport={'width':1280,'height':900})
  def route(r):
   request=r.request
   if not request.url.startswith(BASE):raise AssertionError('External request')
   if request.url.endswith('/station-config.json'):r.fulfill(content_type='application/json',body=json.dumps(config));return
   if request.url.endswith('/network-api/v1/wan'):
    r.fulfill(content_type='application/json',body=json.dumps({'enabled':False,'state':'disabled','method':'tcp-connect','checkedUnixMs':None,'ageSeconds':None,'observedFailureSpanSeconds':None,'targets':[]}));return
   if '/network-api/' in request.url:
    if request.method=='POST':
     assert request.url.endswith('/plug/output');assert request.headers['authorization']=='Bearer '+TOKEN
     assert request.post_data_json=={'on':True};writes.append(request.post_data_json)
     if mode['value']=='unknown':r.fulfill(status=503,content_type='application/json',body='{"outcome":"unknown"}');return
     device['output']=True
     r.fulfill(content_type='application/json',body=json.dumps({'requestedOutput':True,'confirmed':True,'observed':{'state':'available','output':True,'metrics':{}}}));return
    assert request.method=='GET'
    if hold['value']:
     held.append((r,json.dumps(snapshot)));return
    if mode['value']=='down':r.fulfill(status=503,body='unavailable');return
    r.fulfill(content_type='application/json',body=json.dumps(snapshot));return
   r.continue_()
  context.route('**/*',route)
  page=context.new_page();page.set_default_timeout(12000);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(BASE+'/network');on=page.get_by_role('button',name='Turn on',exact=True)
  expect(on).to_be_disabled();token=page.get_by_label('Operator token (this page only)');token.fill(TOKEN)
  expect(on).to_be_enabled();on.click();expect(page.get_by_role('dialog')).to_be_visible();assert writes==[]
  page.get_by_role('button',name='Cancel',exact=True).click();assert writes==[]
  on.click();page.get_by_role('button',name='Confirm power request').click()
  expect(page.get_by_text('Relay reported On.',exact=False)).to_be_visible();expect(page.get_by_text('Relay report: On',exact=True)).to_be_visible()
  assert len(writes)==1
  page.get_by_role('button',name='Lock controls').click();expect(token).to_have_value('')
  assert page.evaluate('localStorage.length')==0 and page.evaluate('sessionStorage.length')==0
  device['output']=False;mode['value']='unknown';page.reload();token=page.get_by_label('Operator token (this page only)');token.fill(TOKEN)
  on=page.get_by_role('button',name='Turn on',exact=True);expect(on).to_be_enabled();on.click();page.get_by_role('button',name='Confirm power request').click()
  expect(page.get_by_text('Power outcome unknown.',exact=False)).to_be_visible();expect(token).to_have_value('');expect(on).to_be_disabled()
  page.wait_for_timeout(3300);assert len(writes)==2
  mode['value']='down';expect(page.get_by_role('alert')).to_be_visible();expect(on).to_be_disabled()
  mode['value']='normal';page.reload();expect(token).to_have_value('')
  expect(page.get_by_text('Relay report: Off',exact=True)).to_be_visible();token.fill(TOKEN)
  hold['value']=True;page.wait_for_timeout(3300);assert held
  on.click();page.get_by_role('button',name='Confirm power request').click()
  expect(page.get_by_text('Relay reported On.',exact=False)).to_be_visible()
  hold['value']=False
  for pending_route,old_body in held:pending_route.fulfill(content_type='application/json',body=old_body)
  held.clear()
  expect(page.get_by_text('Relay report: On',exact=True)).to_be_visible();assert len(writes)==3
  device['output']=False;page.reload();expect(page.get_by_text('Relay report: Off',exact=True)).to_be_visible();token.fill(TOKEN)
  on.click();device['connectedLoad']='Different fixture'
  expect(page.get_by_text('Connected load: Different fixture',exact=True)).to_be_visible()
  page.get_by_role('button',name='Confirm power request').click()
  expect(page.get_by_text('Power request cancelled:',exact=False)).to_be_visible();assert len(writes)==3
  page.get_by_role('button',name='Lock controls').click()
  page.set_viewport_size({'width':390,'height':844});page.wait_for_load_state('networkidle')
  page.screenshot(path='/private/tmp/crt-network-power-mobile.png',full_page=True)
  assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
  assert not errors,errors
  print('Network power UI: confirmation/cancel, relay readback, unknown lock/no retry, stale state, pre-write polling race, changed-load cancellation, navigation-memory and mobile passed')
 finally:browser.close()
