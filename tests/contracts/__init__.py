"""Contracts every public entry point must satisfy, parametrized over them.

Structural check C from the audit post-mortem. The pattern the re-audit kept
finding is a fix landed on one entry point and a regression test parametrized
over the callers of *that* entry point, which is why the same defect was still
live on the three entry points nobody enumerated. A contract in here is stated
once and run against every way into the engine, and a meta-test refuses to
pass while a shipped transport is missing from the list.
"""
