"""Export reviewed source changes with base hashes; optionally compare live main.

Does not modify any checkout or Git metadata. Remote files and clean three-way
merges are written only inside a new review directory, never onto production.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from package_static_data import ROOT,canonical,digest,valid_path,workspace_directory

PREFIXES=('.github/workflows/','scripts/','shared/','config/','tests/','frontend/src/','frontend/tests/','frontend/build/','automation/','docs/')
EXACT={'.gitignore','frontend/package.json','frontend/vite.config.ts'}


def git(*args):
    return subprocess.check_output(['git','-c','safe.directory='+ROOT.as_posix(),'-c','core.safecrlf=false','-C',ROOT.as_posix(),*args])


def export(output,repository=None):
    paths=set(git('diff','--name-only','--diff-filter=ACMRT','HEAD').decode().splitlines())
    paths.update(git('ls-files','--others','--exclude-standard').decode().splitlines())
    if any(path not in EXACT and not path.startswith(PREFIXES) for path in paths): raise ValueError('Unexpected files in source review; inspect before exporting')
    output=Path(output).resolve()
    if output==ROOT or output.is_relative_to(ROOT/'frontend') or output.is_relative_to(ROOT/'scripts'): raise ValueError('Keep review output separate from source')
    output.mkdir(parents=True,exist_ok=True)
    folder=workspace_directory(output, 'source-review-')
    report={'schema_version':1,'created_at':datetime.now(timezone.utc).isoformat(),'base_commit':git('rev-parse','HEAD').decode().strip(),'directory':str(folder),'files':[]}
    remote_sha=None
    if repository:
        if not re.fullmatch(r'[\w.-]+/[\w.-]+',repository): raise ValueError('Invalid repository')
        req=urllib.request.Request(f'https://api.github.com/repos/{repository}/commits/main',headers={'User-Agent':'stock-study-read-only-review'})
        with urllib.request.urlopen(req,timeout=20) as response: remote_sha=json.load(response)['sha']
        report.update(remote_repository=repository,remote_commit=remote_sha)
    def row(path):
        check_path=path.removeprefix('.github/') if path.startswith('.github/workflows/') else path
        if path!='.gitignore' and not valid_path(check_path): raise ValueError('Invalid reviewed path')
        source=ROOT/path
        if source.is_symlink() or not source.is_file() or source.stat().st_size>5*1024*1024: raise ValueError('Unexpected source artifact')
        proposed=source.read_bytes()
        base=subprocess.run(['git','-c','safe.directory='+ROOT.as_posix(),'-C',ROOT.as_posix(),'show','HEAD:'+path],capture_output=True)
        base_raw=base.stdout if base.returncode==0 else None
        item={'path':path,'base_sha256':digest(base_raw) if base_raw is not None else None,'proposed_sha256':digest(proposed)}
        for kind,raw in [('proposed',proposed),('base',base_raw)]:
            if raw is not None:
                destination=folder/kind/path; destination.parent.mkdir(parents=True,exist_ok=True); destination.write_bytes(raw)
        if remote_sha:
            req=urllib.request.Request(f'https://raw.githubusercontent.com/{repository}/{remote_sha}/{path}',headers={'User-Agent':'stock-study-read-only-review'})
            try:
                with urllib.request.urlopen(req,timeout=20) as response: remote=response.read()
            except urllib.error.HTTPError as exc:
                if exc.code!=404: raise
                remote=None
            item['remote_sha256']=digest(remote) if remote is not None else None
            if remote is not None:
                target=folder/'remote'/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(remote)
            merged=None
            if remote==base_raw: item['integration']='base_unchanged'; merged=proposed
            elif remote==proposed: item['integration']='already_present'; merged=proposed
            elif remote is None or base_raw is None: item['integration']='conflict_add_delete'
            else:
                merge=subprocess.run(['git','merge-file','-p',str(folder/'remote'/path),str(folder/'base'/path),str(folder/'proposed'/path)],capture_output=True)
                if merge.returncode==0: item['integration']='clean_three_way'; merged=merge.stdout
                else: item['integration']='conflict'; conflict=folder/'conflicts'/path; conflict.parent.mkdir(parents=True,exist_ok=True); conflict.write_bytes(merge.stdout)
            if merged is not None:
                target=folder/'integrated'/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(merged); item['integrated_sha256']=digest(merged)
        return item
    with ThreadPoolExecutor(max_workers=8) as pool: report['files']=list(pool.map(row,sorted(paths)))
    report['conflicts']=[row['path'] for row in report['files'] if row.get('integration','').startswith('conflict')]
    report['complete_source_integration_review']=bool(remote_sha) and not report['conflicts']
    (folder/'inventory.json').write_bytes(canonical(report))
    (output/'latest-source-review.json').write_bytes(canonical({'directory':str(folder),'remote_commit':remote_sha}))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--output',type=Path,required=True); parser.add_argument('--remote-repository')
    args=parser.parse_args(); value=export(args.output,args.remote_repository)
    print(json.dumps({key:value[key] for key in value if key!='files'})); print(f"Source files reviewed: {len(value['files'])}")
