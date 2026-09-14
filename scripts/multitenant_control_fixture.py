"""Internal-only authorization fault injection for the disposable browser proof."""
import json,os,subprocess,sys
from http.server import BaseHTTPRequestHandler,HTTPServer
assert os.environ.get('MULTITENANT_PROOF')=='disposable'
allowed={'disable','enable','user-disable','user-enable','access-disable','enhancement-disable','restore-services',
 'downgrade','restore-role','membership-remove','membership-restore','mapping-suspend','mapping-restore'}
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  try:
   data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
   assert self.path=='/control' and data['action'] in allowed and data['index'] in [0,1,2]
   result=subprocess.run([sys.executable,'/app/scripts/multitenant_runtime_proof.py',data['action'],str(data['index'])],capture_output=True)
   assert result.returncode==0
   self.send_response(200);self.end_headers();self.wfile.write(b'{"ok":true}')
  except Exception:self.send_response(400);self.end_headers()
HTTPServer(('0.0.0.0',9100),Handler).serve_forever()
