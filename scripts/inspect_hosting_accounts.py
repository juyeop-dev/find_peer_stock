"""Read-only hosting checks. Never refresh credentials or change billing/deployments.

Reports only selected public metadata and status codes, never credential values.
Billing confirmation remains manual when an authenticated API cannot establish it.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib
import urllib.error
import urllib.request


def request(url, token=None):
    headers = {'User-Agent': 'stock-study-read-only-review', 'Accept': 'application/json'}
    if token: headers['Authorization'] = 'Bearer ' + token
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15) as response:
            return json.load(response), {'http_status': response.status}
    except urllib.error.HTTPError as exc:
        return None, {'http_status': exc.code, 'confirmed': False}
    except Exception as exc:
        return None, {'error_type': type(exc).__name__, 'confirmed': False}


def inspect(repository, cloudflare_config=None):
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', repository): raise ValueError('Invalid GitHub repository')
    report = {'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(), 'read_only': True,
              'billing_verified': False, 'deployment_authorized_by_cost_checks': False}
    if cloudflare_config:
        config = tomllib.loads(Path(cloudflare_config).read_text())
        accounts, status = request('https://api.cloudflare.com/client/v4/accounts', config.get('oauth_token'))
        report['cloudflare'] = {**status, 'local_auth_expiration': config.get('expiration_time'), 'workers_free_confirmed': False}
        if accounts and accounts.get('success'):
            report['cloudflare']['accounts'] = []
            for account in accounts.get('result',[]):
                row = {'account_id':account['id']}
                for label, route in [('subscriptions','subscriptions'),('worker_settings','workers/account-settings'),('scripts','workers/scripts')]:
                    result, status = request(f"https://api.cloudflare.com/client/v4/accounts/{account['id']}/{route}", config.get('oauth_token'))
                    if result is not None:
                        if label=='subscriptions': status['subscriptions'] = [{key:item.get(key) for key in ['id','state','rate_plan','price','frequency']} for item in result.get('result',[])]
                        elif label=='worker_settings': status['settings'] = result.get('result')
                        else: status['scripts'] = [{key:item.get(key) for key in ['id','modified_on','usage_model']} for item in result.get('result',[])]
                    row[label]=status
                report['cloudflare']['accounts'].append(row)
    credential = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n',
                                text=True, capture_output=True, timeout=20,
                                env={**os.environ, 'GIT_TERMINAL_PROMPT':'0', 'GCM_INTERACTIVE':'never'})
    values = dict(line.split('=',1) for line in credential.stdout.splitlines() if '=' in line) if credential.returncode == 0 else {}
    token = values.get('password')
    report['github_authenticated'] = bool(token)
    for name, route in [('repository',''), ('main','/commits/main'), ('workflows','/actions/workflows'),
                        ('cache_usage','/actions/cache/usage'), ('artifacts','/actions/artifacts?per_page=100'), ('runs','/actions/runs?per_page=5')]:
        value, status = request('https://api.github.com/repos/'+repository+route, token)
        if value is not None:
            if name == 'repository': status.update({key:value.get(key) for key in ['full_name','private','visibility','default_branch','pushed_at','size','has_pages']})
            if name == 'main': status.update({'sha':value['sha'], 'date':value['commit']['committer']['date']})
            if name == 'workflows': status['workflows'] = [{key:row.get(key) for key in ['name','path','state']} for row in value.get('workflows',[])]
            if name == 'cache_usage': status.update({key:value.get(key) for key in ['active_caches_size_in_bytes','active_caches_count']})
            if name == 'artifacts':
                rows=value.get('artifacts',[])
                status.update({'total_count':value.get('total_count'), 'first_page_bytes':sum(row['size_in_bytes'] for row in rows),
                               'first_page_expired':sum(row['expired'] for row in rows),
                               'names':sorted({row['name'] for row in rows}),
                               'pages_artifact_count':sum(row['name']=='github-pages' for row in rows)})
            if name == 'runs': status['runs'] = [{key:row.get(key) for key in ['name','head_sha','status','conclusion','created_at','run_started_at']} for row in value.get('workflow_runs',[])]
        report['github_'+name] = status
    owner = repository.split('/')[0]
    if token:
        current=datetime.now(timezone.utc)
        value, status = request(f'https://api.github.com/users/{owner}/settings/billing/usage?year={current.year}&month={current.month}', token)
        if value is not None:
            status['product_totals'] = {}
            for row in value.get('usageItems',[]):
                product = row.get('product','unknown')
                status['product_totals'][product] = status['product_totals'].get(product,0) + row.get('netAmount',0)
            status['note'] = 'Current returned usage only; spending-stop budgets are not established by this endpoint'
        report['github_billing_usage'] = status
    report['unverified'] = ['Cloudflare Workers Free subscription and existing paid products',
                            'GitHub spending budgets and whether returned storage usage can accrue charges',
                            'Current data host and its deployment revision']
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--github-repository', required=True)
    parser.add_argument('--cloudflare-config', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.github_repository, args.cloudflare_config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
