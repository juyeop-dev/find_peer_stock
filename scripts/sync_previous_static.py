"""Download one public immutable release for retention; no authentication or uploads."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import urllib.request
from urllib.parse import urlsplit
from package_static_data import MAX_ASSET,MAX_FILES,HEADERS,canonical,digest,valid_path,workspace_directory
from prepare_hosting_release import validate_release


def download(base_url,output):
    url=urlsplit(base_url)
    if url.scheme!='https' and not (url.scheme=='http' and url.hostname in {'localhost','127.0.0.1','::1'}): raise ValueError('Public release requires HTTPS')
    if url.username or url.password or url.query or url.fragment: raise ValueError('Invalid release base')
    output=Path(output).resolve(); output.mkdir(parents=True,exist_ok=True); directory=workspace_directory(output,'previous-')
    def fetch(path,descriptor=None):
        if not valid_path(path): raise ValueError('Invalid remote asset path')
        with urllib.request.urlopen(base_url.rstrip('/')+'/'+path,timeout=30) as response:
            raw=response.read(MAX_ASSET+1)
            if response.headers.get('Content-Encoding')=='gzip': raw=gzip.decompress(raw)
        if len(raw)>MAX_ASSET or (descriptor and (len(raw)!=descriptor['size'] or digest(raw)!=descriptor['sha256'])): raise ValueError('Previous release asset differs')
        destination=directory/path; destination.parent.mkdir(parents=True,exist_ok=True); destination.write_bytes(raw)
        return raw
    manifest=json.loads(fetch('manifest.json'))
    # Only current references of the old host are retained, not its recursive
    # retention chain. previous is excluded from the core revision by contract.
    manifest.pop('previous',None)
    (directory/'manifest.json').write_bytes(canonical(manifest)); (directory/'_headers').write_text(HEADERS,encoding='utf-8')
    assets={}
    for shard in manifest['shards'].values():
        index=json.loads(fetch(shard['path'],shard))
        for entry in index['entries'].values():
            for part in ([entry['container']] if entry['format']=='ustar-v1' else entry['parts']):
                if part['path'] in assets and assets[part['path']]!=part: raise ValueError('Conflicting old asset descriptor')
                assets[part['path']]=part
    if len(assets)+len(manifest['shards'])+2>MAX_FILES: raise ValueError('Previous release exceeds Free file limit')
    with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(lambda part:fetch(part['path'],part),assets.values()))
    report=validate_release(directory)
    return {**report,'directory':str(directory)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--base-url',required=True); parser.add_argument('--output',type=Path,required=True); parser.add_argument('--report',type=Path)
    args=parser.parse_args(); report=download(args.base_url,args.output)
    if args.report: args.report.write_bytes(canonical(report))
    print(json.dumps(report))
