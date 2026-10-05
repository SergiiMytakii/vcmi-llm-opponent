#include "../Nullkiller2/StdInc.h"
#include "NativeCampaign.h"
#include "KnownLandApproach.h"
#include "NativeTrace.h"
#include "Forecasts.h"
#include "NativePersistence.h"
#include "OffensivePreparation.h"
#include "StrategicDecision.h"
#include "../../lib/StartInfo.h"
#include "../Nullkiller2/Markers/DefendTown.h"
#include "../../lib/mapObjects/IOwnableObject.h"
#include "../ExternalAI/StrategyMemory.h"
#include "../ExternalAI/ObservationRules.h"
#include "../Nullkiller2/Engine/Nullkiller.h"
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
#include "../../lib/battle/CombatValue.h"
#include "../../lib/mapping/CMap.h"
#include <fstream>
#include <cmath>

namespace nullkiller3
{
namespace
{
JsonNode resourceValues(const TResources & values)
{
    JsonNode result;
    for(int index = 0; index < 7; ++index) result.Vector().emplace_back(values[GameResID(index)]);
    return result;
}
std::string objectKind(const CGObjectInstance * object)
{
    switch(object->ID.toEnum())
    {
    case Obj::TOWN: return "town";
    case Obj::HERO: return "hero";
    case Obj::MINE: return "mine";
    case Obj::RESOURCE: return "resource";
    case Obj::MONSTER: return "monster";
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
NativeCampaign::NativeCampaign(const JsonNode & saved) : persisted(restoreNativeNamespace(saved)), campaign(persisted["native_campaign"])
{
    if(!campaign.restoreReason().empty()) logAi->warn("NK3 saved campaign discarded: %s", campaign.restoreReason());
    if(!saved.isNull() && persisted!=saved) logAi->debug("NK3 saved namespace validated before restoring intentions");
    externalai::initializeObjectAliases(persisted);
    experienceID=externalai::initializeExperience(persisted);
    acceptedRevision=campaign.plan()["revision"].Integer();
    if(acceptedRevision) acceptedLossRatio=campaign.plan()["policy"]["max_loss_ratio"].Float();
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
            const auto floor=campaign.reservedForce(reference(helper),world,sources,goal["id"].String());
            const auto surplus=strength>floor ? strength-floor : 0;
            if(!surplus || actor->estimateCombatValue()+surplus<goal["complete_when"]["value"].Integer()) continue;
            auto prospectiveSources=sources;
            prospectiveSources[goal["id"].String()]=reference(helper);
            NK2AI::Goals::TGoalVec admitted;
            rememberTasks(admitted,deliveryTasks(ai,actor,helper),goal,ai,&prospectiveSources);
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
NK2AI::Goals::TGoalVec NativeCampaign::deliveryTasks(NK2AI::Nullkiller & ai,const CGHeroInstance * actor,const CGObjectInstance * target) const
{
    using namespace NK2AI;
    if(!actor || !target) return {};
    Goals::TGoalVec generated;
    if(const auto * town=dynamic_cast<const CGTownInstance *>(target))
    {
        auto paths=ai.pathfinder->getPathInfo(town->visitablePos(),false);
        std::erase_if(paths,[&](const AIPath & path){return path.targetHero!=actor;});
        generated=Goals::CaptureObjectsBehavior::getVisitGoals(paths,&ai,town,true);
    }
    else generated=Goals::GatherArmyBehavior(actor,target).decompose(&ai);
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
        const auto floor=campaign.reservedForce(sources.at(goal["id"].String()),world,sources,goal["id"].String());
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
    }
}
void NativeCampaign::battleResult(JsonNode ownResult)
{
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
        const auto day=action["day"].Integer();
        const auto won=action["won"].Bool(),draw=action["draw"].Bool();
        const auto & aliases=static_cast<const JsonNode &>(persisted)["object_ids"].Struct();
        const auto found=aliases.find(std::to_string(action["engine_object_id"].Integer()));
        action["actor_ref"]=found==aliases.end() ? JsonNode() : JsonNode(externalai::objectReference(found->second));
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
    world["confirmed_resource_pickups"].Vector();
    for(const auto & [ref, day] : persisted["confirmed_resource_pickups"].Struct())
        world["confirmed_resource_pickups"].Vector().emplace_back(ref);
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
        item["strength"]["army_ai_value"] = item["army_value"];
        item["movement"].Integer() = hero->movementPointsRemaining();
        item["mana"].Integer() = hero->mana;
        item["movement_per_day"].Integer() = hero->movementPointsLimit();
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
        item["army_holder_ref"].String() = reference(town->getUpperArmy());
        if(const auto * visitor=town->getVisitingHero();visitor && visitor->getOwner()==ai.playerID)
            item["visiting_hero_ref"].String()=reference(visitor);
        item["daily_income"] = resourceValues(town->dailyIncome());
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
    JsonNode actions;
    actions.Vector();
    std::set<std::string> retainedTargets;
    for(const auto & goal : campaign.plan()["goals"].Vector())
    {
        const auto & status = campaign.statuses()[goal["id"].String()]["state"].String();
        if(status == "completed" || status == "cancelled") continue;
        retainedTargets.insert(goal["target_ref"].String());
        if(goal["actor_ref"].isString()) retainedTargets.insert(goal["actor_ref"].String());
        if(goal["kind"].String() == "reinforce_hero") retainedTargets.insert(campaign.deliverySource(goal,helperSources()));
    }
    externalai::observeMemory(persisted["memory"], world, actions, visiblePositions,retainedTargets);
    world["objects"].Vector();
    for(auto object : persisted["memory"]["known_objects"].Vector())
    {
        object["visible"].Bool() = !object["stale"].Bool() && !object["not_seen_at_last_position"].Bool();
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
JsonNode NativeCampaign::observedEnemyApproaches(NK2AI::Nullkiller & ai)
{
    std::map<int3,size_t> index;std::vector<KnownLandTile> land;
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
                cell.neutralGuards.push_back(reference(guard));
        index.emplace(position,land.size());land.push_back(std::move(cell));
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
void NativeCampaign::updateForecasts(NK2AI::Nullkiller & ai)
{
    repairedSourcesChanged |= repairDeliverySources(ai);
    world["forecasts"] = forecastBranches(world,campaign.reservedResources());
    auto & forecasts=world["forecasts"];
    world["enemy_approaches"]=observedEnemyApproaches(ai);
    forecasts["threats"]=forecastThreats(world);

    auto arrivals = [&](const JsonNode & pos, bool frontier) {
        JsonNode result;result.Vector();
        const int3 position(pos[0].Integer(),pos[1].Integer(),pos[2].Integer());
        const auto paths=ai.pathfinder->getPathInfo(position,false);
        for(const auto * hero:ai.cc->getHeroesInfo())
        {
            for(const auto & path:paths)
            {
                if(path.targetHero!=hero || !path.heroArmy || path.getFirstBlockedAction()) continue;
                if(frontier && path.exchangeCount>1) continue;
                bool single=true;
                for(const auto & step:path.nodes) single &= step.targetHero==hero;
                if(!single) continue;
                JsonNode arrival;
                arrival["hero_ref"].String()=reference(hero);
                arrival["day"].Integer()=world["day"].Integer()+path.turn();
                arrival["movement_cost"].Float()=path.movementCost();
                arrival["army_loss_estimate"].Integer()=path.getTotalArmyLoss();
                arrival["army_value"].Integer()=path.heroArmy->estimateCombatValue();
                arrival["fighting_strength_estimate"].Integer()=path.getHeroStrength();
                if(std::find(result.Vector().begin(),result.Vector().end(),arrival)==result.Vector().end()) result.Vector().push_back(arrival);
            }
        }
        return result;
    };
    for(auto & frontier:world["frontier_options"].Vector())
        frontier["own_arrivals"]=arrivals(frontier["position"],true);
    forecasts["routes"].Vector();
    for(const auto & object:world["visible_objects"].Vector())
    {
        const auto & kind=object["kind"].String();
        if(kind!="town" && kind!="mine" && kind!="resource") continue;
        const auto & pos=object["position"];
        JsonNode route;
        route["target_ref"]=object["ref"];
        route["own_arrivals"]=arrivals(pos,false);
        forecasts["routes"].Vector().push_back(route);
    }
    // Own hero destinations are known even when a garrisoned hero is absent
    // from the map's visitable-object list. They support courier meetings only.
    for(const auto & hero:world["heroes"].Vector())
    {
        JsonNode route;route["target_ref"]=hero["ref"];route["own_arrivals"]=arrivals(hero["position"],false);
        forecasts["routes"].Vector().push_back(route);
    }
    forecasts["defenses"]=forecastDefenses(world,campaign);
    const auto joint=forecastCommitments(world,campaign,helperSources());
    for(const auto * field:{"commitments","resource_calendar","army_pools","deliveries","stock_at_deadline"}) forecasts[field]=joint[field];
    world["goal_statuses"]=campaign.review(world);
    world["goal_feedback"].Vector();
    for(const auto & goal:campaign.plan()["goals"].Vector())
    {
        if(goal["kind"].String()!="capture_target" && goal["kind"].String()!="secure_resource" && goal["kind"].String()!="scout_frontier") continue;
        auto feedback=campaign.routeFeedback(goal,world);
        feedback["status"]=world["goal_statuses"][goal["id"].String()];
        world["goal_feedback"].Vector().push_back(feedback);
    }
    observeBuildingProgress();
    observeOperationProgress();
    world["offensive_preparation"]=offensivePreparation(campaign,world);
    forecasts["route_assumptions"].String()="All visible town/mine/resource targets, complete own hero positions and known frontiers, current permitted land/boat paths and movement, including presently funded owned shipyard quotes. Frontier arrivals require a single hero without an army exchange. No hidden target, future shipyard, boat spell, enemy intention or battle win probability. Empty arrivals mean unknown/unestablished, not absent.";
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
        for(const auto & town : world["towns"].Vector())
        { JsonNode item; for(const auto * field:{"ref","buildings","army_holder_ref","defense_value"}) item[field]=town[field]; trace["towns"].Vector().push_back(item); }
        logAi->info("NK3_CAMPAIGN %s", trace.toCompactString());
    }
}
void NativeCampaign::persist(NK2AI::Nullkiller & ai)
{
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
            if(loss>strength*campaign.plan()["policy"]["max_loss_ratio"].Float()) return false;
            const auto reserve=prospectiveSources
                ? campaign.reservedForce(reference(path.targetHero),world,*prospectiveSources,executingGoal())
                : forceReserve(path.targetHero);
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
        if(world["goal_statuses"][goal["id"].String()]["state"].String() != "ready" && !stabilizing) continue;
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
        if(kind=="defend_area" && actor && target && actor->visitablePos()==target->visitablePos())
        {
            const auto * town=dynamic_cast<const CGTownInstance *>(target);
            if(town && town->getOwner()==ai.playerID)
            {
                const auto * source=town->getUpperArmy();
                const auto floor=campaign.reservedForce(reference(source),world,helperSources(),goal["id"].String());
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
            const auto floor=campaign.reservedForce(reference(town),world,sources,goal["id"].String());
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
            if(kind == "scout_frontier")
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
                std::erase_if(paths, [&](const AIPath & path) { return path.targetHero != actor; });
                generated = CaptureObjectsBehavior::getVisitGoals(paths, &ai, target, true);
                if(std::none_of(generated.begin(),generated.end(),[](const auto & task){return !task->invalid();}) && target)
                    generated=repairRoute(ai,actor,target);
            }
        }
        const auto countBefore = output.size();
        rememberTasks(output, generated, goal, ai);
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
            const std::string reason=late ? "deadline_unreachable" : "route_not_established";
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
        else if(output.size()>countBefore) persisted["goal_blockers"].Struct().erase(goal["id"].String());
    }
    return output;
}
std::string NativeCampaign::heroHireReason(const NK2AI::Nullkiller & ai, const CGTownInstance * town, const CGHeroInstance * candidate) const
{
    if(!town || !candidate || town->getOwner()!=ai.playerID) return {};
    TResources price;price[EGameResID::GOLD]=GameConstants::HERO_GOLD_COST;
    if(!ai.getFreeResources().canAfford(price)) return {};
    const auto heroes=ai.cc->getHeroesInfo();
    if(heroes.empty()) return "main:no_owned_hero";
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
float NativeCampaign::priority(const NK2AI::Nullkiller & ai, const NK2AI::Goals::TSubgoal & task, float nativeScore) const
{
    // The accepted risk ceiling applies to every selected native path, even
    // when its hero/opportunity is outside the campaign's named goals.
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
                if(path.getTotalArmyLoss()>path.heroArmy->estimateCombatValue()*campaign.plan()["policy"]["max_loss_ratio"].Float())
                    return false;
            }
            return true;
        };
        if(!withinRisk(task,0)) return 0;
    }
    std::function<bool(const NK2AI::Goals::TSubgoal &,int)> hiringAllowed = [&](const auto & item,int depth) {
        if(depth>16) return false;
        if(const auto * hire=dynamic_cast<const NK2AI::Goals::RecruitHero *>(item.get()))
        {
            const auto * candidate=hire->getHero();
            if(!candidate && hire->town)
                for(const auto * available:ai.cc->getAvailableHeroes(hire->town))
                    if(!candidate || available->estimateHeroCombatValue()>candidate->estimateHeroCombatValue()) candidate=available;
            return !heroHireReason(ai,hire->town,candidate).empty();
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
    return campaign.reservedForce(ref,world,helperSources(),spending);
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
        emergencyTown=goal ? goal->strategicEmergencyTown : "";
        emergencyCost=goal ? goal->strategicEmergencyCost : TResources();
        emergencyFunds=ai.cc->getResourceAmount();
        resourceLedger.begin(resourceValues(emergencyFunds));resourceLedgerActive=true;
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
        persisted.Struct().erase("pending_native_task");
    }
    executionActive=false;
    {
        std::lock_guard lock(executionMutex);
        spendingGoal.clear();
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
            return goal["kind"].String() == "scout_frontier" || goal["kind"].String() == "preserve_force" ? "scout" : "main";
    if(!obligations.empty()) return "scout";
    return "";
}
}
