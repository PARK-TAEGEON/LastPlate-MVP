import unittest
from copy import deepcopy
from uuid import uuid4
from langgraph.types import Command
from lastplate_decision.graph.decision_workflow import build_decision_workflow, route_events
from lastplate_decision.config.decision_policy import DecisionPolicy
from examples.fixtures import baseline, refreshed, recheck_names


class WorkflowTests(unittest.TestCase):
    def config(self):
        return {"configurable": {"thread_id": str(uuid4())}, "recursion_limit": 80}

    def test_full_order_interrupt_approve_no_execution(self):
        calls = []
        p = baseline()
        def cb(name, key):
            def run(payload):
                calls.append(name)
                return payload[key]
            return run
        graph = build_decision_workflow({name: cb(name, key) for name, key in (
            ("demand_forecast", "demand_result"), ("operation", "operation_result"), ("inventory_risk", "inventory_risk_result"))})
        config = self.config()
        result = graph.invoke({"payload": p}, config)
        self.assertIn("__interrupt__", result)
        self.assertEqual(calls, ["demand_forecast", "inventory_risk", "operation"])
        result = graph.invoke(Command(resume={"recommendation_revision": graph.get_state(config).values["recommendation"]["recommendation_revision"], "choice": "approve", "operator_id": "operator-1"}), config)
        self.assertFalse(result["approval"]["executed"])
        self.assertEqual(result["recommendation"]["approval_status"], "pending")
        self.assertEqual(calls, ["demand_forecast", "inventory_risk", "operation"])

    def test_attendance_refreshes_final_recommendation(self):
        p = baseline()
        p["user_events"] = [{"event_id": "visit", "event_type": "attendance_event", "attendance_delta": 35}]
        calls = []
        def demand(payload):
            calls.append("demand")
            return refreshed(dict(payload["demand_result"], prediction=522, applied_event_ids=["visit"]), payload)
        def operation(payload):
            calls.append("operation")
            self.assertEqual(payload["demand_result"]["prediction"], 522)
            return refreshed(dict(payload["operation_result"], recommended_servings=558, applied_event_ids=["visit"]), payload)
        g = build_decision_workflow({"demand_forecast": demand, "operation": operation})
        r = g.invoke({"payload": p}, self.config())
        self.assertEqual(r["recommendation"]["recommended_servings"], 558)
        self.assertEqual(calls, ["demand", "operation"])

    def test_expiry_route(self):
        p = baseline()
        p["user_events"] = [{"event_id": "expiry", "event_type": "expiry_event", "ingredient": "두부"}]
        calls = []
        def inventory(payload):
            calls.append("inventory")
            return refreshed(dict(payload["inventory_risk_result"], applied_event_ids=["expiry"]), payload)
        def operation(payload):
            calls.append("operation")
            return refreshed(payload["operation_result"], payload)
        r = build_decision_workflow({"inventory_risk": inventory,"operation":operation}).invoke({"payload": p}, self.config())
        self.assertEqual(calls, ["inventory","operation"])
        self.assertEqual(r["recommendation"]["recommended_rechecks"], [])

    def test_price_route_inventory_before_operation(self):
        self.assertEqual(route_events({"user_events": [{"event_type": "price_event"}]}), ["inventory_risk", "operation"])

    def test_compound_route(self):
        self.assertEqual(route_events({"user_events": [{"event_type": "attendance_event"}, {"event_type": "price_event"}]}),
                         ["demand_forecast", "inventory_risk", "operation"])

    def test_modify_revalidates_and_interrupts_again(self):
        g = build_decision_workflow()
        c = self.config()
        g.invoke({"payload": baseline()}, c)
        revised = baseline()
        revised["operation_result"]["recommended_servings"] = 400
        r = g.invoke(Command(resume={"recommendation_revision": g.get_state(c).values["recommendation"]["recommendation_revision"], "choice": "modify", "operator_id": "op", "revised_input": revised}), c)
        self.assertIn("__interrupt__", r)
        self.assertEqual(r["recommendation"]["status"], "blocked")
        self.assertEqual(len(r["approval_history"]), 1)
        r = g.invoke(Command(resume={"recommendation_revision": g.get_state(c).values["recommendation"]["recommendation_revision"], "choice": "reject", "operator_id": "op"}), c)
        self.assertEqual(r["approval"]["choice"], "reject")
        self.assertFalse(r["approval"]["executed"])

    def test_blocked_cannot_be_approved(self):
        p = baseline()
        p["operation_result"]["recommended_servings"] = 1
        g, c = build_decision_workflow(), self.config()
        g.invoke({"payload": p}, c)
        with self.assertRaises(ValueError):
            g.invoke(Command(resume={"recommendation_revision": g.get_state(c).values["recommendation"]["recommendation_revision"], "choice": "approve", "operator_id": "op"}), c)

    def test_recheck_cycles_bounded(self):
        p = baseline()
        p["inventory_risk_result"]["recommended_rechecks"] = ["inventory_risk"]
        calls = []
        def inventory(payload):
            calls.append(1)
            return payload["inventory_risk_result"]
        g = build_decision_workflow({"inventory_risk": inventory}, policy=DecisionPolicy(max_recheck_rounds=2))
        r = g.invoke({"payload": p}, self.config())
        self.assertIn("__interrupt__", r)
        self.assertEqual(len(calls), 3)
        self.assertEqual(r["recommendation"]["confidence"], "LOW")

    def test_callback_failure_invalidates_stale_result(self):
        def fail(payload):
            raise RuntimeError("unavailable")
        g = build_decision_workflow({"operation": fail})
        r = g.invoke({"payload": baseline()}, self.config())
        self.assertIsNone(r["recommendation"]["recommended_servings"])
        self.assertIn("실패", str(r["recommendation"]["data_quality_notes"]))

    def test_separate_threads(self):
        g = build_decision_workflow()
        c1, c2 = self.config(), self.config()
        g.invoke({"payload": baseline()}, c1)
        p = baseline()
        p["operation_result"]["recommended_servings"] = 600
        g.invoke({"payload": p}, c2)
        r = g.invoke(Command(resume={"recommendation_revision": g.get_state(c1).values["recommendation"]["recommendation_revision"], "choice": "approve", "operator_id": "op"}), c1)
        self.assertEqual(r["recommendation"]["recommended_servings"], 523)


if __name__ == "__main__":
    unittest.main()
