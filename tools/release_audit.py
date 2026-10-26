"""Review the exact Git index without printing any matched credential values."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

FIRST='This project was submitted to the ryze.ai hackathon by Rahmat Ullah.'
FORBIDDEN=('handoffs/','tasks/','research/','test-output/','output/','models/','.venv/','node_modules/',
           '.playwright-cli/','.pytest_cache/','__pycache__/')
ROOT_PRIVATE={'AGENTS.md','BUILD_PLAN.md','RESEARCH_NOTES.md','SayTheMath-improvement-brief.md','requirements-research.txt'}
PNG={'tests/integration/fraction.png','tests/integration/root-power.png','tests/integration/integral.png'}
HIGH=re.compile(r'sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]+|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----')
GENERIC=re.compile(r'''(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*["'][^"']{8,}''')
PRIVATE_PATH=re.compile(r'[A-Za-z]:[\\/]Users[\\/]|/[U]sers/[^/]+/')


def git(*args):
    return subprocess.check_output(['git',*args])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path)
    args=parser.parse_args()
    paths=git('ls-files','-z').decode().split('\0')[:-1]
    blobs={path:git('show',':'+path) for path in paths}
    findings=[];manifest=[]
    for path,data in blobs.items():
        p=PurePosixPath(path)
        if path.startswith(FORBIDDEN) or path in ROOT_PRIVATE or '__pycache__' in p.parts:
            findings.append({'file':path,'issue':'excluded path'})
        if p.name.startswith('.env') or p.suffix.lower() in {'.pem','.key','.p12','.pfx','.pth','.pt','.ckpt','.safetensors','.pdf','.xml','.log','.docx','.xlsx','.pptx','.pyc'}:
            findings.append({'file':path,'issue':'excluded file type'})
        if len(data)>2_000_000:
            findings.append({'file':path,'issue':'unexpectedly large file'})
        if path in PNG:
            if not data.startswith(b'\x89PNG\r\n\x1a\n'):
                findings.append({'file':path,'issue':'invalid authored PNG'})
        else:
            try:
                text=data.decode('utf-8')
            except UnicodeDecodeError:
                findings.append({'file':path,'issue':'unreviewed binary'});continue
            for line_number,line in enumerate(text.splitlines(),1):
                if HIGH.search(line) or GENERIC.search(line):
                    findings.append({'file':path,'line':line_number,'issue':'credential pattern; value omitted'})
                if PRIVATE_PATH.search(line):
                    findings.append({'file':path,'line':line_number,'issue':'personal filesystem path'})
            if p.suffix=='.md':
                for link in re.findall(r'\]\(([^)]+)\)',text):
                    if '://' in link or link.startswith('#'):
                        continue
                    # Repository-relative Markdown links must resolve within the index.
                    target=p.parent/link.split('#',1)[0]
                    parts=[]
                    for part in target.parts:
                        if part=='..':
                            if parts: parts.pop()
                        elif part!='.': parts.append(part)
                    if '/'.join(parts) not in blobs:
                        findings.append({'file':path,'issue':'missing public documentation link','target':link})
        manifest.append({'path':path,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    if not blobs.get('README.md',b'').splitlines() or blobs['README.md'].splitlines()[0]!=FIRST.encode():
        findings.append({'file':'README.md','issue':'required first line mismatch or BOM'})
    hashes=('a63d9141c53d266cb682fb5a8bd83bd5cbe283145e0e78ebdc0f895195a1dfaa',
            '1c3820659985ad142b526490bb25c23d977176ac2073591b3bddada692718458')
    for digest in hashes:
        if any(digest.encode() not in blobs.get(path,b'') for path in ('README.md','recognition/config.py','THIRD_PARTY_NOTICES.md')):
            findings.append({'file':'README.md','issue':'checkpoint hash documentation mismatch'})
    if args.manifest:
        args.manifest.parent.mkdir(parents=True,exist_ok=True)
        args.manifest.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'files':len(paths),'bytes':sum(len(d) for d in blobs.values()),'findings':findings,
                      'scope':'staged text, allowlisted authored PNGs, exclusions, README, hashes and Markdown links'}))
    return bool(findings)


if __name__=='__main__':
    raise SystemExit(main())
