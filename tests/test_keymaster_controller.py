"""Caller reply validation includes key collection and unlocked border visits."""
import copy
import unittest
from test_nullkiller3_controller import strategic_request
from controller.native_strategy import validate_reply

class KeymasterControllerTest(unittest.TestCase):
    def reply(self,request):
        return dict(protocol=2,request_id=request['request_id'],identity=request['identity'],decision='revise',
          reason='Unlock a known route with the player key',evidence_refs=['observation:day'],victory_method='Find conquest routes',
          assignments=[dict(hero_ref='object:0',role='scout')],
          alternatives=[dict(approach='scouting',benefit='Open route',cost='Movement',uncertainty='Exit'),dict(approach='economy',benefit='Income',cost='Delay',uncertainty='Route')],
          reconsider_when=[dict(goal_id='access',kind='deadline_missed')],
          plan=dict(version=3,revision=1,approach='scouting',horizon_days=3,
            goals=[dict(id='access',kind='visit_site',actor_ref='object:0',target_ref='key-site',deadline_day=3,priority=90,
              building_id=-1,min_army_value=5000,depends_on=[],required_capabilities=['land'],complete_when=dict(kind='site_visited',value=0))],
            reserves=[],policy=dict(max_loss_ratio=.1,allow_route_repair=True,allow_helper_replacement=False,critical_towns=[])))
    def test_tent_and_matching_unlocked_borders_are_supported(self):
        for kind in ('keymaster_tent','border_guard','border_gate'):
            r=strategic_request();site=dict(ref='key-site',kind=kind,owner=-1,visible=True,visited=False,key_color=2,
              key_owned=kind!='keymaster_tent',eligible_hero_refs=['object:0'])
            r['observation']['objects'].append(site);validate_reply(r,self.reply(r))
            for patch in ({'visible':False},{'visited':True}, {'key_owned':kind=='keymaster_tent'}):
                bad=copy.deepcopy(r);bad['observation']['objects'][-1].update(patch)
                with self.subTest(kind=kind,patch=patch),self.assertRaises(ValueError):validate_reply(bad,self.reply(bad))
            if kind!='keymaster_tent':
                r['observation']['heroes'].append(dict(ref='other',id=2,army_value=10))
                site['eligible_hero_refs']=['other']
                with self.assertRaises(ValueError):validate_reply(r,self.reply(r))
                site['eligible_hero_refs']=[]
                with self.assertRaises(ValueError):validate_reply(r,self.reply(r))
if __name__=='__main__':unittest.main()
