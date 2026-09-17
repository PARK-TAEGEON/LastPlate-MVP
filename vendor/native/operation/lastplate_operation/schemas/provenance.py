"""Proposed Operation evidence contract; identifiers are declarations, not certification."""
from pydantic import Field
from .base import Model, Name


class EvidenceRef(Model):
    source: Name
    version: Name
    snapshot_id: Name
    meal_id: Name


class NutritionEvidence(EvidenceRef):
    recipe_version: Name
    recipe_snapshot_id: Name


class EvidenceBundle(Model):
    recipe: EvidenceRef | None = None
    inventory: EvidenceRef | None = None
    nutrition: NutritionEvidence | None = None
    policy: EvidenceRef | None = None
