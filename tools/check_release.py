#!/usr/bin/env python3
"""Audit only Git-tracked application source. Never print matched secret values."""
import pathlib,re,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
DENIED_SUFFIXES={'.bin','.elf','.hex','.uf2','.sqlite','.sqlite3','.db','.csv','.log','.png','.jpg','.jpeg','.zip','.pyc'}
DENIED_DIRS={'data','verification','firmware','backups','build','local','__pycache__'}
PATTERNS=[
 re.compile(r'gh[pousr]_[A-Za-z0-9]{30,}'),
 re.compile(r'github_pat_[A-Za-z0-9_]{30,}'),
 re.compile(r'^-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',re.M),
 re.compile(r'''(?i)\bWIFI_(?:PASSWORD|PSK|SSID)\s*[:=]\s*["'][^"'\r\n]+["']'''),
]
def main():
 names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0');errors=[];checked=0
 for name in filter(None,names):
  path=pathlib.PurePosixPath(name)
  if path.suffix.lower() in DENIED_SUFFIXES or any(p in DENIED_DIRS or p.startswith('build-') for p in path.parts) or 'wifi_credentials' in name.lower() or path.name.startswith('.env') and path.name!='.env.example':
   errors.append(name+': excluded runtime/firmware artifact');continue
  raw=(ROOT/name).read_bytes();checked+=1
  if b'\0' in raw:errors.append(name+': binary content is not allowed');continue
  try:text=raw.decode('utf-8')
  except UnicodeDecodeError:errors.append(name+': non-text content is not allowed');continue
  if any(p.search(text) for p in PATTERNS):errors.append(name+': potential credential content')
 if errors:
  print('\n'.join(errors),file=sys.stderr);return 1
 if not checked:print('No tracked source files found',file=sys.stderr);return 1
 print(f'PASS: {checked} tracked text files; no firmware, runtime data or detected credentials')
 return 0
if __name__=='__main__':raise SystemExit(main())
