"""LightrayRegistry — event-sourced system of record for the R&D pipeline.

Core dependency policy (TECH_SPEC §0): stdlib + Pydantic v2 ONLY.
pyarrow/pandas live behind registry.bridges and are never imported by the core.
"""

REGISTRY_SPEC_VERSION = "TS-2.0"   # the spec this code implements (docs/TECH_SPEC.md)
SCHEMA_VERSION = 1                 # envelope schema version (upcasters guard evolution)
