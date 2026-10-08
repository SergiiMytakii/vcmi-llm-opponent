#include "../engine/Nullkiller3/BackgroundExchange.h"
#include "../engine/Nullkiller3/RequestArbiter.h"
#undef NDEBUG
#include <cassert>
#include <iostream>
int main(int argc,char ** argv)
{
    using namespace nullkiller3;
    std::atomic<bool> foregroundDone{false},cancelled{false};
    externalai::Reply foreground;
    // Large input holds a live writer until the delayed reader starts. The
    // second child must not inherit it and postpone foreground EOF.
    const auto start=std::chrono::steady_clock::now();
    std::thread worker([&] {
        foreground=externalai::exchange(argv[1],{argv[3]},std::string(400000,'x'),std::chrono::milliseconds(2000),cancelled);
        foregroundDone=true;
    });
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    {
        BackgroundExchange background;
        background.publish("{}",argv[1],argv[2]);
        assert(background.start());assert(!background.start());
        for(int i=0;i<90 && !foregroundDone;++i) std::this_thread::sleep_for(std::chrono::milliseconds(10));
        assert(foregroundDone); // Foreground finishes while background is alive.
        assert(!background.available());
        auto beforeCancel=std::chrono::steady_clock::now();
        assert(!background.take());
        assert(std::chrono::steady_clock::now()-beforeCancel<std::chrono::milliseconds(100));
    }
    worker.join();
    assert(foreground.error.empty() && foreground.output=="foreground\n");
    assert(std::chrono::steady_clock::now()-start<std::chrono::milliseconds(1000));
    std::cout<<"pending background cancelled; foreground completed without waiting\n";
    for(int i=0;i<200 && !BackgroundExchange().available();++i) std::this_thread::sleep_for(std::chrono::milliseconds(10));
    assert(BackgroundExchange().available());
    // Saved daily time is exhausted well beyond the former 280000 ms limit.
    // Each distinct noncritical question must reach the real shared transport,
    // including after a 60-second call and a spawn failure, without callbacks.
    RequestArbiter arbiter(ArbiterState{1,1,7,{0,0,0},{{"opening","old"}}});
    arbiter.beginTurn(1,{0,120000,0});
    for(int i=0;i<3;++i)
    {
        auto decision=arbiter.consider({{"checkpoint:offense",std::to_string(i),true,true,true,false}});
        assert(decision.request && decision.deadlineMs==80000);
        arbiter.dispatched(decision);
        auto reply=externalai::exchange(i==1 ? "missing-background-budget-executable" : argv[1],{argv[3]},
            "{}",std::chrono::milliseconds(decision.deadlineMs),cancelled);
        assert(i==1 ? !reply.error.empty() : reply.error.empty() && reply.output=="foreground\n");
        arbiter.finished(60000,120000);
        assert(!arbiter.consider({{"checkpoint:offense",std::to_string(i),true,true,true,false}}).request);
    }
    std::cout<<"fresh foreground transport after spent time and spawn failure, without callback\n";
}
