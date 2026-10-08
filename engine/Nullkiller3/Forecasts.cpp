#include "Global.h"
#include "Forecasts.h"
#include "constants/NumericConstants.h"

namespace nullkiller3
{
JsonNode forecastDailyIncome(const JsonNode & world, int64_t date, const JsonNode & baseIncome)
{
    const auto week=std::max<int64_t>(1,world["days_in_week"].Integer());
    const auto dayOfWeek=(date-1)%week+1;
    const auto & bonuses=world["economy"]["weekly_bonus_percent"];
    constexpr const char * resourceNames[]={"wood","mercury","ore","sulfur","crystal","gems","gold"};
    JsonNode result;
    for(int i=0;i<7;++i)
    {
        const auto base=baseIncome[i].Integer(), bonus=bonuses[resourceNames[i]].Integer();
        // Keep NewTurnProcessor's integer division order, including signed easy
        // difficulty bonuses. Averaging the multiplier loses calendar rounding.
        const auto before=base*bonus*(dayOfWeek-1)/week/100;
        const auto after=base*bonus*dayOfWeek/week/100;
        result.Vector().emplace_back(std::min(GameConstants::PLAYER_RESOURCES_CAP,base+after-before));
    }
    return result;
}

std::string allocationCheckpointFacts(const CampaignState & campaign,const JsonNode & world)
{
    using Funds=std::array<int64_t,7>;
    Funds free{};
    const auto protectedFunds=campaign.reservedResources();
    for(int i=0;i<7;++i) free[i]=std::max<int64_t>(0,world["resources"][i].Integer()-protectedFunds[i].Integer());
    const auto day=world["day"].Integer(),week=std::max<int64_t>(1,world["days_in_week"].Integer());
    std::set<std::string> choices;
    for(const auto & town:world["towns"].Vector())
    {
        bool committed=false;
        for(const auto & goal:campaign.plan()["goals"].Vector())
            if(campaign.holdsCommitment(goal["id"].String()) && goal["target_ref"]==town["ref"]
                && (goal["kind"].String()=="develop_town" || goal["kind"].String()=="reinforce_hero"
                    || goal["kind"].String()=="defend_area")) committed=true;
        if(committed) continue; // A supported promised purchase is native continuation.
        for(const bool afterGrowth:{false,true})
        {
            if(afterGrowth && day%week!=0) continue;
            Funds armyCost{};
            JsonNode stock;stock.Vector();
            int64_t power=0;
            bool fundable=true,paid=false;
            for(const auto & unit:town["recruitment_options"].Vector())
            {
                const auto count=unit["available"].Integer()+(afterGrowth ? unit["weekly_growth"].Integer() : 0);
                if(count<=0 || unit["unit_value"].Integer()<=0) continue;
                for(int i=0;i<7;++i)
                {
                    const auto price=unit["unit_cost"][i].Integer();
                    if(price<0 || (price>0 && count>(free[i]-armyCost[i])/price)) { fundable=false;break; }
                    armyCost[i]+=count*price;paid |= price>0;
                }
                if(!fundable) break;
                if(count>(std::numeric_limits<int64_t>::max()-power)/unit["unit_value"].Integer())
                    return "allocation_context_overflow";
                power+=count*unit["unit_value"].Integer();
                JsonNode item;item["creature"]=unit["creature"];item["count"].Integer()=count;
                item["unit_cost"]=unit["unit_cost"];item["unit_value"]=unit["unit_value"];
                stock.Vector().push_back(item);
            }
            if(!fundable || !paid || !power) continue;
            std::ranges::sort(stock.Vector(),[](const auto & a,const auto & b){return a["creature"].Integer()<b["creature"].Integer();});
            for(const auto & option:town["building_options"].Vector())
            {
                if(!option["supported"].Bool() || option["availability"].String()!="allowed_now"
                    || option["income_delta"][6].Integer()<=0) continue;
                bool affordable=true,conflict=false;
                for(int i=0;i<7;++i)
                {
                    const auto cost=option["cost"][i].Integer();
                    affordable &= cost>=0 && cost<=free[i];
                    conflict |= cost>free[i]-armyCost[i];
                }
                if(!affordable || !conflict) continue;
                JsonNode choice;choice["town_ref"]=town["ref"];choice["building_id"]=option["id"];
                choice["investment_cost"]=option["cost"];choice["income_delta"]=option["income_delta"];
                choice["recruitment_stock"]=stock;choice["army_value"].Integer()=power;
                // These are conditional budget alternatives, not battle or delivery
                // guarantees. Packing, transport and existing force floors remain
                // authoritative at command admission. No raw cash/day/route score
                // enters the decision identity; affordability crossings do.
                choices.insert(choice.toCompactString());
            }
        }
    }
    std::string facts;
    for(const auto & choice:choices) { facts+=choice;facts+='\n'; }
    // Keep the complete own building/stock DTO in the request. Never select a
    // top-K subset when a pathological map exceeds the signal/storage bound.
    return facts.size()>8192 ? "allocation_context_overflow" : facts;
}

bool buildingSequence(const JsonNode & town, const JsonNode & target, std::vector<const JsonNode *> & sequence)
{
    std::set<int64_t> built, visiting;
    for(const auto & id:town["buildings"].Vector()) built.insert(id.Integer());
    std::function<bool(const JsonNode &,std::set<int64_t> &,std::vector<const JsonNode *> &,std::set<int64_t> &)> satisfy;
    satisfy = [&](const JsonNode & expression,auto & present,auto & steps,auto & active) {
        if(expression.isNull()) return true;
        if(expression.getType()==JsonNode::JsonType::DATA_INTEGER)
        {
            const auto id=expression.Integer();
            if(present.count(id)) return true;
            if(active.size()>32 || !active.insert(id).second) return false;
            const JsonNode * option=nullptr;
            for(const auto & candidate:town["building_options"].Vector()) if(candidate["id"]==expression) option=&candidate;
            if(!option || !(*option)["supported"].Bool()) { active.erase(id); return false; }
            const auto & availability=(*option)["availability"].String();
            if(availability=="forbidden" || availability=="another_capitol_exists" || availability=="unsupported_build_mechanic" || availability=="no_water" || availability=="unknown") { active.erase(id); return false; }
            if(!satisfy((*option)["requirements"],present,steps,active)) { active.erase(id); return false; }
            active.erase(id); present.insert(id); steps.push_back(option);
            return steps.size()<=7;
        }
        if(!expression.isVector() || expression.Vector().empty() || !expression[0].isString()) return false;
        if(expression[0].String()=="allOf")
        {
            for(size_t i=1;i<expression.Vector().size();++i) if(!satisfy(expression[i],present,steps,active)) return false;
            return true;
        }
        if(expression[0].String()=="anyOf")
        {
            bool found=false; int64_t bestCost=std::numeric_limits<int64_t>::max();
            std::set<int64_t> bestBuilt;
            std::vector<const JsonNode *> bestSteps;
            for(size_t i=1;i<expression.Vector().size();++i)
            {
                auto alternativeBuilt=present, alternativeActive=active;
                auto alternativeSteps=steps;
                if(!satisfy(expression[i],alternativeBuilt,alternativeSteps,alternativeActive)) continue;
                int64_t cost=0;
                for(const auto * step:alternativeSteps) cost+=(*step)["cost"][6].Integer();
                if(cost<bestCost) { found=true; bestCost=cost; bestBuilt=alternativeBuilt; bestSteps=alternativeSteps; }
            }
            if(found) { present=bestBuilt; steps=bestSteps; }
            return found;
        }
        // Negative prerequisites require a separate proven forecast mechanic.
        return false;
    };
    return satisfy(target["id"],built,sequence,visiting);
}

JsonNode forecastBranches(const JsonNode & world, const JsonNode & reserves, const JsonNode & selectedGoal)
{
    using Funds = std::array<int64_t,7>;
    auto funds = [](const JsonNode & values) {
        Funds result{};
        for(int i=0;i<7;++i) result[i]=values[i].Integer();
        return result;
    };
    auto node = [](const Funds & values) {
        JsonNode result; for(auto value:values) result.Vector().emplace_back(value); return result;
    };
    const auto protectedFunds = funds(reserves), initial = funds(world["resources"]);
    const auto daily = funds(world["economy"]["base_daily_income"].isVector() ? world["economy"]["base_daily_income"] : world["daily_income"]);
    const int day = world["day"].Integer();
    const int deadline = selectedGoal.isNull() ? day+6 : selectedGoal["deadline_day"].Integer();
    const int week = std::max<int64_t>(1,world["days_in_week"].Integer());
    JsonNode result;
    result["deadline_day"].Integer()=deadline;
    result["weekly_growth_day"].Integer()=((day-1)/week+1)*week+1;
    result["alternatives"].Vector();
    for(const auto & town:world["towns"].Vector())
    {
        if(!selectedGoal.isNull() && selectedGoal["target_ref"]!=town["ref"]) continue;
        const JsonNode * best=nullptr;
        std::vector<const JsonNode *> bestSequence;
        for(const auto & option:town["building_options"].Vector())
        {
            const auto & availability=option["availability"].String();
            if(!option["supported"].Bool() || availability=="built") continue;
            std::vector<const JsonNode *> sequence;
            if(!buildingSequence(town,option,sequence) || sequence.empty()) continue;
            const bool selected = !selectedGoal.isNull() && option["id"]==selectedGoal["building_id"];
            if(selected || (selectedGoal.isNull() && option["income_delta"][6].Integer()>0
                && (!best || option["income_delta"][6].Integer()>(*best)["income_delta"][6].Integer()))) { best=&option; bestSequence=sequence; }
        }
        JsonNode development;
        development["approach"].String()="economy";
        development["town_ref"]=town["ref"];
        if(!selectedGoal.isNull()) development["goal_id"]=selectedGoal["id"];
        development["status"].String()=best ? "conditional" : "unknown";
        development["assumptions"].Vector().emplace_back("Retain current income sources; no pickups, trade or other spending; protect existing reserves.");
        development["assumptions"].Vector().emplace_back("One building per town/day including positive prerequisite chains; OR branches choose the lowest gold cost. Loaded AI bonuses use calendar rounding; weekly rewards/events and negative prerequisites are excluded.");
        auto balance=initial, income=daily;
        int buildDay=-1;
        if(best)
        {
            development["building_id"]=(*best)["id"];
            Funds totalCost{};
            for(const auto * step:bestSequence) for(int i=0;i<7;++i) totalCost[i]+=(*step)["cost"][i].Integer();
            development["cost"]=node(totalCost);
            size_t next=0;
            for(int date=day;date<=deadline;++date)
            {
                bool affordable=true;
                if(next<bestSequence.size())
                {
                    const auto & step=*bestSequence[next];
                    const auto cost=funds(step["cost"]), increment=funds(step["income_delta"]);
                    for(int i=0;i<7;++i) affordable &= balance[i]-protectedFunds[i]>=cost[i];
                    if(affordable && (date>day || step["availability"].String()!="daily_limit"))
                    {
                        for(int i=0;i<7;++i) { balance[i]-=cost[i]; income[i]+=increment[i]; }
                        JsonNode built; built["building_id"]=step["id"]; built["day"].Integer()=date;
                        development["schedule"].Vector().push_back(built);
                        if(++next==bestSequence.size()) buildDay=date;
                    }
                }
                if(date<deadline)
                {
                    const auto nextIncome=funds(forecastDailyIncome(world,date+1,node(income)));
                    for(int i=0;i<7;++i) balance[i]+=nextIncome[i];
                }
            }
            if(buildDay>=0) development["build_day"].Integer()=buildDay;
            else development["status"].String()="unfunded_at_deadline";
        }
        development["resources_at_deadline"]=node(balance);
        result["alternatives"].Vector().push_back(development);

        JsonNode army;
        army["approach"].String()="offense";
        army["town_ref"]=town["ref"];
        army["status"].String()="conditional";
        army["assumptions"].Vector().emplace_back("Recruit available own stock now without building; retain income and protect reserves; transport and battle losses remain separate.");
        balance=initial;
        int64_t power=0;
        for(const auto & unit:town["recruitment_options"].Vector())
        {
            auto count=unit["available"].Integer();
            const auto cost=funds(unit["unit_cost"]);
            for(int i=0;i<7;++i) if(cost[i]>0) count=std::min(count,std::max<int64_t>(0,balance[i]-protectedFunds[i])/cost[i]);
            power+=count*unit["unit_value"].Integer();
            for(int i=0;i<7;++i) balance[i]-=count*cost[i];
            JsonNode stock;
            stock["creature"]=unit["creature"];
            stock["remaining_now"].Integer()=unit["available"].Integer()-count;
            stock["at_next_growth"].Integer()=unit["available"].Integer()-count+unit["weekly_growth"].Integer();
            army["stock"].Vector().push_back(stock);
        }
        army["army_purchased_value"].Integer()=power;
        for(int date=day+1;date<=deadline;++date)
        {
            const auto nextIncome=funds(forecastDailyIncome(world,date,node(daily)));
            for(int i=0;i<7;++i) balance[i]+=nextIncome[i];
        }
        army["resources_at_deadline"]=node(balance);
        result["alternatives"].Vector().push_back(army);
    }
    return result;
}

int64_t wholeCreatureSourceFloor(const std::string & pool,int64_t power,
    int64_t required,const JsonNode & world,const JsonNode * recipientUnits)
{
    required=std::max(required,minimumRetainedArmyValue(pool,world));
    const auto * units=ownArmyUnits(pool,world);
    if(!units || !units->isVector()) return std::max(power,required);
    std::set<int64_t> recipientTypes;
    size_t freeSlots=0;
    if(recipientUnits)
    {
        if(!recipientUnits->isVector() || recipientUnits->Vector().size()>7) return std::max(power,required);
        freeSlots=7-recipientUnits->Vector().size();
        for(const auto & unit:recipientUnits->Vector())
        {
            if(!unit["creature"].isNumber() || unit["count"].Integer()<=0) return std::max(power,required);
            recipientTypes.insert(unit["creature"].Integer());
        }
    }
    std::vector<const JsonNode *> stacks;
    int64_t total=0;
    for(const auto & unit:units->Vector())
    {
        const auto count=unit["count"].Integer(), value=unit["unit_value"].Integer();
        if(count<=0 || value<=0 || value>power || count>(power-total)/value
            || (recipientUnits && !unit["creature"].isNumber())) return std::max(power,required);
        total+=count*value;stacks.push_back(&unit);
    }
    if(total!=power) return std::max(power,required);
    if(!recipientUnits) std::stable_sort(stacks.begin(),stacks.end(),[](const auto * a,const auto * b) {
        return (*a)["unit_value"].Integer()>(*b)["unit_value"].Integer();
    });
    auto budget=std::max<int64_t>(0,power-required);
    int64_t donated=0;
    for(const auto * unit:stacks)
    {
        const auto value=(*unit)["unit_value"].Integer(), count=(*unit)["count"].Integer();
        const auto creature=(*unit)["creature"].Integer();
        if(recipientUnits && !recipientTypes.count(creature) && !freeSlots) continue;
        const auto take=std::min(count,budget/value);
        if(take<=0) continue;
        if(recipientUnits && recipientTypes.insert(creature).second) --freeSlots;
        donated+=take*value;budget-=take*value;
    }
    return std::max(required,power-donated);
}

JsonNode forecastDeliveries(const JsonNode & world, const CampaignState & campaign,
    const std::map<std::string,std::string> & replacements)
{
    std::map<std::string,int64_t> armies;
    std::map<std::string,std::set<std::string>> aliases;
    for(const auto & hero:world["heroes"].Vector())
    { const auto ref=hero["ref"].String();armies[ref]=hero["army_value"].Integer();aliases[ref].insert(ref); }
    for(const auto & town:world["towns"].Vector())
    {
        const auto ref=town["ref"].String(), pool=CampaignState::armyPool(ref,world);
        armies.try_emplace(pool,town["defense_value"].Integer());aliases[pool].insert(ref);
    }
    JsonNode result;result["army_pools"].Vector();result["deliveries"].Vector();
    for(const auto & [pool,power]:armies)
    {
        JsonNode item;item["holder_ref"].String()=pool;item["army_value"].Integer()=power;
        item["reserved_value"].Integer()=wholeCreatureSourceFloor(pool,power,campaign.exchangeForce(pool,world,replacements),world);
        item["unpledged_now"].Integer()=std::max<int64_t>(0,power-item["reserved_value"].Integer());
        for(const auto & ref:aliases[pool]) item["aliases"].Vector().emplace_back(ref);
        result["army_pools"].Vector().push_back(item);
    }
    for(const auto & goal:campaign.plan()["goals"].Vector())
    {
        if(goal["kind"].String()!="reinforce_hero") continue;
        const auto & id=goal["id"].String(), & recipient=goal["actor_ref"].String();
        const auto & status=campaign.statuses()[id]["state"].String();
        if(status=="completed" || status=="cancelled") continue;
        const auto source=campaign.deliverySource(goal,replacements), pool=CampaignState::armyPool(source,world);
        JsonNode delivery;delivery["goal_id"]=goal["id"];delivery["source_ref"].String()=source;
        delivery["source_holder_ref"].String()=pool;delivery["recipient_ref"]=goal["actor_ref"];
        delivery["deadline_day"]=goal["deadline_day"];delivery["required_value"]=goal["complete_when"]["value"];
        delivery["status"].String()="unknown";
        delivery["assumptions"].Vector().emplace_back("Current owned troops and one current permitted owned land/boat route, including a presently funded owned shipyard quote; no future recruitment, growth, bonuses or alternate unseen route. Army losses are native estimates; a meeting still requires legal stack packing and an acknowledged handoff.");
        delivery["assumptions"].Vector().emplace_back("Each physical pool is counted once. This delivery may spend only its own pledge; all other force floors remain protected. Current surplus uses a feasible selection of whole creatures; the selection is conservative, not a maximum. Source and recipient remain owned and at the observed positions.");
        if(armies.count(pool) && armies.count(recipient) && pool!=recipient)
        {
            bool townSource=false;for(const auto & town:world["towns"].Vector()) townSource |= town["ref"].String()==source;
            const auto target=townSource ? source : recipient, traveler=townSource ? recipient : pool;
            const JsonNode * best=nullptr;
            for(const auto & route:world["forecasts"]["routes"].Vector()) if(route["target_ref"].String()==target)
                for(const auto & arrival:route["own_arrivals"].Vector())
                    if(arrival["hero_ref"].String()==traveler
                        && (!best || arrival["day"].Integer()<(*best)["day"].Integer()
                            || (arrival["day"]==(*best)["day"] && arrival["army_loss_estimate"].Integer()<(*best)["army_loss_estimate"].Integer()))) best=&arrival;
            const auto sourceReserve=campaign.exchangeForce(pool,world,replacements,id);
            const bool reservedExchange=sourceReserve || campaign.exchangeForce(recipient,world,replacements,id);
            const auto * recipientUnits=reservedExchange ? ownArmyUnits(recipient,world) : nullptr;
            const auto floor=reservedExchange && !recipientUnits ? std::max(armies.at(pool),sourceReserve)
                : wholeCreatureSourceFloor(pool,armies.at(pool),sourceReserve,world,recipientUnits);
            delivery["source_army_now"].Integer()=armies.at(pool);delivery["source_floor"].Integer()=floor;
            delivery["recipient_army_now"].Integer()=armies.at(recipient);
            if(best)
            {
                const auto loss=std::max<int64_t>(0,(*best)["army_loss_estimate"].Integer());
                const auto donor=std::max<int64_t>(0,armies.at(pool)-(townSource ? 0 : loss)-floor);
                const auto receiver=std::max<int64_t>(0,armies.at(recipient)-(townSource ? loss : 0));
                const auto possible=receiver+donor;
                delivery["arrival_day"]=(*best)["day"];delivery["army_loss_estimate"].Integer()=loss;
                delivery["recipient_possible_value"].Integer()=possible;
                delivery["shortfall_value"].Integer()=std::max<int64_t>(0,goal["complete_when"]["value"].Integer()-possible);
                if(armies.at(recipient)>=goal["complete_when"]["value"].Integer()) delivery["status"].String()="delivery_unconfirmed";
                else if((*best)["day"].Integer()>goal["deadline_day"].Integer()) delivery["status"].String()="late_on_current_route";
                else if(loss>armies.at(traveler)*campaign.plan()["policy"]["max_loss_ratio"].Float()) delivery["status"].String()="route_loss_exceeds_policy";
                else if(possible<goal["complete_when"]["value"].Integer()) delivery["status"].String()="additional_army_required";
                else delivery["status"].String()="conditional";
            }
        }
        result["deliveries"].Vector().push_back(delivery);
    }
    return result;
}

JsonNode forecastCommitments(const JsonNode & world, const CampaignState & campaign,
    const std::map<std::string,std::string> & replacements)
{
    using Funds=std::array<int64_t,7>;
    auto amounts=[](const JsonNode & values) { Funds result{};for(int i=0;i<7;++i) result[i]=values[i].Integer();return result; };
    auto values=[](const Funds & amounts) { JsonNode result;for(auto value:amounts) result.Vector().emplace_back(value);return result; };
    const int day=world["day"].Integer(), week=std::max<int64_t>(1,world["days_in_week"].Integer());
    int deadline=day;
    auto balance=amounts(world["resources"]);
    auto income=amounts(world["economy"]["base_daily_income"].isVector() ? world["economy"]["base_daily_income"] : world["daily_income"]);
    std::set<std::string> completed, moved;
    for(const auto & [id,status]:campaign.statuses().Struct()) if(status["state"].String()=="completed") completed.insert(id);
    const auto currentLogistics=forecastDeliveries(world,campaign,replacements);
    std::map<std::string,int64_t> army;
    for(const auto & pool:currentLogistics["army_pools"].Vector()) army[pool["holder_ref"].String()]=pool["army_value"].Integer();
    std::map<std::string,std::set<int64_t>> built;
    struct Stock { const JsonNode * unit;int64_t count; };
    std::map<std::string,std::vector<Stock>> stock;
    for(const auto & town:world["towns"].Vector())
    {
        const auto & ref=town["ref"].String();
        for(const auto & id:town["buildings"].Vector()) built[ref].insert(id.Integer());
        // Native procurement visits existing dwelling tiers from highest to
        // lowest. It buys an affordable stack, then stops once enough is bought.
        for(auto it=town["recruitment_options"].Vector().rbegin();it!=town["recruitment_options"].Vector().rend();++it)
            stock[ref].push_back({&*it,(*it)["available"].Integer()});
    }
    auto protectedFunds=[&](const std::string & spending) {
        Funds result{};
        const auto all=campaign.reservedResources();
        for(const auto & reserve:campaign.plan()["reserves"].Vector())
        {
            const auto & id=reserve["goal_id"].String();
            if(id==spending || completed.count(id)) continue;
            const auto without=campaign.reservedResources(id);
            for(int i=0;i<7;++i) result[i]+=all[i].Integer()-without[i].Integer();
        }
        return result;
    };
    struct Commitment
    {
        const JsonNode * goal;
        const JsonNode * sourceTown=nullptr;
        std::vector<const JsonNode *> sequence;
        JsonNode estimate;
        int meeting=-1;
    };
    std::vector<Commitment> entries;
    for(const auto & goal:campaign.plan()["goals"].Vector())
    {
        const auto & id=goal["id"].String(), & kind=goal["kind"].String();
        if(completed.count(id) || campaign.statuses()[id]["state"].String()=="cancelled" || goal["deadline_day"].Integer()<day) continue;
        if(kind!="develop_town" && kind!="reinforce_hero") continue;
        Commitment entry{};entry.goal=&goal;auto & estimate=entry.estimate;
        if(kind=="develop_town")
        {
            const JsonNode * town=nullptr,* target=nullptr;
            for(const auto & own:world["towns"].Vector()) if(own["ref"]==goal["target_ref"]) town=&own;
            if(town) for(const auto & option:(*town)["building_options"].Vector()) if(option["id"]==goal["building_id"]) target=&option;
            const bool supported=target && buildingSequence(*town,*target,entry.sequence);
            estimate["goal_id"]=goal["id"];estimate["town_ref"]=goal["target_ref"];
            estimate["approach"].String()="economy";estimate["building_id"]=goal["building_id"];
            estimate["status"].String()=supported ? "unfunded_at_deadline" : "unknown";
            estimate["schedule"].Vector();
            Funds cost{};for(const auto * step:entry.sequence) for(int i=0;i<7;++i) cost[i]+=(*step)["cost"][i].Integer();
            estimate["cost"]=values(cost);
        }
        else
        {
            if(!campaign.participantGoals(goal["actor_ref"].String(),replacements,world).count(id)) continue;
            for(const auto & delivery:currentLogistics["deliveries"].Vector()) if(delivery["goal_id"]==goal["id"]) estimate=delivery;
            for(const auto & own:world["towns"].Vector()) if(own["ref"]==estimate["source_ref"]) entry.sourceTown=&own;
            estimate["recruitment_schedule"].Vector();
            if(estimate["status"].String()=="additional_army_required") estimate["status"].String()="unfunded_at_deadline";
        }
        estimate["assumptions"].Vector().emplace_back("One treasury and existing dwelling stock calendar for accepted building and town-source delivery commitments; priority order and dependencies. No pickups, trade or unrelated spending. Each town builds once per day; keep other live resource and force reserves.");
        estimate["assumptions"].Vector().emplace_back("Existing own income, positive building prerequisites and current weekly growth remain valid. New dwellings, changed growth bonuses, stack packing and routes after a projected meeting remain unproved. Future delivery uses the current route and loss estimate; its recipient can arrive at the source town and wait for recruitment.");
        estimate["assumptions"].Vector().emplace_back("Use post-handicap recurring income and loaded AI bonuses with daily calendar rounding; weekly rewards/events are excluded.");
        deadline=std::max(deadline,static_cast<int>(goal["deadline_day"].Integer()));entries.push_back(std::move(entry));
    }
    std::ranges::sort(entries,[](const auto & a,const auto & b) {
        if((*a.goal)["priority"]!=(*b.goal)["priority"]) return (*a.goal)["priority"].Integer()>(*b.goal)["priority"].Integer();
        if((*a.goal)["deadline_day"]!=(*b.goal)["deadline_day"]) return (*a.goal)["deadline_day"].Integer()<(*b.goal)["deadline_day"].Integer();
        return (*a.goal)["id"].String()<(*b.goal)["id"].String();
    });
    JsonNode result;result["commitments"].Vector();result["deliveries"].Vector();result["resource_calendar"].Vector();
    result["army_pools"]=currentLogistics["army_pools"];
    for(int date=day;date<=deadline;++date)
    {
        if(date>day && (date-1)%week==0)
            for(auto & [ref,units]:stock) for(auto & unit:units) unit.count+=(*unit.unit)["weekly_growth"].Integer();
        JsonNode calendar;calendar["day"].Integer()=date;calendar["resources_start"]=values(balance);calendar["spending"].Vector();
        std::set<std::string> usedTowns;
        bool progress=true;
        while(progress)
        {
            progress=false;
            for(auto & entry:entries)
            {
                const auto & goal=*entry.goal;const auto & id=goal["id"].String();auto & estimate=entry.estimate;
                if(completed.count(id) || date>goal["deadline_day"].Integer() || estimate["status"].String()=="unknown") continue;
                bool dependencies=true;for(const auto & dependency:goal["depends_on"].Vector()) dependencies &= completed.count(dependency.String());
                if(!dependencies) continue;
                if(goal["kind"].String()=="develop_town")
                {
                    const auto & ref=goal["target_ref"].String();
                    if(built[ref].count(goal["building_id"].Integer()))
                    { completed.insert(id);estimate["build_day"].Integer()=date;estimate["status"].String()="conditional";progress=true;continue; }
                    if(usedTowns.count(ref)) continue;
                    const JsonNode * next=nullptr;for(const auto * step:entry.sequence) if(!built[ref].count((*step)["id"].Integer())) { next=step;break; }
                    if(!next || (date==day && (*next)["availability"].String()=="daily_limit")) continue;
                    const auto cost=amounts((*next)["cost"]), increment=amounts((*next)["income_delta"]), protectedAmounts=protectedFunds(id);
                    bool affordable=true;for(int i=0;i<7;++i) affordable &= balance[i]-protectedAmounts[i]>=cost[i];
                    if(!affordable) continue;
                    for(int i=0;i<7;++i) { balance[i]-=cost[i];income[i]+=increment[i]; }
                    built[ref].insert((*next)["id"].Integer());usedTowns.insert(ref);progress=true;
                    JsonNode step;step["building_id"]=(*next)["id"];step["day"].Integer()=date;step["cost"]=(*next)["cost"];
                    estimate["schedule"].Vector().push_back(step);
                    step["goal_id"]=goal["id"];step["town_ref"]=goal["target_ref"];step["kind"].String()="build";calendar["spending"].Vector().push_back(step);
                    continue;
                }
                if(!estimate["arrival_day"].isNumber() || estimate["status"].String()=="route_loss_exceeds_policy"
                    || estimate["status"].String()=="delivery_unconfirmed" || estimate["status"].String()=="late_on_current_route") continue;
                const auto & source=estimate["source_holder_ref"].String(), & recipient=goal["actor_ref"].String();
                if(moved.count(source) || moved.count(recipient))
                { estimate["status"].String()="unknown_after_projected_meeting";continue; }
                const auto loss=estimate["army_loss_estimate"].Integer(), floor=estimate["source_floor"].Integer(), required=goal["complete_when"]["value"].Integer();
                const auto donorLoss=entry.sourceTown ? 0 : loss, receiverLoss=entry.sourceTown ? loss : 0;
                auto possible=[&] { return std::max<int64_t>(0,army[recipient]-receiverLoss)+std::max<int64_t>(0,army[source]-donorLoss-floor); };
                if(possible()<required && entry.sourceTown)
                {
                    const auto & ref=(*entry.sourceTown)["ref"].String();
                    for(auto & unit:stock[ref])
                    {
                        if(possible()>=required) break;
                        const auto cost=amounts((*unit.unit)["unit_cost"]), protectedAmounts=protectedFunds(id);
                        auto count=unit.count;
                        for(int i=0;i<7;++i) if(cost[i]>0) count=std::min(count,std::max<int64_t>(0,balance[i]-protectedAmounts[i])/cost[i]);
                        if(count<=0 || (*unit.unit)["unit_value"].Integer()<=0) continue;
                        const auto power=count*(*unit.unit)["unit_value"].Integer();
                        Funds spent{};for(int i=0;i<7;++i) { spent[i]=count*cost[i];balance[i]-=spent[i]; }
                        army[source]+=power;unit.count-=count;progress=true;
                        JsonNode step;step["town_ref"].String()=ref;step["day"].Integer()=date;step["creature"]=(*unit.unit)["creature"];
                        step["count"].Integer()=count;step["purchased_value"].Integer()=power;step["cost"]=values(spent);
                        estimate["recruitment_schedule"].Vector().push_back(step);
                        step["goal_id"]=goal["id"];step["kind"].String()="recruit";calendar["spending"].Vector().push_back(step);
                    }
                }
                estimate["recipient_possible_value"].Integer()=possible();estimate["shortfall_value"].Integer()=std::max<int64_t>(0,required-possible());
                if(possible()<required) continue;
                if(entry.meeting<0) entry.meeting=std::max(date,static_cast<int>(estimate["arrival_day"].Integer()));
                estimate["arrival_day"].Integer()=entry.meeting;
                if(entry.meeting>goal["deadline_day"].Integer()) { estimate["status"].String()="late_after_recruitment";continue; }
                estimate["status"].String()="conditional";
                if(date<entry.meeting) continue;
                // Do not promise leftover unreserved donor troops to another
                // delivery: the native picker can donate that whole surplus.
                // Only the requested recipient floor and retained source floor
                // are carried forward as conservative conditional minima.
                army[source]=floor;army[recipient]=required;completed.insert(id);progress=true;
                if(entry.sourceTown) moved.insert(recipient);else moved.insert(source);
            }
        }
        const auto nextIncome=forecastDailyIncome(world,date+1,values(income));
        calendar["resources_end"]=values(balance);calendar["income_for_next_day"]=nextIncome;
        result["resource_calendar"].Vector().push_back(calendar);
        for(auto & entry:entries) if(date==(*entry.goal)["deadline_day"].Integer()) entry.estimate["resources_at_deadline"]=values(balance);
        if(date<deadline) for(int i=0;i<7;++i) balance[i]+=nextIncome[i].Integer();
    }
    for(const auto & entry:entries)
        result[(*entry.goal)["kind"].String()=="develop_town" ? "commitments" : "deliveries"].Vector().push_back(entry.estimate);
    result["stock_at_deadline"].Vector();
    for(const auto & [ref,units]:stock) for(const auto & unit:units)
    { JsonNode item;item["town_ref"].String()=ref;item["creature"]=(*unit.unit)["creature"];item["remaining"].Integer()=unit.count;result["stock_at_deadline"].Vector().push_back(item); }
    return result;
}

JsonNode forecastThreats(const JsonNode & world)
{
    JsonNode result; result.Vector();
    for(const auto & enemy:world["objects"].Vector())
    {
        if(enemy["kind"].String()!="hero" || std::find(world["enemy_players"].Vector().begin(),world["enemy_players"].Vector().end(),enemy["owner"])==world["enemy_players"].Vector().end()) continue;
        for(const auto & town:world["towns"].Vector())
        {
            const auto & a=enemy["position"], & b=town["position"];
            if(!a.isVector() || a.Vector().size()!=3 || !b.isVector() || b.Vector().size()!=3 || a[2]!=b[2]) continue;
            const auto distance=std::max(std::abs(a[0].Integer()-b[0].Integer()),std::abs(a[1].Integer()-b[1].Integer()));
            const auto age=std::max<int64_t>(0,world["day"].Integer()-enemy["last_seen_day"].Integer());
            JsonNode threat;
            threat["source_ref"]=enemy["ref"]; threat["town_ref"]=town["ref"];
            threat["army_interval"]=enemy["army_interval"];
            for(const auto & approach:world["enemy_approaches"].Vector())
                if(approach["source_ref"]==enemy["ref"] && approach["target_ref"]==town["ref"])
                    threat["neutral_screen"]=approach;
            threat["sighting_age_days"].Integer()=age;
            threat["last_observed_distance"].Integer()=distance;
            // Historical sightings and unestablished/guarded connections are
            // information to scout, not deadlines for diverting the main army.
            const auto visible=std::any_of(world["visible_objects"].Vector().begin(),world["visible_objects"].Vector().end(),
                [&](const auto & object) { return object["ref"]==enemy["ref"]; });
            const auto & approach=threat["neutral_screen"];
            const auto open=approach["status"].String()=="no_visible_neutral_barrier_on_known_land_connection";
            threat["assessment"].String()=!visible || age>0 ? "historical_sighting"
                : open ? "observed_open_approach"
                : approach["status"].String()=="neutral_encounter_required_on_known_land_connections"
                    ? "guarded_approach" : "unconfirmed_approach";
            threat["eta_status"].String()="unknown";
            threat["earliest_possible_day"]=JsonNode();
            threat["latest_possible_day"]=JsonNode();
            threat["advance_scenario_day"]=JsonNode();
            threat["delay_scenario_day"]=JsonNode();
            // A legal adjacent approach proves local exposure without guessing enemy movement.
            // An open distant route supplies no defensive deadline.
            if(visible && age==0 && open && approach["known_land_steps"].isNumber()
                && approach["known_land_steps"].Integer()<=1)
            {
                threat["advance_scenario_day"]=world["day"];
                threat["delay_scenario_day"].Integer()=world["day"].Integer()+1;
            }
            threat["redirect_scenario_day"]=JsonNode();
            threat["assumptions"].String()="Only a currently visible enemy on a legal adjacent unguarded land connection receives a local advance/delay scenario. Distant open connections have unknown timing and do not impose urgent defense. This is not an ETA, movement bound or attack intent. Historical, guarded and unconfirmed approaches require new evidence, not preventive main-army holding. Fog, water and spells remain unknown.";
            result.Vector().push_back(threat);
        }
    }
    return result;
}

JsonNode forecastDefenses(const JsonNode & world, const CampaignState & campaign)
{
    struct Front { const JsonNode * town; int64_t day, required; bool critical, bounded; JsonNode threats, unconfirmed; };
    std::vector<Front> fronts;
    std::set<std::string> allocated;
    const auto today=world["day"].Integer();
    for(const auto & town:world["towns"].Vector())
    {
        Front front{&town,today+7,0,world["towns"].Vector().size()==1,true,{},{}};
        const auto & critical=campaign.plan()["policy"]["critical_towns"].Vector();
        front.critical |= std::find(critical.begin(),critical.end(),town["ref"])!=critical.end();
        front.threats.Vector();
        front.unconfirmed.Vector();
        for(const auto & threat:world["forecasts"]["threats"].Vector())
            if(threat["town_ref"]==town["ref"])
            {
                if(!threat["advance_scenario_day"].isNumber())
                { front.unconfirmed.Vector().push_back(threat);continue; }
                front.day=std::min(front.day,threat["advance_scenario_day"].Integer());
                front.bounded &= threat["army_interval"]["upper"].isNumber();
                front.required+=threat["army_interval"]["upper"].Integer();
                front.threats.Vector().push_back(threat);
            }
        // A stationary garrison pool is already included in its town. It
        // cannot simultaneously serve as a mobile reinforcement elsewhere.
        allocated.insert(CampaignState::armyPool(town["ref"].String(),world));
        fronts.push_back(front);
    }
    std::sort(fronts.begin(),fronts.end(),[](const Front & a,const Front & b) {
        if(a.critical!=b.critical) return a.critical>b.critical;
        if(a.day!=b.day) return a.day<b.day;
        if(a.required!=b.required) return a.required>b.required;
        return (*a.town)["ref"].String()<(*b.town)["ref"].String();
    });
    JsonNode result;result.Vector();
    for(const auto & front:fronts)
    {
        const auto & town=*front.town;
        JsonNode estimate;
        estimate["town_ref"]=town["ref"];
        estimate["critical"].Bool()=front.critical;
        if(front.threats.Vector().empty()) estimate["scenario_deadline_day"]=JsonNode();
        else estimate["scenario_deadline_day"].Integer()=front.day;
        estimate["garrison_value"]=town["defense_value"];
        estimate["allocated_hero_refs"].Vector();
        estimate["own_arrivals"].Vector();
        estimate["threats"]=front.threats;
        estimate["unconfirmed_threats"]=front.unconfirmed;
        int64_t capacity=town["defense_value"].Integer();
        if(front.bounded) estimate["opposing_upper_sum"].Integer()=front.required;
        struct Candidate { const JsonNode * hero, * arrival; int64_t value; };
        std::vector<Candidate> candidates;
        for(const auto & route:world["forecasts"]["routes"].Vector()) if(route["target_ref"]==town["ref"])
            for(const auto & arrival:route["own_arrivals"].Vector())
            {
                if(arrival["day"].Integer()>front.day || allocated.count(arrival["hero_ref"].String())) continue;
                for(const auto & hero:world["heroes"].Vector()) if(hero["ref"]==arrival["hero_ref"])
                {
                    const auto value=std::min(hero["army_value"].Integer(),arrival["army_value"].Integer());
                    const auto loss=arrival["army_loss_estimate"].Integer();
                    const auto allowed=campaign.plan().isNull() ? .2 : campaign.plan()["policy"]["max_loss_ratio"].Float();
                    if(loss<=value*allowed && value>loss) candidates.push_back({&hero,&arrival,value-loss});
                }
            }
        std::sort(candidates.begin(),candidates.end(),[](const Candidate & a,const Candidate & b) {
            if((*a.arrival)["day"]!=(*b.arrival)["day"]) return (*a.arrival)["day"].Integer()<(*b.arrival)["day"].Integer();
            if(a.value!=b.value) return a.value>b.value;
            return (*a.hero)["ref"].String()<(*b.hero)["ref"].String();
        });
        for(const auto & candidate:candidates)
        {
            if(front.threats.Vector().empty() || (front.bounded && capacity>=front.required)) break;
            const auto & ref=(*candidate.hero)["ref"];
            if(!allocated.insert(ref.String()).second) continue;
            capacity+=candidate.value;
            estimate["allocated_hero_refs"].Vector().push_back(ref);
            JsonNode arrival=*candidate.arrival;
            arrival["retained_troop_value"].Integer()=candidate.value;
            for(const auto & goal:campaign.participantGoals(ref.String(),{},world))
                arrival["diverted_goal_ids"].Vector().emplace_back(goal);
            estimate["own_arrivals"].Vector().push_back(arrival);
        }
        estimate["conditional_force_value"].Integer()=capacity;
        estimate["status"].String()=front.threats.Vector().empty() ? "no_observed_front"
            : !front.bounded ? "unbounded_opposition" : capacity>=front.required ? "conditional_force_available" : "insufficient_current_force";
        estimate["assumptions"].String()="Current owned garrison and single-hero permitted land/boat arrivals, including presently funded owned shipyard quotes, by the earliest advance scenario; each pool is allocated once. Visible enemy upper bounds are summed as a conservative joint front. Opponent route, intent and combat bonuses remain unknown. Hero diversion costs are listed. No battle win, recruit stock, future meeting or fortification bonus is assumed.";
        result.Vector().push_back(estimate);
    }
    return result;
}

JsonNode forecastTownChoices(const JsonNode & world,const CampaignState & campaign,
    const std::map<std::string,std::string> & replacements)
{
    JsonNode result;result.Vector();
    for(const auto & town:world["towns"].Vector()) for(const auto & hero:world["heroes"].Vector())
    {
        if(!town["position"].isVector() || hero["position"]!=town["position"]) continue;
        JsonNode item;item["town_ref"]=town["ref"];item["actor_ref"]=hero["ref"];
        const auto force=hero["army_value"].Integer();
        const auto stationary=town["army_holder_ref"]==hero["ref"] ? 0 : town["defense_value"].Integer();
        item["hero_force_now"].Integer()=force;
        item["garrison_after_departure"].Integer()=stationary;
        item["hold_force"].Integer()=town["army_holder_ref"]==hero["ref"] ? force : force+stationary;
        item["active_main_floor"].Integer()=campaign.exchangeForce(hero["ref"].String(),world,replacements);
        item["separable_surplus_under_current_plan"].Integer()=std::max<int64_t>(0,force-item["active_main_floor"].Integer());
        item["detachable_units"]=hero["army_units"];
        item["threats"].Vector();
        for(const auto & threat:world["forecasts"]["threats"].Vector())
            if(threat["town_ref"]==town["ref"]) item["threats"].Vector().push_back(threat);
        auto budget=world["resources"];
        const auto reserved=campaign.reservedResources();
        for(int i=0;i<7;++i) budget[i].Integer()=std::max<int64_t>(0,budget[i].Integer()-reserved[i].Integer());
        JsonNode purchase;purchase["units"].Vector();for(int i=0;i<7;++i) purchase["cost"].Vector().emplace_back(0);
        int64_t bought=0;
        for(const auto & unit:town["recruitment_options"].Vector())
        {
            auto count=unit["available"].Integer();
            for(int i=0;i<7;++i) if(unit["unit_cost"][i].Integer()>0)
                count=std::min(count,budget[i].Integer()/unit["unit_cost"][i].Integer());
            if(count<=0) continue;
            JsonNode quoted;quoted["creature"]=unit["creature"];quoted["count"].Integer()=count;
            purchase["units"].Vector().push_back(quoted);bought+=count*unit["unit_value"].Integer();
            for(int i=0;i<7;++i)
            {
                const auto cost=count*unit["unit_cost"][i].Integer();
                budget[i].Integer()-=cost;purchase["cost"][i].Integer()+=cost;
            }
        }
        purchase["additional_force"].Integer()=bought;
        purchase["garrison_after_preparation"].Integer()=stationary+bought;
        purchase["main_after_purchase"].Integer()=force;
        purchase["requires_separate_town_pool"].Bool()=true;
        purchase["assumptions"].String()="Independent stock quote before native stack/fund revalidation; not delivery to the main. Occupied visitor/garrison may prevent preparation.";
        item["buy_garrison"]=purchase;
        item["operations"].Vector();
        for(const auto & entry:world["forecasts"]["routes"].Vector())
        {
            const JsonNode * target=nullptr;
            for(const auto & object:world["visible_objects"].Vector())
                if(object["ref"]==entry["target_ref"] && std::find(world["enemy_players"].Vector().begin(),world["enemy_players"].Vector().end(),object["owner"])!=world["enemy_players"].Vector().end()) target=&object;
            if(!target) continue;
            for(const auto & arrival:entry["own_arrivals"].Vector()) if(arrival["hero_ref"]==hero["ref"])
            {
                JsonNode operation;operation["target_ref"]=entry["target_ref"];operation["target_kind"]=(*target)["kind"];
                operation["arrival"]=arrival;operation["enemy_army_interval"]=(*target)["army_interval"];
                operation["main_after_preparation_requires_fresh_route"].Bool()=true;
                item["operations"].Vector().push_back(operation);
            }
        }
        item["assumptions"].String()="Compare departure, funded separate garrison, whole-creature detachment, interception and hold. Threat ETA/intent remain unknown; city value, walls, hero bonuses and return route require explicit reasoning. Smaller post-split armies need fresh native routes.";
        result.Vector().push_back(item);
    }
    return result;
}
}
