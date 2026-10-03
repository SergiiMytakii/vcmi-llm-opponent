#pragma once

#include "../../lib/callback/CAdventureAI.h"
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
	uint64_t turnNumber = 0;
	void runTurn(uint64_t turn);
	void answer(QueryID id, int choice);

public:
	~ExternalAI() override;
	void initGameInterface(std::shared_ptr<Environment> environment, std::shared_ptr<CCallback> callback) override;
	void yourTurn(QueryID queryID) override;
	void finish() override;
	std::string getBattleAIName() const override;
	void requestSent(const CPackForServer * pack, int requestID) override;
	void requestRealized(PackageApplied * pack) override;
	void heroGotLevel(const CGHeroInstance *, PrimarySkill, std::vector<SecondarySkill> &, QueryID id) override;
	void commanderGotLevel(const CCommanderInstance *, std::vector<ui32>, QueryID id) override;
	void showBlockingDialog(const std::string &, const std::vector<Component> &, QueryID id, int, bool selection, bool cancel, bool safeToAutoaccept) override;
	void showTeleportDialog(const CGHeroInstance *, TeleportChannelID, TTeleportExitsList, bool, QueryID id) override;
	void showGarrisonDialog(const CArmedInstance *, const CGHeroInstance *, bool, QueryID id, const MetaString &) override;
	void showMapObjectSelectDialog(QueryID id, const Component &, const MetaString &, const MetaString &, const std::vector<ObjectInstanceID> &) override;
	std::optional<BattleAction> makeSurrenderRetreatDecision(const BattleID &, const BattleStateInfoForRetreat &) override;
};
