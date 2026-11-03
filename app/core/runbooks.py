from typing import Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Route(TypedDict):
    when: dict[str, list[str]]
    to: str


class Step(TypedDict):
    step_order: int
    instruction: str
    step_type: str
    next_steps: list[str] | None
    collects: NotRequired[str | None]
    routes: NotRequired[list[Route] | None]


class FactDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)
    description: str = Field(min_length=1, max_length=500)
    options: list[str] | None = Field(default=None, min_length=2, max_length=20)


class RunbookRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Every listed fact must match one of its values; empty means "otherwise".
    when: dict[str, list[str]] = Field(default_factory=dict)
    to: str = Field(pattern=r"^[A-Za-z0-9_-]+$", max_length=256)

    @model_validator(mode="before")
    @classmethod
    def listify_values(cls, data):
        if isinstance(data, dict) and isinstance(data.get("when"), dict):
            data = {**data, "when": {
                key: value if isinstance(value, list) else [value] for key, value in data["when"].items()
            }}
        return data


class RunbookStep(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    step_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$", max_length=256)
    step_order: int = Field(ge=1)
    instruction: str = Field(min_length=1, max_length=8000)
    step_type: Literal["input", "message"]
    next_steps: list[str] | None = Field(default=None, min_length=1)
    collects: str | None = None
    routes: list[RunbookRoute] | None = Field(default=None, min_length=1)


class RunbookDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    runbook_name: str = Field(min_length=1, max_length=200)
    issue_category: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    facts: list[FactDefinition] = Field(default_factory=list, max_length=50)
    steps: list[RunbookStep] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_routes(self) -> "RunbookDefinition":
        ids = {step.step_id for step in self.steps}
        orders = {step.step_order for step in self.steps}
        if len(ids) != len(self.steps) or len(orders) != len(self.steps):
            raise ValueError("Step IDs and orders must be unique")
        if ids & {"END", "ESCALATE"}:
            raise ValueError("END and ESCALATE are reserved destinations")
        facts = {fact.name: fact for fact in self.facts}
        if len(facts) != len(self.facts):
            raise ValueError("Fact names must be unique")
        by_id = {step.step_id: step for step in self.steps}
        for step in self.steps:
            if step.collects is not None and step.collects not in facts:
                raise ValueError(f"{step.step_id} collects undeclared fact {step.collects}")
            if step.routes is not None:
                if step.next_steps is not None:
                    raise ValueError(f"{step.step_id} cannot define both next_steps and routes")
                if step.routes[-1].when or any(not route.when for route in step.routes[:-1]):
                    raise ValueError(f"{step.step_id} routes must end with exactly one otherwise route")
                for route in step.routes:
                    for name, values in route.when.items():
                        if name not in facts:
                            raise ValueError(f"{step.step_id} route uses undeclared fact {name}")
                        options = facts[name].options
                        if options and not set(values) <= set(options):
                            raise ValueError(f"{step.step_id} route uses unknown values for {name}")
            targets = [route.to for route in step.routes] if step.routes else step.next_steps or []
            for target in targets:
                if target in {"END", "ESCALATE"}:
                    continue
                if target not in by_id or by_id[target].step_order <= step.step_order:
                    raise ValueError(f"Invalid forward destination {target} from {step.step_id}")
        return self
