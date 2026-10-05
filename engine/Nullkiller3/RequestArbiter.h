#pragma once

#include <algorithm>
#include <cstdint>
#include <map>
#include <string>
#include <vector>

namespace nullkiller3
{
// Signals contain only strategic facts. Route/action IDs and local scores are
// deliberately outside this boundary; each module identifies its own question.
struct StrategicSignal
{
    std::string question;
    std::string facts;
    bool strategicImpact;
    bool needsModel;
    bool actionable;
    bool critical;
};

struct RequestBudget
{
    int64_t waitMs;
    int64_t tokens;
    int64_t criticalReserveMs;
};

struct ArbiterState
{
    int version = 1;
    int day = -1;
    int requests = 0;
    RequestBudget remaining{};
    std::map<std::string, std::string> addressed;
};

enum class RequestReason { Needed, NoNewDecision, BudgetExhausted, InFlight };

struct RequestDecision
{
    bool request = false;
    RequestReason reason = RequestReason::NoNewDecision;
    int64_t deadlineMs = 0;
    std::vector<StrategicSignal> signals;
};

// One planner owns this object. Dispatch records the facts before transport,
// so an invalid reply or timeout cannot turn the same blocker into a retry loop.
class RequestArbiter
{
    int day = -1;
    int requests = 0;
    bool inFlight = false;
    RequestBudget budget{};
    std::map<std::string, std::string> addressed;
    int64_t reservedWait = 0;
    int64_t reservedTokens = 0;

public:
    RequestArbiter() = default;
    explicit RequestArbiter(const ArbiterState & saved)
    {
        if(saved.version != 1 || saved.day < -1 || saved.requests < 0
            || saved.remaining.waitMs < 0 || saved.remaining.tokens < 0
            || saved.remaining.criticalReserveMs < 0) return;
        day = saved.day;
        requests = saved.requests;
        budget = saved.remaining;
        addressed = saved.addressed;
        // A restored in-flight request remains charged and is never replayed.
    }
    ArbiterState save() const { return {1, day, requests, budget, addressed}; }

    void beginTurn(int currentDay, RequestBudget limits)
    {
        if(day == currentDay || inFlight)
            return;
        day = currentDay;
        budget = limits;
        requests = 0;
    }

    RequestDecision consider(const std::vector<StrategicSignal> & signals) const
    {
        RequestDecision result;
        bool critical = false;
        // Keep one current fact-set per question; duplicate module signals
        // describe one decision, not multiple model calls.
        std::map<std::string, StrategicSignal> questions;
        for(const auto & signal : signals)
        {
            if(!signal.strategicImpact || !signal.needsModel || !signal.actionable)
                continue;
            // Successful routine execution is not a new strategic emergency.
            // Leave this question unaddressed so the next own turn can review it.
            if(signal.question == "campaign_exhausted" && requests > 0)
                continue;
            const auto old = addressed.find(signal.question);
            if(old != addressed.end() && old->second == signal.facts)
                continue;
            questions.insert_or_assign(signal.question, signal);
        }
        for(const auto & [question, signal] : questions)
        {
            result.signals.push_back(signal);
            critical |= signal.critical;
        }
        if(result.signals.empty())
            return result;
        if(inFlight)
        {
            result.reason = RequestReason::InFlight;
            return result;
        }
        result.deadlineMs = std::max<int64_t>(0,
            budget.waitMs - (critical ? 0 : budget.criticalReserveMs));
        // A normal decision needs a useful inference window. Critical events
        // may still spend the reserved time, including a shorter last window.
        if(result.deadlineMs == 0 || (!critical && result.deadlineMs < 60000) || budget.tokens <= 0)
        {
            result.reason = RequestReason::BudgetExhausted;
            return result;
        }
        result.request = true;
        result.reason = RequestReason::Needed;
        return result;
    }

    void dispatched(const RequestDecision & decision)
    {
        if(!decision.request || inFlight)
            return;
        for(const auto & signal : decision.signals)
            addressed.insert_or_assign(signal.question, signal.facts);
        inFlight = true;
        reservedWait = std::min(budget.waitMs, decision.deadlineMs);
        reservedTokens = budget.tokens;
        budget.waitMs -= reservedWait;
        budget.tokens -= reservedTokens;
        ++requests;
    }

    void finished(int64_t elapsedMs, int64_t consumedTokens)
    {
        if(!inFlight)
            return;
        budget.waitMs = std::max<int64_t>(0, budget.waitMs + reservedWait - std::max<int64_t>(0, elapsedMs));
        budget.tokens = std::max<int64_t>(0, budget.tokens + reservedTokens - std::max<int64_t>(0, consumedTokens));
        reservedWait = reservedTokens = 0;
        inFlight = false;
    }

    int requestsThisTurn() const { return requests; }
    const RequestBudget & remainingBudget() const { return budget; }
    // Native resolution changes the decision baseline without pretending a
    // model call occurred or spending/refunding its wait/token allowance.
    void resolved(const StrategicSignal & signal)
    {
        addressed.insert_or_assign(signal.question,signal.facts);
    }
};
}
