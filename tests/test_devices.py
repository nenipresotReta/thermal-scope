import json,socket,struct,tempfile,threading,time,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from devices import validate_host,scan_network,probe_device,Discovery
from server import Scope,Store,receive

class ValidationTest(unittest.TestCase):
 def test_private_ip_and_subnet_bounds(self):
  self.assertEqual(validate_host(' 192.168.1.100 '),'192.168.1.100')
  for host in ('8.8.8.8','http://192.168.1.1','host.invalid','192.168.1.1:502','::1'):
   with self.assertRaises(ValueError):validate_host(host)
  self.assertEqual(str(scan_network('192.168.1.100/24')),'192.168.1.0/24')
  for net in ('192.168.0.0/16','8.8.8.0/24','127.0.0.0/24','invalid'):
   with self.assertRaises(ValueError):scan_network(net)

class ProbeTest(unittest.TestCase):
 def setUp(self):
  outer=self;self.http_match=True;self.warming=False
  class Fixture(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    obj={'valid':True,'derivatives_ready':True,'time_s':12,'raw_c':25,'temperature_c':25,'d1_c_per_s':0,'d2_c_per_s2':0} if outer.http_match else {'ordinary':'web server'}
    body=json.dumps(obj).encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
  self.http=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=self.http.serve_forever,daemon=True).start()
  self.listener=socket.socket();self.listener.bind(('127.0.0.1',0));self.listener.listen();self.listener.settimeout(.2);self.stop=threading.Event()
  def modbus():
   while not self.stop.is_set():
    try:client,_=self.listener.accept()
    except socket.timeout:continue
    with client:
     try:
      client.settimeout(1);q=receive(client,12);tid=struct.unpack('>H',q[:2])[0]
      body=b'\x83\x04' if self.warming else b'\x03\x10'+struct.pack('>ffff',25,25,.1,.01)
      reply=struct.pack('>HHHB',tid,0,len(body)+1,1)+body
      client.sendall(reply[:5]);client.sendall(reply[5:])
     except OSError:pass
  self.thread=threading.Thread(target=modbus,daemon=True);self.thread.start()
 def tearDown(self):
  self.http.shutdown();self.http.server_close();self.stop.set();self.thread.join(2);self.listener.close()
 def probe(self,**kw):return probe_device('127.0.0.1',http_port=self.http.server_port,modbus_port=self.listener.getsockname()[1],**kw)
 def test_dual_protocol_and_warmup_detection(self):
  info=self.probe(require_http=True);self.assertEqual(info['temperature_c'],25);self.assertTrue(info['http_verified'])
  self.warming=True;info=self.probe(require_http=True);self.assertEqual(info['status'],'SENSOR NOT READY')
 def test_ordinary_http_service_not_discovered(self):
  self.http_match=False
  with self.assertRaises(ValueError):self.probe(require_http=True)
  self.assertFalse(self.probe()['http_verified'])

class ConfigurationTest(unittest.TestCase):
 def test_saved_address_and_failed_probe_does_not_change_selection(self):
  with tempfile.TemporaryDirectory() as directory:
   scope=Scope(Store(Path(directory)/'db'),'192.168.1.10',.1)
   with patch('server.probe_device',return_value={'host':'192.168.1.11','compatible':True,'status':'READY','temperature_c':25}):
    result=scope.configure_device({'action':'connect','host':'192.168.1.11'})
   self.assertTrue(result['saved']);self.assertEqual(scope.host,'192.168.1.11');self.assertEqual(scope.source_revision,1)
   self.assertEqual(json.loads((Path(directory)/'device.json').read_text())['host'],scope.host)
   with patch('server.probe_device',side_effect=ValueError('not reachable')):
    with self.assertRaises(ValueError):scope.configure_device({'action':'connect','host':'192.168.1.12'})
   self.assertEqual(scope.host,'192.168.1.11')
 def test_do_not_switch_during_recording(self):
  with tempfile.TemporaryDirectory() as directory:
   scope=Scope(Store(Path(directory)/'db'),'192.168.1.10',.1);scope.action({'action':'start'})
   with patch('server.probe_device',return_value={}):
    with self.assertRaises(ValueError):scope.configure_device({'action':'connect','host':'192.168.1.11'})
   self.assertEqual(scope.host,'192.168.1.10')
 def test_reselecting_same_device_is_safe_during_recording(self):
  with tempfile.TemporaryDirectory() as directory:
   scope=Scope(Store(Path(directory)/'db'),'192.168.1.10',.1);scope.action({'action':'start'})
   with patch('server.probe_device',return_value={'host':'192.168.1.10'}):
    result=scope.configure_device({'action':'connect','host':'192.168.1.10'})
   self.assertTrue(result['saved']);self.assertEqual(scope.source_revision,0)
 def test_discovery_bounded_and_returns_compatible_devices(self):
  with patch('devices.probe_device',return_value={'host':'192.168.1.100','compatible':True,'status':'READY','temperature_c':25}):
   discovery=Discovery();discovery.start('192.168.1.100/32')
   deadline=time.monotonic()+2
   while discovery.status()['running'] and time.monotonic()<deadline:time.sleep(.01)
   state=discovery.status();self.assertEqual(state['checked'],1);self.assertEqual(len(state['devices']),1)
if __name__=='__main__':unittest.main()
