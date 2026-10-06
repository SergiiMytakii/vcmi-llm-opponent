"""The native request boundary, independent of game pointers and model transport."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StrategicRequestsTest(unittest.TestCase):
    def test_token_usage_and_old_saves_do_not_block_new_decisions(self):
        source = r'''
#include "RequestArbiter.h"
#include <cassert>
using namespace nullkiller3;
int main() {
    RequestArbiter arbiter;
    arbiter.beginTurn(5, {280000, 120000, 40000});
    const StrategicSignal opening{"opening", "no_campaign", true, true, true, false};
    auto first = arbiter.consider({opening});
    assert(first.request);
    arbiter.dispatched(first);
    arbiter.finished(10000, 120000);
    assert(arbiter.remainingBudget().tokens == 0);
    assert(arbiter.remainingBudget().waitMs == 270000);
    RequestArbiter restored(arbiter.save());
    restored.beginTurn(5, {280000, 120000, 40000});
    assert(restored.requestsThisTurn() == 1);
    assert(restored.remainingBudget().tokens == 0);
    assert(restored.remainingBudget().waitMs == 270000);
    assert(!restored.consider({opening}).request);
    const StrategicSignal threat{"front", "enemy_arrived", true, true, true, false};
    auto second = restored.consider({threat});
    assert(second.request && second.deadlineMs == 230000);
    restored.dispatched(second);
    // Saving during a request never refunds its unknown walltime.
    RequestArbiter interrupted(restored.save());
    interrupted.beginTurn(5, {280000, 120000, 40000});
    assert(interrupted.requestsThisTurn() == 2);
    assert(interrupted.remainingBudget().waitMs == 40000);
    assert(!interrupted.consider({threat}).request);
    const StrategicSignal another{"army", "changed", true, true, true, false};
    auto exhausted = interrupted.consider({another});
    assert(!exhausted.request && exhausted.reason == RequestReason::BudgetExhausted);
    const StrategicSignal critical{"town", "capital_threatened", true, true, true, true};
    auto reserved = interrupted.consider({critical});
    assert(reserved.request && reserved.deadlineMs == 40000);
    restored.finished(10000, 120000);
    assert(restored.consider({another}).request);
}
'''
        self.compile_and_run(source)

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
        self.compile_and_run(source)

    def compile_and_run(self, source):
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
