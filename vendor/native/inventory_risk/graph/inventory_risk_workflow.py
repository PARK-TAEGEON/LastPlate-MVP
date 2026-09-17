from typing import TypedDict, Any
from langgraph.graph import StateGraph, START, END
from agents.inventory_risk import InventoryRiskAgent, STAGES
from schemas.errors import DataQualityError, validation_error
from pydantic import ValidationError

class InventoryRiskState(TypedDict, total=False):
    request: dict
    user_event: Any
    as_of: Any
    horizon_end: Any
    horizon_start: Any
    plan: list
    executed_nodes: list
    errors: list
    parsing_result: dict
    validation_warnings: list
    inventory_impacts: list
    priority_use_candidates: list
    menus: list
    inventory: list
    recipes: dict
    events: list
    alerts: list
    rechecks: list
    trace: list
    inventory_status: list
    allocation_audit: list
    price_risks: list
    supply_risks: list
    affected: list
    candidate_work: list
    candidates: list
    nutrition_results: list
    cost_impacts: list
    report: dict

def build_inventory_risk_subgraph(adapters, config):
    agent=InventoryRiskAgent(adapters,config)
    graph=StateGraph(InventoryRiskState)
    def guarded(name):
        def execute(state):
            try:
                update=getattr(agent,name)(state)
            except (DataQualityError,ValidationError) as exc:
                detail=exc.detail if isinstance(exc,DataQualityError) else validation_error(exc).detail
                update={"errors":[detail.model_dump()],"trace":state.get("trace",[])+[f"ERROR {name}: {detail.message}"]}
            update["executed_nodes"]=([] if name=="event_parser" else state.get("executed_nodes",[]))+[name]
            return update
        return execute

    def route(state):
        if state.get("errors"):
            return "risk_report_builder"
        executed=state.get("executed_nodes",[])
        for name in state.get("plan",[]):
            if name in executed:
                continue
            if name=="substitute_candidate_generator" and not state.get("affected"):
                continue
            if name=="nutrition_constraint_checker" and not state.get("candidate_work"):
                continue
            return name
        return "risk_report_builder"

    for name in STAGES:
        graph.add_node(name,guarded(name) if name!="risk_report_builder" else agent.risk_report_builder)
        if name!="risk_report_builder":
            graph.add_conditional_edges(name,route,{n:n for n in STAGES[1:]})
    graph.add_edge(START,"event_parser")
    graph.add_edge("risk_report_builder",END)
    return graph.compile()
