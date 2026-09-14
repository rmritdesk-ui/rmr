"""Final proof ingress config only: TLS edge -> shipped trusted frontend -> backend."""
import os,sys
from pathlib import Path
assert os.environ.get('MULTITENANT_PROOF')=='disposable'
root=Path('/proof')
path=root/'nginx.conf'
content=path.read_text()
start=content.index('    root /proof/piq-dist;')
end=content.index('\n  }',start)
content=content[:start]+'''    location / {
      proxy_pass http://final-frontend:80;
      proxy_set_header Host piq.test;
      proxy_set_header X-Forwarded-Proto https;
      proxy_set_header X-Forwarded-For $remote_addr;
    }'''+content[end:]
path.write_text(content)
print('Final fixture ingress configured; no keys or installed configuration changed')
