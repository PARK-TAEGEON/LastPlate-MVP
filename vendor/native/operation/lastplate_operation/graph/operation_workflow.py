"""Actual LangGraph subgraph; state['payload'] -> state['operation_report']."""
from copy import deepcopy
from typing import Any, TypedDict
from langgraph.graph import StateGraph, START, END
from ..agents.operation import initialize, run_stage, build_report, STAGES


class OperationState(TypedDict, total=False):
    payload: dict[str, Any]
    context: dict[str, Any]
    operation_report: dict[str, Any]
    route: str


def build_operation_subgraph():
    graph = StateGraph(OperationState)
    graph.add_node("validate_input", lambda state: {"context": initialize(state.get("payload", {}))})
    names = [stage.__name__ for stage in STAGES]
    for name, stage in zip(names, STAGES):
        def node(state, fn=stage):
            return {"context": run_stage(deepcopy(state["context"]), fn)}
        graph.add_node(name, node)

    def report_node(state):
        report = build_report(deepcopy(state["context"]))
        return {"operation_report": report, "route": report["status"]}

    graph.add_node("operation_report_builder", report_node)
    graph.add_edge(START, "validate_input")
    chain = ["validate_input"] + names
    for index, name in enumerate(chain):
        next_node = chain[index + 1] if index + 1 < len(chain) else "operation_report_builder"
        def route(state, target=next_node):
            return "operation_report_builder" if state["context"]["halt"] else target
        graph.add_conditional_edges(name, route)
    graph.add_edge("operation_report_builder", END)
    return graph.compile()
