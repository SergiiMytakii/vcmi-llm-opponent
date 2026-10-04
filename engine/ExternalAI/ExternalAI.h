#pragma once

#include "../../lib/callback/CAdventureAI.h"
#include "../../lib/json/JsonNode.h"
#include <atomic>
#include <condition_variable>
#include <thread>

class ExternalAI final : public CAdventureAI
{
	std::shared_ptr<CCallback> cb;
	std::atomic<bool> stopping{false};
	std::thread worker;
	std::mutex requestMutex;
	std::condition_variable requestChanged;
	int pendingRequest = -1;
	bool requestCompleted = false;
	bool requestSucceeded = false;
	bool battleBlocked = false;
	std::set<QueryID> pendingQueries;
	std::map<int, QueryID> queryRequests;
	// Published by the turn worker under requestMutex; level-up callbacks never
	// read worker-owned savedState while a battle is unwinding.
	std::map<ObjectInstanceID, bool> developmentCombatGoals;
	std::vector<JsonNode> resourceNotifications;
	uint64_t turnNumber = 0;
	JsonNode savedState;
	JsonNode selectedAction;
	std::vector<JsonNode> queuedActions;
	JsonNode batchObservation;
	JsonNode batchPreviousAction;
	std::string batchRequestID;
	std::string experienceID;
	std::atomic<bool> finalReviewStarted{false};
	int objectAlias(ObjectInstanceID id);
	bool persistState();
	void runTurn(uint64_t turn);
	bool runDecision(uint64_t turn, int attempt);
	bool waitForRequest(int seconds = 5);
	bool moveTo(ObjectInstanceID hero, int3 destination, const std::string & requestID, const std::string & actionID);
	void answer(QueryID id, int choice);

public:
	~ExternalAI() override;
	void initGameInterface(std::shared_ptr<Environment> environment, std::shared_ptr<CCallback> callback) override;
	void yourTurn(QueryID queryID) override;
	void finish() override;
	std::string getBattleAIName() const override;
	void requestSent(const CPackForServer * pack, int requestID) override;
	void requestRealized(PackageApplied * pack) override;
	void playerBlocked(int reason, bool start) override;
	void battleEnded() override;
	void gameOver(PlayerColor player, const EVictoryLossCheckResult & result) override;
	void queryResolved(QueryID id) override;
	void showInfoDialog(EInfoWindowMode, const std::string &, const std::vector<Component> &, int) override;
	void showRecruitmentDialog(const CGDwelling *, const CArmedInstance *, int, QueryID id) override;
	void showMarketWindow(const IMarket *, const CGHeroInstance *, QueryID id) override;
	void showUniversityWindow(const IMarket *, const CGHeroInstance *, QueryID id) override;
	void showTavernWindow(const CGObjectInstance *, const CGHeroInstance *, QueryID id) override;
	void heroGotLevel(const CGHeroInstance *, PrimarySkill, std::vector<SecondarySkill> &, QueryID id) override;
	void commanderGotLevel(const CCommanderInstance *, std::vector<ui32>, QueryID id) override;
	void showBlockingDialog(const std::string &, const std::vector<Component> &, QueryID id, int, bool selection, bool cancel, bool safeToAutoaccept) override;
	void showTeleportDialog(const CGHeroInstance *, TeleportChannelID, TTeleportExitsList, bool, QueryID id) override;
	void showGarrisonDialog(const CArmedInstance *, const CGHeroInstance *, bool, QueryID id, const MetaString &) override;
	void showMapObjectSelectDialog(QueryID id, const Component &, const MetaString &, const MetaString &, const std::vector<ObjectInstanceID> &) override;
	std::optional<BattleAction> makeSurrenderRetreatDecision(const BattleID &, const BattleStateInfoForRetreat &) override;
};
