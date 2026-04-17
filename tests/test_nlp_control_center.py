import unittest

import pandas as pd

from nlp.control_center import (
    build_query_answer,
    find_plant_mention,
    heuristic_intent,
    select_hitl_item,
)


PLANTS = [
    "Noida Plant (India)",
    "Gumi (Korea)",
    "Thai Nguyen (Vietnam)",
    "Foxconn (Taiwan)",
]


class ControlCenterTests(unittest.TestCase):
    def test_find_plant_mention_matches_short_name(self):
        self.assertEqual(
            find_plant_mention("replan noida with 80% workforce", PLANTS),
            "Noida Plant (India)",
        )

    def test_heuristic_intent_detects_reconfigure(self):
        parsed = heuristic_intent(
            "Reduce workforce to 80% and replan Noida for cost",
            PLANTS,
        )
        self.assertEqual(parsed["intent"], "reconfigure")
        self.assertEqual(parsed["params"]["plant"], "Noida Plant (India)")
        self.assertEqual(parsed["params"]["workforce_pct"], 80.0)
        self.assertEqual(parsed["params"]["optimise_for"], "Cost")

    def test_heuristic_intent_detects_simulate(self):
        parsed = heuristic_intent("What if Foxconn goes offline for 8 hours?", PLANTS)
        self.assertEqual(parsed["intent"], "simulate")
        self.assertEqual(parsed["params"]["plant"], "Foxconn (Taiwan)")
        self.assertEqual(parsed["params"]["downtime_hrs"], 8.0)

    def test_select_hitl_item_prefers_matching_type_and_plant(self):
        pending_items = [
            {
                "id": 1,
                "item_type": "procurement",
                "source": "Buyer",
                "payload": {"plant": "Noida Plant (India)", "reorder_qty": 34000},
            },
            {
                "id": 2,
                "item_type": "maintenance",
                "source": "Mechanic",
                "payload": {"facility": "Foxconn (Taiwan)", "ttf_hrs": 1.0},
            },
        ]
        selected = select_hitl_item(
            "Approve the procurement order for Noida",
            pending_items,
            PLANTS,
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected["id"], 1)

    def test_build_query_answer_uses_inventory_snapshot(self):
        out = {
            "plants": PLANTS,
            "buyer_inventory": {
                "Noida Plant (India)": {
                    "days_remaining": 6.4,
                    "lead_days": 3,
                    "reorder_qty": 34000,
                    "cost_usd": 183940,
                }
            },
        }
        df = pd.DataFrame()
        answer, agent = build_query_answer("How is Noida inventory looking?", out, df)
        self.assertIn("6.4 days", answer)
        self.assertEqual(agent, "Buyer Agent")


if __name__ == "__main__":
    unittest.main()
