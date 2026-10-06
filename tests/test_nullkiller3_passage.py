"""Visible passage goals use the same strategic controller contract as callers."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from test_nullkiller3_controller import strategic_request
from controller.native_strategy import validate_reply

ROOT=Path(__file__).resolve().parents[1]

class PassageContractTest(unittest.TestCase):
    def test_only_visible_subterranean_entry_and_transition_predicate_are_admitted(self):
        request=strategic_request()
        request['observation']['heroes'][0]['position']=[4,15,0]
        request['observation']['objects'].append(dict(ref='entry',kind='subterranean_gate',owner=-1,visible=True,position=[6,5,0]))
        result=subprocess.run([sys.executable,str(ROOT/'tests/fixtures/nk3_strategy_probe.py')],input=json.dumps(request),
            text=True,capture_output=True,check=True,env={**os.environ,'NK3_PROBE_MODE':'passage'})
        reply=json.loads(result.stdout);reply.pop("usage")
        accepted=validate_reply(request,reply)
        self.assertEqual(accepted['plan']['goals'][0]['kind'],'explore_passage')
        self.assertEqual(accepted['plan']['goals'][0]['target_ref'],'entry')
        for change in ({'visible':False},{'kind':'other'},{'kind':'monolith'}):
            invalid=copy.deepcopy(request);invalid['observation']['objects'][-1].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):validate_reply(invalid,reply)
        invalid=copy.deepcopy(reply)
        invalid['plan']['goals'][0]['complete_when']={'kind':'target_owned','value':0}
        with self.assertRaises(ValueError):validate_reply(request,invalid)

if __name__=='__main__':unittest.main()
