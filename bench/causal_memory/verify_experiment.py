from __future__ import annotations

import argparse
import json

from aetnamem.impact.verify import verify_experiment


parser = argparse.ArgumentParser()
parser.add_argument("results")
parser.add_argument("--public-key", required=True)
args = parser.parse_args()
result = verify_experiment(args.results, public_key_path=args.public_key)
print(json.dumps(result, indent=2, sort_keys=True))
raise SystemExit(0 if result["valid"] else 1)
