"""Optional cached TCP reachability observations, not packet loss or Starlink telemetry."""
from collections import deque
import ipaddress
import math
import socket
import threading
import time

def disabled_status():
    return {'enabled':False,'state':'disabled','method':'tcp-connect','checkedUnixMs':None,
            'ageSeconds':None,'observedFailureSpanSeconds':None,'targets':[]}

def tcp_probe(address,port,timeout):
    start=time.monotonic()
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as peer:
            peer.settimeout(timeout);peer.connect((address,port))
        return {'reachable':True,'connectMs':max(0,time.monotonic()-start)*1000}
    except OSError:return {'reachable':False,'connectMs':None}

class WanMonitor:
    def __init__(self,config,*,probe=tcp_probe,clock=time.monotonic,wall=time.time):
        if not isinstance(config,dict) or set(config)-{'targets','intervalSeconds','timeoutSeconds'}:raise ValueError('Invalid WAN configuration')
        targets=config.get('targets')
        if not isinstance(targets,list) or not 1<=len(targets)<=3:raise ValueError('WAN needs 1..3 explicit targets')
        interval=config.get('intervalSeconds',10);timeout=config.get('timeoutSeconds',1)
        if type(interval) is not int or not 5<=interval<=300:raise ValueError('Invalid WAN interval')
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0.1<=timeout<=3:raise ValueError('Invalid WAN timeout')
        self.targets=[];seen=set()
        for target in targets:
            if not isinstance(target,dict) or set(target)!={'label','address','port'}:raise ValueError('Invalid WAN target')
            try:address=ipaddress.IPv4Address(target['address'])
            except (ValueError,TypeError):raise ValueError('Expected public IPv4 WAN target') from None
            label=target['label'];port=target['port']
            if not address.is_global or address.is_multicast or address.is_reserved:raise ValueError('Expected public unicast IPv4 WAN target')
            if not isinstance(label,str) or not label.strip() or len(label)>80 or not label.isprintable():raise ValueError('Invalid WAN label')
            if type(port) is not int or not 1<=port<=65535:raise ValueError('Invalid WAN target port')
            key=(str(address),port)
            if key in seen:raise ValueError('Duplicate WAN target')
            seen.add(key);self.targets.append({'label':label,'address':str(address),'port':port})
        self.interval=interval;self.timeout=timeout;self.probe=probe;self.clock=clock;self.wall=wall
        self.samples=deque(maxlen=30);self.checked=None;self.checked_unix=None;self.failed_since=None
        self.lock=threading.Lock();self.stop_event=threading.Event();self.thread=None

    def tick(self):
        # No monitor lock during network I/O; API snapshot reads remain local.
        observations=[self.probe(target['address'],target['port'],self.timeout) for target in self.targets]
        for row in observations:
            if not isinstance(row,dict) or type(row.get('reachable')) is not bool:raise ValueError('Invalid WAN observation')
            timing=row.get('connectMs')
            if row['reachable'] and (type(timing) not in (int,float) or not math.isfinite(timing) or timing<0):raise ValueError('Invalid WAN timing')
            if not row['reachable'] and timing is not None:raise ValueError('Failed probe cannot claim connection timing')
        checked=self.clock()
        with self.lock:
            self.samples.append(observations);self.checked=checked;self.checked_unix=int(self.wall()*1000)
            if any(row['reachable'] for row in observations):self.failed_since=None
            elif self.failed_since is None:self.failed_since=checked

    def snapshot(self):
        with self.lock:
            age=None if self.checked is None else max(0,self.clock()-self.checked)
            stale=age is not None and age>self.interval+len(self.targets)*self.timeout+5
            latest=self.samples[-1] if self.samples else None
            state=('pending' if latest is None else 'stale' if stale else
                   'reachable' if any(row['reachable'] for row in latest) else 'unreachable')
            reports=[]
            for index,target in enumerate(self.targets):
                rows=[sample[index] for sample in self.samples]
                failures=sum(not row['reachable'] for row in rows)
                times=[row['connectMs'] for row in rows if row['reachable']]
                reports.append({**target,'reachable':None if not latest or stale else latest[index]['reachable'],
                    'connectMs':None if not latest or stale else latest[index]['connectMs'],
                    'attempts':len(rows),'failures':failures,'failureFraction':failures/len(rows) if rows else None,
                    'meanSuccessfulConnectMs':sum(times)/len(times) if times else None})
            span=None if stale or self.failed_since is None else max(0,self.checked-self.failed_since)
            return {'enabled':True,'state':state,'method':'tcp-connect','checkedUnixMs':self.checked_unix,
                    'ageSeconds':age,'observedFailureSpanSeconds':span,'targets':reports}

    def start(self):
        if self.thread is not None:raise RuntimeError('WAN monitor already started')
        def loop():
            while not self.stop_event.is_set():
                try:self.tick()
                except Exception:pass  # Do not manufacture failed observations; old data becomes stale.
                self.stop_event.wait(self.interval)
        self.thread=threading.Thread(target=loop,name='wan-probes',daemon=True);self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=len(self.targets)*self.timeout+1)
