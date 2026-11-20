"""Build an assets-only refresh from the audited Pages data in the current job."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zipfile import ZipFile

from package_static_data import canonical, package, valid_path
from prepare_hosting_release import cost_status, prepare
from sync_previous_static import download


def github_cost_evidence(repository, token, account):
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', repository):
        raise ValueError('Invalid GitHub repository')
    base = f'https://api.github.com/repos/{repository}'

    def read(path):
        request = Request(base + path, headers={'User-Agent': 'stock-static-publisher'})
        request.add_unredirected_header('Authorization', f'Bearer {token}')
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    repo = read('')
    cache = read('/actions/cache/usage')
    artifacts = read('/actions/artifacts?per_page=100')
    rows = artifacts['artifacts']
    evidence = {
        'schema_version': 2,
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'cloudflare_account_id': account,
        'github_repository': repository,
        'cloudflare_static_assets_only_verified': True,
        'no_new_paid_subscriptions_verified': True,
        'github_public_repository_verified': repo['private'] is False,
        'github_standard_runner_verified': os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted',
        'github_pages_artifacts_only_verified': len(rows) == artifacts['total_count'] and all(
            row['name'] == 'github-pages' for row in rows
        ),
        'github_cache_within_free_allowance_verified': cache['active_caches_size_in_bytes'] <= 10 * 1024**3,
        'estimated_additional_monthly_usd': 0,
        'evidence_reference': 'Public repository, standard Ubuntu runner, Pages artifacts and assets-only Wrangler configuration',
    }
    status = cost_status(evidence)
    if not status['verified']:
        raise ValueError(f'Static publication cost checks failed: {status["missing"]}')
    return evidence


def extract_compatibility(archive, destination):
    seen = set()
    total = 0
    destination.mkdir()
    with ZipFile(archive) as compressed:
        if compressed.namelist() != ['artifact.tar']:
            raise ValueError('Unexpected Pages compatibility archive members')
        with compressed.open('artifact.tar') as stream, tarfile.open(fileobj=stream, mode='r|') as packed:
            for member in packed:
                name = member.name.removeprefix('./')
                if member.isdir() or not name.startswith(('data/', 'assets/')):
                    continue
                if not member.isfile() or not valid_path(name) or name in seen:
                    raise ValueError('Unsafe or duplicate Pages compatibility asset')
                total += member.size
                if total > 1_000_000_000:
                    raise ValueError('Pages compatibility files exceed the publishing limit')
                seen.add(name)
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with packed.extractfile(member) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output)
    if 'data/index.json' not in seen or not any(name.startswith('assets/') for name in seen):
        raise ValueError('Pages compatibility files are incomplete')


def download_compatibility(url, checksum, repository, output):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'github.com'
            or not parsed.path.startswith(f'/{repository}/releases/download/') or parsed.query or parsed.fragment
            or not re.fullmatch(r'[a-f0-9]{64}', checksum)):
        raise ValueError('A pinned public compatibility archive in this repository is required')
    archive = output / 'compatibility.zip'
    total = 0
    fingerprint = hashlib.sha256()
    with urlopen(url, timeout=90) as response, archive.open('xb') as target:
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total >= 2 * 1024**3:
                raise ValueError('Pages compatibility archive exceeds the release asset limit')
            fingerprint.update(chunk)
            target.write(chunk)
    if fingerprint.hexdigest() != checksum:
        raise ValueError('Pages compatibility archive checksum differs')
    destination = output / 'compatibility'
    extract_compatibility(archive, destination)
    return destination / 'data'


def prepare_publication(source, output, data_base, *, pages):
    repository = os.environ['GITHUB_REPOSITORY']
    # A CI credential is scoped to the configured account and paired with an assets-only release.
    account = os.environ['CLOUDFLARE_ACCOUNT_ID']
    evidence = github_cost_evidence(repository, os.environ['GH_TOKEN'], account)
    output.mkdir()
    evidence_path = output / 'cost-evidence.json'
    evidence_path.write_bytes(canonical(evidence))

    compatibility = None
    compatibility_inventory = None
    if pages:
        compatibility_inventory = os.environ['STATIC_PAGES_COMPAT_INVENTORY_SHA256']
        if not re.fullmatch(r'[a-f0-9]{64}', compatibility_inventory):
            raise ValueError('The frozen Pages inventory must be pinned')
        compatibility = download_compatibility(
            os.environ['STATIC_PAGES_COMPAT_URL'], os.environ['STATIC_PAGES_COMPAT_SHA256'], repository, output
        )
    if source is None:
        if compatibility is None:
            raise ValueError('A data source is required for a data-only refresh')
        source = compatibility

    previous = download(data_base, output / 'previous')
    old = json.loads((Path(previous['directory']) / 'manifest.json').read_bytes())
    packed = package(source, output / 'packed', previous=Path(previous['directory']))
    release = Path(packed['ready_directory'])
    current = json.loads((release / 'manifest.json').read_bytes())
    changed = any(current[key] != old[key] for key in ('source_inventory_sha256', 'publication'))
    if not changed:
        release = Path(previous['directory'])

    plan = prepare(
        release, output / 'prepared', data_base, base_path='/' + repository.split('/')[1] + '/',
        cost_evidence=evidence_path, build_ui=pages, compat_data=compatibility,
        compat_inventory_sha256=compatibility_inventory,
    )
    if not plan['cost_checks']['verified']:
        raise ValueError('Static publication cost evidence expired')
    folder = Path(plan['prepared_directory'])
    return {'revision': plan['data']['revision'], 'changed': changed,
            'config': str(folder / 'wrangler.json'), 'pages': str(folder / 'ui') if pages else ''}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Audited data directory. Omit with --pages to rehearse against the frozen archive.')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-base-url', required=True)
    parser.add_argument('--pages', action='store_true')
    options = parser.parse_args()
    plan = prepare_publication(options.source, options.output, options.data_base_url, pages=options.pages)
    with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as stream:
        for key, value in plan.items():
            stream.write(f'{key}={str(value).lower() if isinstance(value, bool) else value}\n')
