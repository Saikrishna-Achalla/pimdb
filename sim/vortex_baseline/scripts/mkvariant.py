#!/usr/bin/env python3
"""Derive a configuration variant: mkvariant.py <base> <name> KEY=VALUE ... -> configs/calib/<name>.json.
KEY is a VX_CFG_* knob (prefix optional); it replaces the value in whichever section holds it (else 'platform')."""
import json, sys, os
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'configs')
base, name, kv = sys.argv[1], sys.argv[2], sys.argv[3:]
cfg = json.load(open(os.path.join(D, base + '.json')))
cfg['name'] = name
cfg['description'] = f"Variant of {base}: " + ', '.join(kv)
for a in kv:
    k, v = a.split('=', 1)
    k = k if k.startswith('VX_CFG_') else 'VX_CFG_' + k
    v = json.loads(v) if v not in ('true', 'false') or True else v
    sec = next((s for s in ('core', 'chip', 'platform') if k in cfg[s]), 'platform')
    cfg[sec][k] = v
cfg['sources'] = {'variant_of': base, 'changes': kv}
json.dump(cfg, open(os.path.join(D, 'calib', name + '.json'), 'w'), indent=2)
print(name)
