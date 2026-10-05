"""The native request boundary, independent of game pointers and model transport."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StrategicRequestsTest(unittest.TestCase):
    def test_coalesces_modules_and_allows_three_independent_revisions(self):
        source = r'''
#include "RequestArbiter.h"
#include <cassert>
using namespace nullkiller3;
int main() {
    RequestArbiter arbiter;
    arbiter.beginTurn(1, {90000, 12000, 10000});
    auto first = arbiter.consider({
        {"front", "enemy_reached_bridge", true, true, true, true},
        {"delivery", "helper_lost", true, true, true, true}});
    assert(first.request && first.signals.size() == 2);
    arbiter.dispatched(first);
    arbiter.finished(10000, 1000);
    assert(!arbiter.consider(first.signals).request);
    const StrategicSignal localRepair{"courier", "lost:1:replaced:2", true, true, true, true};
    const auto beforeRepair = arbiter.remainingBudget();
    arbiter.resolved(localRepair);
    assert(!arbiter.consider({localRepair}).request);
    assert(arbiter.requestsThisTurn() == 1);
    assert(arbiter.remainingBudget().waitMs == beforeRepair.waitMs);
    assert(arbiter.remainingBudget().tokens == beforeRepair.tokens);
    RequestArbiter repaired(arbiter.save());
    repaired.beginTurn(2, {90000, 12000, 10000});
    assert(!repaired.consider({localRepair}).request);
    assert(repaired.consider({{"courier", "lost:2", true, true, true, true}}).request);
    // Routing IDs and ordinary movement are not strategic events.
    assert(!arbiter.consider({{"route", "new_step", false, false, true, false}}).request);
    auto second = arbiter.consider({{"front", "second_front_opened", true, true, true, true}});
    assert(second.request);
    arbiter.dispatched(second);
    arbiter.finished(10000, 1000);
    auto third = arbiter.consider({{"army", "main_hero_lost", true, true, true, true}});
    assert(third.request && third.deadlineMs == 70000);
    arbiter.dispatched(third);
    arbiter.finished(70000, 1000);
    auto exhausted = arbiter.consider({{"town", "capital_threatened", true, true, true, true}});
    assert(!exhausted.request && exhausted.reason == RequestReason::BudgetExhausted);
    assert(exhausted.signals.size() == 1); // Keep the question for a later review.
    assert(arbiter.requestsThisTurn() == 3);
    RequestArbiter restored(arbiter.save());
    restored.beginTurn(1, {90000, 12000, 10000});
    assert(restored.remainingBudget().waitMs == 0);
    assert(!restored.consider(first.signals).request);
    restored.beginTurn(2, {90000, 12000, 10000});
    auto newFacts = restored.consider({{"front", "third_front", true, true, true, true}});
    assert(newFacts.request);
    restored.dispatched(newFacts);
    // A save during exchange reserves the whole possible cost. Loading cannot
    // grant a fresh budget for an exchange with an unknown result.
    RequestArbiter interrupted(restored.save());
    interrupted.beginTurn(2, {90000, 12000, 10000});
    assert(interrupted.remainingBudget().waitMs == 0);
    assert(interrupted.remainingBudget().tokens == 0);
    assert(!interrupted.consider(newFacts.signals).request);
    restored.finished(3000, 1500);
    assert(restored.remainingBudget().waitMs == 87000);
    assert(restored.remainingBudget().tokens == 10500);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / 'proof.cpp'
            binary = Path(directory) / 'proof'
            cpp.write_text(source)
            subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++20',
                            '-I', str(ROOT / 'engine/Nullkiller3'), str(cpp),
                            '-o', str(binary)], check=True, capture_output=True, text=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
