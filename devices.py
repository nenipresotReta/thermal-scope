"""Read-only LAN discovery for the Thermal Scope firmware's HTTP/Modbus contract."""
import concurrent.futures,http.client,ipaddress,json,math,socket,struct,threading

PRIVATE_NETWORKS=tuple(ipaddress.IPv4Network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))
def validate_host(value):
    try:address=ipaddress.IPv4Address(str(value).strip())
    except ipaddress.AddressValueError:raise ValueError('Enter an IPv4 address, for example 192.168.1.100') from None
    if not (any(address in network for network in PRIVATE_NETWORKS) or address.is_loopback):
        raise ValueError('Use a private LAN IPv4 address')
    return str(address)

def scan_network(value):
    try:network=ipaddress.IPv4Network(str(value).strip(),strict=False)
    except (ValueError,TypeError):raise ValueError('Enter a private network, for example 192.168.1.0/24') from None
    if network.prefixlen<24 or not any(network.subnet_of(n) for n in PRIVATE_NETWORKS):
        raise ValueError('Choose a private subnet of /24 or smaller (at most 256 addresses)')
    return network

def suggested_networks(host=''):
    addresses=[host]
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            # Route lookup only: no packet is sent.
            sock.connect(('192.0.2.1',9));addresses.append(sock.getsockname()[0])
    except OSError:pass
    result=[]
    for address in addresses:
        try:
            ip=ipaddress.IPv4Address(address)
            if any(ip in n for n in PRIVATE_NETWORKS):
                subnet=str(ipaddress.IPv4Network(f'{ip}/24',strict=False))
                if subnet not in result:result.append(subnet)
        except ValueError:pass
    return result

def receive(sock,count):
    data=b''
    while len(data)<count:
        chunk=sock.recv(count-len(data))
        if not chunk:raise OSError('Connection closed')
        data+=chunk
    return data

def probe_device(host,timeout=.7,require_http=False,http_port=80,modbus_port=502):
    host=validate_host(host);metadata=None
    connection=http.client.HTTPConnection(host,http_port,timeout=timeout)
    try:
        connection.request('GET','/api/temperature',headers={'Connection':'close'})
        response=connection.getresponse();body=response.read(4097)
        if response.status==200 and len(body)<=4096:
            obj=json.loads(body)
            fields=('valid','derivatives_ready','time_s','raw_c','temperature_c','d1_c_per_s','d2_c_per_s2')
            if isinstance(obj,dict) and all(k in obj for k in fields) and isinstance(obj['valid'],bool) and isinstance(obj['derivatives_ready'],bool):metadata=obj
    except (OSError,ValueError,http.client.HTTPException):pass
    finally:connection.close()
    if require_http and metadata is None:raise ValueError('No compatible Thermal Scope HTTP endpoint')
    try:
        with socket.create_connection((host,modbus_port),timeout) as sock:
            sock.settimeout(timeout);sock.sendall(struct.pack('>HHHBBHH',18761,0,6,1,3,0,8))
            transaction,protocol,length,unit=struct.unpack('>HHHB',receive(sock,7))
            if (transaction,protocol,unit)!=(18761,0,1) or not 2<=length<=254:raise ValueError('Invalid Modbus response')
            body=receive(sock,length-1)
            if body==b'\x83\x04' and metadata is not None:
                return {'host':host,'compatible':True,'status':'SENSOR NOT READY','temperature_c':None,'http_verified':True}
            if len(body)!=18 or body[:2]!=b'\x03\x10':raise ValueError('Expected four Float32 values at registers 0–7')
            values=struct.unpack('>ffff',body[2:])
            if not all(math.isfinite(x) for x in values):raise ValueError('Device returned non-finite measurements')
            return {'host':host,'compatible':True,'status':'READY','temperature_c':values[1],'http_verified':metadata is not None}
    except (OSError,struct.error) as error:raise ValueError('No compatible Modbus response at '+host+':502') from error

class Discovery:
    def __init__(self):
        self.lock=threading.Lock();self.state={'running':False,'network':'','checked':0,'total':0,'devices':[],'error':None}
    def status(self):
        with self.lock:return {**self.state,'devices':[dict(d) for d in self.state['devices']]}
    def start(self,network):
        network=scan_network(network);hosts=[str(h) for h in network.hosts()]
        with self.lock:
            if self.state['running']:return {**self.state,'devices':[dict(d) for d in self.state['devices']]}
            self.state={'running':True,'network':str(network),'checked':0,'total':len(hosts),'devices':[],'error':None}
        threading.Thread(target=self._scan,args=(hosts,),daemon=True).start()
        return self.status()
    def _scan(self,hosts):
        def check(host):
            try:return probe_device(host,timeout=.35,require_http=True)
            except (ValueError,OSError):return None
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                for result in pool.map(check,hosts):
                    with self.lock:
                        self.state['checked']+=1
                        if result:self.state['devices'].append(result)
        except Exception as error:
            with self.lock:self.state['error']=str(error)
        finally:
            with self.lock:self.state['running']=False
