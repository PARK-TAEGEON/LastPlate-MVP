"""Narrow InventoryUse regression matrix; menu substitution remains ingredient-optional."""
import unittest
from pydantic import ValidationError
from examples.fixtures import baseline, PASS
from lastplate_decision import make_final_recommendation as decide
from lastplate_decision.schemas.decision_input import InventoryUse


class InventoryUseContractTests(unittest.TestCase):
    def test_valid_inventory_values_are_trimmed(self):
        p=baseline();item=p['inventory_risk_result']['inventory_recommendations'][0]
        item.update(ingredient='  두부  ',unit=' kg\t')
        parsed=InventoryUse.model_validate(item)
        self.assertEqual(parsed.ingredient,'두부');self.assertEqual(parsed.unit,'kg')
        r=decide(**p)
        action=r['inventory_actions'][0]
        self.assertTrue(action['selected']);self.assertEqual(action['decision'],'ADJUST')
        self.assertEqual(action['unit'],'kg');self.assertEqual(action['ingredient'],'두부')

    def test_menu_substitution_without_ingredient_remains_supported(self):
        for supplied in (False,True):
            with self.subTest(explicit_null=supplied):
                p=baseline()
                candidate={'candidate_id':'menu-only','kind':'menu_substitution','menu':'두부조림',
                           'candidate_menu':'버섯볶음','constraints':PASS}
                if supplied:candidate['ingredient']=None
                p['inventory_risk_result']['substitute_candidates']=[candidate]
                r=decide(**p)
                self.assertEqual(r['status'],'ok')
                self.assertEqual(r['candidate_evaluations'][0]['decision'],'REVIEW')
                self.assertIsNone(r['candidate_evaluations'][0]['ingredient'])

    def test_non_string_inventory_identity_rejected(self):
        for field in ('ingredient','unit'):
            with self.subTest(field=field):
                p=baseline();p['inventory_risk_result']['inventory_recommendations'][0][field]=123
                with self.assertRaises(ValidationError):decide(**p)


def case(field,kind,with_alert):
    def test(self):
        p=baseline();item=p['inventory_risk_result']['inventory_recommendations'][0]
        if kind=='missing':item.pop(field,None)
        else:item[field]={'null':None,'empty':'','whitespace':' \t\n\u3000'}[kind]
        if with_alert:
            p['inventory_risk_result']['alerts']=[{'type':'expiry_risk','severity':'HIGH',
                'ingredient':'두부','menu':'두부조림','message':'두부 D-1 확인'}]
        # Must fail at the input boundary, never reach normalize(None) or select an invalid action.
        with self.assertRaises(ValidationError) as raised:decide(**p)
        self.assertIn(('inventory_risk_result','inventory_recommendations',0,field),
                      [e['loc'] for e in raised.exception.errors()])
    return test


for field in ('ingredient','unit'):
    for kind in ('missing','null','empty','whitespace'):
        for alert in (False,True):
            setattr(InventoryUseContractTests,f'test_{field}_{kind}_'+('with_expiry_alert' if alert else 'alone'),case(field,kind,alert))
