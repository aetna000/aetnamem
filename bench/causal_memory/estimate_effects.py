from __future__ import annotations

import argparse
import json
from pathlib import Path

from aetnamem.impact.estimate import cell_rates, estimate_registered_effects


parser = argparse.ArgumentParser()
parser.add_argument("observations", help="JSON array of signed-result observations")
parser.add_argument("--output", required=True)
args = parser.parse_args()
rows = json.loads(Path(args.observations).read_text(encoding="utf-8"))
report = {
    "effects": {
        name: value.to_dict()
        for name, value in estimate_registered_effects(rows).items()
    },
    "arms": cell_rates(rows),
}
Path(args.output).write_text(
    json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
