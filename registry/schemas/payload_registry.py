"""Event type → payload model. This IS the discriminated union, applied at the ingest
boundary: ingest validates payload against the model and stores the VALIDATED dump, which is
what canonical hashing covers (cross-language identity, TECH_SPEC §1.1)."""
from __future__ import annotations

from pydantic import BaseModel

from . import artifacts, blocks, cards, certs, conditionals, constants, features, misc, scorecards, windows

PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    # NS1/NS2/NS4
    "dataset.register": features.DatasetRegister,
    "feature.register": features.FeatureRegister,
    "feature.status_change": features.FeatureStatusChange,
    "featureset.freeze": features.FeaturesetFreeze,
    "family.register": features.FamilyRegister,
    "family.activate": features.FamilyActivate,
    # NS5
    "block.register": blocks.BlockRegister,
    "block.freeze": blocks.BlockFreeze,
    "block.supersede": blocks.BlockSupersede,
    "block.kill_axis": blocks.BlockKillAxis,
    "block.close": blocks.BlockClose,
    # trials
    "trials.open_batch": blocks.TrialsOpenBatch,
    "trials.record": blocks.TrialsRecord,
    "trials.close_batch": blocks.TrialsCloseBatch,
    # NS8
    "artifact.register": artifacts.ArtifactRegister,
    "artifact.stamp": artifacts.ArtifactStamp,
    "artifact.attest_missing": artifacts.ArtifactAttestMissing,
    "artifact.integrity_checked": artifacts.ArtifactIntegrityChecked,
    # NS9
    "card.emit": cards.CardEmit,
    "scorecard.emit": scorecards.ScorecardEmit,
    # NS3/NS7
    "windowset.register": windows.WindowsetRegister,
    "windowset.supersede": windows.WindowsetSupersede,
    "scope.mint": windows.ScopeMint,
    # readouts
    "readout.request": blocks.ReadoutRequest,
    "readout.record": blocks.ReadoutRecord,
    "readout.void": blocks.ReadoutVoid,
    # NS10
    "cert.clause_stamp": certs.CertClauseStamp,
    "cert.certify": certs.CertCertify,
    "cert.displace": certs.CertDisplace,
    "cert.revoke": certs.CertRevoke,
    # NS11
    "constants.register": constants.ConstantsRegister,
    "constants.amend": constants.ConstantsAmend,
    # NS12
    "conditional.arm": conditionals.ConditionalArm,
    "conditional.disarm": conditionals.ConditionalDisarm,
    # rules channel
    "rules.propose": scorecards.RulesPropose,
    "rules.adopt": scorecards.RulesAdopt,
    "rules.revert": scorecards.RulesRevert,
    # cycles
    "cycle.open": scorecards.CycleOpen,
    "cycle.close": scorecards.CycleClose,
    "stage.dispatch": scorecards.StageDispatch,
    # agent channels
    "shadow_ranking": misc.ShadowRanking,
    "queue_reorder": misc.QueueReorder,
    # housekeeping
    "replay.verified": misc.ReplayVerified,
    "note.record": misc.NoteRecord,
}


def validate_payload(event_type: str, payload: dict) -> dict:
    """Validate + return the model dump (the canonical-hash input). Raises on mismatch."""
    model = PAYLOAD_MODELS[event_type]
    return model.model_validate(payload).model_dump(mode="json")
