"""Strategic visit and candidate contracts for player-wide keys; no game launch."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'.build/vcmi-nk3'
LIBRARY=ROOT/'.build/nk3-mac/bin/libvcmi.dylib'
@unittest.skipUnless((SOURCE/'Global.h').exists() and LIBRARY.exists(),'requires native headers/library')
class KeymasterAccessTest(unittest.TestCase):
    def proof(self,body):
        code=r'''
#include "Global.h"
#include "CampaignState.h"
#include "StrategicCandidates.h"
#include "NativePersistence.h"
#include <stdexcept>
using namespace nullkiller3;
JsonNode json(const std::string & t) {JsonParsingSettings p;p.strict=true;p.mode=JsonParsingSettings::JsonFormatMode::JSON;return JsonNode(t.data(),t.size(),p,"keymaster proof");}
void require(bool ok,const std::string & why) {if(!ok) throw std::runtime_error(why);}
int main(){
auto world=json(R"({"day":3,"player":0,"capabilities":["land"],"resources":[0,0,0,0,0,0,0],"heroes":[{"ref":"scout","army_value":500,"position":[0,0,0]}],"towns":[],"objects":[{"ref":"tent","kind":"keymaster_tent","owner":-1,"visible":true,"visited":false,"key_color":2,"key_owned":false,"position":[2,0,0]}],"forecasts":{"routes":[]}})");
auto plan=json(R"({"version":3,"revision":1,"approach":"scouting","horizon_days":3,"goals":[{"id":"get-key","kind":"visit_site","actor_ref":"scout","target_ref":"tent","deadline_day":5,"priority":85,"building_id":-1,"min_army_value":500,"depends_on":[],"required_capabilities":["land"],"complete_when":{"kind":"site_visited","value":0}}],"reserves":[],"policy":{"max_loss_ratio":0.1,"allow_route_repair":true,"allow_helper_replacement":false,"critical_towns":[]}})");
std::string reason;
''' + body+'\n}'
        with tempfile.TemporaryDirectory() as f:
            cpp=Path(f)/'proof.cpp';bin=Path(f)/'proof';cpp.write_text(code)
            includes=[SOURCE,SOURCE/'lib',SOURCE/'include',ROOT/'engine/Nullkiller3',next((ROOT/'.build/conan/p').glob('boost*/p/include'))]
            cmd=[os.environ.get('CXX','c++'),'-std=c++20','-DVCMI_DLL=1','-DBOOST_ALL_DYN_LINK',*[f'-I{x}' for x in includes],str(cpp),str(ROOT/'engine/Nullkiller3/CampaignState.cpp'),str(LIBRARY),'-Wl,-rpath,'+str(LIBRARY.parent),'-o',str(bin)]
            r=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
            r=subprocess.run([str(bin)],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
    def test_tent_visit_is_executable_but_seeing_or_owning_key_is_not_visit_receipt(self):
        self.proof(r'''
CampaignState c;require(c.accept(plan,world,reason),reason);
c.review(world,false);require(c.statuses()["get-key"]["state"].String()!="completed","seeing tent completed visit");
world["objects"][0]["visited"].Bool()=true;world["objects"][0]["key_owned"].Bool()=true;
c.review(world,false);require(c.statuses()["get-key"]["state"].String()!="completed","another hero's key replaced assigned visit");
JsonNode receipt;receipt["goal"]=plan["goals"][0];receipt["day"].Integer()=3;world["confirmed_site_visits"].Vector().push_back(receipt);
c.review(world,false);require(c.statuses()["get-key"]["state"].String()=="completed","receipt not completed");
CampaignState restored(c.save());require(restored.restoreReason().empty(),restored.restoreReason());
''')
    def test_unlocked_border_is_offered_and_requires_actual_actor_eligibility(self):
        self.proof(r'''
auto & gate=world["objects"][0];gate["kind"].String()="border_guard";gate["key_owned"].Bool()=true;gate["eligible_hero_refs"].Vector().emplace_back("scout");
CampaignState c;require(c.accept(plan,world,reason),reason);
world["visible_objects"]=world["objects"];
auto quote=[&](const JsonNode &,bool,bool){return json(R"([{"hero_ref":"scout","day":4,"army_value":500,"army_loss_estimate":0,"movement_cost":1}])");};
auto candidates=generateTargetCandidates(world,JsonNode(),quote);
require(std::any_of(candidates["routes"].Vector().begin(),candidates["routes"].Vector().end(),[](const auto & r){return r["target_ref"].String()=="tent";}),"unlocked border omitted from offered routes");
gate["key_owned"].Bool()=false;CampaignState locked;require(!locked.accept(plan,world,reason),"wrong/missing key accepted");
gate["key_owned"].Bool()=true;gate["eligible_hero_refs"].Vector().clear();CampaignState extra;require(!extra.accept(plan,world,reason),"key bypassed extra native conditions");
''')
    def test_matching_colours_link_only_seen_tents_and_borders(self):
        self.proof(r'''
world["visible_objects"]=world["objects"];
auto gate=world["objects"][0];gate["ref"].String()="guard";gate["kind"].String()="border_guard";
world["visible_objects"].Vector().push_back(gate);
gate["ref"].String()="different";gate["key_color"].Integer()=3;world["visible_objects"].Vector().push_back(gate);
linkKeymasterSites(world);
require(world["visible_objects"][0]["matching_visible_refs"]==json(R"(["guard"])"),"colour mismatch/hidden relation");
require(world["visible_objects"][1]["matching_visible_refs"]==json(R"(["tent"])"),"reverse tent link missing");
require(world["visible_objects"][2]["matching_visible_refs"].Vector().empty(),"wrong colour matched");
''')
    def test_key_does_not_bypass_route_losses_or_prove_border_opening(self):
        self.proof(r'''
auto & gate=world["objects"][0];gate["kind"].String()="border_gate";gate["key_owned"].Bool()=true;gate["eligible_hero_refs"].Vector().emplace_back("scout");
world["forecasts"]["routes"]=json(R"([{"target_ref":"tent","own_arrivals":[{"hero_ref":"scout","day":4,"army_value":500,"army_loss_estimate":200}]}])");
CampaignState c;require(c.accept(plan,world,reason),reason);c.review(world);
require(c.statuses()["get-key"]["state"].String()=="blocked","key bypassed loss policy");
world["forecasts"]["routes"][0]["own_arrivals"][0]["army_loss_estimate"].Integer()=0;c.review(world);
require(c.statuses()["get-key"]["state"].String()=="ready","zero-loss route not offered");
require(c.statuses()["get-key"]["state"].String()!="completed","key alone proved opening");
JsonNode receipt;receipt["goal"]=plan["goals"][0];receipt["day"].Integer()=4;world["day"].Integer()=4;world["confirmed_site_visits"].Vector().push_back(receipt);
c.review(world);require(c.statuses()["get-key"]["state"].String()=="completed","gate receipt not completed");
CampaignState restored(c.save());require(restored.restoreReason().empty(),restored.restoreReason());
''')
    def test_empty_visit_end_needs_fresh_success_and_survives_checkpoint(self):
        self.proof(r'''
auto facts=json(R"({"kind":"keymaster_tent","actor_owned":true,"target_visible":true,"target_present":true,"visited_by_player":false,"actor_at_target":false,"entry_allowed":false})");
require(!keySiteVisitConfirmed(facts),"end callback falsely acquired key");
facts["visited_by_player"].Bool()=true;require(keySiteVisitConfirmed(facts),"real player key not confirmed");
facts["kind"].String()="border_guard";require(!keySiteVisitConfirmed(facts),"guard not yet removed counted complete");
facts["target_present"].Bool()=false;require(keySiteVisitConfirmed(facts),"fresh removed guard not confirmed");
facts["target_visible"].Bool()=false;require(!keySiteVisitConfirmed(facts),"fog absence counted as removal");
facts["target_visible"].Bool()=true;facts["target_present"].Bool()=true;facts["kind"].String()="border_gate";
require(!keySiteVisitConfirmed(facts),"gate end alone completed passage");
facts["actor_at_target"].Bool()=true;require(!keySiteVisitConfirmed(facts),"unpermitted gate counted entered");
facts["entry_allowed"].Bool()=true;require(keySiteVisitConfirmed(facts),"permitted gate entry not confirmed");
JsonNode saved;saved["object_ids"]=json(R"({"100":0})");
JsonNode event;event["goal"]=plan["goals"][0];event["day"].Integer()=4;event["kind"].String()="border_gate";event["target_id"].Integer()=100;
recordStrategicSiteVisit(saved,event);
auto loaded=restoreNativeNamespace(saved);
require(loaded["confirmed_border_visits"]["tent"].Integer()==4,"visit mark lost at checkpoint");
auto receipt=loaded["site_receipts"]["get-key"];require(receipt.Struct().size()==2,"callback metadata leaked into receipt");
world["confirmed_site_visits"].Vector().push_back(receipt);world["day"].Integer()=4;
CampaignState c;require(c.accept(plan,world,reason),reason);c.review(world,false);
require(c.statuses()["get-key"]["state"].String()=="completed","saved receipt not accepted");
saved["confirmed_border_visits"]["tent"].String()="invalid";
require(restoreNativeNamespace(saved)["confirmed_border_visits"].isNull(),"invalid saved mark trusted");
''')
if __name__=='__main__':unittest.main()
