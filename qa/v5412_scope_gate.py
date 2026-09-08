#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "5.4.1.2-interaction-regression-correction-po1"
checks=[]
def check(name,ok,evidence=None): checks.append({'name':name,'passed':bool(ok),'evidence':evidence})
def load(name): return json.loads((ROOT/name).read_text(encoding='utf-8'))

product=load('qa/V5412-PRODUCT-OWNER-QC.json')
persist=load('qa/V5412-PERSISTENCE-QC.json')
interaction=load('qa/V5412-INTERACTION-REGRESSION-GATE.json')
launcher=load('qa/V5412-LAUNCHER-STATIC-RESULTS.json')
upgrade=load('qa/V5412-UPGRADE-PRESERVATION-RESULTS.json')
baseline=load('qa/V5412-BASELINE-PRESERVATION-RESULTS.json')
change=load('CHANGE-IMPACT.json')

check('Functional Product Owner QC passed', product.get('status')=='passed' and product.get('failed')==0, {'passed':product.get('passed'),'failed':product.get('failed')})
check('Restart persistence passed', persist.get('status')=='passed' and persist.get('failed')==0, {'passed':persist.get('passed'),'failed':persist.get('failed')})
check('Interaction regression gate passed', interaction.get('status')=='passed' and interaction.get('failed')==0, {'passed':interaction.get('passed'),'failed':interaction.get('failed')})
check('Windows launcher static gate passed', launcher.get('status')=='passed' and launcher.get('failed')==0, {'passed':launcher.get('passed'),'failed':launcher.get('failed')})
check('Upgrade preservation passed', upgrade.get('status')=='passed' and upgrade.get('failed')==0, {'passed':upgrade.get('passed'),'failed':upgrade.get('failed')})
check('Exact baseline preservation passed', baseline.get('status')=='passed' and baseline.get('removed_count')==0, {'changed':baseline.get('changed_count'),'added':baseline.get('added_count'),'removed':baseline.get('removed_count')})
check('Theme rendering was not authorized to change', change.get('theme_rendering_changed') is False)
check('Theme presets were not authorized to change', change.get('theme_presets_changed') is False)
check('No database migration was added', change.get('database_migration') is None and change.get('current_migration')=='005.006.100-four-workspace-themes')
check('Isolated Product Owner port is 8088', change.get('isolated_product_owner',{}).get('port')==8088)
check('Immediate source is exact v5.4.1.1 artifact', change.get('source_baseline',{}).get('sha256')=='1aa552533e5471ac70ffc2d82ab88551b748a7934e1e3ddbb89aa6405a9efed9')
check('Production and Hasan handoff remain unauthorized', change.get('production_authorized') is False and change.get('hasan_handoff_authorized') is False)

failed=[x for x in checks if not x['passed']]
payload={'release':RELEASE,'status':'passed' if not failed else 'failed','passed':len(checks)-len(failed),'failed':len(failed),'checks':checks}
(ROOT/'qa/V5412-SCOPE-GATE.json').write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8')
print(json.dumps(payload,indent=2))
raise SystemExit(1 if failed else 0)
