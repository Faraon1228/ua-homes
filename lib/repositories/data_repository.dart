import '../models/models.dart';
import '../services/hive_storage_service.dart';
import '../services/remote_sync_service.dart';

class DataRepository {
  final HiveStorageService localStorage;
  final RemoteSyncService remoteSync;

  DataRepository({required this.localStorage, required this.remoteSync});

  Future<List<Story>> fetchStories() async {
    final localStories = await localStorage.loadStories();
    try {
      final remoteStories = await remoteSync.fetchStories();
      if (remoteStories.isNotEmpty) {
        final merged = _mergeStories(localStories, remoteStories);
        await localStorage.saveStories(merged);
        return merged;
      }
    } catch (_) {
      // If remote sync is unavailable, fall back to local storage.
    }
    return localStories;
  }

  Future<List<ChatThread>> fetchChatThreads() async {
    final localThreads = await localStorage.loadChatThreads();
    try {
      final remoteThreads = await remoteSync.fetchChatThreads();
      if (remoteThreads.isNotEmpty) {
        final merged = _mergeChatThreads(localThreads, remoteThreads);
        await localStorage.saveChatThreads(merged);
        return merged;
      }
    } catch (_) {
      // Use local data if remote sync fails.
    }
    return localThreads;
  }

  Future<void> saveStories(List<Story> stories) async {
    await localStorage.saveStories(stories);
    try {
      await remoteSync.syncStories(stories);
    } catch (_) {
      // Ignore remote failure for now. Local storage remains primary.
    }
  }

  Future<void> saveChatThreads(List<ChatThread> threads) async {
    await localStorage.saveChatThreads(threads);
    try {
      await remoteSync.syncChatThreads(threads);
    } catch (_) {
      // Ignore remote failure for now. Local storage remains primary.
    }
  }

  Future<void> syncAll() async {
    final stories = await localStorage.loadStories();
    final threads = await localStorage.loadChatThreads();

    try {
      await Future.wait([
        remoteSync.syncStories(stories),
        remoteSync.syncChatThreads(threads),
      ]);
    } catch (_) {
      // Keep local state if remote sync fails.
    }
  }

  List<Story> _mergeStories(List<Story> local, List<Story> remote) {
    final storyMap = <String, Story>{};
    for (final story in local) {
      storyMap[story.id] = story;
    }
    for (final story in remote) {
      final existing = storyMap[story.id];
      if (existing == null || story.updatedAt.isAfter(existing.updatedAt)) {
        storyMap[story.id] = story;
      }
    }
    return storyMap.values.toList()
      ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
  }

  List<ChatThread> _mergeChatThreads(List<ChatThread> local, List<ChatThread> remote) {
    final threadMap = <String, ChatThread>{};
    for (final thread in local) {
      threadMap[thread.id] = thread;
    }
    for (final thread in remote) {
      final existing = threadMap[thread.id];
      if (existing == null || thread.lastUpdated.isAfter(existing.lastUpdated)) {
        threadMap[thread.id] = thread;
      }
    }
    return threadMap.values.toList()
      ..sort((a, b) => b.lastUpdated.compareTo(a.lastUpdated));
  }
}
