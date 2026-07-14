"""Loopback control service for the aetnamem governed core.

A single enforcement point that both the assistant loop and the human dashboard
drive over ``127.0.0.1`` HTTP. Two bearer tokens separate the roles: the
*agent* token may list tools, dispatch tool calls, and read state; only the
*reviewer* token may approve, commit, or deny a staged action. The reviewer
holds the approval key, so the model — which only ever reaches the agent token
via the host loop — can stage effects but never authorize its own.

Stdlib only (``http.server``): the zero-dependency promise holds.
"""

from aetnamem.service.app import ControlService, build_service, serve

__all__ = ["ControlService", "build_service", "serve"]
