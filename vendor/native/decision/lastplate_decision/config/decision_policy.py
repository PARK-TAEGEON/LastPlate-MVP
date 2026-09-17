from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Objective = Literal["shortage", "safety", "nutrition", "supply", "waste", "cost", "preference"]
HARD_CONSTRAINTS = ("shortage", "expiry", "allergy", "nutrition", "restriction", "supply")


class DecisionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    priorities: tuple[Objective, ...] = (
        "shortage", "safety", "nutrition", "supply", "waste", "cost", "preference"
    )
    max_shortage_probability: float = Field(default=0.05, ge=0, le=1, allow_inf_nan=False)
    aliases: dict[str, str] = Field(default_factory=lambda: {"달걀": "계란"})
    operation_inventory_dependency: Literal["when_relevant", "always"] = "when_relevant"
    max_recheck_rounds: int = Field(default=2, ge=0, le=10)

    @model_validator(mode="after")
    def validate_priorities(self):
        if len(self.priorities) != 7 or set(self.priorities) != {
            "shortage", "safety", "nutrition", "supply", "waste", "cost", "preference"
        }:
            raise ValueError("priorities must contain every objective exactly once")
        return self

    def normalize(self, name: str) -> str:
        key = "".join(name.split()).casefold()
        aliases = {"".join(k.split()).casefold(): "".join(v.split()).casefold()
                   for k, v in self.aliases.items()}
        return aliases.get(key, key)
