"""Validate a packed dataset and prepare an isolated UI/configuration locally.

No credentials, collection, Git writes, uploads, or paid service changes.
The output remains a preparation plan until actual cost evidence is supplied.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit
from package_static_data import MAX_FILES, MAX_ASSET, ROOT, canonical, digest, referenced_assets, validate_publication, verify_roundtrip, source_files, workspace_directory, HEADERS, valid_path, verify_publication_evidence


def validate_release(directory, *, publication_proof=None, require_evidence=False):
    directory = Path(directory).resolve()
    raw = (directory/'manifest.json').read_bytes(); manifest = json.loads(raw)
    if (directory/'_headers').read_text(encoding='utf-8') != HEADERS: raise ValueError('Static CORS and cache headers differ')
    core = {key:value for key,value in manifest.items() if key not in {'revision','previous'}}
    if (manifest.get('schema_version') != 1 or manifest.get('format') != 'static-dataset-v1' or
            digest(canonical(core)) != manifest.get('revision')): raise ValueError('Invalid release manifest')
    validate_publication(manifest['publication'])
    evidence_verified=verify_publication_evidence(manifest['publication'],publication_proof) if require_evidence else False
    expected = referenced_assets(directory, manifest) | {'manifest.json','_headers'}
    if 'previous' in manifest:
        prior = manifest['previous']
        if not valid_path(prior.get('path')) or not (directory/prior['path']).resolve().is_relative_to(directory): raise ValueError('Invalid prior manifest path')
        prior_raw = (directory/prior['path']).read_bytes()
        if digest(prior_raw) != prior['sha256'] or len(prior_raw) != prior['size']: raise ValueError('Prior manifest differs')
        old = json.loads(prior_raw)
        old_core = {key:value for key,value in old.items() if key not in {'revision','previous'}}
        if digest(canonical(old_core)) != old['revision']: raise ValueError('Prior manifest revision differs')
        expected |= referenced_assets(directory, old) | {prior['path']}
    actual = set(); inventory = {}; sizes = []
    for path in directory.rglob('*'):
        if path.is_symlink() or getattr(path, 'is_junction', lambda:False)(): raise ValueError('Linked public asset')
        if not path.is_file(): continue
        name = path.relative_to(directory).as_posix(); actual.add(name); size = path.stat().st_size; sizes.append(size)
        if name not in {'manifest.json','_headers'} and digest(path.read_bytes()) != path.stem: raise ValueError('Public content address differs')
    if actual != expected: raise ValueError('Release has missing or unapproved extra public files')
    if len(actual) > MAX_FILES or max(sizes) > MAX_ASSET: raise ValueError('Free asset limits exceeded')
    for prefix,shard in manifest['shards'].items():
        index_raw = (directory/shard['path']).read_bytes()
        if len(index_raw) != shard['size']: raise ValueError('Index size differs')
        index = json.loads(index_raw)
        if index.get('schema_version') != 1: raise ValueError('Invalid index schema')
        for name, entry in index['entries'].items():
            if not valid_path(name) or name in inventory or digest(name.encode())[:2] != prefix: raise ValueError('Invalid index membership')
            inventory[name] = entry
    if len(inventory) != manifest['source_files']: raise ValueError('Source count differs')
    source_hash = digest(canonical({name:{'size':row['size'],'sha256':row['sha256']} for name,row in sorted(inventory.items())}))
    if source_hash != manifest['source_inventory_sha256']: raise ValueError('Source inventory differs')
    verify_roundtrip(directory, inventory, [])
    return {'revision':manifest['revision'], 'source_inventory_sha256':source_hash, 'source_files':len(inventory),
            'output_files':len(actual), 'output_bytes':sum(sizes), 'largest_asset_bytes':max(sizes), 'integrity_verified':True,
            'publication_evidence_verified':evidence_verified}


def cost_status(evidence, now=None):
    # Version 2 verifies the resources introduced by this release. Assets-only
    # storage/requests are free on both Workers plans, so reading unrelated
    # subscriptions and global spending budgets is not a prerequisite.
    version=evidence.get('schema_version')
    required = (['cloudflare_static_assets_only_verified','no_new_paid_subscriptions_verified','github_public_repository_verified',
                 'github_standard_runner_verified','github_pages_artifacts_only_verified','github_cache_within_free_allowance_verified']
                if version==2 else ['cloudflare_workers_free_verified','cloudflare_existing_paid_products_reviewed','github_public_repository_verified',
                                   'github_standard_runner_verified','github_artifact_and_cache_costs_reviewed','github_spending_stop_verified'])
    missing = [key for key in required if evidence.get(key) is not True]
    if version not in {1,2}: missing.append('schema_version')
    if version==2 and (type(evidence.get('estimated_additional_monthly_usd')) not in {int,float} or evidence['estimated_additional_monthly_usd']!=0):
        missing.append('zero_additional_cost_estimate')
    if not re.fullmatch('[a-f0-9]{32}', evidence.get('cloudflare_account_id') or ''): missing.append('cloudflare_account_id')
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', evidence.get('github_repository') or ''): missing.append('github_repository')
    if not isinstance(evidence.get('evidence_reference'),str) or not evidence['evidence_reference'].strip(): missing.append('evidence_reference')
    try:
        checked = datetime.fromisoformat(evidence['checked_at'].replace('Z','+00:00'))
        if checked.tzinfo is None or not timedelta(0) <= (now or datetime.now(timezone.utc))-checked <= timedelta(hours=24): missing.append('recent_checked_at')
    except (KeyError,TypeError,ValueError,AttributeError): missing.append('recent_checked_at')
    return {'verified':not missing, 'missing':missing}


def prepare(release, output, data_base_url, *, base_path='/', cost_evidence=None, build_ui=True, compat_data=None, compat_inventory_sha256=None, publication_proof=None, compat_ui=None):
    release, output = Path(release).resolve(), Path(output).resolve()
    url = urlsplit(data_base_url)
    if url.scheme != 'https' or not url.netloc or url.username or url.password or url.query or url.fragment: raise ValueError('Production data base must use HTTPS')
    if not re.fullmatch(r'/(?:[\w.-]+/)*', base_path) or '..' in base_path: raise ValueError('Invalid Pages base path')
    if (output == ROOT or output.is_relative_to(ROOT/'frontend') or output.is_relative_to(release) or release.is_relative_to(output)):
        raise ValueError('Output must be separate from source UI and packed data')
    integrity = validate_release(release,publication_proof=publication_proof,require_evidence=True)
    output.mkdir(parents=True,exist_ok=True)
    prepared = workspace_directory(output, 'prepared-')
    config = {'name':'find-peer-stock-static-data','compatibility_date':'2026-11-18','workers_dev':True,'preview_urls':False,
              'observability':{'enabled':False},'assets':{'directory':str(release),'run_worker_first':False,'html_handling':'none','not_found_handling':'none'}}
    (prepared/'wrangler.json').write_bytes(canonical(config))
    evidence = json.loads(Path(cost_evidence).read_bytes()) if cost_evidence else {}
    cost = cost_status(evidence)
    report = {'schema_version':1,'prepared_at':datetime.now(timezone.utc).isoformat(),'data':integrity,
              'data_directory':str(release),'data_base_url':data_base_url,'base_path':base_path,'prepared_directory':str(prepared),
              'cost_checks':cost,'deployed':False,'ui_built':False,
              'cost_evidence_sha256':digest(canonical(evidence)) if evidence else None,
              'next_steps':['Recheck current production source before integrating reviewed changes',
                            'Verify Free account and spending-stop evidence before upload',
                            'Upload data first; verify real CORS, revision and original bytes',
                            'Publish UI only after the exact data revision is verified',
                            'Retain existing Pages artifact for rollback and older clients']}
    if build_ui:
        frontend = ROOT/'frontend'
        subprocess.run(['node',str(frontend/'node_modules/typescript/bin/tsc'),'--project',str(frontend/'tsconfig.json'),'--noEmit'],cwd=frontend,check=True)
        destination = prepared/'ui'
        assert destination.resolve().is_relative_to(output)
        env = {**os.environ,'VITE_DATA_BASE_URL':data_base_url,'VITE_BASE_PATH':base_path}
        subprocess.run(['node',str(frontend/'node_modules/vite/bin/vite.js'),'build','--configLoader','runner','--outDir',str(destination)],cwd=frontend,env=env,check=True)
        if (destination/'data').exists(): raise ValueError('UI build unexpectedly contains the dataset')
        ui_files = [path for path in destination.rglob('*') if path.is_file()]
        total = sum(path.stat().st_size for path in ui_files)
        if total > 100 * 1024 * 1024: raise ValueError('UI-only output exceeds conservative local size guard')
        (destination/'404.html').write_bytes((destination/'index.html').read_bytes())
        report.update(ui_built=True,ui_files=len(ui_files)+1,ui_bytes=total+(destination/'404.html').stat().st_size)
        legacy_assets=Path(compat_ui).resolve() if compat_ui else Path(compat_data).resolve().parent/'assets' if compat_data else None
        if legacy_assets and legacy_assets.is_dir():
            retained={}; added=0; added_files=0
            for source in legacy_assets.rglob('*'):
                if source.is_symlink() or getattr(source,'is_junction',lambda:False)(): raise ValueError('Linked legacy UI asset')
                if not source.is_file(): continue
                name=source.relative_to(legacy_assets).as_posix()
                if not valid_path(name): raise ValueError('Invalid legacy UI asset')
                target=destination/'assets'/name; raw=source.read_bytes()
                if target.exists():
                    if target.read_bytes()!=raw: raise ValueError('Same legacy UI asset path has different bytes')
                else:
                    target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(raw); added+=len(raw); added_files+=1
                retained[name]={'size':len(raw),'sha256':digest(raw)}
            report.update(legacy_ui_assets=len(retained),legacy_ui_inventory_sha256=digest(canonical(retained)),legacy_ui_added_bytes=added)
            report['ui_bytes']+=added
            report['ui_files']+=added_files
        if compat_data:
            originals=list(source_files(Path(compat_data).resolve()))
            if report['ui_bytes']+sum(row[2] for row in originals)>1_000_000_000: raise ValueError('Frozen compatibility assets exceed Pages size guard')
            inventory={}
            for name,source,size,mtime in originals:
                target=destination/'data'/name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(source,target)
                copied=target.read_bytes(); current=source.stat()
                if len(copied)!=size or current.st_mtime_ns!=mtime or digest(source.read_bytes())!=digest(copied): raise ValueError('Compatibility source changed during copy')
                inventory[name]={'size':size,'sha256':digest(copied)}
            fingerprint=digest(canonical(inventory))
            if fingerprint!=(compat_inventory_sha256 or integrity['source_inventory_sha256']): raise ValueError('Frozen compatibility inventory differs from its verified baseline')
            report.update(compatibility_files=len(originals),compatibility_inventory_sha256=fingerprint,
                          pages_bytes=report['ui_bytes']+sum(row[2] for row in originals),ui_only=False,older_flat_clients_supported=True)
        else:
            report.update(ui_only=True,pages_bytes=report['ui_bytes'],older_flat_clients_supported=False)
    (prepared/'plan.json').write_bytes(canonical(report))
    (output/'latest-preparation.json').write_bytes(canonical({'prepared_directory':str(prepared)}))
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',type=Path,required=True); parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--data-base-url',required=True); parser.add_argument('--base-path',default='/')
    parser.add_argument('--cost-evidence',type=Path); parser.add_argument('--validate-only',action='store_true')
    parser.add_argument('--compat-data',type=Path); parser.add_argument('--compat-inventory-sha256')
    parser.add_argument('--publication-proof',type=Path)
    parser.add_argument('--compat-ui',type=Path)
    args=parser.parse_args()
    print(json.dumps(validate_release(args.release,publication_proof=args.publication_proof,require_evidence=True) if args.validate_only else prepare(args.release,args.output,args.data_base_url,base_path=args.base_path,cost_evidence=args.cost_evidence,compat_data=args.compat_data,compat_inventory_sha256=args.compat_inventory_sha256,publication_proof=args.publication_proof,compat_ui=args.compat_ui)))
