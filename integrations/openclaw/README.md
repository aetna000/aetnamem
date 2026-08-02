# AetnaMem OpenClaw bridge

This npm package is the host bridge for AetnaMem. It is not a standalone memory engine and should not be installed directly.

Use the Python-owned installer:

```bash
python -m pip install --pre aetnamem==1.0.0a3
aetnamem openclaw install
```

The installer pins `openclaw-memory-aetnamem@1.0.0-experimental.3`, binds the exact `aetnamem` executable, copies existing OpenClaw memory, configures shadow mode, restarts the gateway and verifies the loaded plugin. Direct npm installation cannot perform or prove those steps.

In shadow mode the bridge observes native-memory changes without injecting AetnaMem context. In active mode it exposes compatible memory search/get tools, model-semantic capture, bounded recall and native-path protection. `aetnamem control restore` restores the saved OpenClaw configuration and native memory.

See the repository [OpenClaw setup](../../docs/openclaw-setup.md) and [control-plane guarantees](../../docs/control-plane.md).
