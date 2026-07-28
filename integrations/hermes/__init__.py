"""Development-checkout Hermes loader.

`aetnamem trial start --host hermes` installs the standalone copy so Hermes
and AetnaMem do not need to share a Python environment.
"""

from aetnamem.trial.hermes_standalone import register

__all__ = ["register"]
