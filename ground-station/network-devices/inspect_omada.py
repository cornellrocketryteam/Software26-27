"""Explicit read-only management reachability inspection; never a control adapter."""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import socket
import ssl
import time

PRIVATE_NETWORKS=tuple(ipaddress.ip_network(value) for value in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))
ID=re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')


def targets(inventory):
    if not isinstance(inventory,dict) or inventory.get('schemaVersion')!=1 or not isinstance(inventory.get('devices'),list):
        raise ValueError('Invalid inventory schema')
    result=[];seen=set()
    for device in inventory['devices']:
        if not isinstance(device,dict):raise ValueError('Invalid inventory entry')
        if device.get('kind') not in ('omada-switch','omada-bridge'):continue
        name=device.get('id')
        if not isinstance(name,str) or not ID.fullmatch(name) or name in seen:raise ValueError('Invalid or duplicate device ID')
        seen.add(name)
        try:address=ipaddress.IPv4Address(device.get('address'))
        except (ValueError,TypeError):raise ValueError('Expected private IPv4 inventory address') from None
        if not any(address in network for network in PRIVATE_NETWORKS):raise ValueError('Expected private IPv4 inventory address')
        result.append({'id':name,'address':str(address),'kind':device['kind']})
    if len(result)>5:raise ValueError('Inspection supports at most five recorded Omada devices')
    return result


def probe_endpoint(address,scheme,*,timeout=2,socket_factory=socket.create_connection):
    """One root GET; bounded headers, total deadline, no authentication/redirects.

    HTTPS inspects self-signed certificates without authenticating the peer.
    Verify fingerprints independently before using any future login adapter.
    """
    if scheme not in ('http','https'):raise ValueError('Invalid inspection scheme')
    connection=None
    deadline=time.monotonic()+timeout
    def remaining():
        value=deadline-time.monotonic()
        if value<=0:raise TimeoutError()
        return value
    try:
        connection=socket_factory((address,443 if scheme=='https' else 80),remaining())
        fingerprint=None
        if scheme=='https':
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname=False
            context.verify_mode=ssl.CERT_NONE
            connection.settimeout(remaining())
            connection=context.wrap_socket(connection,server_hostname=address)
            certificate=connection.getpeercert(binary_form=True)
            fingerprint=hashlib.sha256(certificate).hexdigest() if certificate else None
        connection.settimeout(remaining())
        connection.sendall(f'GET / HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\nUser-Agent: CRT-read-only-inspection/1\r\n\r\n'.encode('ascii'))
        headers=b''
        while b'\r\n\r\n' not in headers:
            connection.settimeout(remaining())
            chunk=connection.recv(min(4096,16384-len(headers)))
            if not chunk:raise ValueError('Incomplete or oversized headers')
            headers+=chunk
            if len(headers)>=16384 and b'\r\n\r\n' not in headers:raise ValueError('Oversized headers')
        status=re.fullmatch(rb'HTTP/1\.[01] ([1-5][0-9]{2})(?: [^\r\n]*)?',headers.split(b'\r\n',1)[0])
        if status is None:raise ValueError('Invalid response')
        code=int(status[1])
        result={'state':'http_response','status':code,'redirect':300<=code<400}
        if scheme=='https':result.update(certificateSha256=fingerprint,certificateVerified=False)
        return result
    except (TimeoutError,socket.timeout):return {'state':'unavailable','error':'timeout'}
    except ssl.SSLError:return {'state':'unavailable','error':'tls_error'}
    except (OSError,ValueError):return {'state':'unavailable','error':'connection_or_protocol_error'}
    finally:
        if connection is not None:connection.close()


def inspect(inventory,*,probe=False):
    devices=targets(inventory) # Validate the entire list before opening any connection.
    report={'schemaVersion':1,'probed':bool(probe),'authenticated':False,'powerWritesEnabled':False,'devices':[]}
    for device in devices:
        item={**device,'endpoints':[f'{scheme}://{device["address"]}/' for scheme in ('http','https')]}
        if probe:item['observations']=[{'scheme':scheme,**probe_endpoint(device['address'],scheme)} for scheme in ('http','https')]
        report['devices'].append(item)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory',type=Path,default=Path(__file__).with_name('inventory.json'))
    parser.add_argument('--probe',action='store_true',help='contact only recorded HTTP/HTTPS endpoints; default prints a plan')
    args=parser.parse_args(argv)
    try:report=inspect(json.loads(args.inventory.read_text()),probe=args.probe)
    except (OSError,ValueError):parser.exit(1,'Invalid or unreadable Omada inventory\n')
    print(json.dumps(report,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
