#pragma once
#include "../ExternalAI/ProcessExchange.h"
#include <memory>
#include <thread>
#include <functional>

namespace nullkiller3
{
// One process-wide background transport, independent of planner/game lifetime.
// Foreground exchange never acquires this lease. No destructor joins a worker.
class BackgroundExchange
{
public:
    struct Attempt
    {
        std::string request, executable, script, requestID;
        uint64_t epoch=0;
        std::atomic<bool> cancelled{false}, ready{false};
        externalai::Reply reply;
        int64_t elapsedMs=0;
    };
private:
    inline static std::atomic<bool> leased{false}, disabled{false};
    std::atomic<uint64_t> epoch{1};
    std::shared_ptr<Attempt> prepared, running;
public:
    ~BackgroundExchange() { cancel(); }
    bool available() const { return !leased.load() && !disabled.load(); }
    void publish(std::string request,std::string executable,std::string script,std::string requestID={})
    {
        cancel();
        auto value=std::make_shared<Attempt>();
        value->request=std::move(request);value->executable=std::move(executable);value->script=std::move(script);
        value->epoch=epoch.load();value->requestID=std::move(requestID);
        std::atomic_store(&prepared,value);
    }
    bool start(std::string * requestID=nullptr)
    {
        auto value=std::atomic_exchange(&prepared,std::shared_ptr<Attempt>());
        if(!value || disabled.load() || value->epoch!=epoch.load()) return false;
        bool expected=false;
        if(!leased.compare_exchange_strong(expected,true)) return false;
        if(requestID) *requestID=value->requestID;
        std::atomic_store(&running,value);
        if(value->epoch!=epoch.load()) value->cancelled=true;
        try
        {
            std::thread([value] {
                struct Lease { ~Lease() { leased=false; } } lease;
                const auto started=std::chrono::steady_clock::now();
                try {
                    value->reply=externalai::exchange(value->executable,{value->script},value->request,
                        std::chrono::milliseconds(80000),value->cancelled,32*1024+1024);
                } catch(const std::exception & error) { value->reply.error=error.what(); }
                catch(...) { value->reply.error="background_transport_exception"; }
                if(value->reply.error=="controller cleanup did not complete") disabled=true;
                value->elapsedMs=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-started).count();
                value->ready.store(true,std::memory_order_release);
            }).detach();
        }
        catch(...) { leased=false;value->reply.error="background_spawn_failed";value->ready.store(true,std::memory_order_release); }
        return true;
    }
    // Nonblocking poll: a turn boundary must not cancel a live model call.
    // Only consume a published result after its release/acquire handoff.
    std::shared_ptr<const Attempt> take()
    {
        auto value=std::atomic_load(&running);
        if(!value || !value->ready.load(std::memory_order_acquire)) return {};
        if(!std::atomic_compare_exchange_strong(&running,&value,std::shared_ptr<Attempt>())) return {};
        if(value->cancelled.load() || value->epoch!=epoch.load()) return {};
        return value;
    }
    void cancel()
    {
        epoch.fetch_add(1);
        for(auto * slot:{&prepared,&running})
            if(auto value=std::atomic_exchange(slot,std::shared_ptr<Attempt>())) value->cancelled=true;
    }
};
}
