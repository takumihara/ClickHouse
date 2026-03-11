#pragma once

#include <chrono>
#include <cstdint>
#include <mutex>
#include <unordered_map>
#include <vector>
#include <base/types.h>
#include <Common/ZooKeeper/IKeeper.h>
#include <Common/ZooKeeper/ZooKeeperCommon.h>
#include <Common/ZooKeeper/ZooKeeperConstants.h>

namespace Coordination
{

struct WatchInfo
{
    std::chrono::system_clock::time_point create_time;
    String path;
    XID request_xid;
    OpNum op_num;
    bool active = false;
};

using WatchInfoPtr = std::shared_ptr<WatchInfo>;
using WatchInfoConstPtr = std::shared_ptr<const WatchInfo>;

class ZooKeeperWatchesTracker
{
public:
    ZooKeeperWatchesTracker() = default;

    // request is made to zk server
    void requested(const ZooKeeperRequestPtr & request, const WatchCallbackPtrOrEventPtr & watch);

    // request succeed, now waiting for firing
    void activated(const WatchCallbackPtrOrEventPtr & watch);

    void fired(const WatchCallbackPtrOrEventPtr & watch);

    // watch request failed
    void deactivated(const WatchCallbackPtrOrEventPtr & watch);

    std::vector<WatchInfoConstPtr> getSnapshot() const;

private:
    void removeWatch(const WatchCallbackPtrOrEventPtr & watch);

    mutable std::mutex mutex;
    std::unordered_map<WatchCallbackPtrOrEventPtr, WatchInfoPtr> watches;
};

}
