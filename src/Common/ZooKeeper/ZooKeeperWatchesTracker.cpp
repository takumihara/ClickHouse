#include <chrono>
#include <base/types.h>
#include <Common/MultiVersion.h>
#include <Common/ZooKeeper/ZooKeeperWatchesTracker.h>


namespace Coordination
{

void ZooKeeperWatchesTracker::requested(const ZooKeeperRequestPtr & request, const WatchCallbackPtrOrEventPtr & watch)
{
    auto info = std::make_shared<WatchInfo>();
    info->path = request->getPath();
    info->request_xid = request->xid;
    info->op_num = request->getOpNum();

    // FIXME: what is implied by "create time"? when watch was requested by client or when server responded or when user code request it?
    info->create_time = std::chrono::system_clock::now();

    std::lock_guard lock(mutex);
    watches[watch] = std::move(info);
}

void ZooKeeperWatchesTracker::activated(const WatchCallbackPtrOrEventPtr & watch)
{
    std::lock_guard lock(mutex);
    if (auto it = watches.find(watch); it != watches.end())
        it->second->active = true;
}

void ZooKeeperWatchesTracker::fired(const WatchCallbackPtrOrEventPtr & watch)
{
    removeWatch(watch);
}

void ZooKeeperWatchesTracker::deactivated(const WatchCallbackPtrOrEventPtr & watch)
{
    removeWatch(watch);
}

void ZooKeeperWatchesTracker::removeWatch(const WatchCallbackPtrOrEventPtr & watch)
{
    std::lock_guard lock(mutex);
    watches.erase(watch);
}

std::vector<WatchInfoConstPtr> ZooKeeperWatchesTracker::getSnapshot() const
{
    std::lock_guard lock(mutex);

    std::vector<WatchInfoConstPtr> result;
    result.reserve(watches.size());

    for (const auto & [_, info] : watches)
    {
        if (!info->active)
            continue;

        result.emplace_back(info);
    }

    return result;
}

}
