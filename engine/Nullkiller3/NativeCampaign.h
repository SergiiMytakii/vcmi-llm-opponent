#pragma once

#include "CampaignState.h"
#include "RequestArbiter.h"
#include "ResourceLedger.h"
#include <atomic>
#include <mutex>
#include <chrono>
#include <tuple>
#include <exception>
#include "../Nullkiller2/Goals/CGoal.h"
#include "../../lib/ResourceSet.h"

namespace NK2AI { class Nullkiller; }
class CGHeroInstance;
class CGObjectInstance;
class CGTownInstance;
class CArmedInstance;

namespace nullkiller3
{
// Unwind a stale composition at a command boundary. This is a fresh replan,
// not task completion, loss of the turn or a reason to lock the survivor.
struct ExecutionReplanAfterCombat : std::exception
{
    const char * what() const noexcept override { return "Own combat result invalidated the current native task"; }
};
// The one native planner owns intentions, observations and the transient
// association of freshly built tasks with those intentions. No task is saved.
class NativeCampaign
{
    JsonNode persisted;
    std::string experienceID; // Immutable after construction; callbacks never read mutable JSON.
    std::atomic<bool> terminalRecorded{false};
    std::atomic<int> observedBattleEnemy{-1};
    JsonNode world;
    CampaignState campaign;
    std::string spendingGoal;
    std::string deliveryGoal;
    std::string emergencyTown;
    TResources emergencyCost, emergencyFunds;
    mutable std::mutex executionMutex;
    ResourceLedger resourceLedger;
    bool resourceLedgerActive=false;
    std::string executingGoal() const;
    bool seedRead = false;
    bool repairedSourcesChanged = false;
    RequestArbiter arbiter;
    std::mutex visitMutex;
    std::map<int, int> resourceVisits;
    std::vector<int> completedResourceVisits;
    // Execution context is copied on the planner thread; callbacks use only
    // these mutex-protected values, never mutable campaign/persisted JSON.
    JsonNode activePassageGoal;
    int activePassageActor=-1, activePassageEntry=-1, activePassageDay=0;
    std::map<int, JsonNode> passageVisits;
    std::vector<JsonNode> completedPassageVisits;
    JsonNode activeSiteGoal;
    int activeSiteActor=-1,activeSiteObject=-1,activeSiteDay=0;
    std::map<int,JsonNode> siteVisits;
    std::vector<JsonNode> completedSiteVisits;
    std::vector<JsonNode> completedBattles;
    void applyBattleObservations();
    void applyPassageObservations();
    std::atomic<int64_t> acceptedRevision{0};
    std::atomic<double> acceptedLossRatio{1};
    std::atomic<bool> replanAfterCombat{false};
    std::map<std::tuple<int64_t,int,int>,uint64_t> forceMinima;
    void applyForceObservations();
    std::atomic<bool> stopping{false};
    std::atomic<bool> exchangeCancelled{false};
    std::string generation;
    bool invalidBudget = false;
    std::mutex learningMutex;
    int64_t learningSequence = 0;
    JsonNode pendingLearningEnd;
    void writeLearningEvent(JsonNode event);
    std::atomic<bool> executionActive{false};
    std::chrono::steady_clock::time_point executionStarted;
    JsonNode executionSnapshot(NK2AI::Nullkiller & ai);
    void restoreArbiter();
    void saveArbiter();
    void traceCampaign() const;
    void observeBuildingProgress();
    void observeOperationProgress();
    void recordCheckpointBaseline();
    std::vector<StrategicSignal> strategicSignals(NK2AI::Nullkiller & ai,bool includeIdle);

    bool helperHireSlotAvailable(const NK2AI::Nullkiller & ai,const CGTownInstance * town) const;
    std::string reference(const CGObjectInstance * object);
    const CGObjectInstance * resolve(const NK2AI::Nullkiller & ai, const JsonNode & ref) const;
    std::map<std::string,std::string> helperSources() const;
    bool repairDeliverySources(NK2AI::Nullkiller & ai);
    bool locallyRepairedCourierLoss(NK2AI::Nullkiller & ai,const std::string & actor);
    NK2AI::Goals::TGoalVec deliveryTasks(NK2AI::Nullkiller & ai,const CGHeroInstance * recipient,const CGObjectInstance * source,
        bool collectFromTown = false,const std::map<std::string,std::string> * prospectiveSources = nullptr) const;
    NK2AI::Goals::TGoalVec repairRoute(NK2AI::Nullkiller & ai, const CGHeroInstance * hero, const CGObjectInstance * destination) const;
    bool repairOwnHeroObstruction(NK2AI::Nullkiller & ai);
    void rememberTasks(NK2AI::Goals::TGoalVec & output, NK2AI::Goals::TGoalVec generated,
                       const JsonNode & goal, const NK2AI::Nullkiller & ai,
                       const std::map<std::string,std::string> * prospectiveSources = nullptr);
public:
    explicit NativeCampaign(const JsonNode & saved,const JsonNode & returnNamespaces = JsonNode());
    bool reviewStrategy(NK2AI::Nullkiller & ai,bool includeIdle = false);
    bool reviewIdleArmy(NK2AI::Nullkiller & ai);
    void cancelExchange() { exchangeCancelled = true; }
    void cancel() { stopping = true; cancelExchange(); }
    bool isStopping() const { return stopping; }
    bool executionWasInterrupted() const { return replanAfterCombat; }
    bool shouldInterruptExecution() const { return executionActive && replanAfterCombat; }
    void observe(NK2AI::Nullkiller & ai);
    void resourceVisit(const CGHeroInstance * hero, const CGObjectInstance * object, bool start);
    void forceChanged(const CGHeroInstance * hero, int day);
    void resourcesChanged(const TResources & resources);
    void battleResult(JsonNode ownResult);
    void battleOpponent(int engineID) { observedBattleEnemy.store(engineID); }
    void terminalResult(int player,int day,bool won);
    void recordDelivery(NK2AI::Nullkiller & ai, const CGHeroInstance * receiver, const CArmedInstance * source,
                        uint64_t receiverBefore, uint64_t sourceBefore);
    void persist(NK2AI::Nullkiller & ai);
    void updateForecasts(NK2AI::Nullkiller & ai);
    void recordLearningTurn(NK2AI::Nullkiller & ai,const std::string & phase);
    void finishLearningTurn();
    void recordLearningExecution(const JsonNode & result);
    bool accept(const JsonNode & proposal, std::string & reason);
    const JsonNode & observation() const { return world; }
    JsonNode observedPassages() const { return persisted["observed_passages"]; }
    const JsonNode & memory() const { return persisted["memory"]; }
    const CampaignState & commitments() const { return campaign; }
    NK2AI::Goals::TGoalVec generate(NK2AI::Nullkiller & ai, bool priorityPass, bool stabilizationOnly = false);
    float priority(const NK2AI::Nullkiller & ai, const NK2AI::Goals::TSubgoal & task, float nativeScore) const;
    std::string heroHireReason(const NK2AI::Nullkiller & ai, const CGTownInstance * town, const CGHeroInstance * candidate, const std::string & goalID = {}) const;
    void recordHelperHire(NK2AI::Nullkiller & ai,const CGTownInstance * town,const CGHeroInstance * candidate,const std::string & goalID);
    TResources reservedResources(const TResources & currentFunds) const;
    TResources plannedBoatResources(const CGHeroInstance * hero, const TResources & currentFunds, const TResources & nativeLocks) const;
    bool emergencySpending() const;
    uint64_t forceReserve(const CArmedInstance * army) const;
    uint64_t directDeliveryValue(const CGHeroInstance * receiver, const CGHeroInstance * source,
        const std::map<std::string,std::string> * prospectiveSources = nullptr) const;
    const CGHeroInstance * deliveryReceiver(const CGHeroInstance * first, const CGHeroInstance * second) const;
    bool beginDelivery(const CGHeroInstance * receiver, const CArmedInstance * source);
    void endDelivery();
    void beginExecution(NK2AI::Nullkiller & ai,const NK2AI::Goals::TTask & task);
    void endExecution(NK2AI::Nullkiller & ai,const std::string & acknowledgment);
    std::string role(const CGHeroInstance * hero) const;
};
}
