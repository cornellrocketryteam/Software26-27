"""Preliminary local Shelly Gen2+ RPC adapter; no discovery or background writes."""
import hashlib
import ipaddress
import json
import math
import urllib.request


class UnknownOutcome(RuntimeError):
    """A power request or its read-back failed. Never automatically retry it."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _Digest(urllib.request.HTTPDigestAuthHandler):
    # Keep SHA-256 support consistent across Python versions shipped by Nix.
    def get_algorithm_impls(self, algorithm):
        if algorithm == 'SHA-256':
            def h(value):
                return hashlib.sha256(value.encode('ascii')).hexdigest()
            return h, lambda secret, data: h(secret + ':' + data)
        return super().get_algorithm_impls(algorithm)


def http_transport(address, *, username=None, password=None, timeout=3):
    """Bounded HTTP RPC; proxies and redirects are disabled; credentials stay here."""
    base='http://' + address + '/rpc'
    handlers=[urllib.request.ProxyHandler({}), _NoRedirect()]
    if password is not None:
        passwords=urllib.request.HTTPPasswordMgrWithDefaultRealm()
        passwords.add_password(None,base,username or 'admin',password)
        handlers.append(_Digest(passwords))
    opener=urllib.request.build_opener(*handlers)
    def send(method, params):
        body=json.dumps({'id':1,'src':'crt-ground-station','method':method,'params':params}).encode()
        request=urllib.request.Request(base,data=body,headers={'Content-Type':'application/json'},method='POST')
        with opener.open(request,timeout=timeout) as response:
            raw=response.read(65537)
        if len(raw)>65536:
            raise ValueError('Shelly response exceeds size limit')
        result=json.loads(raw)
        if (not isinstance(result,dict) or type(result.get('id')) is not int or result['id']!=1
                or 'error' in result or not isinstance(result.get('result'),dict)):
            raise ValueError('Shelly returned an invalid or unsuccessful RPC response')
        return result['result']
    return send


class ShellyDevice:
    def __init__(self, config, *, transport=None, username=None, password=None):
        if type(config.get('enabled',False)) is not bool:
            raise ValueError('enabled must be boolean')
        self.enabled=config.get('enabled',False)
        self.component=config.get('componentId',0)
        if type(self.component) is not int or self.component<0:
            raise ValueError('componentId must be a nonnegative integer')
        self.transport=None
        if not self.enabled:
            return
        address=config.get('address')
        try:
            parsed=ipaddress.IPv4Address(address) if isinstance(address,str) else None
        except ipaddress.AddressValueError:
            parsed=None
        if (parsed is None or not parsed.is_private or parsed.is_loopback or parsed.is_link_local
                or parsed.is_multicast or parsed.is_unspecified or parsed.is_reserved):
            raise ValueError('enabled Shelly requires an explicit private IPv4 address')
        self.transport=transport or http_transport(str(parsed),username=username,password=password)

    def status(self):
        if not self.enabled:
            return {'state':'not_configured','output':None,'metrics':{}}
        result=self.transport('Switch.GetStatus',{'id':self.component})
        if not isinstance(result,dict) or type(result.get('output')) is not bool:
            raise ValueError('Shelly response has no boolean output state')
        metrics={}
        energy=result.get('aenergy')
        values={key:result.get(key) for key in ('apower','voltage','current')}
        values['energy']=energy.get('total') if isinstance(energy,dict) else None
        for key,label in [('apower','powerW'),('voltage','voltageV'),('current','currentA'),('energy','energyWh')]:
            value=values[key]
            if type(value) in (int,float) and math.isfinite(value):
                metrics[label]=value
        return {'state':'available','output':result['output'],'metrics':metrics}

    def set_output(self,on):
        if not self.enabled or type(on) is not bool:
            raise ValueError('power writes require an enabled device and explicit boolean state')
        try:
            self.transport('Switch.Set',{'id':self.component,'on':on})
            observed=self.status()
        except Exception as exc:
            # Preserve no raw device response or authentication details in the UI.
            raise UnknownOutcome('Power request outcome unknown; read current state before another request') from exc
        return {'requestedOutput':on,'confirmed':observed['output'] is on,'observed':observed}
