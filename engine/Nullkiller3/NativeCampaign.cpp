#include "../Nullkiller2/StdInc.h"
#include "NativeCampaign.h"
#include "KnownLandApproach.h"
#include "NativeTrace.h"
#include "Forecasts.h"
#include "NativePersistence.h"
#include "ReturnedHeroRecovery.h"
#include "../../lib/entities/artifact/CArtifactInstance.h"
#include "OffensivePreparation.h"
#include "StrategicCandidates.h"
#include "StrategicDecision.h"
#include "../../lib/StartInfo.h"
#include "../Nullkiller2/Markers/DefendTown.h"
#include "../../lib/mapObjects/IOwnableObject.h"
#include "../../lib/mapObjects/MiscObjects.h"
#include "../../lib/mapObjects/Quest.h"
#include "../ExternalAI/StrategyMemory.h"
#include "../ExternalAI/ObservationRules.h"
#include "../Nullkiller2/Engine/Nullkiller.h"
#include "../Nullkiller2/AIGateway.h"
#include "../Nullkiller2/Behaviors/CaptureObjectsBehavior.h"
#include "../Nullkiller2/Behaviors/GatherArmyBehavior.h"
#include "../Nullkiller2/Goals/RecruitHero.h"
#include "../Nullkiller2/Goals/BuildThis.h"
#include "../Nullkiller2/Goals/BuyArmy.h"
#include "../Nullkiller2/Goals/ExecuteHeroChain.h"
#include "../Nullkiller2/Goals/Composition.h"
#include "../../lib/CPlayerState.h"
#include "../../lib/gameState/CGameState.h"
#include "../../lib/entities/building/CBuilding.h"
#include "../../lib/entities/hero/CHero.h"
#include "../../lib/battle/CombatValue.h"
#include "../../lib/mapping/CMap.h"
#include "../TransportJSON/TransportJSON.h"
#include <fstream>
#include <cmath>
#include <cstdlib>

namespace nullkiller3
{
void NativeCampaign::writeLearningEvent(JsonNode event)
{
    const auto * path=std::getenv("VCMI_NK3_LEARNING_JOURNAL");
    if(!path || !*path) return;
    std::lock_guard ownLock(learningMutex);
    event["version"].Integer()=1;
    event["game"].String()=experienceID;
    event["generation"].String()=generation;
    event["sequence"].Integer()=++learningSequence;
    event["complete"].Bool()=true;
    // One shared append owner prevents two NK3 players interleaving JSON lines.
    static std::mutex journalMutex;
    std::lock_guard journalLock(journalMutex);
    try
    {
        const auto raw=ai_transport::transportJSON(event.toCompactString());
        if(raw.size()>512*1024) throw std::runtime_error("own learning event exceeds journal budget");
        std::ofstream stream(path,std::ios::app);
        stream.exceptions(std::ios::badbit|std::ios::failbit);
        stream << raw << '\n';
    }
    catch(const std::exception & error) { logAi->warn("NK3 learning journal unavailable: %s",error.what()); }
}
void NativeCampaign::recordLearningExecution(const JsonNode & result)
{
    JsonNode event;
    event["phase"].String()="execution";
    event["player"]=result["player"];
    event["day"]=result["day"];
    event["observation"]["player"]=event["player"];
    event["observation"]["day"]=event["day"];
    event["own_result"]=result;
    writeLearningEvent(event);
}
void NativeCampaign::recordLearningTurn(NK2AI::Nullkiller & ai,const std::string & phase)
{
    if(!std::getenv("VCMI_NK3_LEARNING_JOURNAL")) return;
    if(phase=="begin") { std::lock_guard lock(learningMutex);pendingLearningEnd=JsonNode(); }
    ai.aiGw->checkStrategicTurn();
    ai.updateState(); // Existing PlayerView and forecast owners; no GPT request.
    JsonNode event,observed;
    event["phase"].String()=phase;
    event["player"]=world["player"];event["day"]=world["day"];
    event["campaign"]=campaign.plan();
    event["reason"]=persisted["strategy_metadata"]["reason"];
    event["results"]=persisted["memory"]["recent_results"];
    for(const auto * field:{"day","player","resources","resource_order","daily_income","rules","heroes","towns","main_army_idle",
            "goal_statuses","confirmed_deliveries","observed_frontiers","observed_scout_areas","strategy_assignments"})
        observed[field]=world[field];
    for(auto & town:observed["towns"].Vector())
        for(const auto * field:{"building_options","recruitment","recruitment_options"}) town.Struct().erase(field);
    observed["execution_mechanism"].String()="native_campaign_v3";
    observed["opportunities"].Vector();observed["opportunities_complete"].Bool()=true;
    auto add=[&](const JsonNode & route,const JsonNode & target,const std::string & kind,const std::string & category)
    {
        if(observed["opportunities"].Vector().size()>=32)
        { observed["opportunities_complete"].Bool()=false;return; }
        JsonNode option;
        option["actor_ref"]=route["hero_ref"];option["target_ref"]=target;
        option["kind"].String()=kind;option["category"].String()=category;
        option["arrival_day"]=route["day"];option["route"]=route;
        bool defenseConflict=false;
        for(const auto & defense:world["forecasts"]["defenses"].Vector())
            if(defense["critical"].Bool() && defense["scenario_deadline_day"].Integer()<=route["day"].Integer())
                for(const auto & actor:defense["allocated_hero_refs"].Vector()) defenseConflict |= actor==route["hero_ref"];
        option["available"].Bool()=!defenseConflict;
        option["constraints_checked"].Bool()=!defenseConflict;
        option["expected_effect"].String()=kind=="scout" ? "resolve an observed information frontier; discoveries unknown" : "known target ownership and production; capture not guaranteed";
        if(kind=="capture_mine")
        {
            option["produced_resource"]=JsonNode();option["base_production_per_day"]=JsonNode();
            const auto * mine=dynamic_cast<const CGMine *>(resolve(ai,target));
            // An unflagged abandoned mine's randomly selected resource is hidden.
            if(mine && (!mine->isAbandoned() || mine->getOwner()!=PlayerColor::NEUTRAL))
            {
                const auto resource=mine->producedResource.getNum();
                if(resource>=0 && resource<7)
                {
                    option["produced_resource"].String()=GameConstants::RESOURCE_NAMES[resource];
                    option["base_production_per_day"].Integer()=mine->defaultResProduction();
                }
            }
            option["production_basis"].String()="Public mine type/base rules; future capture and own income modifiers remain conditional.";
        }
        option["competing_commitments"]=campaign.plan()["goals"];
        option["defense_context"].Vector();
        for(const auto & defense:world["forecasts"]["defenses"].Vector())
        {
            JsonNode summary;
            for(const auto * field:{"town_ref","critical","status","scenario_deadline_day","allocated_hero_refs","garrison_value","conditional_force_value"}) summary[field]=defense[field];
            option["defense_context"].Vector().push_back(summary);
        }
        observed["opportunities"].Vector().push_back(option);
    };
    for(const auto & target:world["offensive_preparation"]["targets"].Vector())
    {
        std::string kind;
        for(const auto & object:world["visible_objects"].Vector()) if(object["ref"]==target["target_ref"])
        {
            if(object["owner"]==world["player"]) continue;
            if(object["kind"].String()=="mine") kind="capture_mine";
            if(object["kind"].String()=="town") kind="capture_town";
        }
        if(kind.empty()) continue;
        for(const auto & route:target["current_routes"].Vector())
            if(route["issues"].isVector() && route["issues"].Vector().empty() && route["meets_deadline"].Bool())
                add(route,target["target_ref"],kind,kind=="capture_mine" ? "economy" : "combat");
    }
    observed["scouting_blocked"].Bool()=world["main_army_idle"]["reason"].String()=="no_safe_route";
    for(const auto & area:world["scouting_options"].Vector()) for(const auto & route:area["own_arrivals"].Vector())
    {
        const auto army=route["army_value"].Integer(),loss=route["army_loss_estimate"].Integer();
        const auto floor=campaign.exchangeForce(route["hero_ref"].String(),world,helperSources());
        bool defending=false;
        for(const auto & defense:world["forecasts"]["defenses"].Vector())
            if(defense["critical"].Bool() && defense["scenario_deadline_day"].Integer()<=world["day"].Integer()+1)
                for(const auto & actor:defense["allocated_hero_refs"].Vector()) defending |= actor==route["hero_ref"];
        if(!defending && army>0 && loss<=army*campaign.plan()["policy"]["max_loss_ratio"].Float()
            && loss<=army && army-loss>=floor && route["expected_new_tiles"].Integer()>0)
            add(route,area["ref"],"scout","exploration");
    }
    event["observation"]=observed;
    if(phase=="end")
    {
        // Publish completion only after the server's playerEndsTurn callback.
        std::lock_guard lock(learningMutex);pendingLearningEnd=event;
    }
    else writeLearningEvent(event);
}
void NativeCampaign::finishLearningTurn()
{
    JsonNode event;
    { std::lock_guard lock(learningMutex);event=pendingLearningEnd;pendingLearningEnd=JsonNode(); }
    if(!event.isNull()) writeLearningEvent(event);
}
namespace
{
class PrepareGarrison final : public NK2AI::Goals::ElementarGoal<PrepareGarrison>
{
    int64_t required, retained;
    std::string mode;
public:
    PrepareGarrison(const CGTownInstance * target,const CGHeroInstance * source,int64_t defense,int64_t keep,const std::string & method)
        : ElementarGoal(NK2AI::Goals::BUY_ARMY),required(defense),retained(keep),mode(method)
    { town=target;hero=source; }
    bool operator==(const PrepareGarrison & other) const override
    { return town==other.town && hero==other.hero && required==other.required && retained==other.retained && mode==other.mode; }
    std::string toString() const override { return "Prepare separate town garrison"; }
    void accept(NK2AI::AIGateway * gateway) override
    {
        auto & ai=*gateway->nullkiller;
        const auto floor=std::max<int64_t>(retained,ai.strategicCampaign->forceReserve(hero));
        if(town->getOwner()!=ai.playerID || hero->getOwner()!=ai.playerID || hero->getVisitedTown()!=town
            || hero->estimateCombatValue()<floor)
            throw NK2AI::cannotFulfillGoalException("Garrison participants changed");
        if(town->getGarrisonHero()==hero)
        {
            if(town->getVisitingHero()) throw NK2AI::cannotFulfillGoalException("Town visitor occupies exit");
            gateway->checkStrategicTurn();ai.cc->swapGarrisonHero(town);
        }
        if(town->getVisitingHero()!=hero)
            throw NK2AI::cannotFulfillGoalException("Separate garrison unavailable");
        const auto * defense=town->getUpperArmy();
        if(defense==hero) throw NK2AI::cannotFulfillGoalException("Garrison aliases departing hero");
        // Recruit into the stationary town pool, never into the departing hero.
        const auto stock=ai.armyManager->getArmyAvailableToBuy(defense,town,ai.getFreeResources());
        if(mode!="detach") for(const auto & unit:stock)
        {
            const auto current=defense->estimateCombatValue();
            if(current>=required) break;
            const auto power=unit.creID.toCreature()->getAIValue();
            if(!power || !defense->getSlotFor(unit.creID).validSlot()) continue;
            const auto count=std::min<int64_t>(unit.count,(required-current+power-1)/power);
            if(count<=0) continue;
            gateway->checkStrategicTurn();ai.cc->recruitCreatures(town,defense,unit.creID,count,unit.level);
        }
        // Whole creatures only; preserve every active source obligation too.
        std::vector<SlotID> slots;
        for(const auto & entry:hero->Slots()) slots.push_back(entry.first);
        std::sort(slots.begin(),slots.end(),[&](SlotID a,SlotID b) {
            return hero->getStack(a).estimateCombatValue()/hero->getStackCount(a)
                < hero->getStack(b).estimateCombatValue()/hero->getStackCount(b);
        });
        if(mode!="recruit") for(const auto sourceSlot:slots)
        {
            if(defense->estimateCombatValue()>=required) break;
            if(!hero->hasStackAtSlot(sourceSlot)) continue;
            const auto count=hero->getStackCount(sourceSlot);
            const auto strength=hero->estimateCombatValue();
            const auto power=hero->getStack(sourceSlot).estimateCombatValue()/count;
            const auto destination=defense->getSlotFor(hero->getCreature(sourceSlot));
            if(!power || !destination.validSlot() || strength<=floor) continue;
            auto moved=std::min<int64_t>(count,std::min<int64_t>((strength-floor)/power,
                (required-defense->estimateCombatValue()+power-1)/power));
            if(hero->needsLastStack() && hero->stacksCount()==1) moved=std::min<int64_t>(moved,count-1);
            if(moved<=0) continue;
            gateway->checkStrategicTurn();
            if(moved==count) ai.cc->mergeOrSwapStacks(hero,defense,sourceSlot,destination);
            else ai.cc->splitStack(hero,defense,sourceSlot,destination,defense->getStackCount(destination)+moved);
        }
        if(defense->estimateCombatValue()<required || hero->estimateCombatValue()<floor)
            throw NK2AI::cannotFulfillGoalException("Garrison floor not reached");
        ai.unlockHero(hero);
    }
};
size_t unseenInArea(const CCallback & callback,const int3 & position,int radius,PlayerColor player)
{
    FowTilesType hidden;
    callback.getTilesInRange(hidden,position,radius,ETileVisibility::HIDDEN,player);
    return hidden.size();
}
JsonNode resourceValues(const TResources & values)
{
    JsonNode result;
    for(int index = 0; index < 7; ++index) result.Vector().emplace_back(values[GameResID(index)]);
    return result;
}
JsonNode armyUnits(const CArmedInstance * army)
{
    JsonNode result;result.Vector();
    for(const auto & [slot,stack]:army->Slots())
    {
        const auto count=army->getStackCount(slot);
        if(count<=0) continue;
        JsonNode unit;unit["count"].Integer()=count;
        unit["creature"].Integer()=army->getCreature(slot)->getId().getNum();
        unit["unit_value"].Integer()=stack->estimateCombatValue()/count;
        result.Vector().push_back(unit);
    }
    return result;
}
bool canOpenKeyBorder(const CGObjectInstance * object,const CGHeroInstance * hero)
{
    if(object->ID==Obj::BORDER_GATE) return object->passableFor(hero);
    if(object->ID!=Obj::BORDERGUARD) return false;
    const auto * source=object->asQuestSource();
    const auto * quest=source ? source->getActiveQuest() : nullptr;
    return quest && quest->checkQuest(hero);
}
std::string objectKind(const CGObjectInstance * object)
{
    switch(object->ID.toEnum())
    {
    case Obj::TOWN: return "town";
    case Obj::HERO: return "hero";
    case Obj::MINE: return "mine";
    case Obj::RESOURCE: return "resource";
    case Obj::SUBTERRANEAN_GATE: return "subterranean_gate";
    case Obj::KEYMASTER: return "keymaster_tent";
    case Obj::BORDERGUARD: return "border_guard";
    case Obj::BORDER_GATE: return "border_gate";
    case Obj::MONSTER: return "monster";
    case Obj::SCHOLAR: return "scholar";
    case Obj::TREASURE_CHEST: return "treasure_chest";
    case Obj::OBELISK: return "obelisk";
    case Obj::GARRISON:
    case Obj::GARRISON2: return "garrison";
    case Obj::BOAT: return "boat";
    case Obj::SHIPYARD: return "shipyard";
    default: return "other";
    }
}
bool safeStabilizationPath(const NK2AI::AIPath & path,const CGHeroInstance * actor,const NK2AI::Nullkiller & ai)
{
    if(path.targetHero!=actor || path.getTotalArmyLoss() || path.getTotalDanger()
        || path.exchangeCount>1 || path.getFirstBlockedAction()) return false;
    for(const auto & node:path.nodes)
        if(node.targetHero!=actor || node.layer!=EPathfindingLayer::LAND || node.specialAction
            || !ai.cc->isVisible(node.coord)) return false;
    return true;
}
}
NativeCampaign::NativeCampaign(const JsonNode & saved,const JsonNode & returnNamespaces) : persisted(restoreNativeNamespace(saved)), campaign(persisted["native_campaign"])
{
    // Validate the original namespace before adding independent callback facts.
    // A missing namespace must retain fresh-game budget semantics.
    persisted=restoreOwnHeroReturns(persisted,returnNamespaces);
    persisted["own_returned_heroes"]=restoreReturnedHeroes(persisted["own_returned_heroes"]);
    if(!campaign.restoreReason().empty()) logAi->warn("NK3 saved campaign discarded: %s", campaign.restoreReason());
    if(!saved.isNull() && persisted!=saved) logAi->debug("NK3 saved namespace validated before restoring intentions");
    externalai::initializeObjectAliases(persisted);
    experienceID=externalai::initializeExperience(persisted);
    acceptedRevision=campaign.plan()["revision"].Integer();
    if(acceptedRevision) acceptedLossRatio=campaign.plan()["policy"]["max_loss_ratio"].Float();
    persisted["observed_passages"].Vector();
    // Older saves already contain validated completed-crossing proofs. Their
    // actual geometry is player knowledge even after those goals are replaced.
    if(campaign.restoreReason().empty())
        for(const auto & goal:campaign.plan()["goals"].Vector())
            if(goal["kind"].String()=="explore_passage" && campaign.statuses()[goal["id"].String()]["state"].String()=="completed")
            {
                const auto & receipt=static_cast<const JsonNode &>(persisted)["native_campaign"]["passage_completions"][goal["id"].String()];
                recordObservedPassage(persisted["observed_passages"],receipt["from"],receipt["to"]);
            }
    restoreArbiter();
}
std::string NativeCampaign::reference(const CGObjectInstance * object)
{
    const auto alias = externalai::objectAlias(persisted["object_ids"], object->id.getNum());
    return "object:" + std::to_string(alias);
}
const CGObjectInstance * NativeCampaign::resolve(const NK2AI::Nullkiller & ai, const JsonNode & ref) const
{
    if(!ref.isString()) return nullptr;
    for(const auto & [id, alias] : persisted["object_ids"].Struct())
        if(externalai::objectReference(alias) == ref.String())
            return ai.cc->getObj(ObjectInstanceID(std::stoi(id)), false);
    return nullptr;
}
std::map<std::string,std::string> NativeCampaign::helperSources() const
{
    std::map<std::string,std::string> result;
    for(const auto & goal : campaign.plan()["goals"].Vector())
    {
        if(goal["kind"].String() != "reinforce_hero") continue;
        const auto & repair = persisted["local_repairs"][goal["id"].String()];
        if(repair["kind"].isString() && repair["kind"].String() == "helper_replaced"
            && repair["revision"] == campaign.plan()["revision"] && repair["from"] == goal["target_ref"]
            && repair["to"].isString())
            for(const auto & hero : world["heroes"].Vector())
                if(hero["ref"] == repair["to"]) result[goal["id"].String()] = repair["to"].String();
    }
    return result;
}
bool NativeCampaign::repairDeliverySources(NK2AI::Nullkiller & ai)
{
    if(!campaign.plan()["policy"]["allow_helper_replacement"].Bool()) return false;
    bool changed=false;
    for(const auto & goal:campaign.plan()["goals"].Vector())
    {
        if(goal["kind"].String()!="reinforce_hero" || !campaign.holdsCommitment(goal["id"].String())
            || world["day"].Integer()>goal["deadline_day"].Integer()) continue;
        const auto * actor=dynamic_cast<const CGHeroInstance *>(resolve(ai,goal["actor_ref"]));
        if(!actor || actor->getOwner()!=ai.playerID) continue;
        const auto sources=helperSources();
        const auto ref=sources.count(goal["id"].String()) ? JsonNode(sources.at(goal["id"].String())) : goal["target_ref"];
        const auto * original=resolve(ai,ref);
        // Keep the model's healthy named source. A local replacement must
        // still have an admitted delivery; ownership alone does not prove it.
        if(original && original->getOwner()==ai.playerID && !sources.count(goal["id"].String())) continue;
        const CGHeroInstance * target=nullptr;
        uint64_t bestSurplus=0;
        for(const auto * helper:ai.cc->getHeroesInfo())
        {
            if(helper==actor) continue;
            const auto commitments=campaign.participantGoals(reference(helper),sources,world);
            bool compatible=true;
            for(const auto & obligation:campaign.plan()["goals"].Vector())
                if(obligation["id"]!=goal["id"] && commitments.count(obligation["id"].String())
                    && obligation["kind"].String()!="preserve_force") compatible=false;
            if(!compatible) continue;
            const auto strength=helper->estimateCombatValue();
            const auto floor=campaign.exchangeForce(reference(helper),world,sources,goal["id"].String());
            const auto surplus=strength>floor ? strength-floor : 0;
            if(!surplus || actor->estimateCombatValue()+surplus<goal["complete_when"]["value"].Integer()) continue;
            auto prospectiveSources=sources;
            prospectiveSources[goal["id"].String()]=reference(helper);
            NK2AI::Goals::TGoalVec admitted;
            rememberTasks(admitted,deliveryTasks(ai,actor,helper,false,&prospectiveSources),goal,ai,&prospectiveSources);
            if(admitted.empty()) continue;
            if(helper==original) { target=helper;break; } // Retain a feasible replacement without churn.
            if(surplus>bestSurplus) { target=helper;bestSurplus=surplus; }
        }
        if(!target)
        {
            if(sources.count(goal["id"].String()))
            { persisted["local_repairs"].Struct().erase(goal["id"].String());changed=true; }
            continue;
        }
        if(sources.count(goal["id"].String()) && sources.at(goal["id"].String())==reference(target)) continue;
        JsonNode repair;repair["day"]=world["day"];repair["goal"]=goal["id"];repair["revision"]=campaign.plan()["revision"];
        repair["kind"].String()="helper_replaced";repair["from"]=goal["target_ref"];repair["to"].String()=reference(target);
        persisted["local_repairs"][goal["id"].String()]=repair;changed=true;
    }
    return changed;
}
NK2AI::Goals::TGoalVec NativeCampaign::deliveryTasks(NK2AI::Nullkiller & ai,const CGHeroInstance * actor,const CGObjectInstance * target,
    bool collectFromTown,const std::map<std::string,std::string> * prospectiveSources) const
{
    using namespace NK2AI;
    if(!actor || !target) return {};
    Goals::TGoalVec generated;
    if(!collectFromTown) generated=Goals::GatherArmyBehavior(actor,target,prospectiveSources).decompose(&ai);
    if(const auto * helper=dynamic_cast<const CGHeroInstance *>(target))
        if(directDeliveryValue(actor,helper,prospectiveSources)>0)
        {
            auto paths=ai.pathfinder->getPathInfo(helper->visitablePos(),false);
            std::erase_if(paths,[&](const AIPath & path){return !safeStabilizationPath(path,actor,ai);});
            auto pickup=Goals::CaptureObjectsBehavior::getVisitGoals(paths,&ai,helper,true);
            generated.insert(generated.end(),pickup.begin(),pickup.end());
        }
    if(collectFromTown) if(const auto * town=dynamic_cast<const CGTownInstance *>(target))
    {
        auto paths=ai.pathfinder->getPathInfo(town->visitablePos(),false);
        std::erase_if(paths,[&](const AIPath & path){return path.targetHero!=actor;});
        generated=Goals::CaptureObjectsBehavior::getVisitGoals(paths,&ai,town,true);
    }
    if(generated.empty())
    {
        if(const auto * helper=dynamic_cast<const CGHeroInstance *>(target))
        {
            generated=repairRoute(ai,helper,actor);
            if(generated.empty()) generated=repairRoute(ai,actor,helper);
        }
        else generated=repairRoute(ai,actor,target);
    }
    return generated;
}
bool NativeCampaign::locallyRepairedCourierLoss(NK2AI::Nullkiller & ai,const std::string & lost)
{
    for(const auto & hero:world["heroes"].Vector()) if(hero["ref"].String()==lost) return false;
    for(const auto & assignment:persisted["strategy_metadata"]["assignments"].Vector())
        if(assignment["hero_ref"].String()==lost && assignment["role"].String()=="main") return false;
    const auto sources=helperSources();bool affected=false;
    for(const auto & goal:campaign.plan()["goals"].Vector())
    {
        if(!campaign.holdsCommitment(goal["id"].String())) continue;
        if(goal["actor_ref"].isString() && goal["actor_ref"].String()==lost) return false;
        if(goal["kind"].String()!="reinforce_hero" || goal["target_ref"].String()!=lost) continue;
        affected=true;
        if(!sources.count(goal["id"].String()) || world["day"].Integer()>goal["deadline_day"].Integer()) return false;
        const auto * actor=dynamic_cast<const CGHeroInstance *>(resolve(ai,goal["actor_ref"]));
        const auto * source=dynamic_cast<const CGHeroInstance *>(resolve(ai,JsonNode(sources.at(goal["id"].String()))));
        if(!actor || !source || actor->getOwner()!=ai.playerID || source->getOwner()!=ai.playerID) return false;
        const auto floor=campaign.exchangeForce(sources.at(goal["id"].String()),world,sources,goal["id"].String());
        const auto strength=source->estimateCombatValue();
        if(actor->estimateCombatValue()+(strength>floor ? strength-floor : 0)<goal["complete_when"]["value"].Integer()) return false;
        for(const auto & dependency:goal["depends_on"].Vector())
        {
            if(world["goal_statuses"][dependency.String()]["state"].String()=="completed") continue;
            bool scheduled=false;
            for(const auto & commitment:world["forecasts"]["commitments"].Vector())
                if(commitment["goal_id"]==dependency && commitment["status"].String()=="conditional"
                    && commitment["build_day"].isNumber() && commitment["build_day"].Integer()<=goal["deadline_day"].Integer()) scheduled=true;
            if(!scheduled) return false;
        }
        NK2AI::Goals::TGoalVec admitted;
        rememberTasks(admitted,deliveryTasks(ai,actor,source),goal,ai);
        if(admitted.empty() && !supportedDeliveryWait(world["forecasts"],goal,world["day"].Integer())) return false;
    }
    return affected;
}
void NativeCampaign::resourceVisit(const CGHeroInstance * hero, const CGObjectInstance * object, bool start)
{
    if(!hero) return;
    std::lock_guard lock(visitMutex);
    const int actor = hero->id.getNum();
    if(start)
    {
        if(object && object->ID == Obj::RESOURCE) resourceVisits[actor] = object->id.getNum();
        else resourceVisits.erase(actor);
        passageVisits.erase(actor);
        siteVisits.erase(actor);
        if(object && actor==activeSiteActor && object->id.getNum()==activeSiteObject && !activeSiteGoal.isNull())
        {
            JsonNode event;event["goal"]=activeSiteGoal;event["day"].Integer()=activeSiteDay;
            event["target_id"].Integer()=object->id.getNum();event["kind"].String()=objectKind(object);
            event["position"]=coordinate(object->visitablePos());
            event["entry_allowed"].Bool()=object->ID==Obj::BORDER_GATE && canOpenKeyBorder(object,hero);
            siteVisits[actor]=event;
        }
        if(object && object->ID==Obj::SUBTERRANEAN_GATE)
        {
            JsonNode receipt;receipt["from"]=coordinate(object->visitablePos());
            if(actor==activePassageActor && object->id.getNum()==activePassageEntry && !activePassageGoal.isNull())
            { receipt["goal"]=activePassageGoal;receipt["day"].Integer()=activePassageDay; }
            passageVisits[actor]=receipt;
        }
    }
    else
    {
        const auto found = resourceVisits.find(actor);
        // A resource disappearing at the end of our visit is confirmed by
        // the engine event, rather than by unrelated income or fog absence.
        if(found != resourceVisits.end())
        {
            if(!object) completedResourceVisits.push_back(found->second);
            resourceVisits.erase(found);
        }
        const auto site=siteVisits.find(actor);
        if(site!=siteVisits.end())
        {
            endedSiteVisits.push_back(site->second);
            siteVisits.erase(site);
        }
        const auto passage=passageVisits.find(actor);
        if(passage!=passageVisits.end())
        {
            if(passage->second["from"][2].Integer()!=hero->visitablePos().z)
            {
                auto receipt=passage->second;receipt["to"]=coordinate(hero->visitablePos());
                completedPassageVisits.push_back(receipt);
            }
            passageVisits.erase(passage);
        }
    }
}
void NativeCampaign::applySiteObservations(NK2AI::Nullkiller & ai)
{
    std::lock_guard lock(visitMutex);
    for(const auto & event:endedSiteVisits)
    {
        const auto * actor=dynamic_cast<const CGHeroInstance *>(resolve(ai,event["goal"]["actor_ref"]));
        const auto * target=ai.cc->getObj(ObjectInstanceID(event["target_id"].Integer()),false);
        const auto & pos=event["position"];
        const int3 position(pos[0].Integer(),pos[1].Integer(),pos[2].Integer());
        JsonNode facts;facts["kind"]=event["kind"];facts["entry_allowed"]=event["entry_allowed"];
        facts["actor_owned"].Bool()=actor && actor->getOwner()==ai.playerID;
        facts["target_visible"].Bool()=ai.cc->isVisible(position);
        facts["target_present"].Bool()=target!=nullptr;
        facts["visited_by_player"].Bool()=target && target->wasVisited(ai.playerID);
        facts["actor_at_target"].Bool()=actor && actor->visitablePos()==position;
        if(keySiteVisitConfirmed(facts)) recordStrategicSiteVisit(persisted,event);
    }
    endedSiteVisits.clear();
}
void NativeCampaign::applyPassageObservations()
{
    std::lock_guard lock(visitMutex);
    for(const auto & receipt:completedPassageVisits)
    {
        recordObservedPassage(persisted["observed_passages"],receipt["from"],receipt["to"]);
        if(receipt["goal"].isStruct()) persisted["passage_receipts"][receipt["goal"]["id"].String()]=receipt;
    }
    completedPassageVisits.clear();
}
void NativeCampaign::battleResult(JsonNode ownResult)
{
    ownResult["enemy_engine_object_id"].Integer()=observedBattleEnemy.exchange(-1);
    ownResult["goal_id"].String()=executingGoal();
    ownResult["campaign_revision"].Integer()=acceptedRevision.load();
    // The callback uses only immutable own result facts and atomic accepted
    // policy. The turn worker consumes the flag after mandatory battle queries
    // finish, before any subsequent movement or composition subtask.
    const auto before=ownResult["army_value_before"].Integer();
    const auto loss=ownResult["army_loss_value"].Integer();
    if(executionActive && acceptedRevision && before>0
        && ((!ownResult["won"].Bool() && !ownResult["draw"].Bool())
            || loss>before*acceptedLossRatio.load())) replanAfterCombat=true;
    std::lock_guard lock(visitMutex);
    completedBattles.push_back(std::move(ownResult));
}
void NativeCampaign::terminalResult(int player,int day,bool won)
{
    if(terminalRecorded.exchange(true)) return;
    {
        // Interface callbacks run after the pack's game-state lock is released.
        // Exclude the turn worker while assigning result sequences/own aliases.
        // An opponent-turn defeat has no subsequent own turn to drain this queue.
        // No game command or external exchange is performed under this lock.
        std::unique_lock lock(CGameState::mutex);
        applyBattleObservations();
        JsonNode event;
        event["phase"].String()="terminal";
        event["player"].Integer()=player;event["day"].Integer()=day;
        event["observation"]["player"]=event["player"];event["observation"]["day"]=event["day"];
        event["observation"]["terminal_result"].String()=won ? "win" : "loss";
        event["results"]=persisted["memory"]["recent_results"];
        writeLearningEvent(event);
    }
    JsonNode result;
    result["experience_id"].String()=experienceID;
    result["player"].Integer()=player;
    result["day"].Integer()=day;
    result["outcome"].String()=won ? "win" : "loss";
    // Own callback facts only. Postgame reflection is supervised outside the
    // engine after command cleanup; no model waits inside this callback.
    logAi->info("NK3_TERMINAL %s",result.toCompactString());
}
void NativeCampaign::applyBattleObservations()
{
    std::vector<JsonNode> observed;
    { std::lock_guard lock(visitMutex);observed.swap(completedBattles); }
    for(auto & action:observed)
    {
        recordOwnHeroReturn(persisted["own_returned_heroes"],action);
        const auto day=action["day"].Integer();
        const auto won=action["won"].Bool(),draw=action["draw"].Bool();
        const auto & aliases=static_cast<const JsonNode &>(persisted)["object_ids"].Struct();
        const auto found=aliases.find(std::to_string(action["engine_object_id"].Integer()));
        action["actor_ref"]=found==aliases.end() ? JsonNode() : JsonNode(externalai::objectReference(found->second));
        const auto enemy=action["enemy_engine_object_id"].Integer()<0 ? aliases.end()
            : aliases.find(std::to_string(action["enemy_engine_object_id"].Integer()));
        if(enemy!=aliases.end()) action["target_ref"].String()=externalai::objectReference(enemy->second);
        if(won && action["campaign_revision"]==campaign.plan()["revision"])
            for(const auto & goal:campaign.plan()["goals"].Vector())
                if(goal["kind"].String()=="intercept_hero" && goal["id"]==action["goal_id"]
                    && goal["actor_ref"]==action["actor_ref"] && goal["target_ref"]==action["target_ref"])
                {
                    JsonNode receipt;receipt["goal"]=goal;receipt["won"].Bool()=true;receipt["day"].Integer()=day;
                    persisted["confirmed_interceptions"].Vector().push_back(receipt);
                }
        action.Struct().erase("enemy_engine_object_id");
        for(const auto * field:{"engine_object_id","day","won","draw"}) action.Struct().erase(field);
        action["kind"].String()="battle";
        action["source"].String()="own_battle_result";
        externalai::recordResult(persisted["memory"],day,action,false);
        auto & result=persisted["memory"]["recent_results"].Vector().back();
        result["outcome"].String()=draw ? "battle_draw" : won ? "battle_won" : "battle_lost";
        JsonNode trace=result;
        trace["experience_id"].String()=experienceID;
        trace["player"]=action["player"];
        logAi->info("NK3_EXECUTION %s",trace.toCompactString());
        recordLearningExecution(trace);
    }
}
void NativeCampaign::forceChanged(const CGHeroInstance * hero, int day)
{
    if(!hero) return;
    const auto revision=acceptedRevision.load();
    if(!revision) return;
    std::lock_guard lock(visitMutex);
    const auto key=std::make_tuple(revision,day,hero->id.getNum());
    const auto value=hero->estimateCombatValue();
    const auto [item,inserted]=forceMinima.emplace(key,value);
    if(!inserted) item->second=std::min(item->second,value);
}
void NativeCampaign::applyForceObservations()
{
    std::map<std::tuple<int64_t,int,int>,uint64_t> observed;
    { std::lock_guard lock(visitMutex);observed.swap(forceMinima); }
    for(const auto & [key,value]:observed)
    {
        const auto [revision,day,id]=key;
        // A later strategy owns a new interval. A queued packet from the old
        // revision cannot invalidate the replacement intention.
        if(revision!=campaign.plan()["revision"].Integer()) continue;
        const auto & aliases=static_cast<const JsonNode &>(persisted)["object_ids"].Struct();
        const auto found=aliases.find(std::to_string(id));
        if(found==aliases.end()) continue;
        const auto ref=externalai::objectReference(found->second);
        if(!campaign.observeForceMinimum(ref,day,value)) continue;
        JsonNode action;
        action["kind"].String()="own_force_observation";
        action["hero_ref"].String()=ref;
        action["minimum_army_value"].Integer()=value;
        action["campaign_revision"].Integer()=revision;
        externalai::recordResult(persisted["memory"],day,action,false);
        persisted["memory"]["recent_results"].Vector().back()["outcome"].String()="force_floor_breached";
        world["goal_statuses"]=campaign.statuses();
    }
}
void NativeCampaign::recordDelivery(NK2AI::Nullkiller & ai, const CGHeroInstance * receiver, const CArmedInstance * source,
    uint64_t receiverBefore, uint64_t sourceBefore)
{
    if(!receiver || !source || receiver->getOwner()!=ai.playerID || source->getOwner()!=ai.playerID
        || receiver->estimateCombatValue()<=receiverBefore || source->estimateCombatValue()>=sourceBefore) return;
    const auto & aliases=static_cast<const JsonNode &>(persisted)["object_ids"].Struct();
    const auto a=aliases.find(std::to_string(receiver->id.getNum()));
    if(a==aliases.end()) return;
    const auto recipient=externalai::objectReference(a->second);
    std::set<std::string> donors;
    if(const auto b=aliases.find(std::to_string(source->id.getNum()));b!=aliases.end()) donors.insert(externalai::objectReference(b->second));
    for(const auto * town:ai.cc->getTownsInfo())
        if(town->getUpperArmy()==source) donors.insert(reference(town));
    JsonNode transfer;transfer["kind"].String()="army_transfer";
    transfer["recipient_ref"].String()=recipient;transfer["source_refs"].Vector();
    for(const auto & donor:donors) transfer["source_refs"].Vector().emplace_back(donor);
    transfer["recipient_before"].Integer()=receiverBefore;transfer["recipient_after"].Integer()=receiver->estimateCombatValue();
    transfer["source_before"].Integer()=sourceBefore;transfer["source_after"].Integer()=source->estimateCombatValue();
    transfer["affected_operations"].Vector();
    for(const auto & goal:campaign.plan()["goals"].Vector())
        if(goal["actor_ref"].isString() && donors.count(goal["actor_ref"].String())
            && campaign.holdsCommitment(goal["id"].String())
            && (goal["kind"].String()=="capture_target" || goal["kind"].String()=="secure_resource")
            && source->estimateCombatValue()<goal["min_army_value"].Integer())
            transfer["affected_operations"].Vector().push_back(operationIdentity(goal));
    externalai::recordResult(persisted["memory"],world["day"].Integer(),transfer,false);
    persisted["memory"]["recent_results"].Vector().back()["outcome"].String()="transfer_observed";
    for(const auto & goal:campaign.plan()["goals"].Vector())
        if(goal["kind"].String()=="reinforce_hero" && goal["actor_ref"].String()==recipient
            && donors.count(campaign.deliverySource(goal,helperSources()))
            && campaign.participantGoals(recipient,helperSources(),world).count(goal["id"].String())
            && receiverBefore<goal["complete_when"]["value"].Integer()
            && receiver->estimateCombatValue()>=goal["complete_when"]["value"].Integer())
        {
            JsonNode receipt;
            receipt["goal"]=goal; receipt["day"]=world["day"];
            receipt["source_ref"].String()=campaign.deliverySource(goal,helperSources());
            receipt["recipient_after"].Integer()=receiver->estimateCombatValue();
            receipt["source_after"].Integer()=source->estimateCombatValue();
            persisted["delivery_receipts"][goal["id"].String()]=receipt;
            // Commands are acknowledged before this callback records the
            // result. Save it before closing the exchange query, so an ordinary
            // save cannot lose a completed handoff awaiting the next pass.
            persist(ai);
        }
}
void NativeCampaign::observe(NK2AI::Nullkiller & ai)
{
    applyBattleObservations();
    // A returned hero stays urgent only while this exact own instance remains
    // in the player-visible tavern roster. Do not inspect the global hero pool.
    bool rosterObservable=false;
    std::set<std::pair<int,int>> availableReturns;
    for(const auto * town:ai.cc->getTownsInfo())
        if(town->getOwner()==ai.playerID && town->hasBuilt(BuildingID::TAVERN))
        {
            rosterObservable=true;
            for(const auto * candidate:ai.cc->getAvailableHeroes(town))
                if(candidate) availableReturns.emplace(candidate->getHeroTypeID().getNum(),candidate->id.getNum());
        }
    if(rosterObservable) std::erase_if(persisted["own_returned_heroes"].Struct(),[&](const auto & marker) {
        const bool expired=!availableReturns.count({static_cast<int>(marker.second["hero_type_id"].Integer()),static_cast<int>(marker.second["engine_object_id"].Integer())});
        if(expired) ai.cc->saveLocalState(consumedOwnHeroReturnUpdate(marker.second["hero_type_id"].Integer()));
        return expired;
    });
    world = JsonNode();
    world["day"].Integer() = ai.cc->getCalendar().getCurrentDay();
    world["player"].Integer() = ai.playerID.getNum();
    world["days_in_week"].Integer() = ai.cc->getCalendar().getDaysInWeek();
    TResources income;
    for(const auto * object : ai.cc->getMyObjects())
        if(const auto * ownable = object->asOwnable()) income += ownable->dailyIncome();
    world["daily_income"] = resourceValues(income);
    world["resources"] = resourceValues(ai.cc->getResourceAmount());
    {
        std::lock_guard lock(visitMutex);
        for(int id : completedResourceVisits)
        {
            const auto found = persisted["object_ids"].Struct().find(std::to_string(id));
            if(found != persisted["object_ids"].Struct().end())
                persisted["confirmed_resource_pickups"][externalai::objectReference(found->second)] = world["day"];
        }
        completedResourceVisits.clear();
    }
    applySiteObservations(ai);
    applyPassageObservations();
    world["confirmed_resource_pickups"].Vector();
    for(const auto & [ref, day] : persisted["confirmed_resource_pickups"].Struct())
        world["confirmed_resource_pickups"].Vector().emplace_back(ref);
    world["confirmed_passage_explorations"].Vector();
    auto & passageReceipts=persisted["passage_receipts"].Struct();
    std::erase_if(passageReceipts,[&](const auto & item) {
        return std::find(campaign.plan()["goals"].Vector().begin(),campaign.plan()["goals"].Vector().end(),item.second["goal"])
            ==campaign.plan()["goals"].Vector().end();
    });
    for(const auto & [id,receipt]:passageReceipts) world["confirmed_passage_explorations"].Vector().push_back(receipt);
    world["confirmed_interceptions"]=persisted["confirmed_interceptions"];
    world["confirmed_site_visits"].Vector();
    auto & siteReceipts=persisted["site_receipts"].Struct();
    std::erase_if(siteReceipts,[&](const auto & item) {
        return std::find(campaign.plan()["goals"].Vector().begin(),campaign.plan()["goals"].Vector().end(),item.second["goal"])
            ==campaign.plan()["goals"].Vector().end();
    });
    for(const auto & [id,receipt]:siteReceipts) world["confirmed_site_visits"].Vector().push_back(receipt);
    world["confirmed_helper_hires"].Vector();
    auto & hireReceipts=persisted["helper_hire_receipts"].Struct();
    std::erase_if(hireReceipts,[&](const auto & item) {
        return std::find(campaign.plan()["goals"].Vector().begin(),campaign.plan()["goals"].Vector().end(),item.second["goal"])
            ==campaign.plan()["goals"].Vector().end();
    });
    for(const auto & [id,receipt]:hireReceipts) world["confirmed_helper_hires"].Vector().push_back(receipt);
    world["confirmed_deliveries"].Vector();
    auto & receipts=persisted["delivery_receipts"].Struct();
    std::erase_if(receipts,[&](const auto & item) {
        return std::find(campaign.plan()["goals"].Vector().begin(),campaign.plan()["goals"].Vector().end(),item.second["goal"])
            ==campaign.plan()["goals"].Vector().end();
    });
    for(const auto & [id,receipt]:receipts) world["confirmed_deliveries"].Vector().push_back(receipt);

    externalai::observeStrategicRules(*ai.cc, ai.playerID, world);
    for(const auto * name : GameConstants::RESOURCE_NAMES) world["resource_order"].Vector().emplace_back(name);
    for(const auto * cap : {"land", "water", "build_boat", "build", "transfer"}) world["capabilities"].Vector().emplace_back(cap);
    world["unsupported_capabilities"].Vector();
    for(const auto * cap : {"teleport", "fly", "water_walk", "town_portal", "dimension_door"})
        world["unsupported_capabilities"].Vector().emplace_back(cap);
    world["movement_support"]["water"].String()="Current visible boats, known water tiles and legal embark/disembark. New sailing boats require an owned visible shipyard with all potential launch tiles visible, a current placement quote and available funds under the active goal. Summon/scuttle boat, airships, whirlpools and unobserved routes are unsupported.";
    world["movement_support"]["passages"].String()="Observed_passages records real own subterranean crossings. Offered whole routes may cross these learned pairs only while both ends are visible gates; their arrival/loss estimates cover the entire offered known route. explore_passage may visit a visible entrance with an unknown exit; an entry-only quote does not estimate that unknown exit or onward travel. Unlearned channels, other teleport types and teleport spells remain unsupported.";
    // These complete own lists, and visible object sorting, make aliases
    // independent of gaps and insertions in global hidden object IDs.
    world["heroes"].Vector();
    world["heroes"].Vector();
    world["towns"].Vector();
    for(const auto * hero : ai.cc->getHeroesInfo())
    {
        JsonNode item;
        item["ref"].String() = reference(hero);
        item["id"].Integer() = externalai::objectAlias(persisted["object_ids"], hero->id.getNum());
        item["position"] = coordinate(hero->visitablePos());
        item["in_boat"].Bool() = hero->inBoat();
        item["army_value"].Integer() = hero->estimateCombatValue();
        item["hero_type_id"].Integer() = hero->getHeroTypeID().getNum();
        item["army_units"]=armyUnits(hero);
        int64_t lastCreatureValue=0;
        if(hero->needsLastStack())
            for(const auto & [slot,stack]:hero->Slots())
            {
                const auto count=hero->getStackCount(slot);
                if(count<=0) continue;
                const auto unitValue=stack->estimateCombatValue()/count;
                if(!lastCreatureValue || unitValue<lastCreatureValue) lastCreatureValue=unitValue;
            }
        item["minimum_retained_army_value"].Integer()=lastCreatureValue;
        item["strength"]["army_ai_value"] = item["army_value"];
        item["strength"]["hero_multiplier"].Float()=hero->getHeroStrength();
        item["strength"]["hero_combat_value"].Integer()=hero->estimateHeroCombatValue();
        item["movement"].Integer() = hero->movementPointsRemaining();
        item["mana"].Integer() = hero->mana;
        item["movement_per_day"].Integer() = hero->movementPointsLimit();
        item["sight_radius"].Integer() = hero->getSightRadius();
        world["heroes"].Vector().push_back(item);
    }
    world["towns"].Vector();
    for(const auto * town : ai.cc->getTownsInfo())
    {
        JsonNode item;
        item["ref"].String() = reference(town);
        item["id"].Integer() = externalai::objectAlias(persisted["object_ids"], town->id.getNum());
        item["position"] = coordinate(town->visitablePos());
        item["defense_value"].Integer() = town->getUpperArmy()->estimateCombatValue();
        item["army_units"]=armyUnits(town->getUpperArmy());
        item["army_holder_ref"].String() = reference(town->getUpperArmy());
        if(const auto * visitor=town->getVisitingHero();visitor && visitor->getOwner()==ai.playerID)
            item["visiting_hero_ref"].String()=reference(visitor);
        item["daily_income"] = resourceValues(town->dailyIncome());
        item["hiring_options"].Vector();
        TResources hireCost;hireCost[EGameResID::GOLD]=GameConstants::HERO_GOLD_COST;
        const auto * visitor=town->getVisitingHero();
        const bool slotAvailable=helperHireSlotAvailable(ai,town);
        const bool explicitCanRecruit=town->hasBuilt(BuildingID::TAVERN) && !ai.heroManager->heroCapReached()
            && ai.cc->getResourceAmount(EGameResID::GOLD)>=GameConstants::HERO_GOLD_COST;
        const bool nativeCanRecruit=ai.heroManager->canRecruitHero(town);
        const bool hireFunds=ai.getFreeResources().canAfford(hireCost);
        for(const auto * candidate:ai.cc->getAvailableHeroes(town))
        {
            if(!candidate) continue;
            JsonNode option;
            option["hero_type_id"].Integer()=candidate->getHeroTypeID().getNum();
            option["ref"].String()="tavern:"+std::to_string(candidate->getHeroTypeID().getNum());
            option["name"].String()=candidate->getHeroType()->getNameTranslated();
            option["own_returned_hero"].Bool()=isOwnReturnedHero(persisted["own_returned_heroes"],candidate->getHeroTypeID().getNum(),candidate->id.getNum());
            option["level"].Integer()=candidate->level;
            option["primary_skills"].Vector();
            for(int skill=0;skill<4;++skill) option["primary_skills"].Vector().push_back(JsonNode(candidate->getPrimSkillLevel(PrimarySkill(skill))));
            option["secondary_skills"].Vector();
            for(const auto & [skill,level]:candidate->secSkills) if(skill!=SecondarySkill::NONE)
            {
                JsonNode entry;entry["skill_id"].Integer()=skill.getNum();entry["level"].Integer()=level;
                option["secondary_skills"].Vector().push_back(entry);
            }
            option["equipped_artifact_ids"].Vector();option["backpack_artifact_ids"].Vector();
            for(const auto & [slot,info]:candidate->artifactsWorn)
                if(const auto * artifact=info.getArt();artifact && !info.locked)
                    option["equipped_artifact_ids"].Vector().push_back(JsonNode(artifact->getTypeId().getNum()));
            for(const auto & info:candidate->artifactsInBackpack)
                if(const auto * artifact=info.getArt();artifact && !info.locked)
                    option["backpack_artifact_ids"].Vector().push_back(JsonNode(artifact->getTypeId().getNum()));
            option["army_value"].Integer()=candidate->estimateCombatValue();
            option["army_units"]=armyUnits(candidate);
            option["strength"]["army_ai_value"]=option["army_value"];
            option["strength"]["hero_multiplier"].Float()=candidate->getHeroStrength();
            option["strength"]["hero_combat_value"].Integer()=candidate->estimateHeroCombatValue();
            option["cost"]=resourceValues(hireCost);
            option["native_can_recruit"].Bool()=nativeCanRecruit;
            option["visiting_slot_available"].Bool()=slotAvailable;
            option["funds_available"].Bool()=hireFunds;
            option["can_recruit"].Bool()=explicitCanRecruit && slotAvailable && hireFunds;
            option["availability"].String()=!explicitCanRecruit ? "native_hiring_gate" : !slotAvailable ? "town_visiting_slot_occupied"
                : !hireFunds ? "funds_reserved" : visitor ? "allowed_with_safe_garrison_merge" : "allowed_now";
            if(visitor && slotAvailable)
            {
                auto & preparation=option["slot_preparation"];
                preparation["kind"].String()="merge_visiting_hero_into_garrison";
                preparation["hero_ref"].String()=reference(visitor);
                preparation["visiting_army_value"].Integer()=visitor->estimateCombatValue();
                preparation["stationary_army_value"].Integer()=town->estimateCombatValue();
                preparation["merged_army_value"].Integer()=visitor->estimateCombatValue()+town->estimateCombatValue();
                preparation["effect"].String()="Town troops join this visiting hero in the garrison; the helper keeps only its own starting army.";
            }
            item["hiring_options"].Vector().push_back(option);
        }
        item["recruitment_options"].Vector();
        for(size_t level=0;level<town->creatures.size();++level)
        {
            const auto & [amount, types] = town->creatures[level];
            if(types.empty()) continue;
            const auto * creature = LIBRARY->creh->objects[types.back().getNum()].get();
            JsonNode unit;
            unit["creature"].Integer()=types.back().getNum();
            unit["available"].Integer()=amount;
            unit["weekly_growth"].Integer()=town->creatureGrowth(level);
            unit["unit_value"].Integer()=LIBRARY->creh->getCombatValue().getAIValue(creature);
            unit["unit_cost"]=resourceValues(creature->getFullRecruitCost());
            item["recruitment_options"].Vector().push_back(unit);
        }
        item["buildings"].Vector();
        for(const auto & [building, info] : town->getTown()->buildings)
            if(town->hasBuilt(building)) item["buildings"].Vector().emplace_back(building.getNum());
        item["building_options"].Vector();
        for(const auto & [id, building] : town->getTown()->buildings)
        {
            JsonNode option;
            option["id"].Integer() = id.getNum();
            option["name"].String() = building->getNameTranslated();
            option["cost"] = resourceValues(building->resources);
            const auto availability = ai.cc->canBuildStructure(town, id);
            option["supported"].Bool() = building->mode == CBuilding::BUILD_NORMAL;
            option["state"].Integer() = static_cast<int>(availability);
            option["availability"].String() = building->mode == CBuilding::BUILD_NORMAL ? externalai::buildingAvailability(availability) : "unsupported_build_mechanic";
            option["production"] = resourceValues(building->produce);
            auto incomeDelta = building->produce;
            if(town->getTown()->buildings.count(building->upgrade)) incomeDelta -= town->getTown()->buildings.at(building->upgrade)->produce;
            incomeDelta.applyHandicap(ai.cc->getPlayerSettings(ai.playerID)->handicap.percentIncome);
            option["income_delta"] = resourceValues(incomeDelta);
            option["requirements"] = town->genBuildingRequirements(id,false).toJson([](BuildingID required) { return JsonNode(required.getNum()); });
            item["building_options"].Vector().push_back(option);
        }
        world["towns"].Vector().push_back(item);
    }
    auto objects = ai.cc->getAllVisitableObjs();
    std::ranges::sort(objects, [](const auto * a, const auto * b) {
        if(a->visitablePos() != b->visitablePos()) return a->visitablePos() < b->visitablePos();
        return a->ID < b->ID;
    });
    world["visible_objects"].Vector();
    world["shipyards"].Vector();
    for(const auto * object : objects)
    {
        JsonNode item;
        item["ref"].String() = reference(object);
        item["id"].Integer() = externalai::objectAlias(persisted["object_ids"], object->id.getNum());
        item["kind"].String() = objectKind(object);
        item["visible"].Bool()=true;
        if(object->ID==Obj::SCHOLAR || object->ID==Obj::TREASURE_CHEST || object->ID==Obj::OBELISK)
            item["visited"].Bool()=object->wasVisited(ai.playerID);
        if(keymasterObject(item))
        {
            item["key_color"].Integer()=object->subID.getNum();
            item["key_owned"].Bool()=ai.cc->getPlayerState(ai.playerID)->wasKeymasterVisited(object->subID);
            item["visited"].Bool()=object->ID==Obj::KEYMASTER ? object->wasVisited(ai.playerID)
                : !static_cast<const JsonNode &>(persisted)["confirmed_border_visits"][item["ref"].String()].isNull();
            item["eligible_hero_refs"].Vector();
            if(object->ID!=Obj::KEYMASTER)
                for(const auto * hero:ai.cc->getHeroesInfo())
                    if(canOpenKeyBorder(object,hero)) item["eligible_hero_refs"].Vector().emplace_back(reference(hero));
        }
        item["owner"].Integer() = object->getOwner().getNum();
        item["position"] = coordinate(object->visitablePos());
        item["army_value"].Integer() = observedArmyStrength(*ai.cc, object);
        item["army_interval"] = observedArmyInterval(*ai.cc,object);
        world["visible_objects"].Vector().push_back(item);
        if(const auto * shipyard=dynamic_cast<const IShipyard *>(object))
        {
            const auto place=observedBoatPlacement(*ai.cc,shipyard);
            if(place.isValid())
            {
                JsonNode quote;quote["ref"]=item["ref"];quote["boat_position"]=coordinate(place);
                TResources cost;shipyard->getBoatCost(cost);quote["cost"]=resourceValues(cost);
                world["shipyards"].Vector().push_back(quote);
            }
        }
    }
    linkKeymasterSites(world);
    JsonNode visiblePositions;
    world["frontiers"].Vector();
    world["frontier_options"].Vector();
    const auto size = ai.cc->getMapSize();
    for(int z = 0; z < size.z; ++z)
        for(int y = 0; y < size.y; ++y)
            for(int x = 0; x < size.x; ++x)
            {
                const int3 tile(x,y,z);
                if(!ai.cc->isVisible(tile)) continue;
                visiblePositions.Vector().push_back(coordinate(tile));
                const auto * terrain = ai.gameInfo().getTile(tile, false);
                if(!terrain->isLand() || terrain->blocked()) continue;
                bool frontier = false;
                for(const auto & direction : int3::getDirs())
                    if(ai.cc->isInTheMap(tile + direction) && !ai.cc->isVisible(tile + direction)) frontier = true;
                const std::string ref = "tile:" + coordinate(tile).toCompactString();
                if(frontier)
                {
                    world["frontiers"].Vector().emplace_back(ref);
                    persisted["frontier_positions"][ref] = coordinate(tile);
                    JsonNode item; item["ref"].String() = ref; item["position"] = coordinate(tile);
                    world["frontier_options"].Vector().push_back(item);
                }
            }
    world["observed_frontiers"].Vector();
    for(const auto & [ref, position] : persisted["frontier_positions"].Struct())
        if(std::find(world["frontiers"].Vector().begin(), world["frontiers"].Vector().end(), JsonNode(ref)) == world["frontiers"].Vector().end())
            world["observed_frontiers"].Vector().emplace_back(ref);
    world["observed_scout_areas"].Vector();
    for(const auto & goal:campaign.plan()["goals"].Vector())
    {
        if(goal["kind"].String()!="scout_area") continue;
        const auto & pos=static_cast<const JsonNode &>(persisted)["frontier_positions"][goal["target_ref"].String()];
        if(!pos.isVector() || pos.Vector().size()!=3) continue;
        const int3 center(pos[0].Integer(),pos[1].Integer(),pos[2].Integer());
        if(ai.cc->isVisible(center) && !unseenInArea(*ai.cc,center,goal["complete_when"]["value"].Integer(),ai.playerID))
        {
            JsonNode observed;observed["target_ref"]=goal["target_ref"];observed["sight_radius"]=goal["complete_when"]["value"];
            world["observed_scout_areas"].Vector().push_back(observed);
        }
    }
    JsonNode actions;
    actions.Vector();
    std::set<std::string> retainedTargets;
    for(const auto & goal : campaign.plan()["goals"].Vector())
    {
        const auto & status = campaign.statuses()[goal["id"].String()]["state"].String();
        if(status == "completed" || status == "cancelled") continue;
        retainedTargets.insert(goal["target_ref"].String());
        if(goal["kind"].String()=="hire_helper") retainedTargets.insert(goal["job_ref"].String());
        if(goal["actor_ref"].isString()) retainedTargets.insert(goal["actor_ref"].String());
        if(goal["kind"].String() == "reinforce_hero") retainedTargets.insert(campaign.deliverySource(goal,helperSources()));
    }
    externalai::observeMemory(persisted["memory"], world, actions, visiblePositions,retainedTargets);
    world["objects"].Vector();
    for(auto object : persisted["memory"]["known_objects"].Vector())
    {
        object["visible"].Bool() = !object["stale"].Bool() && !object["not_seen_at_last_position"].Bool();
        if(keymasterObject(object) && object["key_color"].isNumber())
        {
            object["key_owned"].Bool()=ai.cc->getPlayerState(ai.playerID)->wasKeymasterVisited(MapObjectSubID(object["key_color"].Integer()));
            if(!object["visible"].Bool()) object["eligible_hero_refs"].Vector().clear();
        }
        world["objects"].Vector().push_back(object);
    }
    applyBattleObservations();
    applyForceObservations();
    if(!executionActive && !persisted["pending_native_task"].isNull())
    {
        campaign.unconfirmedExecution(persisted["pending_native_task"]["before"]["day"].Integer());
        world["goal_statuses"]=campaign.statuses();
        endExecution(ai,"recovered_unknown");
    }
    world["goal_statuses"] = campaign.review(world,false);
    world["observed_passages"]=observedPassages();
    if(!seedRead && campaign.plan().isNull())
    {
        seedRead = true;
        // Deterministic integration input; it uses exactly the same atomic
        // value contract as a model reply, with no direct game commands.
        if(const auto * path = std::getenv("VCMI_NK3_SEED_CAMPAIGN"))
        {
            std::ifstream stream(path);
            std::string text((std::istreambuf_iterator<char>(stream)), {});
            if(text.size() <= 8192)
            {
                JsonParsingSettings parser; parser.strict = true; parser.mode = JsonParsingSettings::JsonFormatMode::JSON;
                JsonNode seed(text.data(), text.size(), parser, "NK3 integration campaign");
                std::string reason;
                if(!accept(seed, reason)) logAi->warn("NK3 campaign seed rejected: %s", reason);
                else world["goal_statuses"] = campaign.review(world,false);
            }
        }
    }
}
namespace
{
struct VisibleLandGraph
{
    std::map<int3,size_t> index;
    std::vector<KnownLandTile> land;
    JsonNode positions;
};
VisibleLandGraph visibleLandGraph(NK2AI::Nullkiller & ai,const JsonNode & world,
    const std::function<std::string(const CGObjectInstance *)> & objectReference)
{
    VisibleLandGraph graph;graph.positions.Vector();
    auto & index=graph.index;auto & land=graph.land;
    const auto size=ai.cc->getMapSize();
    const auto & view=ai.gameInfo();
    for(int z=0;z<size.z;++z) for(int y=0;y<size.y;++y) for(int x=0;x<size.x;++x)
    {
        const int3 position(x,y,z);
        if(!ai.cc->isVisible(position)) continue;
        const auto * tile=view.getTile(position,false);
        if(!tile || !tile->isLand() || !tile->entrableTerrain() || (tile->blocked() && !tile->visitable())) continue;
        KnownLandTile cell;
        for(const auto * guard:view.getGuardingCreatures(position))
            if(guard->ID==Obj::MONSTER && guard->getOwner()==PlayerColor::NEUTRAL)
                cell.neutralGuards.push_back(objectReference(guard));
        index.emplace(position,land.size());land.push_back(std::move(cell));
        graph.positions.Vector().push_back(coordinate(position));
    }
    // Occupied neutral garrisons block their visitable tile, not an adjacent
    // monster guard zone. Use the ordinary visible army interval, never hidden stacks.
    for(const auto & object:world["visible_objects"].Vector())
    {
        if(object["kind"].String()!="garrison" || object["owner"].Integer()!=PlayerColor::NEUTRAL.getNum()
            || object["army_interval"]["lower"].Integer()<=0) continue;
        const auto & pos=object["position"];
        const auto cell=index.find(int3(pos[0].Integer(),pos[1].Integer(),pos[2].Integer()));
        if(cell!=index.end()) land[cell->second].neutralGuards.push_back(object["ref"].String());
    }
    // Allow extra geometric edges rather than falsely proving a barrier from
    // directional entrances or private opponent abilities. Unknown stays unknown.
    for(const auto & [position,id]:index)
        for(int dy=-1;dy<=1;++dy) for(int dx=-1;dx<=1;++dx)
            if(dx || dy)
                if(const auto next=index.find(position+int3(dx,dy,0));next!=index.end())
                    land[id].neighbors.push_back(next->second);
    return graph;
}
JsonNode enemyApproaches(const JsonNode & world,const VisibleLandGraph & graph)
{
    const auto & index=graph.index;const auto & land=graph.land;
    JsonNode result;result.Vector();
    for(const auto & enemy:world["visible_objects"].Vector())
    {
        if(enemy["kind"].String()!="hero" || std::find(world["enemy_players"].Vector().begin(),world["enemy_players"].Vector().end(),enemy["owner"])==world["enemy_players"].Vector().end()) continue;
        const auto & pos=enemy["position"];
        const auto source=index.find(int3(pos[0].Integer(),pos[1].Integer(),pos[2].Integer()));
        if(source==index.end()) continue;
        for(const auto * kind:{"towns","heroes"}) for(const auto & asset:world[kind].Vector())
        {
            const auto & where=asset["position"];
            const auto target=index.find(int3(where[0].Integer(),where[1].Integer(),where[2].Integer()));
            if(target==index.end()) continue;
            auto approach=knownLandApproach(land,source->second,target->second);
            approach["source_ref"]=enemy["ref"];approach["target_ref"]=asset["ref"];
            approach["assumptions"].String()="Currently visible land connectivity only; directional entrances and other armies are ignored. Interior visible neutral guard zones and occupied neutral garrisons require an encounter on that connection; guards on the final attack tile alone provide no shield. Fog, water, spells, neutral encounter outcomes and enemy intent remain unknown.";
            result.Vector().push_back(approach);
        }
    }
    return result;
}
}
void NativeCampaign::updateForecasts(NK2AI::Nullkiller & ai)
{
    repairedSourcesChanged |= repairDeliverySources(ai);
    world["forecasts"] = forecastBranches(world,campaign.reservedResources());
    auto & forecasts=world["forecasts"];
    const auto landGraph=visibleLandGraph(ai,world,[&](const auto * object){return reference(object);});
    world["enemy_approaches"]=enemyApproaches(world,landGraph);
    forecasts["threats"]=forecastThreats(world);

    std::map<std::tuple<std::string,bool,bool>,JsonNode> arrivalQuotes;
    auto arrivals = [&](const JsonNode & pos, bool frontier, bool area=false) {
        const auto key=std::tuple{pos.toCompactString(),frontier,area};
        if(const auto known=arrivalQuotes.find(key);known!=arrivalQuotes.end()) return known->second;
        JsonNode result;result.Vector();
        const int3 position(pos[0].Integer(),pos[1].Integer(),pos[2].Integer());
        const auto paths=ai.pathfinder->getPathInfo(position,false);
        for(const auto * hero:ai.cc->getHeroesInfo())
        {
            CGPath ownPath;JsonNode routeNodes;routeNodes.Vector();
            const bool ownRoute=!(frontier || area) || ai.getPathsInfo(hero)->getPath(ownPath,position,EPathfindingLayer::LAND);
            if((frontier || area) && ownRoute && ownPath.nodes.size()>1)
                for(auto step=ownPath.nodes.rbegin()+1;step!=ownPath.nodes.rend();++step)
                {
                    JsonNode node;node["position"]=coordinate(step->coord);node["turn"].Integer()=step->turns;
                    node["interaction"].Bool()=step->action!=EPathNodeAction::NORMAL || step->layer!=EPathfindingLayer::LAND;
                    routeNodes.Vector().push_back(node);
                }
            for(const auto & path:paths)
            {
                if(path.targetHero!=hero || !path.heroArmy || path.getFirstBlockedAction()) continue;
                if(frontier && path.exchangeCount>1) continue;
                if(area && std::any_of(path.nodes.begin(),path.nodes.end(),[&](const auto & step) {
                    return step.layer!=EPathfindingLayer::LAND || !ai.cc->isVisible(step.coord);
                })) continue;
                bool single=true;
                for(const auto & step:path.nodes) single &= step.targetHero==hero;
                if(!single) continue;
                JsonNode arrival;
                arrival["hero_ref"].String()=reference(hero);
                arrival["day"].Integer()=world["day"].Integer()+path.turn();
                arrival["movement_cost"].Float()=path.movementCost();
                arrival["army_loss_estimate"].Integer()=path.getTotalArmyLoss();
                auto & loss=arrival["loss_estimate"];
                loss["path_component"].Integer()=path.armyLoss;
                loss["target_component"].Integer()=path.targetObjectArmyLoss;
                loss["basis"].String()="Native heuristic: cumulative path loss plus target loss using maximum visible danger along the path. Enemy count categories use upper bounds; unknown strength uses a safety sentinel. Not a battle simulation or win probability.";
                for(const auto * object : ai.cc->getVisitableObjs(position))
                    if(object->ID==Obj::HERO && object->getOwner()!=ai.playerID && ai.cc->isVisible(object))
                    {
                        const auto interval=observedArmyInterval(*ai.cc,object);
                        loss["visible_target_army_interval"]=interval;
                        if(interval["upper"].isNumber() && interval["upper"].Integer()>0
                            && path.targetObjectDanger==uint64_t(interval["upper"].Integer()))
                        {
                            auto & sensitivity=loss["enemy_count_sensitivity"];
                            for(const auto * key : {"lower","estimate","upper"})
                            {
                                const double ratio=interval[key].Integer()/double(interval["upper"].Integer());
                                sensitivity[key].Integer()=path.armyLoss+uint64_t(path.targetObjectArmyLoss*ratio*ratio);
                            }
                            sensitivity["assumptions"].String()="Conditional count sensitivity only: fixed path and own strength, this visible target dominates danger. Enemy bonuses, spells, retreat and movement unknown; not a guaranteed loss range or win probability.";
                        }
                    }

                arrival["army_value"].Integer()=path.heroArmy->estimateCombatValue();
                arrival["fighting_strength_estimate"].Integer()=path.getHeroStrength();
                if(frontier || area)
                {
                    // Native paths compress ordinary tiles into waypoints.
                    // Every retained waypoint must agree, in movement order,
                    // with the player route used by ordinary native movement.
                    JsonNode nativeWaypoints,playerWaypoints;nativeWaypoints.Vector();playerWaypoints.Vector();
                    for(auto node=path.nodes.rbegin();node!=path.nodes.rend();++node)
                    {
                        JsonNode waypoint;waypoint["position"]=coordinate(node->coord);waypoint["turn"].Integer()=node->turns;
                        nativeWaypoints.Vector().push_back(waypoint);
                    }
                    for(auto node=ownPath.nodes.rbegin();node!=ownPath.nodes.rend();++node)
                    {
                        JsonNode waypoint;waypoint["position"]=coordinate(node->coord);waypoint["turn"].Integer()=node->turns;
                        playerWaypoints.Vector().push_back(waypoint);
                    }
                    const bool ordinary=ownRoute && path.exchangeCount<=1
                        && std::all_of(path.nodes.begin(),path.nodes.end(),[&](const auto & node) {
                            return node.targetHero==hero && !node.specialAction && node.layer==EPathfindingLayer::LAND;
                        }) && scoutRouteCorresponds(nativeWaypoints,playerWaypoints);
                    arrival["end_turn_exposure"]=scoutStopExposure(coordinate(hero->visitablePos()),routeNodes,ordinary,world,landGraph.land,landGraph.positions);
                }
                if(std::find(result.Vector().begin(),result.Vector().end(),arrival)==result.Vector().end()) result.Vector().push_back(arrival);
            }
        }
        if(std::getenv("VCMI_NK3_ROUTE_DIAGNOSTICS"))
            for(const auto * hero:ai.cc->getHeroesInfo())
            {
                JsonNode trace;trace["day"]=world["day"];trace["target_position"]=pos;
                trace["hero_ref"].String()=reference(hero);trace["native_paths"].Integer()=0;
                trace["blocked_action_paths"].Integer()=0;trace["mixed_actor_paths"].Integer()=0;
                for(const auto & path:paths) if(path.targetHero==hero)
                {
                    ++trace["native_paths"].Integer();
                    if(path.getFirstBlockedAction()) ++trace["blocked_action_paths"].Integer();
                    if(std::any_of(path.nodes.begin(),path.nodes.end(),[&](const auto & node){return node.targetHero!=hero;}))
                        ++trace["mixed_actor_paths"].Integer();
                }
                const bool admitted=std::any_of(result.Vector().begin(),result.Vector().end(),[&](const auto & item){return item["hero_ref"].String()==reference(hero);});
                if(admitted) continue;
                CGPath ordinary;trace["ordinary_path_established"].Bool()=ai.getPathsInfo(hero)->getPath(ordinary,position,EPathfindingLayer::LAND);
                trace["state"].String()=trace["native_paths"].Integer()==0 ? "native_route_not_established" : "native_routes_filtered";
                logAi->info("NK3_ROUTE_DIAGNOSTICS %s",trace.toCompactString());
            }
        arrivalQuotes.emplace(key,result);
        return result;
    };
    // Select viewpoints and object objectives before asking the pathfinder for
    // detailed quotes. Required intentions retain their original destinations.
    auto screening=world;
    for(const auto & goal:campaign.plan()["goals"].Vector())
    {
        if(goal["kind"].String()!="scout_area" && goal["kind"].String()!="scout_frontier") continue;
        const auto & pos=static_cast<const JsonNode &>(persisted)["frontier_positions"][goal["target_ref"].String()];
        if(!pos.isVector() || pos.Vector().size()!=3) continue;
        if(std::none_of(screening["frontier_options"].Vector().begin(),screening["frontier_options"].Vector().end(),
            [&](const auto & option){return option["ref"]==goal["target_ref"];}))
        {
            JsonNode option;option["ref"]=goal["target_ref"];option["position"]=pos;
            screening["frontier_options"].Vector().push_back(option);
        }
    }
    const auto scouts=generateScoutCandidates(screening,campaign.plan(),[&](const JsonNode & pos,int radius) {
        FowTilesType hidden;
        ai.cc->getTilesInRange(hidden,int3(pos[0].Integer(),pos[1].Integer(),pos[2].Integer()),radius,ETileVisibility::HIDDEN,ai.playerID);
        std::set<std::string> result;
        for(const auto & tile:hidden) result.insert(coordinate(tile).toCompactString());
        return result;
    },arrivals);
    world["frontier_options"]=scouts["frontiers"];
    world["scouting_options"]=scouts["scouting"];
    for(const auto & option:world["scouting_options"].Vector()) persisted["frontier_positions"][option["ref"].String()]=option["position"];
    const auto targets=generateTargetCandidates(world,campaign.plan(),arrivals);
    forecasts["routes"]=targets["routes"];
    world["candidate_generation"]["scout_probes"]=scouts["probes"];
    world["candidate_generation"]["scout_centers_considered"]=scouts["considered_centers"];
    world["candidate_generation"]["target_probes"]=targets["probes"];
    world["candidate_generation"]["scout_choices_per_hero"].Integer()=SCOUT_CHOICES_PER_HERO;
    world["candidate_generation"]["target_choices_per_group"].Integer()=TARGET_CHOICES_PER_GROUP;
    world["candidate_generation"]["scope"].String()="Bounded native proposals by additional unseen coverage, distance and objective class; not all opportunities. Screening distance is not an arrival forecast. Required goals and own defense/logistics are preserved. Unknown targets and alternative directions remain unknown, not absent. Native command admission remains authoritative.";
    forecasts["defenses"]=forecastDefenses(world,campaign);
    forecasts["town_choices"]=forecastTownChoices(world,campaign,helperSources());
    const auto joint=forecastCommitments(world,campaign,helperSources());
    for(const auto * field:{"commitments","resource_calendar","army_pools","deliveries","stock_at_deadline"}) forecasts[field]=joint[field];
    world["goal_statuses"]=campaign.review(world);
    retainDefenseExecutionBlockers(campaign,world,persisted["goal_blockers"]);
    world["goal_feedback"].Vector();
    for(const auto & goal:campaign.plan()["goals"].Vector())
    {
        if(goal["kind"].String()!="capture_target" && goal["kind"].String()!="intercept_hero" && goal["kind"].String()!="secure_resource" && goal["kind"].String()!="scout_frontier" && goal["kind"].String()!="scout_area" && goal["kind"].String()!="visit_site" && goal["kind"].String()!="explore_passage") continue;
        auto feedback=campaign.routeFeedback(goal,world);
        feedback["status"]=world["goal_statuses"][goal["id"].String()];
        world["goal_feedback"].Vector().push_back(feedback);
    }
    observeBuildingProgress();
    observeOperationProgress();
    world["offensive_preparation"]=offensivePreparation(campaign,world);
    for(const auto & loss:battleLossSignals(campaign.plan(),persisted["memory"],true))
    {
        JsonNode item;item["question"].String()=loss.question;item["facts"].String()=loss.facts;
        world["offensive_preparation"]["recent_losses"].Vector().push_back(item);
    }
    world["main_army_idle"]=mainArmyIdle(campaign,world);
    forecasts["route_assumptions"].String()="All visible town/mine/resource targets and subterranean gate entrances, including actually observed visible gate pairs in whole routes (unobserved exits remain unknown), complete own hero positions and known frontiers, current permitted land/boat paths and movement, including presently funded owned shipyard quotes. Frontier arrivals require a single hero without an army exchange. No hidden target, future shipyard, boat spell, enemy intention or battle win probability. Empty arrivals mean unknown/unestablished, not absent.";
    traceCampaign();
}
void NativeCampaign::traceCampaign() const
{
    if(!campaign.plan().isNull())
    {
        JsonNode trace;
        trace["day"] = world["day"];
        trace["revision"] = campaign.plan()["revision"];
        trace["statuses"] = world["goal_statuses"];
        trace["resources"] = world["resources"];
        trace["heroes"] = world["heroes"];
        trace["reserves"] = campaign.reservedResources();
        trace["forecasts"] = world["forecasts"];
        trace["local_repairs"] = persisted["local_repairs"];
        trace["confirmed_deliveries"] = world["confirmed_deliveries"];
        trace["confirmed_site_visits"] = world["confirmed_site_visits"];
        for(const auto & town : world["towns"].Vector())
        { JsonNode item; for(const auto * field:{"ref","buildings","army_holder_ref","defense_value"}) item[field]=town[field]; trace["towns"].Vector().push_back(item); }
        logAi->info("NK3_CAMPAIGN %s", trace.toCompactString());
    }
}
void NativeCampaign::persist(NK2AI::Nullkiller & ai)
{
    // Publish confirmed crossings before any ordinary save can observe an
    // acknowledged task with its pending intent already removed.
    applySiteObservations(ai);
    applyPassageObservations();
    applyBattleObservations();
    applyForceObservations();
    persisted["native_campaign"] = campaign.save();
    saveArbiter();
    traceCampaign();
    JsonNode update;
    update["_namespaces"]["Nullkiller3"] = persisted;
    // A final interrupted task still belongs in the local execution journal,
    // but the network may already be shutting down after game-over/cancellation.
    // Sending SaveLocalState then can wait forever for an acknowledgement.
    if(!stopping && ai.cc->getPlayerStatus(ai.playerID)==EPlayerStatus::INGAME)
        ai.cc->saveLocalState(update);
}
bool NativeCampaign::accept(const JsonNode & proposal, std::string & reason)
{
    if(!campaign.accept(proposal, world, reason)) return false;
    acceptedLossRatio=campaign.plan()["policy"]["max_loss_ratio"].Float();
    acceptedRevision=campaign.plan()["revision"].Integer();
    return true;
}
// Yield only idle, uncommitted own heroes. This is a physical route repair,
// never an army exchange, strategic destination, battle or forecasted command.
bool NativeCampaign::repairOwnHeroObstruction(NK2AI::Nullkiller & ai)
{
    if(!campaign.plan()["policy"]["allow_route_repair"].Bool() || stopping) return false;
    const auto * main=dynamic_cast<const CGHeroInstance *>(resolve(ai,world["main_army_idle"]["hero_ref"]));
    if(!main || main->movementPointsRemaining()<=100 || main->isGarrisoned()) return false;
    const auto graph=visibleLandGraph(ai,world,[&](const auto * object){return reference(object);});
    const auto source=graph.index.find(main->visitablePos());
    if(source==graph.index.end()) return false;
    std::set<size_t> occupied;
    for(const auto * hero:ai.cc->getHeroesInfo()) if(hero!=main && !hero->isGarrisoned())
        if(const auto cell=graph.index.find(hero->visitablePos());cell!=graph.index.end()) occupied.insert(cell->second);
    std::vector<const CGObjectInstance *> targets;
    for(const auto * town:ai.cc->getTownsInfo()) targets.push_back(town);
    for(const auto & object:world["visible_objects"].Vector())
    {
        const auto kind=object["kind"].String();
        if((kind=="mine" && object["owner"]!=world["player"]) || kind=="resource"
            || strategicSiteAvailable(object))
            if(const auto * target=resolve(ai,object["ref"])) targets.push_back(target);
    }
    std::optional<NK2AI::AIPath> best;const CGHeroInstance * yielding=nullptr;const CGObjectInstance * opened=nullptr;
    for(const auto * helper:ai.cc->getHeroesInfo())
    {
        if(helper==main || helper->isGarrisoned() || ai.isHeroLocked(helper) || helper->movementPointsRemaining()<=100
            || !campaign.participantGoals(reference(helper),helperSources(),world).empty()) continue;
        bool requiredDefender=false;
        for(const auto * town:ai.cc->getTownsInfo()) requiredDefender |= ai.findRequiredTownDefender(town)==helper;
        if(requiredDefender) continue;
        const auto from=graph.index.find(helper->visitablePos());if(from==graph.index.end()) continue;
        for(const auto * target:targets)
        {
            const auto to=graph.index.find(target->visitablePos());if(to==graph.index.end()) continue;
            CGPath ordinary;
            if(ai.getPathsInfo(main)->getPath(ordinary,target->visitablePos(),EPathfindingLayer::LAND)
                || knownLandConnection(graph.land,source->second,to->second,occupied)) continue;
            auto vacated=occupied;vacated.erase(from->second);
            if(!knownLandConnection(graph.land,source->second,to->second,vacated)) continue;
            for(const auto & [position,id]:graph.index)
            {
                const auto origin=helper->visitablePos();
                if(position.z!=origin.z || std::max(std::abs(position.x-origin.x),std::abs(position.y-origin.y))>3
                    || !ai.cc->getVisitableObjs(position).empty()
                    || !yieldOpensKnownConnection(graph.land,source->second,to->second,occupied,from->second,id)) continue;
                for(const auto & path:ai.pathfinder->getPathInfo(position,false))
                {
                    if(path.targetHero!=helper || path.turn()!=0 || path.exchangeCount>1 || path.getFirstBlockedAction()
                        || path.getTotalArmyLoss()!=0 || path.getTotalDanger()!=0
                        || ai.dangerHitMap->enemyCanKillOurHeroesAlongThePath(path)) continue;
                    if(std::any_of(path.nodes.begin(),path.nodes.end(),[&](const auto & node) {
                        return node.targetHero!=helper || node.specialAction || node.layer!=EPathfindingLayer::LAND;
                    })) continue;
                    if(!best || path.movementCost()<best->movementCost()) {best=path;yielding=helper;opened=target;}
                }
            }
        }
    }
    if(!best) return false;
    const auto before=yielding->visitablePos();
    ai.executeTask(std::make_shared<NK2AI::Goals::ExecuteHeroChain>(*best));
    const bool moved=yielding->visitablePos()!=before;
    JsonNode trace;trace["kind"].String()="own_hero_yield";trace["day"]=world["day"];
    trace["main_ref"].String()=reference(main);trace["helper_ref"].String()=reference(yielding);
    trace["target_ref"].String()=reference(opened);trace["from"]=coordinate(before);
    trace["to"]=coordinate(yielding->visitablePos());trace["movement_observed"].Bool()=moved;
    logAi->info("NK3_ROUTE_REPAIR %s",trace.toCompactString());
    // Quotes are rebuilt from acknowledged positions. The geometric connection
    // above never enters the model as a ready route before this movement.
    if(moved) {ai.invalidatePathfinderData();ai.updateState();}
    return moved;
}

NK2AI::Goals::TGoalVec NativeCampaign::repairRoute(NK2AI::Nullkiller & ai, const CGHeroInstance * hero, const CGObjectInstance * destination) const
{
    using namespace NK2AI;
    if(!hero || !destination || !campaign.plan()["policy"]["allow_route_repair"].Bool()
        || hero->movementPointsRemaining()<=100) return {};
    const auto from=hero->visitablePos(), to=destination->visitablePos();
    if(from.z!=to.z) return {}; // No unproved cross-level or special route.
    auto distance=[&](const int3 & tile) { return std::abs(tile.x-to.x)+std::abs(tile.y-to.y); };
    std::optional<AIPath> best;
    double bestScore=0;
    for(const auto & frontier:world["frontier_options"].Vector())
    {
        const auto & p=frontier["position"];
        const int3 tile(p[0].Integer(),p[1].Integer(),p[2].Integer());
        const auto gain=distance(from)-distance(tile);
        if(tile.z!=from.z || tile==from || gain<=0) continue;
        for(const auto & path:ai.pathfinder->getPathInfo(tile,false))
        {
            if(path.targetHero!=hero || path.getTotalArmyLoss()!=0 || path.getTotalDanger()!=0) continue;
            bool ownRoute=true;
            for(const auto & node:path.nodes) ownRoute &= node.targetHero==hero;
            if(!ownRoute) continue;
            // Geometric progress ranks an information-gathering step. It is
            // neither an ETA nor a claim that the unknown remainder is open.
            // Embark/disembark can make that known step span multiple days.
            // The caller still admits it only within the goal's deadline,
            // and the next own turn rebuilds the route from observed state.
            const auto score=gain/(0.1+path.movementCost());
            if(score>bestScore) { best=path; bestScore=score; }
        }
    }
    if(!best) return {};
    return Goals::CaptureObjectsBehavior::getVisitGoals({*best},&ai,nullptr,true);
}
void NativeCampaign::rememberTasks(NK2AI::Goals::TGoalVec & output, NK2AI::Goals::TGoalVec generated,
                                 const JsonNode & goal, const NK2AI::Nullkiller & ai,
                                 const std::map<std::string,std::string> * prospectiveSources)
{
    const auto * actor = dynamic_cast<const CGHeroInstance *>(resolve(ai, goal["actor_ref"]));
    const bool delivery=goal["kind"].String()=="reinforce_hero";
    const bool stabilizing=goal["kind"].String()=="preserve_force"
        && campaign.requiresStabilization(goal["id"].String());
    std::function<bool(const NK2AI::Goals::TSubgoal &,int)> allowed = [&](const auto & task,int depth) {
        if(depth>16 || task->invalid()) return false;
        if(const auto * composition=dynamic_cast<const NK2AI::Goals::Composition *>(task.get()))
        {
            for(const auto & child:composition->decompose(&ai)) if(!allowed(child,depth+1)) return false;
        }
        else if(const auto * chain=dynamic_cast<const NK2AI::Goals::ExecuteHeroChain *>(task.get()))
        {
            const auto & path=chain->getPath();
            if(actor && !delivery && path.targetHero!=actor) return false;
            // Campaign thresholds/reserves and path losses use creature AI
            // value. A hero's combat multiplier cannot supply missing troops.
            if(!path.heroArmy) return false;
            const auto strength=path.heroArmy->estimateCombatValue(), loss=path.getTotalArmyLoss();
            if(stabilizing)
            {
                if(!safeStabilizationPath(path,actor,ai)) return false;
            }
            else if(!delivery && strength<goal["min_army_value"].Integer()) return false;
            const auto * riskTarget=resolve(ai,goal["target_ref"]);
            const bool namedRoute=actor && path.targetHero==actor && riskTarget && path.targetTile()==riskTarget->visitablePos();
            if(!(namedRoute ? campaign.allowsLoss(goal,strength,loss) : campaign.allowsLoss(std::string(),strength,loss))) return false;
            const auto reserve=prospectiveSources
                ? campaign.reservedForce(reference(path.targetHero),world,*prospectiveSources,executingGoal())
                : campaign.reservedForce(reference(path.targetHero),world,helperSources(),executingGoal());
            if(strength<loss || (!stabilizing && strength-loss<reserve))
            {
                logAi->trace("NK3 campaign path rejected: goal=%s army=%llu loss=%llu reserve=%llu",goal["id"].String(),strength,loss,reserve);
                return false;
            }
            if(world["day"].Integer()+path.turn()>goal["deadline_day"].Integer()) return false;
        }
        else if(stabilizing || (actor && task->hero && !delivery && task->hero!=actor)) return false;
        task->strategicGoalID=goal["id"].String();
        return true;
    };
    for(const auto & task:generated)
        if(task->isElementar() && allowed(task,0)) output.push_back(task);

}
NK2AI::Goals::TGoalVec NativeCampaign::generate(NK2AI::Nullkiller & ai, bool priorityPass, bool stabilizationOnly)
{
    using namespace NK2AI;
    using namespace NK2AI::Goals;
    if(repairedSourcesChanged) { repairedSourcesChanged=false;ai.updateState(); }
    TGoalVec output;
    if(priorityPass)
        for(const auto * town:ai.cc->getTownsInfo())
            for(const auto * candidate:ai.cc->getAvailableHeroes(town))
                if(candidate && isOwnReturnedHero(persisted["own_returned_heroes"],candidate->getHeroTypeID().getNum(),candidate->id.getNum())
                    && heroHireReason(ai,town,candidate).starts_with("recover_own:"))
                    output.push_back(sptr(RecruitHero(town,candidate)));
    if(stabilizationOnly && !priorityPass)
    {
        const auto addressed=arbiter.save().addressed;
        for(const auto & signal:battleLossSignals(campaign.plan(),persisted["memory"],true))
        {
            if(addressed.count(signal.question) && addressed.at(signal.question)==signal.facts) continue;
            const auto * actor=dynamic_cast<const CGHeroInstance *>(resolve(ai,JsonNode(signal.question.substr(std::string("battle_loss:").size()))));
            if(!actor || actor->getOwner()!=ai.playerID || actor->movementPointsRemaining()<=100) continue;
            std::optional<AIPath> best;const CGTownInstance * refuge=nullptr;
            for(const auto * town:ai.cc->getTownsInfo())
            {
                const auto from=actor->visitablePos(),to=town->visitablePos();
                if(from.z==to.z && std::abs(from.x-to.x)<=1 && std::abs(from.y-to.y)<=1) continue;
                for(const auto & path:ai.pathfinder->getPathInfo(to,false))
                    if(path.turn()<=1 && safeStabilizationPath(path,actor,ai)
                        && (!best || path.movementCost()<best->movementCost()))
                    { best=path;refuge=town; }
            }
            if(best)
            {
                auto task=sptr(ExecuteHeroChain(*best,refuge));
                task->strategicStabilizationReason="unexpected_own_combat_loss";
                output.push_back(task);
            }
        }
    }
    if(priorityPass)
        for(const auto & defense:world["forecasts"]["defenses"].Vector())
        {
            if(!defense["critical"].Bool() || defense["status"].String()!="insufficient_current_force"
                || defense["scenario_deadline_day"].Integer()>world["day"].Integer()+1) continue;
            const auto * town=dynamic_cast<const CGTownInstance *>(resolve(ai,defense["town_ref"]));
            if(!town || town->getOwner()!=ai.playerID) continue;
            const auto required=std::max<int64_t>(0,std::ceil(defense["opposing_upper_sum"].Integer()*ai.settings->getSafeAttackRatio())
                -defense["conditional_force_value"].Integer());
            if(!required || required>std::numeric_limits<int>::max()) continue;
            const auto stock=ai.armyManager->getArmyAvailableToBuy(town->getUpperArmy(),town,ai.cc->getResourceAmount());
            TResources cost;int64_t purchased=0;
            for(const auto & unit:stock)
            {
                const auto * creature=unit.creID.toCreature();
                const auto value=LIBRARY->creh->getCombatValue().getAIValue(creature);
                if(value<=0 || unit.count<=0 || purchased>=required) continue;
                // No purchase may depend on dismissing a reserved stack.
                if(BuyArmy::needsFreeSlotToRecruit(town->getUpperArmy(),unit.creID) && forceReserve(town->getUpperArmy())>0) continue;
                const auto count=std::min<int64_t>(unit.count,(required-purchased+value-1)/value);
                cost+=creature->getFullRecruitCost()*count;purchased+=value*count;
            }
            if(purchased<required || !ai.cc->getResourceAmount().canAfford(cost)) continue;
            auto task=sptr(BuyArmy(town,required));
            task->strategicEmergencyTown=defense["town_ref"].String();task->strategicEmergencyCost=cost;
            output.push_back(task);
        }
    for(const auto & goal : campaign.plan()["goals"].Vector())
    {
        const bool stabilizing=goal["kind"].String()=="preserve_force"
            && campaign.requiresStabilization(goal["id"].String());
        if(stabilizationOnly && !stabilizing) continue;
        const auto & goalStatus=world["goal_statuses"][goal["id"].String()];
        const bool retryDefenseBlock=goalStatus["state"].String()=="blocked"
            && goalStatus["reason"].String()=="hero_required_for_defense";
        if(goalStatus["state"].String() != "ready" && !stabilizing && !retryDefenseBlock) continue;
        const auto & kind = goal["kind"].String();
        if(kind!="reinforce_hero" && priorityPass != (kind == "develop_town")) continue;
        if(operationStalled(static_cast<const JsonNode &>(persisted)["operation_progress"][goal["id"].String()],world["forecasts"],goal["id"].String(),world["day"].Integer()))
        {
            campaign.blocked(goal["id"].String(),"no_target_progress");
            world["goal_statuses"]=campaign.statuses();
            continue;
        }
        if(kind=="defend_area" && unchangedHoldingAttempt(persisted["memory"],goal["id"].String(),campaign.plan()["revision"].Integer(),executionSnapshot(ai))) continue;
        const auto * target = resolve(ai, goal["target_ref"]);
        const auto * actor = dynamic_cast<const CGHeroInstance *>(resolve(ai, goal["actor_ref"]));
        if(kind=="hire_helper")
        {
            const auto * town=dynamic_cast<const CGTownInstance *>(target);
            const CGHeroInstance * selected=nullptr;
            if(town && town->getOwner()==ai.playerID)
                for(const auto * candidate:ai.cc->getAvailableHeroes(town))
                    if(candidate && goal["candidate_ref"].String()=="tavern:"+std::to_string(candidate->getHeroTypeID().getNum())) selected=candidate;
            if(selected && !heroHireReason(ai,town,selected,goal["id"].String()).empty())
                rememberTasks(output,{sptr(RecruitHero(town,selected))},goal,ai);
            else
            {
                campaign.blocked(goal["id"].String(),"helper_hire_not_currently_available");
                world["goal_statuses"]=campaign.statuses();
            }
            continue;
        }
        if(kind=="prepare_garrison" && actor)
        {
            const auto before=output.size();
            const auto * town=dynamic_cast<const CGTownInstance *>(target);
            if(town && town->getOwner()==ai.playerID && actor->getVisitedTown()==town
                && !(town->getGarrisonHero()==actor && town->getVisitingHero()))
                rememberTasks(output,{sptr(PrepareGarrison(town,actor,goal["complete_when"]["value"].Integer(),
                    goal["min_army_value"].Integer(),goal["garrison_mode"].String()))},goal,ai);
            else if(town && actor->getVisitedTown()!=town)
                rememberTasks(output,CaptureObjectsBehavior::getVisitGoals(ai.pathfinder->getPathInfo(town->visitablePos(),false),&ai,town,true),goal,ai);
            if(output.size()==before)
            {
                campaign.blocked(goal["id"].String(),"garrison_location_not_established");
                world["goal_statuses"]=campaign.statuses();
            }
            continue;
        }
        if(kind=="defend_area" && actor)
        {
            const auto * town=dynamic_cast<const CGTownInstance *>(target);
            const auto * visitor=town ? town->getVisitingHero() : nullptr;
            if(town && town->getOwner()==ai.playerID && visitor && visitor!=actor)
            {
                auto safeOwnPath=[&](const AIPath & path,const CGHeroInstance * hero) {
                    return path.targetHero==hero && path.heroArmy && path.turn()==0
                        && path.exchangeCount<=1 && !path.getFirstBlockedAction()
                        && !path.getTotalDanger() && !path.getTotalArmyLoss()
                        && std::all_of(path.nodes.begin(),path.nodes.end(),[&](const auto & node) {
                            return node.targetHero==hero && node.layer==EPathfindingLayer::LAND && ai.cc->isVisible(node.coord);
                        });
                };
                const auto entries=ai.pathfinder->getPathInfo(town->visitablePos(),false);
                const bool immediate=std::any_of(entries.begin(),entries.end(),[&](const auto & path) {
                    return safeOwnPath(path,actor) && path.heroArmy->estimateCombatValue()>=goal["min_army_value"].Integer()
                        && path.heroArmy->estimateCombatValue()>=campaign.reservedForce(reference(actor),world,helperSources());
                });
                if(immediate)
                {
                    // A visit to an occupied town only meets its visitor. Clear
                    // an uncommitted visitor first, then replan the entry from
                    // current state; never replay the old occupied-town path.
                    const auto before=output.size();
                    if(visitor->getOwner()==ai.playerID && !ai.isHeroLocked(visitor)
                        && campaign.participantGoals(reference(visitor),helperSources(),world).empty())
                    {
                        std::optional<AIPath> best;
                        const auto center=town->visitablePos();
                        for(int dy=-1;dy<=1;++dy) for(int dx=-1;dx<=1;++dx)
                        {
                            const int3 landing(center.x+dx,center.y+dy,center.z);
                            if(!ai.cc->isVisible(landing)) continue;
                            const auto * tile=ai.cc->getTile(landing,false);
                            if(!tile || !tile->isLand() || tile->blocked() || !ai.cc->getVisitableObjs(landing).empty()) continue;
                            for(const auto & path:ai.pathfinder->getPathInfo(landing,false))
                                if(safeOwnPath(path,visitor) && (!best || path.movementCost()<best->movementCost())) best=path;
                        }
                        if(best)
                        {
                            auto clearance=goal;
                            clearance["actor_ref"].String()=reference(visitor);
                            clearance["min_army_value"].Integer()=visitor->estimateCombatValue();
                            rememberTasks(output,CaptureObjectsBehavior::getVisitGoals({*best},&ai,nullptr,true),clearance,ai);
                        }
                    }
                    if(output.size()==before)
                    {
                        persisted["goal_blockers"][goal["id"].String()]["revision"]=campaign.plan()["revision"];
                        persisted["goal_blockers"][goal["id"].String()]["reason"].String()="town_visiting_slot_occupied";
                        campaign.blocked(goal["id"].String(),"town_visiting_slot_occupied");
                        world["goal_statuses"]=campaign.statuses();
                    }
                    continue;
                }
            }
        }
        if(kind=="defend_area" && actor && target && actor->visitablePos()==target->visitablePos())
        {
            const auto * town=dynamic_cast<const CGTownInstance *>(target);
            if(town && town->getOwner()==ai.playerID)
            {
                const auto * source=town->getUpperArmy();
                const auto floor=campaign.exchangeForce(reference(source),world,helperSources(),goal["id"].String());
                // Holding remains a live commitment, not another visit. Keep
                // its role/reserves; a fresh task is useful here only when the
                // town has another army with surplus that can be acquired.
                if(source==actor || source->estimateCombatValue()<=floor) continue;
                const auto destinationFloor=campaign.reservedForce(reference(actor),world,helperSources(),goal["id"].String());
                if(floor || destinationFloor)
                {
                    // The reserved exchange permits whole creatures into a
                    // matching/free slot, leaving every source floor intact.
                    // A fractional value surplus cannot supply one creature.
                    bool movable=false;
                    for(const auto & [slot,stack]:source->Slots())
                    {
                        const auto count=source->getStackCount(slot);
                        if(count<=0 || !actor->getSlotFor(source->getCreature(slot)).validSlot()) continue;
                        if(source->needsLastStack() && source->stacksCount()==1 && count==1) continue;
                        const auto unitPower=(stack->estimateCombatValue()+count-1)/count;
                        if(unitPower && source->estimateCombatValue()-floor>=unitPower) { movable=true;break; }
                    }
                    if(!movable) continue;
                }
                else if(!ai.armyManager->howManyReinforcementsCanGet(actor,source)) continue;
            }
        }
        TGoalVec generated;
        if(kind=="reinforce_hero" && priorityPass)
        {
            const auto sources=helperSources();
            if(sources.count(goal["id"].String())) target=resolve(ai,JsonNode(sources.at(goal["id"].String())));
            const auto * town=dynamic_cast<const CGTownInstance *>(target);
            if(!actor || !town || town->getOwner()!=ai.playerID) continue;
            const auto floor=campaign.exchangeForce(reference(town),world,sources,goal["id"].String());
            const auto sourceValue=town->getUpperArmy()->estimateCombatValue();
            const auto surplus=sourceValue>floor ? sourceValue-floor : 0;
            const auto required=goal["complete_when"]["value"].Integer();
            if(actor->estimateCombatValue()+surplus>=required) continue;
            TResources available=ai.cc->getResourceAmount();
            const auto reserved=campaign.reservedResources(goal["id"].String());
            for(int i=0;i<7;++i) available[GameResID(i)]=std::max<int64_t>(0,available[GameResID(i)]-reserved[i].Integer());
            const auto stock=ai.armyManager->getArmyAvailableToBuy(town->getUpperArmy(),town,available);
            logAi->trace("NK3 recruitment readiness: goal=%s source=%llu floor=%lld recipient=%llu required=%lld stock=%zu",
                goal["id"].String(),sourceValue,floor,actor->estimateCombatValue(),required,stock.size());
            if(std::none_of(stock.begin(),stock.end(),[](const auto & unit){return unit.count>0;})) continue;
            generated.push_back(sptr(BuyArmy(town,required-actor->estimateCombatValue()-surplus)));
            rememberTasks(output,generated,goal,ai);
            continue;
        }
        if(kind == "develop_town")
        {
            const auto * town = dynamic_cast<const CGTownInstance *>(target);
            const auto buildingID = BuildingID(goal["building_id"].Integer());
            if(!town || !town->getTown()->buildings.count(buildingID)) continue;
            auto building = BuildAnalyzer::getBuildingOrPrerequisite(town, buildingID, ai.armyManager, ai.cc, false);
            if(building.isBuildable) generated.push_back(sptr(BuildThis(building, TownDevelopmentInfo(town))));
        }
        else if(kind == "reinforce_hero" && actor)
        {
            if(actor->estimateCombatValue()>=goal["complete_when"]["value"].Integer())
            {
                persisted["goal_blockers"][goal["id"].String()]["revision"]=campaign.plan()["revision"];
                persisted["goal_blockers"][goal["id"].String()]["reason"].String()="recipient_sufficient_delivery_unconfirmed";
                campaign.blocked(goal["id"].String(),"recipient_sufficient_delivery_unconfirmed");
                world["goal_statuses"]=campaign.statuses();
                continue;
            }
            const auto sources = helperSources();
            if(sources.count(goal["id"].String())) target = resolve(ai,JsonNode(sources.at(goal["id"].String())));
            if(!target || target->getOwner() != ai.playerID)
            {
                target = nullptr;
                if(!target)
                {
                    persisted["goal_blockers"][goal["id"].String()]["revision"]=campaign.plan()["revision"];
                    persisted["goal_blockers"][goal["id"].String()]["reason"].String()="source_no_longer_owned";
                    campaign.blocked(goal["id"].String(), "source_no_longer_owned");
                    world["goal_statuses"] = campaign.statuses();
                    continue;
                }
            }
            if(dynamic_cast<const CGTownInstance *>(target))
                for(const auto & forecast:world["forecasts"]["deliveries"].Vector())
                {
                    const auto & status=forecast["status"].String();
                    if(forecast["goal_id"]!=goal["id"] || !forecast["source_army_now"].isNumber()
                        || !forecast["source_floor"].isNumber()
                        || forecast["source_army_now"].Integer()>forecast["source_floor"].Integer()
                        || (status!="unfunded_at_deadline" && status!="additional_army_required")) continue;
                    // A virtual chain may include the town's protected troops.
                    // No current surplus and no funded completion can
                    // justify spending movement on that chain.
                    persisted["goal_blockers"][goal["id"].String()]["revision"]=campaign.plan()["revision"];
                    persisted["goal_blockers"][goal["id"].String()]["reason"].String()="source_force_unavailable";
                    campaign.blocked(goal["id"].String(),"source_force_unavailable");
                    world["goal_statuses"]=campaign.statuses();
                    break;
                }
            if(world["goal_statuses"][goal["id"].String()]["state"].String()=="blocked") continue;
            generated=deliveryTasks(ai,actor,target);
        }
        else
        {
            if(kind=="preserve_force" && actor && (!target || target->getOwner()!=ai.playerID)
                && campaign.plan()["policy"]["allow_route_repair"].Bool())
            {
                target=nullptr;
                float best=std::numeric_limits<float>::max();
                for(const auto * town:ai.cc->getTownsInfo())
                    for(const auto & path:ai.pathfinder->getPathInfo(town->visitablePos(),false))
                        if(path.targetHero==actor && !path.getFirstBlockedAction() && path.getTotalArmyLoss()==0
                            && path.getTotalDanger()==0 && path.exchangeCount<=1
                            && world["day"].Integer()+path.turn()<=goal["deadline_day"].Integer() && path.movementCost()<best)
                        { target=town;best=path.movementCost(); }
                if(target)
                {
                    JsonNode repair;
                    repair["day"]=world["day"];repair["goal"]=goal["id"];repair["revision"]=campaign.plan()["revision"];
                    repair["kind"].String()="safe_town_replaced";repair["from"]=goal["target_ref"];
                    repair["to"].String()=reference(target);persisted["local_repairs"][goal["id"].String()]=repair;
                }
            }
            int3 position(-1);
            if(kind == "scout_area" && actor && actor->getSightRadius()<goal["complete_when"]["value"].Integer())
            {
                persisted["goal_blockers"][goal["id"].String()]["revision"]=campaign.plan()["revision"];
                persisted["goal_blockers"][goal["id"].String()]["reason"].String()="insufficient_sight_radius";
                campaign.blocked(goal["id"].String(),"insufficient_sight_radius");
                world["goal_statuses"]=campaign.statuses();
                continue;
            }
            if(kind == "scout_frontier" || kind == "scout_area")
            {
                const auto & pos = persisted["frontier_positions"][goal["target_ref"].String()];
                if(pos.isVector() && pos.Vector().size() == 3) position = int3(pos[0].Integer(), pos[1].Integer(), pos[2].Integer());
            }
            else if(target) position = target->visitablePos();
            if(stabilizing && actor && target && target->getOwner()==ai.playerID)
            {
                const auto from=actor->visitablePos();
                if(from.z==position.z && std::abs(from.x-position.x)<=1 && std::abs(from.y-position.y)<=1) continue;
            }
            if(actor && position.isValid())
            {
                auto paths = ai.pathfinder->getPathInfo(position, false);
                std::erase_if(paths, [&](const AIPath & path) {
                    if(path.targetHero!=actor) return true;
                    if(kind=="scout_area" && (path.getFirstBlockedAction()
                        || std::any_of(path.nodes.begin(),path.nodes.end(),[&](const auto & node) {
                            return node.layer!=EPathfindingLayer::LAND || !ai.cc->isVisible(node.coord);
                        }))) return true;
                    if(kind!="explore_passage" && kind!="scout_area") return false;
                    return path.exchangeCount>1 || std::any_of(path.nodes.begin(),path.nodes.end(),[&](const auto & node){return node.targetHero!=actor;});
                });
                generated = CaptureObjectsBehavior::getVisitGoals(paths, &ai, target, true);
                // The stock safe-attack heuristic is conservative. A model's
                // explicit grant can select this exact actor/target route;
                // locks, blocked actions, reserves and deadlines still apply.
                if(target && goal["risk"].isStruct() && campaign.lossLimit(goal)>campaign.lossLimit(std::string()))
                    for(const auto & path:paths)
                    {
                        if(!path.heroArmy || path.getFirstBlockedAction() || ai.arePathHeroesLocked(path)
                            || path.targetTile()!=position || !campaign.allowsLoss(goal,path.heroArmy->estimateCombatValue(),path.getTotalArmyLoss())) continue;
                        const bool already=std::any_of(generated.begin(),generated.end(),[&](const auto & task) {
                            const auto * chain=dynamic_cast<const ExecuteHeroChain *>(task.get());
                            return chain && chain->getPath().targetHero==path.targetHero
                                && chain->getPath().targetTile()==path.targetTile() && chain->getPath().movementCost()==path.movementCost();
                        });
                        if(!already) generated.push_back(sptr(ExecuteHeroChain(path,target)));
                    }
                if(std::none_of(generated.begin(),generated.end(),[](const auto & task){return !task->invalid();}) && target)
                    generated=repairRoute(ai,actor,target);
            }
        }
        const auto countBefore = output.size();
        rememberTasks(output, generated, goal, ai);
        if(output.size()==countBefore && kind=="reinforce_hero" && !priorityPass && actor
            && dynamic_cast<const CGTownInstance *>(target))
            rememberTasks(output,deliveryTasks(ai,actor,target,true),goal,ai);
        logAi->trace("NK3 campaign proposals: goal=%s generated=%zu admitted=%zu",goal["id"].String(),generated.size(),output.size()-countBefore);
        if(output.size() == countBefore && kind != "develop_town" && !stabilizing)
        {
            if(kind=="reinforce_hero" && supportedDeliveryWait(world["forecasts"],goal,world["day"].Integer()))
            {
                persisted["goal_blockers"].Struct().erase(goal["id"].String());
                campaign.waiting(goal["id"].String(),"awaiting_supported_arrival");
                world["goal_statuses"]=campaign.statuses();
                continue;
            }
            const JsonNode * late=nullptr;
            for(const auto & delivery:world["forecasts"]["deliveries"].Vector())
                if(delivery["goal_id"]==goal["id"] && delivery["status"].String()=="late_on_current_route"
                    && delivery["arrival_day"].Integer()>goal["deadline_day"].Integer()) late=&delivery;
            const bool defenseLocked=actor && ai.getHeroLockedReason(actor)==HeroLockedReason::DEFENCE;
            const std::string reason=defenseLocked ? "hero_required_for_defense"
                : late ? "deadline_unreachable" : "route_not_established";
            if(actor && actor->movementPointsRemaining()>100)
            {
                auto & blocker=persisted["goal_blockers"][goal["id"].String()];
                blocker["revision"]=campaign.plan()["revision"];
                blocker["reason"].String()=reason;
                blocker["route_turns"]=JsonNode();
                if(late) blocker["route_turns"].Integer()=std::max<int64_t>(0,(*late)["arrival_day"].Integer()-world["day"].Integer());
            }
            campaign.blocked(goal["id"].String(), reason);
            world["goal_statuses"] = campaign.statuses();
        }
        else if(output.size()>countBefore)
        {
            persisted["goal_blockers"].Struct().erase(goal["id"].String());
            if(retryDefenseBlock)
            {
                world["goal_statuses"]=campaign.review(world);
                retainDefenseExecutionBlockers(campaign,world,persisted["goal_blockers"]);
            }
        }
    }
    return output;
}
bool NativeCampaign::helperHireSlotAvailable(const NK2AI::Nullkiller & ai,const CGTownInstance * town) const
{
    if(!town || town->getOwner()!=ai.playerID) return false;
    const auto * visitor=town->getVisitingHero();
    if(!visitor) return true;
    // This is the server's direct visiting -> garrison operation: all town
    // stacks merge into the same owned hero without loss or movement.
    if(visitor->getOwner()!=ai.playerID || town->getGarrisonHero() || !visitor->canBeMergedWith(*town)) return false;
    const auto & aliases=persisted["object_ids"].Struct();
    const auto heroAlias=aliases.find(std::to_string(visitor->id.getNum()));
    const auto townAlias=aliases.find(std::to_string(town->id.getNum()));
    if(heroAlias==aliases.end() || townAlias==aliases.end()) return false;
    const auto heroRef=externalai::objectReference(heroAlias->second),townRef=externalai::objectReference(townAlias->second);
    const auto obligations=campaign.participantGoals(heroRef,helperSources(),world);
    for(const auto & goal:campaign.plan()["goals"].Vector()) if(obligations.count(goal["id"].String()))
        if((goal["kind"].String()!="defend_area" && goal["kind"].String()!="preserve_force")
            || goal["actor_ref"].String()!=heroRef || goal["target_ref"].String()!=townRef) return false;
    return true;
}
std::string NativeCampaign::heroHireReason(const NK2AI::Nullkiller & ai, const CGTownInstance * town, const CGHeroInstance * candidate,const std::string & goalID) const
{
    if(!town || !candidate || town->getOwner()!=ai.playerID) return {};
    const JsonNode * selectedGoal=nullptr;
    bool namedGoal=goalID.empty();
    for(const auto & goal:campaign.plan()["goals"].Vector()) if(goal["id"].String()==goalID)
    {
        namedGoal=true;
        if(goal["kind"].String()=="hire_helper") selectedGoal=&goal;
    }
    if(!namedGoal) return {};
    const bool recovering=goalID.empty() && isOwnReturnedHero(persisted["own_returned_heroes"],candidate->getHeroTypeID().getNum(),candidate->id.getNum());
    if(recovering)
    {
        if(!town->hasBuilt(BuildingID::TAVERN) || ai.heroManager->heroCapReached() || !helperHireSlotAvailable(ai,town)) return {};
        const auto available=ai.cc->getAvailableHeroes(town);
        if(std::find(available.begin(),available.end(),candidate)==available.end()
            || !recoveryFundsAvailable(resourceValues(ai.cc->getResourceAmount()),resourceValues(ai.getLockedResources()),campaign.reservedResources(),GameConstants::HERO_GOLD_COST)) return {};
    }
    TResources price;price[EGameResID::GOLD]=GameConstants::HERO_GOLD_COST;
    if(!selectedGoal)
    { if(!ai.getFreeResources().canAfford(price)) return {}; }
    else
    {
        const auto protectedFunds=campaign.reservedResources(goalID);
        const auto funds=ai.cc->getResourceAmount(),locks=ai.getLockedResources();
        for(int i=0;i<7;++i) if(funds[i]-locks[i]-protectedFunds[i].Integer()<price[i]) return {};
        if(campaign.statuses()[goalID]["state"].String()!="ready" || !campaign.holdsCommitment(goalID)
            || world["day"].Integer()>(*selectedGoal)["deadline_day"].Integer()
            || (*selectedGoal)["candidate_ref"].String()!="tavern:"+std::to_string(candidate->getHeroTypeID().getNum())
            || !CampaignState::helperJobSupported(*selectedGoal,world)) return {};
        if(resolve(ai,(*selectedGoal)["target_ref"])!=town || !town->hasBuilt(BuildingID::TAVERN)
            || ai.heroManager->heroCapReached() || !helperHireSlotAvailable(ai,town)) return {};
        const auto available=ai.cc->getAvailableHeroes(town);
        if(std::find(available.begin(),available.end(),candidate)==available.end()) return {};
        const auto * job=resolve(ai,(*selectedGoal)["job_ref"]);
        const auto & helperRole=(*selectedGoal)["helper_role"].String();
        if((helperRole=="reinforcement" || helperRole=="defender") && (!job || job->getOwner()!=ai.playerID)) return {};
        if(helperRole=="collector" && (!job || !ai.cc->isVisible(job->visitablePos())
            || (job->ID==Obj::MINE && job->getOwner()==ai.playerID))) return {};
    }
    const auto heroes=ai.cc->getHeroesInfo();
    if(!selectedGoal && !recovering && heroes.empty()) return "main:no_owned_hero";
    // Compare the accepted shared spending calendar before and after hiring.
    // A discretionary purchase must not make funded construction/delivery fail.
    auto before=world;
    before["resources"]=resourceValues(ai.cc->getResourceAmount());
    auto after=before;after["resources"][6].Integer()-=GameConstants::HERO_GOLD_COST;
    const auto baseline=forecastCommitments(before,campaign,helperSources());
    const auto reduced=forecastCommitments(after,campaign,helperSources());
    for(const auto * category:{"commitments","deliveries"})
        for(const auto & funded:baseline[category].Vector())
            if(funded["status"].String()=="conditional")
                for(const auto & remaining:reduced[category].Vector())
                    if(remaining["goal_id"]==funded["goal_id"] && remaining["status"].String()!="conditional") return {};
    if(recovering) return "recover_own:"+std::to_string(candidate->getHeroTypeID().getNum());
    if(selectedGoal) return "model:"+goalID+":"+(*selectedGoal)["helper_role"].String()+":"+(*selectedGoal)["job_ref"].String();
    const auto alias=persisted["object_ids"].Struct().find(std::to_string(town->id.getNum()));
    if(alias!=persisted["object_ids"].Struct().end())
        for(const auto & defense:world["forecasts"]["defenses"].Vector())
            if(defense["town_ref"].String()==externalai::objectReference(alias->second)
                && defense["scenario_deadline_day"].Integer()<=world["day"].Integer()+1
                && defense["status"].String()=="insufficient_current_force"
                && candidate->estimateCombatValue()>=static_cast<uint64_t>(
                    defense["opposing_upper_sum"].Integer()-defense["conditional_force_value"].Integer()))
                return "defender:"+std::to_string(town->id.getNum());
    if(ai.buildAnalyzer->isGoldPressureOverMax()) return {};

    // Starting troops are useful only when an actual main hero can receive
    // a meaningful reinforcement on a current route to this town.
    if(candidate->getArmyCost()>GameConstants::HERO_GOLD_COST/2)
        for(const auto * recipient:heroes)
        {
            const auto assigned=role(recipient);
            if(assigned!="main" && (!assigned.empty()
                || ai.heroManager->getHeroRoleOrDefaultInefficient(recipient)!=NK2AI::HeroRole::MAIN)) continue;
            const auto gain=ai.armyManager->howManyReinforcementsCanGet(recipient,candidate);
            if(gain<std::max<uint64_t>(200,recipient->estimateCombatValue()/4)) continue;
            for(const auto & path:ai.pathfinder->getPathInfo(town->visitablePos(),false))
                if(path.targetHero==recipient && path.heroArmy && path.exchangeCount<=1
                    && path.turn()<=1 && !path.getFirstBlockedAction() && !path.getTotalArmyLoss())
                    return "reinforcement:"+std::to_string(recipient->id.getNum());
        }

    // Collection is a concrete visible workload, not permission to hire merely
    // because cash is available. Existing free scouts cover five nearby jobs
    // each; committed actors cannot be counted as free collectors.
    size_t collectors=0;
    for(const auto * hero:heroes)
        if(role(hero).empty() && ai.heroManager->getHeroRoleOrDefaultInefficient(hero)==NK2AI::HeroRole::SCOUT
            && ai.dangerHitMap->getClosestTown(hero->visitablePos())==town) ++collectors;
    size_t jobs=0;int firstTarget=-1;
    for(const auto * object:ai.objectClusterizer->getNearbyObjects())
        if(ai.cc->isVisible(object->visitablePos()) && ai.dangerHitMap->getClosestTown(object->visitablePos())==town
            && (object->ID==Obj::RESOURCE || object->ID==Obj::TREASURE_CHEST || object->ID==Obj::CAMPFIRE))
        {
            bool committed=false;
            const auto alias=persisted["object_ids"].Struct().find(std::to_string(object->id.getNum()));
            if(alias!=persisted["object_ids"].Struct().end())
                for(const auto & goal:campaign.plan()["goals"].Vector())
                    if(campaign.holdsCommitment(goal["id"].String())
                        && goal["target_ref"].String()==externalai::objectReference(alias->second)) committed=true;
            if(!committed) { ++jobs;if(firstTarget<0) firstTarget=object->id.getNum(); }
        }
    if(jobs>5*(collectors+1)) return "collector:"+std::to_string(firstTarget)+":jobs="+std::to_string(jobs);
    return {};
}
void NativeCampaign::recordHelperHire(NK2AI::Nullkiller & ai,const CGTownInstance * town,const CGHeroInstance * candidate,const std::string & goalID)
{
    if(!town || !candidate) return;
    const auto * hired=town->getVisitingHero();
    if(!hired || hired->getOwner()!=ai.playerID || hired->getHeroTypeID()!=candidate->getHeroTypeID()) return;
    // Recruiting can assign a new map object ID to the same offered instance.
    // The successful exact-candidate command already passed the old-ID gate.
    const auto & returnMarkers=static_cast<const JsonNode &>(persisted)["own_returned_heroes"];
    if(returnMarkers[std::to_string(candidate->getHeroTypeID().getNum())].isStruct())
    {
        ai.cc->saveLocalState(consumedOwnHeroReturnUpdate(candidate->getHeroTypeID().getNum()));
        persisted["own_returned_heroes"].Struct().erase(std::to_string(candidate->getHeroTypeID().getNum()));
        persist(ai);
    }
    if(goalID.empty()) return;
    const auto & pending=static_cast<const JsonNode &>(persisted)["pending_native_task"];
    if(pending["action"]["goal_id"].String()!=goalID || pending["action"]["kind"].String()!="hire_hero"
        || pending["before"]["day"].Integer()!=ai.cc->getCalendar().getCurrentDay()) return;
    const auto hiredRef=reference(hired);
    for(const auto & before:pending["before"]["heroes"].Vector()) if(before["ref"].String()==hiredRef) return;
    for(const auto & goal:campaign.plan()["goals"].Vector())
        if(goal["id"].String()==goalID && goal["kind"].String()=="hire_helper" && campaign.holdsCommitment(goalID)
            && resolve(ai,goal["target_ref"])==town && goal["candidate_ref"].String()=="tavern:"+std::to_string(hired->getHeroTypeID().getNum()))
        {
            JsonNode receipt;receipt["goal"]=goal;receipt["day"].Integer()=ai.cc->getCalendar().getCurrentDay();
            receipt["hero_ref"].String()=hiredRef;receipt["hero_type_id"].Integer()=hired->getHeroTypeID().getNum();
            persisted["helper_hire_receipts"][goalID]=receipt;
            JsonNode assignment;assignment["hero_ref"].String()=hiredRef;assignment["role"]=goal["helper_role"];
            auto & assignments=persisted["strategy_metadata"]["assignments"].Vector();
            std::erase_if(assignments,[&](const auto & old) { return old["hero_ref"]==assignment["hero_ref"]; });
            assignments.push_back(assignment);
            persist(ai);
            return;
        }
}
float NativeCampaign::priority(const NK2AI::Nullkiller & ai, const NK2AI::Goals::TSubgoal & task, float nativeScore) const
{
    // Ordinary policy covers every native path; a model grant applies only
    // to its named actor and exact operation endpoint.
    if(!campaign.plan().isNull())
    {
        std::function<bool(const NK2AI::Goals::TSubgoal &,int)> withinRisk = [&](const auto & item,int depth) {
            if(depth>16) return false;
            if(const auto * composition=dynamic_cast<const NK2AI::Goals::Composition *>(item.get()))
                for(const auto & child:composition->decompose(nullptr)) if(!withinRisk(child,depth+1)) return false;
            if(const auto * chain=dynamic_cast<const NK2AI::Goals::ExecuteHeroChain *>(item.get()))
            {
                const auto & path=chain->getPath();
                if(!path.heroArmy) return false;
                std::string riskGoal;
                for(const auto & intention:campaign.plan()["goals"].Vector())
                    if(intention["id"].String()==task->strategicGoalID)
                    {
                        const auto * target=resolve(ai,intention["target_ref"]);
                        if(path.targetHero==resolve(ai,intention["actor_ref"]) && target && path.targetTile()==target->visitablePos())
                            riskGoal=task->strategicGoalID;
                    }
                if(!campaign.allowsLoss(riskGoal,path.heroArmy->estimateCombatValue(),path.getTotalArmyLoss()))
                    return false;
            }
            return true;
        };
        if(!withinRisk(task,0)) return 0;
    }
    auto referenceOf=[&](const CGHeroInstance * hero) {
        const auto & aliases=static_cast<const JsonNode &>(persisted)["object_ids"].Struct();
        const auto found=aliases.find(std::to_string(hero->id.getNum()));
        return found==aliases.end() ? std::string() : externalai::objectReference(found->second);
    };
    // Native chains must not consume another operation's starting force, or
    // consolidate a stronger commander into a weaker one without a named
    // reinforcement intention. Never reverse a precomputed chain at meeting.
    std::function<bool(const NK2AI::Goals::TSubgoal &,int)> exchangesAllowed = [&](const auto & item,int depth) {
        if(depth>16) return false;
        if(const auto * composition=dynamic_cast<const NK2AI::Goals::Composition *>(item.get()))
            for(const auto & child:composition->decompose(nullptr)) if(!exchangesAllowed(child,depth+1)) return false;
        const auto * chain=dynamic_cast<const NK2AI::Goals::ExecuteHeroChain *>(item.get());
        if(!chain) return true;
        const auto & path=chain->getPath();
        if(!path.heroArmy || !path.targetHero) return false;
        const auto & spending=task->strategicGoalID;
        bool explicitDelivery=false;
        for(const auto & goal:campaign.plan()["goals"].Vector())
            explicitDelivery |= goal["id"].String()==spending && goal["kind"].String()=="reinforce_hero"
                && goal["actor_ref"].String()==referenceOf(path.targetHero);
        std::set<const CGHeroInstance *> participants{path.targetHero};
        for(const auto & node:path.nodes) if(node.targetHero) participants.insert(node.targetHero);
        uint64_t available=0;bool protectedDonor=false;
        for(const auto * hero:participants)
        {
            const auto army=hero->estimateCombatValue();
            const auto ref=referenceOf(hero);
            const auto floor=hero==path.targetHero ? 0 : campaign.exchangeForce(ref,world,helperSources(),spending);
            protectedDonor |= floor>0;
            available+=army-std::min<uint64_t>(army,floor);
            if(hero!=path.targetHero && !explicitDelivery && army>path.targetHero->estimateCombatValue()
                && hero->getHeroStrength()>path.targetHero->getHeroStrength()) return false;
        }
        // The path has no residual-donor-army quote. A protected donor is
        // usable only when its observed surplus proves the offered chain.
        return !protectedDonor || path.heroArmy->estimateCombatValue()<=available;
    };
    if(!exchangesAllowed(task,0)) return 0;
    std::function<bool(const NK2AI::Goals::TSubgoal &,int)> hiringAllowed = [&](const auto & item,int depth) {
        if(depth>16) return false;
        if(const auto * hire=dynamic_cast<const NK2AI::Goals::RecruitHero *>(item.get()))
        {
            const auto * candidate=hire->getCandidate();
            if(!candidate && hire->town)
                for(const auto * available:ai.cc->getAvailableHeroes(hire->town))
                    if(!candidate || available->estimateHeroCombatValue()>candidate->estimateHeroCombatValue()) candidate=available;
            return !heroHireReason(ai,hire->town,candidate,task->strategicGoalID).empty();
        }
        if(const auto * composition=dynamic_cast<const NK2AI::Goals::Composition *>(item.get()))
            for(const auto & child:composition->decompose(nullptr)) if(!hiringAllowed(child,depth+1)) return false;
        return true;
    };
    if(!hiringAllowed(task,0)) return 0;
    if(!task->strategicStabilizationReason.empty()) return 105000.0f;
    if(!task->strategicEmergencyTown.empty())
        for(const auto & defense:world["forecasts"]["defenses"].Vector())
            if(defense["town_ref"].String()==task->strategicEmergencyTown && defense["critical"].Bool()
                && defense["status"].String()=="insufficient_current_force"
                && defense["scenario_deadline_day"].Integer()<=world["day"].Integer()+1) return 110000.0f;
    // A timely native defense of an explicitly critical town can preempt an
    // economic/offensive commitment even when its hero is otherwise assigned.
    std::function<bool(const NK2AI::Goals::TSubgoal &,int)> urgent = [&](const auto & item,int depth) {
        if(depth>16) return false;
        if(const auto * defense=dynamic_cast<const NK2AI::Goals::DefendTown *>(item.get()))
        {
            const auto found=persisted["object_ids"].Struct().find(std::to_string(defense->town->id.getNum()));
            if(found==persisted["object_ids"].Struct().end()) return false;
            const auto ref=JsonNode(externalai::objectReference(found->second));
            const auto & critical=campaign.plan()["policy"]["critical_towns"].Vector();
            return defense->getThreat().turn<=1 && defense->getTurn()<=defense->getThreat().turn
                && std::find(critical.begin(),critical.end(),ref)!=critical.end();
        }
        if(const auto * composition=dynamic_cast<const NK2AI::Goals::Composition *>(item.get()))
            for(const auto & child:composition->decompose(nullptr)) if(urgent(child,depth+1)) return true;
        return false;
    };
    if(urgent(task,0)) return 100000.0f+std::max(0.0f,nativeScore);
    if(const auto * hire=dynamic_cast<const NK2AI::Goals::RecruitHero *>(task.get());hire && task->strategicGoalID.empty()
        && heroHireReason(ai,hire->town,hire->getCandidate()).starts_with("recover_own:")) return 99000.0f;
    if(!task->strategicGoalID.empty())
        for(size_t order=0; order<campaign.plan()["goals"].Vector().size(); ++order)
        {
            const auto & goal=campaign.plan()["goals"][order];
            if(goal["id"].String() == task->strategicGoalID
                && (world["goal_statuses"][goal["id"].String()]["state"].String() == "ready"
                    || (goal["kind"].String()=="preserve_force"
                        && campaign.requiresStabilization(goal["id"].String()))))
            {
                task->asTask()->nativeRank.goalOrder=static_cast<int>(order);
                return (world["goal_statuses"][goal["id"].String()]["state"].String()=="blocked" ? 95000.0f : 50000.0f)
                    + goal["priority"].Integer();
            }
        }
    // Keep independently useful opportunities, but do not divert a committed
    // hero to an unrelated operation before its current obligation completes.
    if(task->hero && !role(task->hero).empty()) return 0;
    for(const auto objectID : task->asTask()->getAffectedObjects())
    {
        const auto found = persisted["object_ids"].Struct().find(std::to_string(objectID.getNum()));
        if(found == persisted["object_ids"].Struct().end()) continue;
        const auto ref = externalai::objectReference(found->second);
        if(!campaign.participantGoals(ref,helperSources(),world).empty()) return 0;
    }
    return nativeScore;
}
TResources NativeCampaign::reservedResources(const TResources & currentFunds) const
{
    TResources result;
    auto reserve = campaign.reservedResources(executingGoal());
    for(int index = 0; index < 7; ++index) result[GameResID(index)] = reserve[index].Integer();
    std::lock_guard lock(executionMutex);
    if(!emergencyTown.empty())
        for(int i=0;i<7;++i)
        {
            const auto resource=GameResID(i);
            const int64_t spent=std::max<int64_t>(0,emergencyFunds[resource]-currentFunds[resource]);
            const int64_t remaining=std::max<int64_t>(0,emergencyCost[resource]-spent);
            // The emergency may spend this bounded purchase and no more;
            // unrelated economic locks cannot veto a concrete critical defense.
            result[resource]=std::max<int64_t>(0,currentFunds[resource]-remaining);
        }
    return result;
}
bool NativeCampaign::emergencySpending() const { std::lock_guard lock(executionMutex);return !emergencyTown.empty(); }
TResources NativeCampaign::plannedBoatResources(const CGHeroInstance * hero, const TResources & currentFunds, const TResources & nativeLocks) const
{
    std::string spending;
    if(hero)
    {
        const auto alias=persisted["object_ids"].Struct().find(std::to_string(hero->id.getNum()));
        if(alias!=persisted["object_ids"].Struct().end())
        {
            const auto participants=campaign.participantGoals(externalai::objectReference(alias->second),helperSources(),world);
            int choices=0;
            for(const auto & goal:campaign.plan()["goals"].Vector())
                if(participants.count(goal["id"].String()) && goal["kind"].String()!="develop_town"
                    && world["goal_statuses"][goal["id"].String()]["state"].String()=="ready")
                { spending=goal["id"].String();++choices; }
            if(choices!=1) spending.clear(); // No ambiguous shared money lease.
        }
    }
    const auto protectedFunds=campaign.reservedResources(spending);
    auto available=currentFunds-nativeLocks;
    for(int i=0;i<7;++i) available[GameResID(i)]-=protectedFunds[i].Integer();
    available.positive();
    return available;
}
uint64_t NativeCampaign::forceReserve(const CArmedInstance * army) const
{
    if(!army) return 0;
    const auto found = persisted["object_ids"].Struct().find(std::to_string(army->id.getNum()));
    if(found == persisted["object_ids"].Struct().end()) return 0;
    const auto ref = externalai::objectReference(found->second);
    std::string spending;
    { std::lock_guard lock(executionMutex); spending=deliveryGoal.empty() ? spendingGoal : deliveryGoal; }
    return campaign.exchangeForce(ref,world,helperSources(),spending);
}
uint64_t NativeCampaign::directDeliveryValue(const CGHeroInstance * receiver, const CGHeroInstance * source,
    const std::map<std::string,std::string> * prospectiveSources) const
{
    if(!receiver || !source || receiver==source || receiver->getOwner().getNum()!=world["player"].Integer()
        || source->getOwner()!=receiver->getOwner()) return 0;
    auto ref=[&](const CGHeroInstance * hero) {
        const auto & aliases=static_cast<const JsonNode &>(persisted)["object_ids"].Struct();
        const auto found=aliases.find(std::to_string(hero->id.getNum()));
        return found==aliases.end() ? std::string() : externalai::objectReference(found->second);
    };
    const auto recipient=ref(receiver), donor=ref(source);
    const auto * sourceUnits=ownArmyUnits(donor,world), *recipientUnits=ownArmyUnits(recipient,world);
    // A fresh direct-source quote must describe these actual armies. Do not
    // apply it to a virtual multi-hero chain or stale post-command snapshot.
    if(!sourceUnits || !recipientUnits || *sourceUnits!=armyUnits(source) || *recipientUnits!=armyUnits(receiver)) return 0;
    const auto replacements=prospectiveSources ? *prospectiveSources : helperSources();
    for(const auto & goal:campaign.plan()["goals"].Vector())
    {
        const auto & id=goal["id"].String();
        if(goal["kind"].String()!="reinforce_hero" || goal["actor_ref"].String()!=recipient
            || !campaign.holdsCommitment(id) || world["day"].Integer()>goal["deadline_day"].Integer()
            || CampaignState::armyPool(campaign.deliverySource(goal,replacements),world)!=donor) continue;
        const auto power=source->estimateCombatValue();
        const auto floor=wholeCreatureSourceFloor(donor,power,campaign.exchangeForce(donor,world,replacements,id),world,recipientUnits);
        return power>floor ? power-floor : 0;
    }
    return 0;
}
const CGHeroInstance * NativeCampaign::deliveryReceiver(const CGHeroInstance * first, const CGHeroInstance * second) const
{
    if(!first || !second) return nullptr;
    auto ref = [&](const CGHeroInstance * hero) {
        const auto found = persisted["object_ids"].Struct().find(std::to_string(hero->id.getNum()));
        return found == persisted["object_ids"].Struct().end() ? std::string() : externalai::objectReference(found->second);
    };
    const auto a = ref(first), b = ref(second);
    for(const auto & goal : campaign.plan()["goals"].Vector())
    {
        const auto & id = goal["id"].String();
        const auto & status = world["goal_statuses"][id]["state"].String();
        if(goal["kind"].String() != "reinforce_hero" || status == "completed" || status == "cancelled") continue;
        const auto source = CampaignState::armyPool(campaign.deliverySource(goal,helperSources()),world);
        if(!campaign.participantGoals(source,helperSources(),world).count(id)) continue;
        if(goal["actor_ref"].String() == a && source == b) return first;
        if(goal["actor_ref"].String() == b && source == a) return second;
    }
    return nullptr;
}
bool NativeCampaign::beginDelivery(const CGHeroInstance * receiver, const CArmedInstance * source)
{
    if(!receiver || !source) return false;
    for(const auto & goal:campaign.plan()["goals"].Vector())
        if(goal["kind"].String()=="reinforce_hero" && goal["actor_ref"].String()==reference(receiver)
            && CampaignState::armyPool(campaign.deliverySource(goal,helperSources()),world)==CampaignState::armyPool(reference(source),world)
            && campaign.participantGoals(reference(receiver),helperSources(),world).count(goal["id"].String())
            && receiver->estimateCombatValue()<goal["complete_when"]["value"].Integer())
        {
            std::lock_guard lock(executionMutex);
            deliveryGoal=goal["id"].String();
            return true;
        }
    return false;
}
void NativeCampaign::endDelivery() { std::lock_guard lock(executionMutex); deliveryGoal.clear(); }
JsonNode NativeCampaign::executionSnapshot(NK2AI::Nullkiller & ai)
{
    JsonNode snapshot;
    snapshot["day"].Integer()=ai.cc->getCalendar().getCurrentDay();
    snapshot["player"].Integer()=ai.playerID.getNum();
    snapshot["resources"]=resourceValues(ai.cc->getResourceAmount());
    snapshot["heroes"].Vector();snapshot["towns"].Vector();
    for(const auto * hero:ai.cc->getHeroesInfo())
    {
        JsonNode item;item["ref"].String()=reference(hero);item["position"]=coordinate(hero->visitablePos());
        item["movement"].Integer()=hero->movementPointsRemaining();item["mana"].Integer()=hero->mana;
        item["hero_type_id"].Integer()=hero->getHeroTypeID().getNum();
        item["army_value"].Integer()=hero->estimateCombatValue();item["in_boat"].Bool()=hero->inBoat();snapshot["heroes"].Vector().push_back(item);
    }
    for(const auto * town:ai.cc->getTownsInfo())
    {
        JsonNode item;item["ref"].String()=reference(town);
        item["army_holder_ref"].String()=reference(town->getUpperArmy());
        item["army_value"].Integer()=town->getUpperArmy()->estimateCombatValue();item["buildings"].Vector();
        for(const auto & [id,building]:town->getTown()->buildings)
            if(town->hasBuilt(id)) item["buildings"].Vector().emplace_back(id.getNum());
        snapshot["towns"].Vector().push_back(item);
    }
    return snapshot;
}
void NativeCampaign::resourcesChanged(const TResources & resources)
{
    std::lock_guard lock(executionMutex);
    if(resourceLedgerActive) resourceLedger.received(resourceValues(resources));
}
void NativeCampaign::beginExecution(NK2AI::Nullkiller & ai,const NK2AI::Goals::TTask & task)
{
    const auto * goal=dynamic_cast<const NK2AI::Goals::AbstractGoal *>(task.get());
    const auto goalID=goal ? goal->strategicGoalID : "";
    const auto goalType=goal ? goal->goalType : NK2AI::Goals::INVALID;
    {
        std::lock_guard lock(executionMutex);
        spendingGoal=goalID;
        acceptedLossRatio=campaign.lossLimit(goalID);
        emergencyTown=goal ? goal->strategicEmergencyTown : "";
        emergencyCost=goal ? goal->strategicEmergencyCost : TResources();
        emergencyFunds=ai.cc->getResourceAmount();
        resourceLedger.begin(resourceValues(emergencyFunds));resourceLedgerActive=true;
    }
    {
        std::lock_guard lock(visitMutex);
        activePassageGoal=JsonNode();activePassageActor=activePassageEntry=-1;activePassageDay=0;
        activeSiteGoal=JsonNode();activeSiteActor=activeSiteObject=-1;activeSiteDay=0;
        siteVisits.clear();
        for(const auto & item:campaign.plan()["goals"].Vector())
            if(item["id"].String()==goalID && item["kind"].String()=="visit_site")
            {
                const auto * actor=dynamic_cast<const CGHeroInstance *>(resolve(ai,item["actor_ref"]));
                const auto * site=resolve(ai,item["target_ref"]);
                if(actor && actor->getOwner()==ai.playerID && site && ai.cc->isVisible(site->visitablePos())
                    && (site->ID==Obj::SCHOLAR || site->ID==Obj::TREASURE_CHEST || site->ID==Obj::OBELISK
                        || site->ID==Obj::KEYMASTER || ((site->ID==Obj::BORDERGUARD || site->ID==Obj::BORDER_GATE)
                            && ai.cc->getPlayerState(ai.playerID)->wasKeymasterVisited(site->subID) && canOpenKeyBorder(site,actor))))
                {
                    activeSiteGoal=item;activeSiteActor=actor->id.getNum();activeSiteObject=site->id.getNum();
                    activeSiteDay=ai.cc->getCalendar().getCurrentDay();
                }
            }
        passageVisits.clear();
        for(const auto & item:campaign.plan()["goals"].Vector())
            if(item["id"].String()==goalID && item["kind"].String()=="explore_passage")
            {
                const auto * actor=dynamic_cast<const CGHeroInstance *>(resolve(ai,item["actor_ref"]));
                const auto * entry=resolve(ai,item["target_ref"]);
                if(actor && actor->getOwner()==ai.playerID && entry && entry->ID==Obj::SUBTERRANEAN_GATE
                    && ai.cc->isVisible(entry->visitablePos()))
                {
                    activePassageGoal=item;activePassageActor=actor->id.getNum();activePassageEntry=entry->id.getNum();
                    activePassageDay=ai.cc->getCalendar().getCurrentDay();
                }
            }
    }
    replanAfterCombat=false;
    executionActive=true;executionStarted=std::chrono::steady_clock::now();
    JsonNode pending;
    pending["version"].Integer()=1;
    pending["before"]=executionSnapshot(ai);
    auto & action=pending["action"];
    action["goal_id"].String()=goalID;
    action["campaign_revision"]=campaign.plan()["revision"];
    action["native_goal_type"].Integer()=goalType;
    if(goal && !goal->strategicStabilizationReason.empty()) action["stabilization"].String()=goal->strategicStabilizationReason;
    using namespace NK2AI::Goals;
    action["kind"].String()=goalType==BUILD_STRUCTURE ? "build" : goalType==BUY_ARMY ? "recruit"
        : goalType==RECRUIT_HERO ? "hire_hero" : goalType==EXECUTE_HERO_CHAIN ? "visit" : "native_task";
    if(goalType==BUY_ARMY) for(const auto & intention:campaign.plan()["goals"].Vector())
        if(intention["id"].String()==goalID && intention["kind"].String()=="prepare_garrison")
        {
            action["kind"].String()="prepare_garrison";
            action["garrison_mode"]=intention["garrison_mode"];
        }
    if(goal && !goal->strategicEmergencyTown.empty())
    {
        action["emergency"]["town_ref"].String()=goal->strategicEmergencyTown;
        action["emergency"]["reason"].String()="insufficient_visible_critical_front_before_economic_spending";
        action["emergency"]["planned_cost"]=resourceValues(goal->strategicEmergencyCost);
        action["emergency"]["reserved_before"]=campaign.reservedResources();
        action["emergency"]["legacy_locks_before"]=resourceValues(ai.getLockedResources());
    }
    persisted["pending_native_task"]=pending;
    persist(ai); // Value intent and own facts only; no task/path survives a save.
}
void NativeCampaign::endExecution(NK2AI::Nullkiller & ai,const std::string & acknowledgment)
{
    const auto pending=persisted["pending_native_task"];
    if(!pending.isNull())
    {
        const auto before=pending["before"],after=executionSnapshot(ai);
        auto action=pending["action"];
        action["before"]=before;action["after"]=after;
        action["acknowledgment"].String()=acknowledgment;
        for(int i=0;i<7;++i) action["resource_delta"].Vector().emplace_back(after["resources"][i].Integer()-before["resources"][i].Integer());
        const bool changed=before["resources"]!=after["resources"] || before["heroes"]!=after["heroes"] || before["towns"]!=after["towns"];
        // Net own-state changes are facts. They do not establish full task
        // completion, gross purchase cost or the cause of changes during load.
        externalai::recordResult(persisted["memory"],after["day"].Integer(),action,false);
        auto & result=persisted["memory"]["recent_results"].Vector().back();
        const bool known=acknowledgment!="recovered_unknown" && acknowledgment!="interrupted" && before["day"]==after["day"];
        {
            std::lock_guard lock(executionMutex);
            if(known && resourceLedgerActive) result["action"]["resource_flows"]=resourceLedger.receipt(after["resources"]);
            resourceLedgerActive=false;
        }
        if(known)
            for(const auto & goal:campaign.plan()["goals"].Vector()) if(goal["id"]==action["goal_id"])
            {
                const auto & progress=static_cast<const JsonNode &>(persisted)["operation_progress"][goal["id"].String()];
                // An acknowledged attempt alone is not target progress. The
                // next fresh path/force observation decides whether it advanced.
                if(!progress.isNull())
                    persisted["operation_progress"][goal["id"].String()]["last_no_change_day"]=after["day"];
            }
        if(known && action["emergency"].isStruct())
        {
            for(int i=0;i<7;++i)
            {
                const auto reserve=action["emergency"]["reserved_before"][i].Integer()+action["emergency"]["legacy_locks_before"][i].Integer();
                const auto oldGap=std::max<int64_t>(0,reserve-before["resources"][i].Integer());
                const auto newGap=std::max<int64_t>(0,reserve-after["resources"][i].Integer());
                result["action"]["reservation_override"].Vector().emplace_back(std::max<int64_t>(0,newGap-oldGap));
            }
        }
        result["outcome"].String()=!known ? "reconciled_unknown" : changed ? "effects_observed" : "no_change_observed";
        JsonNode trace=result;
        trace["experience_id"].String()=experienceID;
        trace["player"]=after["player"];
        if(executionActive) trace["elapsed_ms"].Integer()=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-executionStarted).count();
        logAi->info("NK3_EXECUTION %s",trace.toCompactString());
        recordLearningExecution(trace);
        persisted.Struct().erase("pending_native_task");
    }
    {
        std::lock_guard lock(visitMutex);
        activePassageGoal=JsonNode();activePassageActor=activePassageEntry=-1;activePassageDay=0;
        passageVisits.clear();
    }
    executionActive=false;
    {
        std::lock_guard lock(executionMutex);
        spendingGoal.clear();
        acceptedLossRatio=campaign.lossLimit(std::string());
        emergencyTown.clear();emergencyCost=TResources();emergencyFunds=TResources();
    }
    persist(ai);
}
std::string NativeCampaign::executingGoal() const { std::lock_guard lock(executionMutex); return spendingGoal; }
std::string NativeCampaign::role(const CGHeroInstance * hero) const
{
    if(!hero) return "";
    const auto found = persisted["object_ids"].Struct().find(std::to_string(hero->id.getNum()));
    if(found == persisted["object_ids"].Struct().end()) return "";
    const auto ref = externalai::objectReference(found->second);
    const auto obligations = campaign.participantGoals(ref,helperSources(),world);
    const auto & metadata = static_cast<const JsonNode &>(persisted)["strategy_metadata"];
    for(const auto & assignment : metadata["assignments"].Vector())
        if(assignment["hero_ref"].isString() && assignment["hero_ref"].String() == ref && !obligations.empty())
            {
                const auto & role = assignment["role"].String();
                if(role == "main" || role == "defender") return "main";
                if(role == "scout" || role == "collector" || role == "reinforcement") return "scout";
            }
    for(const auto & goal : campaign.plan()["goals"].Vector())
        if(obligations.count(goal["id"].String()) && goal["actor_ref"].isString() && goal["actor_ref"].String() == ref)
            return goal["kind"].String() == "scout_frontier" || goal["kind"].String() == "scout_area" || goal["kind"].String() == "preserve_force" || goal["kind"].String() == "explore_passage" ? "scout" : "main";
    if(!obligations.empty()) return "scout";
    return "";
}
}
