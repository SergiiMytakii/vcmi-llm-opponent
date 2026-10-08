"""Native rejection diagnostics through the same parser used by strategy exchange."""
import unittest
import test_threat_forecasts as native_proof

@unittest.skipUnless((native_proof.SOURCE / 'Global.h').exists() and native_proof.LIBRARY.exists(), 'requires VCMI headers/library')
class StrategyRejectionFeedbackTest(unittest.TestCase):
    proof = native_proof.ThreatForecastTest.proof

    def test_known_resource_rejection_is_feedback_never_a_plan(self):
        self.proof(r'''
auto request=json(R"({"request_id":"r","identity":{"instance":"i","generation":"g","player":0,"day":1,"revision":1},"observation":{"resources":[0,0,0,0,17,0,10000]}})");
auto reply=json(R"({"protocol":2,"request_id":"r","identity":{"instance":"i","generation":"g","player":0,"day":1,"revision":1},"failure":{"code":"resource_commitments_exceed_available_funds","required":[0,0,0,0,20,0,10000],"available":[0,0,0,0,17,0,10000]},"usage":{"known":true,"input_tokens":100,"output_tokens":10}})");
require(controllerFailureFeedback(reply,request)["code"].String()=="resource_commitments_exceed_available_funds");
reply["identity"]["day"].Integer()=2;require(controllerFailureFeedback(reply,request).isNull());
reply["identity"]=request["identity"];reply["failure"]["available"][4].Integer()=18;require(controllerFailureFeedback(reply,request).isNull());
reply["failure"]["available"]=request["observation"]["resources"];reply["plan"]=json("{}");require(controllerFailureFeedback(reply,request).isNull());
''')
